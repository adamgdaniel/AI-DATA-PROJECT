import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions, StandardOptions, SetupOptions
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

CACHE_TTL_SECONDS = 600


class EscribirInvernadero(beam.DoFn):
    """
    Carga invernaderos y plantas desde Cloud SQL en setup() y refresca cada 10 min.
    Sin side inputs, sin windowing. Cada mensaje se procesa y escribe al llegar.
    """

    def __init__(self, project_id, instance_connection_name, db_user, db_password, db_name):
        self.project_id = project_id
        self.instance_connection_name = instance_connection_name
        self.db_user = db_user
        self.db_password = db_password
        self.db_name = db_name
        self._connector = None
        self._conn = None
        self._fs = None
        self._invernaderos = {}
        self._plant_to_inv = {}
        self._loaded_at = None

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
        self._fs = firestore.Client(project=self.project_id, database='ultimas-lecturas')
        self._cargar_datos()

    def _cargar_datos(self):
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
            self._invernaderos = invernaderos
            self._plant_to_inv = plant_to_inv
            self._loaded_at = datetime.utcnow()
            logger.info(f'[EscribirInvernadero] {len(invernaderos)} invernaderos, {len(plant_to_inv)} plantas cargados')
        except Exception as e:
            logger.error(f'[EscribirInvernadero] Error cargando datos: {e}')

    def process(self, element):
        # Refrescar caché si ha pasado el TTL
        if self._loaded_at is None or (datetime.utcnow() - self._loaded_at).seconds > CACHE_TTL_SECONDS:
            self._cargar_datos()

        try:
            attrs = element.attributes
            entity_type = attrs.get('entity_type', '')

            if entity_type not in ('invernadero', 'planta'):
                return

            entity_id = attrs.get('entity_id', '')
            sensor_tipo = attrs.get('sensor_tipo', '')
            body = json.loads(element.data.decode('utf-8'))
            valor = body.get('valor')
            doc = {sensor_tipo: valor, 'updated_at': datetime.utcnow().isoformat()}

            if entity_type == 'invernadero':
                if entity_id not in self._invernaderos:
                    logger.warning(f'[EscribirInvernadero] invernadero {entity_id!r} no encontrado')
                    return
                inv = self._invernaderos[entity_id]
                self._fs\
                    .collection('usuarios').document(inv['user_id'])\
                    .collection('invernaderos').document(entity_id)\
                    .set(doc, merge=True)
                logger.info(f'[EscribirInvernadero] OK inv={entity_id} {sensor_tipo}={valor}')

            elif entity_type == 'planta':
                inv_id = self._plant_to_inv.get(entity_id)
                if not inv_id or inv_id not in self._invernaderos:
                    logger.warning(f'[EscribirInvernadero] planta {entity_id!r} no encontrada')
                    return
                inv = self._invernaderos[inv_id]
                self._fs\
                    .collection('usuarios').document(inv['user_id'])\
                    .collection('invernaderos').document(inv_id)\
                    .collection('plantas').document(entity_id)\
                    .set(doc, merge=True)
                logger.info(f'[EscribirInvernadero] OK planta={entity_id} {sensor_tipo}={valor}')

        except Exception as e:
            logger.error(f'[EscribirInvernadero] Error: {e}')

    def teardown(self):
        if self._conn:
            self._conn.close()
        if self._connector:
            self._connector.close()
        if self._fs:
            self._fs.close()


def run(argv=None):
    pipeline_options = PipelineOptions(argv)
    pipeline_options.view_as(StandardOptions).streaming = True
    pipeline_options.view_as(SetupOptions).save_main_session = True

    p = beam.Pipeline(options=pipeline_options)

    _ = (
        p
        | 'ReadFromPubSub' >> beam.io.ReadFromPubSub(
            subscription=PUBSUB_SUBSCRIPTION, with_attributes=True
        )
        | 'EscribirInvernadero' >> beam.ParDo(
            EscribirInvernadero(
                PROJECT_ID, INSTANCE_CONNECTION_NAME, DB_USER, DB_PASSWORD, DB_NAME
            )
        )
    )

    p.run()
    logger.info('Dataflow invernaderos streaming job submitted')


if __name__ == '__main__':
    run()
