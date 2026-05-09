import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions, StandardOptions, SetupOptions
from apache_beam.transforms.periodicsequence import PeriodicImpulse
from apache_beam.transforms import window, trigger
import json
import logging
import os
from datetime import datetime
from google.cloud import firestore


PROJECT_ID = os.environ.get('GCP_PROJECT')
if not PROJECT_ID:
    raise ValueError('GCP_PROJECT environment variable not set')

INSTANCE_CONNECTION_NAME = os.environ.get('INSTANCE_CONNECTION_NAME')
DB_USER = os.environ.get('DB_USER')
DB_PASSWORD = os.environ.get('DB_PASSWORD')
DB_NAME = os.environ.get('DB_NAME')
PUBSUB_SUBSCRIPTION = os.environ.get('PUBSUB_SUBSCRIPTION', f'projects/{PROJECT_ID}/subscriptions/sus_invernaderos')

BQ_TABLE = f'{PROJECT_ID}:agri_data.lecturas_plantas'
BQ_SCHEMA = (
    'user_id:STRING,greenhouse_id:STRING,plant_id:STRING,timestamp:DATETIME,'
    'temperatura:FLOAT,humedad_ambiental:FLOAT,humedad_suelo:FLOAT,'
    'tipo_cultivo:STRING,variedad:STRING,fecha_plantacion:DATE'
)

# Tamaño de la ventana de agregación BQ (en segundos). 300 = 5 min para tests, 600 = 10 min en prod.
WINDOW_SECONDS = 300

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


### FUNCIONES

def parsearMensaje(message):
    """Convierte el mensaje de Pub/Sub en un dict plano."""
    try:
        attrs = message.attributes
        body = json.loads(message.data.decode('utf-8'))
        return {
            'entity_type': attrs.get('entity_type'),
            'entity_id': attrs.get('entity_id'),
            'sensor_tipo': attrs.get('sensor_tipo'),
            'usuario_id': attrs.get('usuario_id'),
            'valor': body.get('valor'),
            'sensor_id': body.get('sensor_entity_id'),
        }
    except Exception as e:
        logger.error(f'Error parseando mensaje: {e}')
        return None


def filtrarInvernaderoOPlanta(reading):
    """Solo deja pasar lecturas de invernadero o planta."""
    return reading is not None and reading.get('entity_type') in ('invernadero', 'planta')


def filaFirestore(reading, cache):
    """Devuelve un dict con (path, doc) listo para escribir en Firestore."""
    invs = cache.get('invernaderos', {})
    plantas = cache.get('plantas', {})
    entity_type = reading.get('entity_type')
    entity_id = reading.get('entity_id')
    sensor_tipo = reading.get('sensor_tipo')
    valor = reading.get('valor')

    if entity_type == 'invernadero':
        inv = invs.get(entity_id)
        if not inv:
            logger.warning(f'invernadero {entity_id!r} no encontrado en caché')
            return
        yield {
            'tipo': 'invernadero',
            'user_id': inv['user_id'],
            'inv_id': entity_id,
            'sensor_tipo': sensor_tipo,
            'valor': valor,
        }

    elif entity_type == 'planta':
        p = plantas.get(entity_id)
        if not p:
            logger.warning(f'planta {entity_id!r} no encontrada en caché')
            return
        yield {
            'tipo': 'planta',
            'user_id': p['user_id'],
            'inv_id': p['invernadero_id'],
            'plant_id': entity_id,
            'sensor_tipo': sensor_tipo,
            'valor': valor,
        }


