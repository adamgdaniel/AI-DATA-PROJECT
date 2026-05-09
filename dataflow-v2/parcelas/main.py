import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions, StandardOptions, SetupOptions
from apache_beam.transforms.window import GlobalWindows
from apache_beam.transforms.periodicsequence import PeriodicImpulse
from apache_beam.transforms.trigger import Repeatedly, AfterProcessingTime, AccumulationMode
import json
import logging
from datetime import datetime
from google.cloud import firestore
import os

PROJECT_ID = os.environ.get('GCP_PROJECT')
if not PROJECT_ID:
    raise ValueError('GCP_PROJECT environment variable not set')

INSTANCE_CONNECTION_NAME = os.environ.get('INSTANCE_CONNECTION_NAME')
if not INSTANCE_CONNECTION_NAME:
    raise ValueError('INSTANCE_CONNECTION_NAME environment variable not set')

DB_USER = os.environ.get('DB_USER')
DB_PASSWORD = os.environ.get('DB_PASSWORD')
DB_NAME = os.environ.get('DB_NAME')
PUBSUB_SUBSCRIPTION = os.environ.get('PUBSUB_SUBSCRIPTION', f'projects/{PROJECT_ID}/subscriptions/sus_parcelas')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LoadParcelasSQL(beam.DoFn):

    def __init__(self, instance_connection_name, db_user, db_password, db_name):
        self.instance_connection_name = instance_connection_name
        self.db_user = db_user
        self.db_password = db_password
        self.db_name = db_name
        self._connector = None
        self._conn = None

    def setup(self):
        from google.cloud.sql.connector import Connector
        self._connector = Connector()
        self._conn = self._connector.connect(
            self.instance_connection_name,
            "pg8000",
            user=self.db_user,
            password=self.db_password,
            db=self.db_name
        )

    def process(self, element):
        try:
            cursor = self._conn.cursor()
            cursor.execute("""
                SELECT id, usuario_id, parcela_id, municipio, cultivo, variedad, lat, lng
                FROM parcelas_usuario
            """)
            parcelas_dict = {}
            for row in cursor.fetchall():
                parcelas_dict[str(row[0])] = {
                    'usuario_id': str(row[1]),
                    'parcela_id': row[2],
                    'municipio': str(row[3]),
                    'cultivo': row[4],
                    'variedad': row[5],
                    'lat': float(row[6]) if row[6] else None,
                    'lng': float(row[7]) if row[7] else None,
                }
            cursor.close()
            logger.info(f'[LoadParcelas] {len(parcelas_dict)} parcelas cargadas. Keys: {list(parcelas_dict.keys())}')
            yield parcelas_dict
        except Exception as e:
            logger.error(f'[LoadParcelas] Error: {e}')
            yield {}

    def teardown(self):
        if self._conn:
            self._conn.close()
        if self._connector:
            self._connector.close()


class EscribirEnFirestore(beam.DoFn):
    """
    Parsea el mensaje de Pub/Sub y escribe directamente en Firestore.
    Sin tagged outputs, sin pasos intermedios.
    Si algo falla, loga el error y continúa.
    """

    def __init__(self, project_id):
        self.project_id = project_id
        self.fs_client = None

    def setup(self):
        self.fs_client = firestore.Client(project=self.project_id)

    def process(self, element, parcelas_dict):
        try:
            attrs = element.attributes
            entity_type = attrs.get('entity_type', '')

            if entity_type != 'parcela':
                return

            entity_id = attrs.get('entity_id', '')
            sensor_tipo = attrs.get('sensor_tipo', '')

            if not entity_id:
                logger.warning('[EscribirEnFirestore] entity_id vacío, descartando')
                return

            if entity_id not in parcelas_dict:
                logger.warning(f'[EscribirEnFirestore] parcela {entity_id!r} no encontrada. Dict tiene {len(parcelas_dict)} keys.')
                return

            body = json.loads(element.data.decode('utf-8'))
            valor = body.get('valor')
            parcela = parcelas_dict[entity_id]

            doc = {
                sensor_tipo: valor,
                'updated_at': datetime.utcnow().isoformat()
            }

            self.fs_client\
                .collection('usuarios').document(parcela['usuario_id'])\
                .collection('parcelas').document(entity_id)\
                .set(doc, merge=True)

            logger.info(f'[EscribirEnFirestore] OK parcela={entity_id} {sensor_tipo}={valor}')

        except Exception as e:
            logger.error(f'[EscribirEnFirestore] Error: {e}')

    def teardown(self):
        if self.fs_client:
            self.fs_client.close()


def run(argv=None):
    pipeline_options = PipelineOptions(argv)
    pipeline_options.view_as(StandardOptions).streaming = True
    pipeline_options.view_as(SetupOptions).save_main_session = True

    p = beam.Pipeline(options=pipeline_options)

    parcelas_pcoll = (
        p
        | 'PeriodicImpulse_Parcelas' >> PeriodicImpulse(fire_interval=60)
        | 'GlobalWindow_Parcelas' >> beam.WindowInto(
            GlobalWindows(),
            trigger=Repeatedly(AfterProcessingTime(60)),
            accumulation_mode=AccumulationMode.DISCARDING
        )
        | 'LoadParcelas' >> beam.ParDo(
            LoadParcelasSQL(INSTANCE_CONNECTION_NAME, DB_USER, DB_PASSWORD, DB_NAME)
        )
    )

    _ = (
        p
        | 'ReadFromPubSub' >> beam.io.ReadFromPubSub(
            subscription=PUBSUB_SUBSCRIPTION, with_attributes=True
        )
        | 'EscribirEnFirestore' >> beam.ParDo(
            EscribirEnFirestore(PROJECT_ID),
            parcelas_dict=beam.pvalue.AsSingleton(parcelas_pcoll, default_value={})
        )
    )

    p.run()
    logger.info('Dataflow parcelas streaming job submitted')


if __name__ == '__main__':
    run()
