import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions, StandardOptions, SetupOptions, GoogleCloudOptions
from apache_beam.transforms.window import FixedWindows
from apache_beam.transforms.periodicsequence import PeriodicImpulse
from apache_beam.transforms import trigger, window
import logging
import json
import argparse


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_message(message):
    try:
        return json.loads(message.decode('utf-8'))
    except Exception as e:
        logging.error(f"Error parsing message: {e}")
        return None


# ── DoFns ─────────────────────────────────────────────────────────────────────

class CargarParcelasSQL(beam.DoFn):
    """Carga todas las parcelas de Cloud SQL como dict {id: {...}}.
    Se refresca cada hora como side input."""

    def __init__(self, instance_connection_name, db_user, db_password, db_name):
        self.instance_connection_name = instance_connection_name
        self.db_user     = db_user
        self.db_password = db_password
        self.db_name     = db_name

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
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT id, parcela_id, cultivo, variedad, lat, lng, provincia, municipio, superficie
            FROM parcelas_usuario
        """)
        parcelas = {}
        for row in cursor.fetchall():
            parcelas[row[0]] = {
                'parcela_id': row[1],
                'cultivo':    row[2],
                'variedad':   row[3],
                'lat':        float(row[4]) if row[4] else None,
                'lng':        float(row[5]) if row[5] else None,
                'provincia':  row[6],
                'municipio':  row[7],
                'superficie': float(row[8]) if row[8] else None,
            }
        logging.info(f"CargarParcelasSQL: {len(parcelas)} parcelas cargadas")
        yield parcelas

    def teardown(self):
        if hasattr(self, '_conn') and self._conn:
            self._conn.close()
        if hasattr(self, '_connector'):
            self._connector.close()


class AgregarYEnriquecer(beam.DoFn):
    """Agrega las lecturas de una ventana de 1h y enriquece con datos de parcela."""

    def process(self, element, parcelas, window=beam.DoFn.WindowParam):
        parcela_usuario_id, readings = element
        readings = list(readings)

        # Pivot readings by sensor_type
        by_type = {}
        for r in readings:
            st = r.get('sensor_type')
            if not st:
                continue
            try:
                by_type.setdefault(st, []).append(float(r['value']))
            except (ValueError, TypeError):
                continue

        def _avg(vals):
            return round(sum(vals) / len(vals), 4) if vals else None

        temperatura       = _avg(by_type.get('temperature', []))
        humedad_suelo     = _avg(by_type.get('soil_moisture', []))
        humedad_ambiental = _avg(by_type.get('ambient_humidity', []))

        if temperatura is None and humedad_suelo is None and humedad_ambiental is None:
            return

        first   = readings[0]
        parcela = parcelas.get(parcela_usuario_id, {})

        yield {
            'user_id':              str(first.get('user_id', '')),
            'parcel_id':            parcela.get('parcela_id'),
            'timestamp':            window.start.to_utc_datetime().strftime('%Y-%m-%dT%H:%M:%S'),
            'temperatura':          temperatura,
            'humedad_ambiental':    humedad_ambiental,
            'humedad_suelo':        humedad_suelo,
            'precipitacion_mm':     None,
            'et0':                  None,
            'radiacion_solar':      None,
            'fuente_temperatura':   'sensor' if temperatura is not None else None,
            'tipo_cultivo':         parcela.get('cultivo'),
            'variedad':             parcela.get('variedad'),
            'fecha_plantacion_aprox': None,
        }


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project_id',               required=True)
    parser.add_argument('--subscription',             required=True, default='sensor-readings-dataflow-sub')
    parser.add_argument('--bq_dataset',               required=True, default='agri_data')
    parser.add_argument('--bq_table',                 required=True, default='lecturas_parcelas')
    parser.add_argument('--instance_connection_name', required=True)
    parser.add_argument('--db_user',                  required=True)
    parser.add_argument('--db_password',              required=True)
    parser.add_argument('--db_name',                  required=True)

    known_args, beam_args = parser.parse_known_args()

    options = PipelineOptions(beam_args)
    options.view_as(StandardOptions).streaming = True
    options.view_as(SetupOptions).save_main_session = True

    gcp = options.view_as(GoogleCloudOptions)
    gcp.project          = known_args.project_id
    gcp.region           = 'europe-west1'
    gcp.job_name         = 'iot-sensor-pipeline'
    gcp.temp_location    = f'gs://{known_args.project_id}-dataflow/temp'
    gcp.staging_location = f'gs://{known_args.project_id}-dataflow/staging'

    sub      = f"projects/{known_args.project_id}/subscriptions/{known_args.subscription}"
    bq_table = f"{known_args.project_id}:{known_args.bq_dataset}.{known_args.bq_table}"
    bq_schema = (
        "user_id:STRING,parcel_id:STRING,timestamp:DATETIME,"
        "temperatura:FLOAT,humedad_ambiental:FLOAT,humedad_suelo:FLOAT,"
        "precipitacion_mm:FLOAT,et0:FLOAT,radiacion_solar:FLOAT,"
        "fuente_temperatura:STRING,tipo_cultivo:STRING,variedad:STRING,"
        "fecha_plantacion_aprox:DATE"
    )

    p = beam.Pipeline(options=options)

    # Side input: parcelas de Cloud SQL, se refresca cada hora
    parcelas_side = (
        p
        | "Reloj"         >> PeriodicImpulse(fire_interval=3600, apply_windowing=True)
        | "VentanaGlobal" >> beam.WindowInto(
            window.GlobalWindows(),
            trigger=trigger.Repeatedly(trigger.AfterCount(1)),
            accumulation_mode=trigger.AccumulationMode.DISCARDING
        )
        | "CargarSQL"     >> beam.ParDo(CargarParcelasSQL(
            instance_connection_name=known_args.instance_connection_name,
            db_user=known_args.db_user,
            db_password=known_args.db_password,
            db_name=known_args.db_name
        ))
    )

    vista_parcelas = beam.pvalue.AsSingleton(parcelas_side, default_value={})

    # Pipeline principal
    (
        p
        | "LeerPubSub"        >> beam.io.ReadFromPubSub(subscription=sub)
        | "Parsear"           >> beam.Map(parse_message)
        | "FiltrarNulos"      >> beam.Filter(lambda x: x is not None)
        | "ClaveParcela"      >> beam.Map(lambda x: (x['parcela_usuario_id'], x))
        | "Ventana1h"         >> beam.WindowInto(FixedWindows(3600))
        | "Agrupar"           >> beam.GroupByKey()
        | "AgregarEnriquecer" >> beam.ParDo(AgregarYEnriquecer(), parcelas=vista_parcelas)
        | "EscribirBQ"        >> beam.io.WriteToBigQuery(
            table=bq_table,
            schema=bq_schema,
            write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
            create_disposition=beam.io.BigQueryDisposition.CREATE_IF_NEEDED
        )
    )

    result = p.run()
    logging.info(f"Job de Dataflow lanzado correctamente. Job ID: {result.job_id()}")


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    logging.info("Arrancando pipeline sensores IoT...")
    run()