def expandirAPlantas(reading, cache):
    """Fan-out a clave por planta:
    - invernadero → N pares (plant_id, lectura), uno por planta del invernadero.
    - planta → 1 par (plant_id, lectura).
    """
    invs = cache.get('invernaderos', {})
    plantas = cache.get('plantas', {})
    entity_type = reading.get('entity_type')
    entity_id = reading.get('entity_id')

    if entity_type == 'invernadero':
        if entity_id not in invs:
            logger.warning(f'invernadero {entity_id!r} no encontrado en caché')
            return
        for plant_id, p in plantas.items():
            if p['invernadero_id'] == entity_id:
                yield (plant_id, reading)

    elif entity_type == 'planta':
        if entity_id not in plantas:
            logger.warning(f'planta {entity_id!r} no encontrada en caché')
            return
        yield (entity_id, reading)


def _media(valores):
    return sum(valores) / len(valores) if valores else None


def combinarLecturasPlanta(elemento, cache, ventana=beam.DoFn.WindowParam):
    """Recibe (plant_id, [lecturas de la ventana]) y emite UNA fila para BQ.
    - Media de cada sensor (temperatura, humedad_ambiental, humedad_suelo).
    - Sin lectura → null. Sin fallback meteorológico (espacios cerrados).
    - Timestamp = inicio de la ventana (con minutos, para identificar el más reciente).
    """
    plant_id, lecturas = elemento
    plantas = cache.get('plantas', {})
    p = plantas.get(plant_id)
    if not p:
        return

    temps, hums, suelos = [], [], []
    for r in lecturas:
        v = r.get('valor')
        if v is None:
            continue
        st = r.get('sensor_tipo')
        if st == 'temperatura':
            temps.append(v)
        elif st == 'humedad_ambiental':
            hums.append(v)
        elif st == 'humedad_suelo':
            suelos.append(v)

    ts = ventana.start.to_utc_datetime().strftime('%Y-%m-%dT%H:%M:%S')

    yield {
        'user_id': p['user_id'],
        'greenhouse_id': p['invernadero_id'],
        'plant_id': plant_id,
        'timestamp': ts,
        'temperatura': _media(temps),
        'humedad_ambiental': _media(hums),
        'humedad_suelo': _media(suelos),
        'tipo_cultivo': p.get('tipo'),
        'variedad': p.get('variedad'),
        'fecha_plantacion': None,
    }


### CLASES

class CargarInvernaderosYPlantas(beam.DoFn):
    """Carga invernaderos + plantas_invernadero y emite un dict {invernaderos, plantas}."""

    def __init__(self, project_id, instance_connection_name, db_user, db_password, db_name):
        self.project_id = project_id
        self.instance_connection_name = instance_connection_name
        self.db_user = db_user
        self.db_password = db_password
        self.db_name = db_name
        self._connector = None

    def setup(self):
        from google.cloud.sql.connector import Connector
        self._connector = Connector()

    def process(self, element):
        try:
            conn = self._connector.connect(
                self.instance_connection_name, "pg8000",
                user=self.db_user, password=self.db_password, db=self.db_name
            )
            cur = conn.cursor()

            cur.execute("SELECT id, usuario_id, nombre FROM invernaderos")
            invs = {}
            for row in cur.fetchall():
                invs[str(row[0])] = {
                    'user_id': str(row[1]),
                    'nombre': row[2],
                }

            cur.execute("SELECT id, invernadero_id, tipo, variedad FROM plantas_invernadero")
            plantas = {}
            for row in cur.fetchall():
                inv_id = str(row[1])
                plantas[str(row[0])] = {
                    'invernadero_id': inv_id,
                    'user_id': invs.get(inv_id, {}).get('user_id'),
                    'tipo': row[2],
                    'variedad': row[3],
                }
            cur.close()
            conn.close()

            logger.info(f'[CargarInvernaderosYPlantas] {len(invs)} invernaderos, {len(plantas)} plantas')
            yield {'invernaderos': invs, 'plantas': plantas}
        except Exception as e:
            logger.error(f'[CargarInvernaderosYPlantas] Error: {e}')
            yield {'invernaderos': {}, 'plantas': {}}

    def teardown(self):
        if self._connector:
            self._connector.close()


