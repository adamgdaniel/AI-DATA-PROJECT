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
DB_NAME_METEO = os.environ.get('DB_NAME_METEO', 'agrodb')
PUBSUB_SUBSCRIPTION = os.environ.get('PUBSUB_SUBSCRIPTION', f'projects/{PROJECT_ID}/subscriptions/sus_parcelas')

BQ_TABLE = f'{PROJECT_ID}:agri_data.lecturas_parcelas'
BQ_SCHEMA = (
    'user_id:STRING,parcel_id:STRING,timestamp:DATETIME,'
    'temperatura:FLOAT,humedad_ambiental:FLOAT,humedad_suelo:FLOAT,'
    'precipitacion_mm:FLOAT,et0:FLOAT,radiacion_solar:FLOAT,'
    'fuente_temperatura:STRING,tipo_cultivo:STRING,variedad:STRING,'
    'fecha_plantacion_aprox:DATE,estado_cielo:STRING,sensor_id:STRING'
)

# Tamaño de la ventana de agregación BQ (en segundos). 300 = 5 min para tests, 1200 = 20 min en prod.
WINDOW_SECONDS = 300

WMO_ESTADO = {
    0: 'Despejado', 1: 'Mayormente despejado', 2: 'Parcialmente nublado', 3: 'Nublado',
    45: 'Niebla', 48: 'Niebla con escarcha',
    51: 'Llovizna ligera', 53: 'Llovizna moderada', 55: 'Llovizna intensa',
    61: 'Lluvia ligera', 63: 'Lluvia moderada', 65: 'Lluvia intensa',
    71: 'Nieve ligera', 73: 'Nieve moderada', 75: 'Nieve intensa',
    80: 'Chubascos ligeros', 81: 'Chubascos moderados', 82: 'Chubascos intensos',
    95: 'Tormenta', 96: 'Tormenta con granizo ligero', 99: 'Tormenta con granizo intenso',
}

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


def filtrarParcela(reading):
    """Solo deja pasar lecturas de parcela."""
    return reading is not None and reading.get('entity_type') == 'parcela'


def enriquecerConMeteo(reading, parcelas_meteo):
    """Cruza la lectura del sensor con los datos de parcela + meteo cacheados (para Firestore)."""
    parcela_id = reading.get('entity_id')
    info = parcelas_meteo.get(parcela_id)
    if not info:
        logger.warning(f'parcela {parcela_id!r} no encontrada en caché ({len(parcelas_meteo)} entradas)')
        return

    sensor_tipo = reading.get('sensor_tipo')
    valor = reading.get('valor')

    fila = {
        'user_id': info['user_id'],
        'parcel_id': parcela_id,
        'timestamp': datetime.utcnow().replace(minute=0, second=0, microsecond=0).isoformat(),
        'temperatura': info.get('temperatura'),
        'humedad_ambiental': info.get('humedad_ambiental'),
        'humedad_suelo': None,
        'precipitacion_mm': info.get('precipitacion_mm'),
        'et0': info.get('et0'),
        'radiacion_solar': info.get('radiacion_solar'),
        'fuente_temperatura': 'openmeteo',
        'tipo_cultivo': info.get('cultivo'),
        'variedad': info.get('variedad'),
        'fecha_plantacion_aprox': None,
        'estado_cielo': info.get('estado_cielo'),
        'sensor_id': reading.get('sensor_id'),
    }

    if sensor_tipo == 'temperatura':
        fila['temperatura'] = valor
        fila['fuente_temperatura'] = 'sensor'
    elif sensor_tipo == 'humedad_ambiental':
        fila['humedad_ambiental'] = valor
    elif sensor_tipo == 'humedad_suelo':
        fila['humedad_suelo'] = valor

    yield fila


def _media(valores):
    return sum(valores) / len(valores) if valores else None


