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
PUBSUB_SUBSCRIPTION = os.environ.get('PUBSUB_SUBSCRIPTION', f'projects/{PROJECT_ID}/subscriptions/sus_invernaderos')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LoadInvernaderosSQL(beam.DoFn):

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
            cursor.execute("SELECT id, usuario_id, nombre FROM invernaderos")
            invernaderos = {}
            for row in cursor.fetchall():
                invernaderos[str(row[0])] = {
                    'inv_id': str(row[0]),
                    'user_id': str(row[1]),
                    'nombre': row[2],
                }

            cursor.execute("SELECT id, invernadero_id FROM plantas_invernadero")
            plant_to_inv = {}
            for row in cursor.fetchall():
                plant_to_inv[str(row[0])] = str(row[1])

            cursor.close()
            logger.info(f'[LoadInvernaderos] {len(invernaderos)} invernaderos, {len(plant_to_inv)} plantas')
            yield {'invernaderos': invernaderos, 'plant_to_inv': plant_to_inv}
        except Exception as e:
            logger.error(f'[LoadInvernaderos] Error: {e}')
            yield {'invernaderos': {}, 'plant_to_inv': {}}

    def teardown(self):
        if self._conn:
            self._conn.close()
        if self._connector:
            self._connector.close()


def parsear_mensaje(element):
    """Convierte PubsubMessage a dict plano. Devuelve None si no es de invernadero/planta."""
    try:
        attrs = element.attributes
        entity_type = attrs.get('entity_type', '')
        if entity_type not in ('invernadero', 'planta'):
            return None
        body = json.loads(element.data.decode('utf-8'))
        return {
            'entity_type': entity_type,
            'entity_id': attrs.get('entity_id', ''),
            'usuario_id': attrs.get('usuario_id', ''),
            'sensor_tipo': attrs.get('sensor_tipo', ''),
            'valor': body.get('valor'),
        }
    except Exception as e:
        logger.error(f'[parsear_mensaje] Error: {e}')
        return None


class EscribirEnFirestore(beam.DoFn):
    """
    Recibe un dict con la lectura y escribe en Firestore usando el side input.
    Sin GroupByKey, sin FixedWindows — cada mensaje se escribe al llegar.
    """

    def __init__(self, project_id):
        self.project_id = project_id
        self.fs_client = None

    def setup(self):
        self.fs_client = firestore.Client(project=self.project_id)

    def process(self, lectura, inv_metadata):
        if lectura is None:
            return

        try:
            entity_type = lectura['entity_type']
            entity_id = lectura['entity_id']
            sensor_tipo = lectura['sensor_tipo']
            valor = lectura['valor']

            invernaderos = inv_metadata.get('invernaderos', {})
            plant_to_inv = inv_metadata.get('plant_to_inv', {})

            if entity_type == 'invernadero':
                if entity_id not in invernaderos:
                    logger.warning(f'[EscribirEnFirestore] invernadero {entity_id!r} no encontrado. Dict tiene {len(invernaderos)} keys.')
                    return
                inv = invernaderos[entity_id]
                doc = {sensor_tipo: valor, 'updated_at': datetime.utcnow().isoformat()}
                self.fs_client\
                    .collection('usuarios').document(inv['user_id'])\
                    .collection('invernaderos').document(entity_id)\
                    .set(doc, merge=True)
                logger.info(f'[EscribirEnFirestore] OK invernadero={entity_id} {sensor_tipo}={valor}')

            elif entity_type == 'planta':
                inv_id = plant_to_inv.get(entity_id)
                if not inv_id:
                    logger.warning(f'[EscribirEnFirestore] planta {entity_id!r} no encontrada')
                    return
                if inv_id not in invernaderos:
                    logger.warning(f'[EscribirEnFirestore] invernadero {inv_id!r} de planta no encontrado')
                    return
                inv = invernaderos[inv_id]
                doc = {sensor_tipo: valor, 'updated_at': datetime.utcnow().isoformat()}
                self.fs_client\
                    .collection('usuarios').document(inv['user_id'])\
                    .collection('invernaderos').document(inv_id)\
                    .collection('plantas').document(entity_id)\
                    .set(doc, merge=True)
                logger.info(f'[EscribirEnFirestore] OK planta={entity_id} {sensor_tipo}={valor}')

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

    inv_pcoll = (
        p
        | 'PeriodicImpulse_Inv' >> PeriodicImpulse(fire_interval=60)
        | 'GlobalWindow_Inv' >> beam.WindowInto(
            GlobalWindows(),
            trigger=Repeatedly(AfterProcessingTime(60)),
            accumulation_mode=AccumulationMode.DISCARDING
        )
        | 'LoadInvernaderos' >> beam.ParDo(
            LoadInvernaderosSQL(INSTANCE_CONNECTION_NAME, DB_USER, DB_PASSWORD, DB_NAME)
        )
    )

    inv_side = beam.pvalue.AsSingleton(
        inv_pcoll, default_value={'invernaderos': {}, 'plant_to_inv': {}}
    )

    _ = (
        p
        | 'ReadFromPubSub' >> beam.io.ReadFromPubSub(
            subscription=PUBSUB_SUBSCRIPTION, with_attributes=True
        )
        | 'ParsearMensaje' >> beam.Map(parsear_mensaje)
        | 'EscribirEnFirestore' >> beam.ParDo(EscribirEnFirestore(PROJECT_ID), inv_metadata=inv_side)
    )

    p.run()
    logger.info('Dataflow invernaderos streaming job submitted')


if __name__ == '__main__':
    run()
