import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions, StandardOptions
from apache_beam.transforms.window import FixedWindows, GlobalWindows
from apache_beam.transforms.periodicsequence import PeriodicImpulse
from apache_beam.transforms.trigger import Repeatedly, AfterProcessingTime, AccumulationMode
import json
import logging
from datetime import datetime, timedelta
from google.cloud import bigquery
from google.cloud import firestore
import os

# Configuración
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
DEAD_LETTER_TOPIC = os.environ.get('DEAD_LETTER_TOPIC', f'projects/{PROJECT_ID}/topics/sensor_readings_dead_letter')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LoadParcelasSQL(beam.DoFn):
    """Carga parcelas_usuario como dict {parcela_usuario_id: {...}}. Refresco cada 10 min."""

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
                SELECT
                    id, usuario_id, parcela_id, provincia, municipio,
                    poligono, parcela, recinto, cultivo, superficie,
                    lat, lng, fecha_registro, geometria, zonas, grid,
                    variedad, edad_cultivo
                FROM parcelas_usuario
            """)

            parcelas_dict = {}
            for row in cursor.fetchall():
                parcelas_dict[row[0]] = {
                    'id': row[0],
                    'usuario_id': row[1],
                    'parcela_id': row[2],
                    'provincia': row[3],
                    'municipio': row[4],
                    'poligono': row[5],
                    'parcela': row[6],
                    'recinto': row[7],
                    'cultivo': row[8],
                    'superficie': float(row[9]) if row[9] else None,
                    'lat': float(row[10]) if row[10] else None,
                    'lng': float(row[11]) if row[11] else None,
                    'fecha_registro': row[12],
                    'geometria': row[13],
                    'zonas': row[14],
                    'grid': row[15],
                    'variedad': row[16],
                    'edad_cultivo': row[17]
                }

            cursor.close()
            yield parcelas_dict
        except Exception as e:
            logger.error(f'Error loading parcelas: {e}')
            yield {}

    def teardown(self):
        if self._conn:
            self._conn.close()
        if self._connector:
            self._connector.close()


class LoadMeteoSQL(beam.DoFn):
    """Carga meteorología más reciente por municipio. Refresco cada 10 min."""

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
            # Obtener la meteorología más reciente para cada municipio (no futura)
            cursor.execute("""
                SELECT
                    codigo_ine, fecha_prevision, temperatura_promedio,
                    humedad_promedio, precipitacion_mm, et0_evapotranspiracion,
                    radiacion_solar, estado_cielo_cod
                FROM (
                    SELECT
                        codigo_ine, fecha_prevision,
                        (tmax + tmin) / 2 AS temperatura_promedio,
                        (humedad_max + humedad_min) / 2 AS humedad_promedio,
                        precipitacion_mm, et0_evapotranspiracion,
                        radiacion_solar, estado_cielo_cod,
                        ROW_NUMBER() OVER (PARTITION BY codigo_ine ORDER BY fecha_prevision DESC) as rn
                    FROM prevision_meteorologica
                    WHERE fecha_prevision <= CURRENT_DATE
                ) subq
                WHERE rn = 1
            """)

            meteo_dict = {}
            for row in cursor.fetchall():
                meteo_dict[str(row[0])] = {
                    'codigo_ine': row[0],
                    'fecha_prevision': row[1],
                    'temperatura': float(row[2]) if row[2] else None,
                    'humedad_ambiental': float(row[3]) if row[3] else None,
                    'precipitacion_mm': float(row[4]) if row[4] else None,
                    'et0': float(row[5]) if row[5] else None,
                    'radiacion_solar': float(row[6]) if row[6] else None,
                    'estado_cielo': row[7]
                }

            cursor.close()
            yield meteo_dict
        except Exception as e:
            logger.error(f'Error loading meteo: {e}')
            yield {}

    def teardown(self):
        if self._conn:
            self._conn.close()
        if self._connector:
            self._connector.close()


class ParseSensor(beam.DoFn):
    """Parsea mensaje Pub/Sub (con atributos) y filtra por entity_type=parcela."""

    def process(self, element):
        try:
            attrs = element.attributes
            body = json.loads(element.data.decode('utf-8'))

            # Filtrar: solo mensajes de parcela
            if attrs.get('entity_type') != 'parcela':
                return

            entity_id = attrs.get('entity_id')
            if not entity_id:
                yield beam.pvalue.TaggedOutput('dead_letter', {
                    'error': 'missing_entity_id',
                    'attributes': dict(attrs),
                    'timestamp': datetime.utcnow().isoformat()
                })
                return

            yield beam.pvalue.TaggedOutput('ok', {
                'parcela_usuario_id': entity_id,
                'usuario_id': attrs.get('usuario_id'),
                'sensor_tipo': attrs.get('sensor_tipo'),
                'valor': body.get('valor'),
                'sensor_entity_id': body.get('sensor_entity_id'),
                'timestamp_lectura': body.get('timestamp_lectura')
            })
        except json.JSONDecodeError as e:
            logger.error(f'Error parsing sensor JSON: {e}')
            yield beam.pvalue.TaggedOutput('dead_letter', {
                'error': 'json_decode_error',
                'timestamp': datetime.utcnow().isoformat()
            })
        except Exception as e:
            logger.error(f'Error parsing sensor: {e}')
            yield beam.pvalue.TaggedOutput('dead_letter', {
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            })


class EnrichSensorWithParcelaAndMeteo(beam.DoFn):
    """Enriquece sensor con datos de parcela y meteorología usando side inputs."""

    def process(self, sensor, parcelas_dict=None, meteo_dict=None, window=beam.DoFn.WindowParam):
        try:
            if not parcelas_dict:
                parcelas_dict = {}
            if not meteo_dict:
                meteo_dict = {}

            parcela_usuario_id = sensor.get('parcela_usuario_id')

            # Buscar parcela
            if parcela_usuario_id not in parcelas_dict:
                logger.warning(f'Parcela no encontrada: {parcela_usuario_id}')
                yield beam.pvalue.TaggedOutput('dead_letter', {
                    'error': 'parcela_not_found',
                    'parcela_usuario_id': parcela_usuario_id,
                    'timestamp': datetime.utcnow().isoformat()
                })
                return

            parcela = parcelas_dict[parcela_usuario_id]
            municipio_code = str(parcela.get('municipio'))

            # Buscar meteorología
            meteo = meteo_dict.get(municipio_code, {})

            # Construir registro enriquecido
            sensor_type = sensor.get('sensor_tipo', '').lower()
            value = float(sensor.get('valor', 0) or 0)

            # Obtener timestamp de la ventana
            window_start = window.start.to_utc_datetime().isoformat()

            enriched = {
                'user_id': str(parcela.get('usuario_id')),
                'parcela_usuario_id': parcela_usuario_id,
                'parcela_id': parcela.get('parcela_id'),
                'municipio': municipio_code,
                'cultivo': parcela.get('cultivo'),
                'variedad': parcela.get('variedad'),
                'lat': parcela.get('lat'),
                'lng': parcela.get('lng'),
                'timestamp': window_start,
                'temperatura': None,
                'humedad_ambiental': None,
                'humedad_suelo': None,
                'fuente_temperatura': 'openmeteo',
                'precipitacion_mm': meteo.get('precipitacion_mm'),
                'et0': meteo.get('et0'),
                'radiacion_solar': meteo.get('radiacion_solar'),
                'estado_cielo': meteo.get('estado_cielo'),
                'sensor_id': sensor.get('sensor_entity_id')
            }

            # Aplicar valor del sensor
            if sensor_type == 'temperature':
                enriched['temperatura'] = value
                enriched['fuente_temperatura'] = 'sensor'
            elif sensor_type == 'ambient_humidity':
                enriched['humedad_ambiental'] = value
            elif sensor_type == 'soil_moisture':
                enriched['humedad_suelo'] = value

            # Si no hay sensor, usar meteorología como fallback
            if enriched['temperatura'] is None:
                enriched['temperatura'] = meteo.get('temperatura')
                enriched['fuente_temperatura'] = 'openmeteo'

            if enriched['humedad_ambiental'] is None:
                enriched['humedad_ambiental'] = meteo.get('humedad_ambiental')

            yield beam.pvalue.TaggedOutput('ok', enriched)
        except Exception as e:
            logger.error(f'Error enriching sensor: {e}')
            yield beam.pvalue.TaggedOutput('dead_letter', {
                'error': str(e),
                'sensor': sensor,
                'timestamp': datetime.utcnow().isoformat()
            })


class WriteToBigQuery(beam.DoFn):
    """Escribe registros enriquecidos a BigQuery."""

    def __init__(self, project_id, dataset_id, table_id):
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.table_id = table_id
        self.bq_client = None

    def setup(self):
        self.bq_client = bigquery.Client(project=self.project_id)

    def process(self, element):
        try:
            table_id = f"{self.project_id}.{self.dataset_id}.{self.table_id}"

            rows_to_insert = [{
                'user_id': element['user_id'],
                'parcel_id': element['parcela_id'],
                'timestamp': element['timestamp'],
                'temperatura': element['temperatura'],
                'humedad_ambiental': element['humedad_ambiental'],
                'humedad_suelo': element['humedad_suelo'],
                'precipitacion_mm': element['precipitacion_mm'],
                'et0': element['et0'],
                'radiacion_solar': element['radiacion_solar'],
                'fuente_temperatura': element['fuente_temperatura'],
                'tipo_cultivo': element['cultivo'],
                'variedad': element['variedad'],
                'estado_cielo': element['estado_cielo'],
                'sensor_id': element['sensor_id']
            }]

            errors = self.bq_client.insert_rows_json(table_id, rows_to_insert)
            if errors:
                logger.error(f'BigQuery insert errors: {errors}')

            yield element
        except Exception as e:
            logger.error(f'Error writing to BigQuery: {e}')
            yield element

    def teardown(self):
        if self.bq_client:
            self.bq_client.close()


class WriteToFirestore(beam.DoFn):
    """Escribe registros enriquecidos a Firestore."""

    def __init__(self, project_id):
        self.project_id = project_id
        self.fs_client = None

    def setup(self):
        self.fs_client = firestore.Client(project=self.project_id)

    def process(self, element):
        try:
            doc_data = {
                'temperatura': element['temperatura'],
                'humedad_ambiental': element['humedad_ambiental'],
                'humedad_suelo': element['humedad_suelo'],
                'precipitacion_mm': element['precipitacion_mm'],
                'et0': element['et0'],
                'radiacion_solar': element['radiacion_solar'],
                'estado_cielo': element['estado_cielo'],
                'fuente_temperatura': element['fuente_temperatura'],
                'updated_at': datetime.utcnow().isoformat()
            }

            # Omitir campos None
            doc_data = {k: v for k, v in doc_data.items() if v is not None}

            doc_ref = self.fs_client.collection('usuarios').document(
                element['user_id']
            ).collection('parcelas').document(
                str(element['parcela_usuario_id'])
            )

            doc_ref.set(doc_data, merge=True)
            yield element
        except Exception as e:
            logger.error(f'Error writing to Firestore: {e}')
            yield element

    def teardown(self):
        if self.fs_client:
            self.fs_client.close()


class WriteDeadLetterToPubSub(beam.DoFn):
    """Envía mensajes muertos a Pub/Sub Dead Letter Topic."""

    def __init__(self, project_id, dead_letter_topic):
        self.project_id = project_id
        self.dead_letter_topic = dead_letter_topic
        self.publisher = None

    def setup(self):
        from google.cloud import pubsub_v1
        self.publisher = pubsub_v1.PublisherClient()

    def process(self, element):
        try:
            message_json = json.dumps(element).encode('utf-8')
            self.publisher.publish(self.dead_letter_topic, message_json)
            logger.warning(f'Dead letter published: {element}')
        except Exception as e:
            logger.error(f'Error publishing dead letter: {e}')

    def teardown(self):
        if self.publisher:
            self.publisher.close()


def run(argv=None):
    """Pipeline principal."""

    pipeline_options = PipelineOptions(argv)
    pipeline_options.view_as(StandardOptions).streaming = True

    with beam.Pipeline(options=pipeline_options) as p:
        # Side input: Parcelas — se refresca cada 20 min, no por cada mensaje
        parcelas_pcoll = (
            p
            | 'PeriodicImpulse_Parcelas' >> PeriodicImpulse(fire_interval=1200)
            | 'GlobalWindow_Parcelas' >> beam.WindowInto(
                GlobalWindows(),
                trigger=Repeatedly(AfterProcessingTime(1200)),
                accumulation_mode=AccumulationMode.DISCARDING
            )
            | 'LoadParcelas' >> beam.ParDo(
                LoadParcelasSQL(
                    INSTANCE_CONNECTION_NAME, DB_USER, DB_PASSWORD, DB_NAME
                )
            )
        )

        # Side input: Meteorología — se refresca cada 20 min, no por cada mensaje
        meteo_pcoll = (
            p
            | 'PeriodicImpulse_Meteo' >> PeriodicImpulse(fire_interval=1200)
            | 'GlobalWindow_Meteo' >> beam.WindowInto(
                GlobalWindows(),
                trigger=Repeatedly(AfterProcessingTime(1200)),
                accumulation_mode=AccumulationMode.DISCARDING
            )
            | 'LoadMeteo' >> beam.ParDo(
                LoadMeteoSQL(
                    INSTANCE_CONNECTION_NAME, DB_USER, DB_PASSWORD, DB_NAME
                )
            )
        )

        # Stream: Sensores desde Pub/Sub
        sensors = (
            p
            | 'ReadFromPubSub' >> beam.io.ReadFromPubSub(subscription=PUBSUB_SUBSCRIPTION, with_attributes=True)
            | 'ParseSensor' >> beam.ParDo(ParseSensor()).with_outputs(
                'ok', 'dead_letter', main='ok'
            )
        )

        # Dead letters del parseo
        dead_letters_parse = sensors['dead_letter']

        # Windowing: 20 minutos (FixedWindows)
        windowed_sensors = (
            sensors['ok']
            | 'FixedWindows_Sensors' >> beam.WindowInto(FixedWindows(20 * 60))
        )

        # Enriquecer con parcelas y meteorología
        enriched = (
            windowed_sensors
            | 'EnrichWithMetadata' >> beam.ParDo(
                EnrichSensorWithParcelaAndMeteo(),
                parcelas_dict=beam.pvalue.AsSingleton(parcelas_pcoll, default_value={}),
                meteo_dict=beam.pvalue.AsSingleton(meteo_pcoll, default_value={})
            ).with_outputs('ok', 'dead_letter', main='ok')
        )

        # Escribir a BigQuery
        _ = (
            enriched['ok']
            | 'WriteToBQ' >> beam.ParDo(WriteToBigQuery(PROJECT_ID, 'agri_data', 'lecturas_parcelas'))
        )

        # Escribir a Firestore
        _ = (
            enriched['ok']
            | 'WriteToFirestore' >> beam.ParDo(WriteToFirestore(PROJECT_ID))
        )

        # Combinar todos los dead letters
        all_dead_letters = (
            (dead_letters_parse, enriched['dead_letter'])
            | 'FlattenDeadLetters' >> beam.Flatten()
        )

        # Dead letters a Pub/Sub
        _ = (
            all_dead_letters
            | 'WriteDLQ' >> beam.ParDo(WriteDeadLetterToPubSub(PROJECT_ID, DEAD_LETTER_TOPIC))
        )


if __name__ == '__main__':
    run()



##test deployment 