def combinarLecturas(elemento, parcelas_meteo, ventana=beam.DoFn.WindowParam):
    """Recibe (parcel_id, [lecturas de la ventana]) y emite UNA fila para BQ.
    - Si hay varias lecturas del mismo sensor, hace la media.
    - Si no hay lectura de sensor, usa meteo (excepto humedad_suelo, que queda null).
    - Timestamp = inicio de la ventana (con minutos, para que la IA identifique el más reciente).
    """
    parcela_id, lecturas = elemento
    info = parcelas_meteo.get(parcela_id)
    if not info:
        logger.warning(f'[combinar] parcela {parcela_id!r} no encontrada en caché')
        return

    temps, hums, suelos = [], [], []
    sensor_id = None
    for r in lecturas:
        sensor_id = sensor_id or r.get('sensor_id')
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

    temp_media = _media(temps)
    hum_media = _media(hums)
    suelo_media = _media(suelos)

    ts = ventana.start.to_utc_datetime().strftime('%Y-%m-%dT%H:%M:%S')

    yield {
        'user_id': info['user_id'],
        'parcel_id': parcela_id,
        'timestamp': ts,
        'temperatura': temp_media if temp_media is not None else info.get('temperatura'),
        'humedad_ambiental': hum_media if hum_media is not None else info.get('humedad_ambiental'),
        'humedad_suelo': suelo_media,
        'precipitacion_mm': info.get('precipitacion_mm'),
        'et0': info.get('et0'),
        'radiacion_solar': info.get('radiacion_solar'),
        'fuente_temperatura': 'sensor' if temp_media is not None else 'openmeteo',
        'tipo_cultivo': info.get('cultivo'),
        'variedad': info.get('variedad'),
        'fecha_plantacion_aprox': None,
        'estado_cielo': info.get('estado_cielo'),
        'sensor_id': sensor_id,
    }


### CLASES

