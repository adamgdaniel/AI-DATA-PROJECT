import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions, StandardOptions, SetupOptions
from apache_beam.transforms.window import FixedWindows, GlobalWindows
from apache_beam.transforms.periodicsequence import PeriodicImpulse
from apache_beam.transforms.trigger import Repeatedly, AfterProcessingTime, AccumulationMode
import json
import logging
from datetime import datetime
from google.cloud import bigquery
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
DEAD_LETTER_TOPIC = os.environ.get('DEAD_LETTER_TOPIC', f'projects/{PROJECT_ID}/topics/sensor_readings_dead_letter')
BQ_DATASET = os.environ.get('BQ_DATASET', 'agri_data')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LoadInvernaderosSQL(beam.DoFn):
    """
    Carga invernaderos y plantas_invernadero como un único dict estructurado.
    Refresco cada 10 min vía PeriodicImpulse + GlobalWindows.
    """

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
                SELECT id, usuario_id, nombre, temperatura_entity_id, hum_amb_entity_id
                FROM invernaderos
            """)
            invernaderos = {}
            for row in cursor.fetchall():
                invernaderos[str(row[0])] = {
                    'inv_id': str(row[0]),
                    'user_id': str(row[1]),
                    'nombre': row[2],
                    'temperatura_entity_id': row[3],
                    'hum_amb_entity_id': row[4],
                    'plantas': []
                }

            cursor.execute("""
                SELECT id, invernadero_id, tipo, variedad, soil_entity_id
                FROM plantas_invernadero
            """)
            plant_to_inv = {}
            for row in cursor.fetchall():
                plant_id = str(row[0])
                inv_id = str(row[1])
                plant_to_inv[plant_id] = inv_id
                if inv_id in invernaderos:
                    invernaderos[inv_id]['plantas'].append({
                        'plant_id': plant_id,
                        'tipo': row[2],
                        'variedad': row[3],
                        'soil_entity_id': row[4]
                    })

            cursor.close()
            yield {'invernaderos': invernaderos, 'plant_to_inv': plant_to_inv}
        except Exception as e:
            logger.error(f'Error loading invernaderos from SQL: {e}')
            yield {'invernaderos': {}, 'plant_to_inv': {}}

    def teardown(self):
        if self._conn:
            self._conn.close()
        if self._connector:
            self._connector.close()


class ParseSensorInvernadero(beam.DoFn):
    """
    Parsea mensajes Pub/Sub con atributos.
    Filtra entity_type en ('invernadero', 'planta'); el resto se descarta silenciosamente.
    Los mensajes mal formados van al dead letter.

    Atributos esperados:
      entity_type: 'invernadero' | 'planta'
      entity_id:   id del invernadero o planta en Cloud SQL
      usuario_id:  id del usuario
      sensor_tipo: 'temperatura' | 'humedad_ambiental' | 'humedad_suelo'

    Body (JSON):
      valor, unidad, sensor_entity_id, timestamp_lectura
    """

    def process(self, element):
        try:
            attrs = element.attributes
            entity_type = attrs.get('entity_type')

            if entity_type not in ('invernadero', 'planta'):
                return

            body = json.loads(element.data.decode('utf-8'))
            entity_id = attrs.get('entity_id')

            if not entity_id:
                yield beam.pvalue.TaggedOutput('dead_letter', {
                    'error': 'missing_entity_id',
                    'attributes': dict(attrs),
                    'timestamp': datetime.utcnow().isoformat()
                })
                return

            yield beam.pvalue.TaggedOutput('ok', {
                'entity_type': entity_type,
                'entity_id': entity_id,
                'usuario_id': attrs.get('usuario_id'),
                'sensor_tipo': attrs.get('sensor_tipo'),
                'valor': body.get('valor'),
                'sensor_entity_id': body.get('sensor_entity_id'),
                'timestamp_lectura': body.get('timestamp_lectura')
            })
        except json.JSONDecodeError as e:
            logger.error(f'Error parsing JSON: {e}')
            yield beam.pvalue.TaggedOutput('dead_letter', {
                'error': 'json_decode_error',
                'timestamp': datetime.utcnow().isoformat()
            })
        except Exception as e:
            logger.error(f'Error parsing sensor message: {e}')
            yield beam.pvalue.TaggedOutput('dead_letter', {
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            })


class TagWithInvernaderoId(beam.DoFn):
    """
    Emite (invernadero_id, reading) para GroupByKey posterior.

    'invernadero' readings: entity_id ya ES el invernadero_id.
    'planta' readings: usa plant_to_inv del side input para resolver el inv_id.
    """

    def process(self, reading, inv_metadata):
        entity_type = reading['entity_type']
        entity_id = reading['entity_id']
        invernaderos = inv_metadata.get('invernaderos', {})
        plant_to_inv = inv_metadata.get('plant_to_inv', {})

        if entity_type == 'invernadero':
            if entity_id in invernaderos:
                yield (entity_id, reading)
            else:
                logger.warning(f'Invernadero no encontrado en side input: {entity_id}')

        elif entity_type == 'planta':
            inv_id = plant_to_inv.get(entity_id)
            if inv_id:
                yield (inv_id, reading)
            else:
                logger.warning(f'Planta no encontrada en ningún invernadero: {entity_id}')


class ProcessInvernaderoBatch(beam.DoFn):
    """
    Recibe (inv_id, iterable[readings]) tras GroupByKey.

    Por cada ventana con lecturas:
    - Extrae temperatura y humedad_ambiental del invernadero
    - Extrae humedad_suelo por planta
    - Escribe a Firestore: invernaderos/{inv_id} + plantas/{plant_id}
    - Escribe a BigQuery: una fila por planta si hay alguna lectura en la ventana

    Si no hay ninguna lectura útil en la ventana, no escribe nada.
    Usa merge=True en Firestore para no sobrescribir campos del frontend
    (ultimo_riego, ultima_poda, etc.).
    """

    def __init__(self, project_id, dataset_id):
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.bq_client = None
        self.fs_client = None

    def setup(self):
        self.bq_client = bigquery.Client(project=self.project_id)
        self.fs_client = firestore.Client(project=self.project_id)

    def process(self, element, inv_metadata, window=beam.DoFn.WindowParam):
        inv_id, readings = element
        readings = list(readings)
        inv_data = inv_metadata.get('invernaderos', {})

        if inv_id not in inv_data:
            logger.warning(f'Invernadero {inv_id} no encontrado en side input durante process')
            return

        inv = inv_data[inv_id]
        user_id = inv['user_id']
        window_start = window.start.to_utc_datetime()
        timestamp_str = window_start.isoformat()

        # Clasificar lecturas
        temperatura = None
        humedad_ambiental = None
        soil_readings = {}  # {plant_id: valor}

        for reading in readings:
            try:
                valor = float(reading['valor'])
            except (TypeError, ValueError):
                logger.warning(f'Valor no numérico en lectura: {reading.get("valor")}')
                continue

            if reading['entity_type'] == 'invernadero':
                if reading['sensor_tipo'] == 'temperatura':
                    temperatura = valor
                elif reading['sensor_tipo'] == 'humedad_ambiental':
                    humedad_ambiental = valor

            elif reading['entity_type'] == 'planta':
                plant_id = reading['entity_id']
                if reading['sensor_tipo'] == 'humedad_suelo':
                    soil_readings[plant_id] = valor

        # No hay datos útiles en esta ventana
        if temperatura is None and humedad_ambiental is None and not soil_readings:
            return

        # Firestore: invernadero (solo campos con lectura)
        inv_doc = {'updated_at': datetime.utcnow().isoformat()}
        if temperatura is not None:
            inv_doc['temperatura'] = temperatura
        if humedad_ambiental is not None:
            inv_doc['humedad_ambiental'] = humedad_ambiental

        try:
            self.fs_client\
                .collection('usuarios').document(user_id)\
                .collection('invernaderos').document(inv_id)\
                .set(inv_doc, merge=True)
        except Exception as e:
            logger.error(f'Error Firestore invernadero {inv_id}: {e}')

        # BQ + Firestore por planta
        bq_rows = []
        for planta in inv['plantas']:
            plant_id = planta['plant_id']
            humedad_suelo = soil_readings.get(plant_id)

            # Solo escribir si hay alguna lectura relacionada con esta planta
            if temperatura is None and humedad_ambiental is None and humedad_suelo is None:
                continue

            row = {
                'user_id': user_id,
                'greenhouse_id': inv_id,
                'plant_id': plant_id,
                'timestamp': timestamp_str,
                'tipo_cultivo': planta['tipo'],
                'variedad': planta['variedad']
            }
            if temperatura is not None:
                row['temperatura'] = temperatura
            if humedad_ambiental is not None:
                row['humedad_ambiental'] = humedad_ambiental
            if humedad_suelo is not None:
                row['humedad_suelo'] = humedad_suelo

            bq_rows.append(row)

            # Firestore: planta (solo si hay humedad_suelo)
            if humedad_suelo is not None:
                planta_doc = {
                    'humedad_suelo': humedad_suelo,
                    'updated_at': datetime.utcnow().isoformat()
                }
                try:
                    self.fs_client\
                        .collection('usuarios').document(user_id)\
                        .collection('invernaderos').document(inv_id)\
                        .collection('plantas').document(plant_id)\
                        .set(planta_doc, merge=True)
                except Exception as e:
                    logger.error(f'Error Firestore planta {plant_id}: {e}')

        if bq_rows:
            table_id = f'{self.project_id}.{self.dataset_id}.lecturas_plantas'
            try:
                errors = self.bq_client.insert_rows_json(table_id, bq_rows)
                if errors:
                    logger.error(f'BigQuery insert errors invernadero {inv_id}: {errors}')
            except Exception as e:
                logger.error(f'Error BigQuery invernadero {inv_id}: {e}')

    def teardown(self):
        if self.bq_client:
            self.bq_client.close()
        if self.fs_client:
            self.fs_client.close()


class WriteDeadLetterToPubSub(beam.DoFn):
    """Reenvía mensajes fallidos al Dead Letter Topic de Pub/Sub."""

    def __init__(self, project_id, dead_letter_topic):
        self.project_id = project_id
        self.dead_letter_topic = dead_letter_topic
        self.publisher = None

    def setup(self):
        from google.cloud import pubsub_v1
        self.publisher = pubsub_v1.PublisherClient()

    def process(self, element):
        try:
            self.publisher.publish(
                self.dead_letter_topic,
                json.dumps(element).encode('utf-8')
            )
            logger.warning(f'Dead letter published: {element}')
        except Exception as e:
            logger.error(f'Error publishing dead letter: {e}')

    def teardown(self):
        if self.publisher:
            self.publisher.close()


def run(argv=None):
    """Pipeline streaming para lecturas de invernaderos y plantas."""

    pipeline_options = PipelineOptions(argv)
    pipeline_options.view_as(StandardOptions).streaming = True
    pipeline_options.view_as(SetupOptions).save_main_session = True

    p = beam.Pipeline(options=pipeline_options)

    # Side input: invernaderos + plantas — refresco cada 10 min
    inv_pcoll = (
        p
        | 'PeriodicImpulse_Inv' >> PeriodicImpulse(fire_interval=60)
        | 'GlobalWindow_Inv' >> beam.WindowInto(
            GlobalWindows(),
            trigger=Repeatedly(AfterProcessingTime(60)),
            accumulation_mode=AccumulationMode.DISCARDING
        )
        | 'LoadInvernaderos' >> beam.ParDo(
            LoadInvernaderosSQL(
                INSTANCE_CONNECTION_NAME, DB_USER, DB_PASSWORD, DB_NAME
            )
        )
    )

    inv_side = beam.pvalue.AsSingleton(
        inv_pcoll, default_value={'invernaderos': {}, 'plant_to_inv': {}}
    )

    # Stream principal: lecturas desde Pub/Sub
    sensors = (
        p
        | 'ReadFromPubSub' >> beam.io.ReadFromPubSub(
            subscription=PUBSUB_SUBSCRIPTION, with_attributes=True
        )
        | 'ParseSensor' >> beam.ParDo(ParseSensorInvernadero()).with_outputs(
            'dead_letter', main='ok'
        )
    )

    # Ventanas de 10 minutos
    windowed = (
        sensors['ok']
        | 'FixedWindows' >> beam.WindowInto(FixedWindows(2 * 60))
    )

    # Agrupar lecturas por invernadero_id dentro de la ventana
    grouped = (
        windowed
        | 'TagWithInvId' >> beam.ParDo(TagWithInvernaderoId(), inv_metadata=inv_side)
        | 'GroupByInvernadero' >> beam.GroupByKey()
    )

    # Procesar y escribir a BigQuery + Firestore
    _ = (
        grouped
        | 'ProcessAndWrite' >> beam.ParDo(
            ProcessInvernaderoBatch(PROJECT_ID, BQ_DATASET),
            inv_metadata=inv_side
        )
    )

    # Dead letters al topic de errores
    _ = (
        sensors['dead_letter']
        | 'WriteDLQ' >> beam.ParDo(WriteDeadLetterToPubSub(PROJECT_ID, DEAD_LETTER_TOPIC))
    )

    p.run()
    logger.info('Dataflow invernaderos streaming job submitted')


if __name__ == '__main__':
    run()