class EscribirFirestore(beam.DoFn):
    """Escribe en usuarios/{uid}/invernaderos/{inv_id} o .../plantas/{plant_id}."""

    def __init__(self, project_id, database):
        self.project_id = project_id
        self.database = database

    def setup(self):
        self._fs = firestore.Client(project=self.project_id, database=self.database)

    def process(self, element):
        try:
            doc = {
                element['sensor_tipo']: element['valor'],
                'updated_at': datetime.utcnow().isoformat(),
            }
            if element['tipo'] == 'invernadero':
                self._fs\
                    .collection('usuarios').document(element['user_id'])\
                    .collection('invernaderos').document(element['inv_id'])\
                    .set(doc, merge=True)
                logger.info(f'[Firestore] OK inv={element["inv_id"]} {element["sensor_tipo"]}={element["valor"]}')
            else:
                self._fs\
                    .collection('usuarios').document(element['user_id'])\
                    .collection('invernaderos').document(element['inv_id'])\
                    .collection('plantas').document(element['plant_id'])\
                    .set(doc, merge=True)
                logger.info(f'[Firestore] OK planta={element["plant_id"]} {element["sensor_tipo"]}={element["valor"]}')
            yield element
        except Exception as e:
            logger.error(f'[Firestore] Error: {e}')

    def teardown(self):
        if hasattr(self, '_fs'):
            self._fs.close()


### PIPELINE

def run(argv=None):
    options = PipelineOptions(argv)
    options.view_as(StandardOptions).streaming = True
    options.view_as(SetupOptions).save_main_session = True

    p = beam.Pipeline(options=options)

    # --- Side input: invernaderos + plantas, refrescado cada 5 min (test) ---
    cache = (
        p
        | "Reloj" >> PeriodicImpulse(fire_interval=300, apply_windowing=True)
        | "VentanaGlobal" >> beam.WindowInto(
            window.GlobalWindows(),
            trigger=trigger.Repeatedly(trigger.AfterCount(1)),
            accumulation_mode=trigger.AccumulationMode.DISCARDING)
        | "CargarSQL" >> beam.ParDo(CargarInvernaderosYPlantas(
            PROJECT_ID, INSTANCE_CONNECTION_NAME, DB_USER, DB_PASSWORD, DB_NAME))
    )
    vista = beam.pvalue.AsSingleton(cache, default_value={'invernaderos': {}, 'plantas': {}})

    # --- Stream principal ---
    parsed = (
        p
        | "LeerPubSub" >> beam.io.ReadFromPubSub(
            subscription=PUBSUB_SUBSCRIPTION, with_attributes=True)
        | "ParsearMensaje" >> beam.Map(parsearMensaje)
        | "FiltrarInvOPlanta" >> beam.Filter(filtrarInvernaderoOPlanta)
    )

    # --- Sink Firestore: 1 doc por mensaje ---
    (parsed
     | "PrepararFirestore" >> beam.FlatMap(filaFirestore, cache=vista)
     | "EscribirFirestore" >> beam.ParDo(EscribirFirestore(PROJECT_ID, 'ultimas-lecturas')))

    # --- Sink BigQuery: agregación por ventana fija, 1 fila por planta y ventana ---
    (parsed
     | "ExpandirAPlantas" >> beam.FlatMap(expandirAPlantas, cache=vista)
     | "VentanaFija" >> beam.WindowInto(window.FixedWindows(WINDOW_SECONDS))
     | "AgruparPorPlanta" >> beam.GroupByKey()
     | "CombinarLecturas" >> beam.FlatMap(combinarLecturasPlanta, cache=vista)
     | "EscribirBigQuery" >> beam.io.WriteToBigQuery(
         table=BQ_TABLE,
         schema=BQ_SCHEMA,
         write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
         create_disposition=beam.io.BigQueryDisposition.CREATE_NEVER))

    p.run()
    logger.info('Dataflow invernaderos streaming job submitted')


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    run()