class CargarParcelasYMeteo(beam.DoFn):
    """Carga parcelas_usuario (logindb) + previsión meteo (agrodb) y emite un dict por parcela."""

    def __init__(self, project_id, instance_connection_name, db_user, db_password, db_name, db_name_meteo):
        self.project_id = project_id
        self.instance_connection_name = instance_connection_name
        self.db_user = db_user
        self.db_password = db_password
        self.db_name = db_name
        self.db_name_meteo = db_name_meteo
        self._connector = None

    def setup(self):
        from google.cloud.sql.connector import Connector
        self._connector = Connector()

    def _connect(self, db):
        return self._connector.connect(
            self.instance_connection_name, "pg8000",
            user=self.db_user, password=self.db_password, db=db
        )

    def process(self, element):
        try:
            # 1) Parcelas
            conn = self._connect(self.db_name)
            cur = conn.cursor()
            cur.execute("""
                SELECT id, usuario_id, provincia, municipio, cultivo, variedad
                FROM parcelas_usuario
            """)
            parcelas = {}
            for row in cur.fetchall():
                pid = str(row[0])
                provincia = row[2] or 0
                municipio = row[3] or 0
                codigo_ine = f'{int(provincia):02d}{int(municipio):03d}'
                parcelas[pid] = {
                    'user_id': str(row[1]),
                    'codigo_ine': codigo_ine,
                    'cultivo': row[4],
                    'variedad': row[5],
                }
            cur.close()
            conn.close()

            # 2) Meteo: última fila <= hoy por municipio
            conn = self._connect(self.db_name_meteo)
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT ON (codigo_ine)
                    codigo_ine, tmax, tmin, precipitacion_mm, et0_evapotranspiracion,
                    radiacion_solar, weather_code, humedad_max, humedad_min, estado_cielo_desc
                FROM prevision_meteorologica
                WHERE fecha_prevision <= CURRENT_DATE
                ORDER BY codigo_ine, fecha_prevision DESC
            """)
            meteo = {}
            for row in cur.fetchall():
                meteo[row[0]] = {
                    'tmax': float(row[1]) if row[1] is not None else None,
                    'tmin': float(row[2]) if row[2] is not None else None,
                    'precipitacion_mm': float(row[3]) if row[3] is not None else None,
                    'et0': float(row[4]) if row[4] is not None else None,
                    'radiacion_solar': float(row[5]) if row[5] is not None else None,
                    'weather_code': row[6],
                    'humedad_max': row[7],
                    'humedad_min': row[8],
                    'estado_cielo_desc': row[9],
                }
            cur.close()
            conn.close()

            # 3) Cruzar parcela ← meteo
            for p in parcelas.values():
                m = meteo.get(p['codigo_ine'], {})
                tmax, tmin = m.get('tmax'), m.get('tmin')
                hmax, hmin = m.get('humedad_max'), m.get('humedad_min')
                p['temperatura'] = (tmax + tmin) / 2 if tmax is not None and tmin is not None else None
                p['humedad_ambiental'] = (hmax + hmin) / 2 if hmax is not None and hmin is not None else None
                p['precipitacion_mm'] = m.get('precipitacion_mm')
                p['et0'] = m.get('et0')
                p['radiacion_solar'] = m.get('radiacion_solar')
                wc = m.get('weather_code')
                p['estado_cielo'] = m.get('estado_cielo_desc') or (WMO_ESTADO.get(wc) if wc is not None else None)

            logger.info(f'[CargarParcelasYMeteo] {len(parcelas)} parcelas, {len(meteo)} municipios con meteo')
            yield parcelas
        except Exception as e:
            logger.error(f'[CargarParcelasYMeteo] Error: {e}')
            yield {}

    def teardown(self):
        if self._connector:
            self._connector.close()


class EscribirFirestore(beam.DoFn):
    """Escribe la lectura en usuarios/{uid}/parcelas/{pid}."""

    def __init__(self, project_id, database):
        self.project_id = project_id
        self.database = database

    def setup(self):
        self._fs = firestore.Client(project=self.project_id, database=self.database)

    def process(self, element):
        try:
            doc = {
                'updated_at': datetime.utcnow().isoformat(),
                'temperatura': element.get('temperatura'),
                'humedad_ambiental': element.get('humedad_ambiental'),
                'humedad_suelo': element.get('humedad_suelo'),
                'precipitacion_mm': element.get('precipitacion_mm'),
                'et0': element.get('et0'),
                'radiacion_solar': element.get('radiacion_solar'),
                'estado_cielo': element.get('estado_cielo'),
                'fuente_temperatura': element.get('fuente_temperatura'),
            }
            doc = {k: v for k, v in doc.items() if v is not None}
            self._fs\
                .collection('usuarios').document(element['user_id'])\
                .collection('parcelas').document(element['parcel_id'])\
                .set(doc, merge=True)
            logger.info(f'[Firestore] OK parcela={element["parcel_id"]}')
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

    # --- Side input: parcelas + meteo, refrescado cada 5 min (test) ---
    parcelas_meteo = (
        p
        | "Reloj" >> PeriodicImpulse(fire_interval=300, apply_windowing=True)
        | "VentanaGlobal" >> beam.WindowInto(
            window.GlobalWindows(),
            trigger=trigger.Repeatedly(trigger.AfterCount(1)),
            accumulation_mode=trigger.AccumulationMode.DISCARDING)
        | "CargarSQL" >> beam.ParDo(CargarParcelasYMeteo(
            PROJECT_ID, INSTANCE_CONNECTION_NAME, DB_USER, DB_PASSWORD, DB_NAME, DB_NAME_METEO))
    )
    vista_parcelas = beam.pvalue.AsSingleton(parcelas_meteo, default_value={})

    # --- Stream principal: parsear y filtrar parcelas ---
    parsed = (
        p
        | "LeerPubSub" >> beam.io.ReadFromPubSub(
            subscription=PUBSUB_SUBSCRIPTION, with_attributes=True)
        | "ParsearMensaje" >> beam.Map(parsearMensaje)
        | "FiltrarParcelas" >> beam.Filter(filtrarParcela)
    )

    # --- Sink Firestore: 1 update por mensaje (sin agregación) ---
    (parsed
     | "EnriquecerFirestore" >> beam.FlatMap(enriquecerConMeteo, parcelas_meteo=vista_parcelas)
     | "EscribirFirestore" >> beam.ParDo(EscribirFirestore(PROJECT_ID, 'ultimas-lecturas')))

    # --- Sink BigQuery: agregación por ventana fija, 1 fila por parcela y ventana ---
    (parsed
     | "ClavePorParcela" >> beam.Map(lambda r: (r['entity_id'], r))
     | "VentanaFija" >> beam.WindowInto(window.FixedWindows(WINDOW_SECONDS))
     | "AgruparPorParcela" >> beam.GroupByKey()
     | "CombinarLecturas" >> beam.FlatMap(combinarLecturas, parcelas_meteo=vista_parcelas)
     | "EscribirBigQuery" >> beam.io.WriteToBigQuery(
         table=BQ_TABLE,
         schema=BQ_SCHEMA,
         write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
         create_disposition=beam.io.BigQueryDisposition.CREATE_NEVER))

    p.run()
    logger.info('Dataflow parcelas streaming job submitted')


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    run()
