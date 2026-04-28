import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions, StandardOptions, SetupOptions
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
            SELECT id, parcela_id, cultivo, lat, lng, provincia, municipio, superficie
            FROM parcelas_usuario
        """)
        parcelas = {}
        for row in cursor.fetchall():
            parcelas[row[0]] = {
                'parcela_id': row[1],
                'cultivo':    row[2],
                'lat':        float(row[3]) if row[3] else None,
                'lng':        float(row[4]) if row[4] else None,
                'provincia':  row[5],
                'municipio':  row[6],
                'superficie': float(row[7]) if row[7] else None,
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
        key, readings = element
        readings = list(readings)

        values = []
        for r in readings:
            try:
                values.append(float(r['value']))
            except (ValueError, TypeError):
                continue

        if not values:
            return

        first   = readings[0]
        parcela = parcelas.get(first['parcela_usuario_id'], {})

        yield {
            'sensor_id':          first['sensor_id'],
            'sensor_type':        first['sensor_type'],
            'parcela_usuario_id': first['parcela_usuario_id'],
            'parcela_id':         parcela.get('parcela_id'),
            'user_id':            first['user_id'],
            'cultivo':            parcela.get('cultivo'),
            'lat':                parcela.get('lat'),
            'lng':                parcela.get('lng'),
            'provincia':          parcela.get('provincia'),
            'municipio':          parcela.get('municipio'),
            'superficie':         parcela.get('superficie'),
            'window_start':       window.start.to_utc_datetime().isoformat(),
            'window_end':         window.end.to_utc_datetime().isoformat(),
            'value_avg':          round(sum(values) / len(values), 4),
            'value_min':          min(values),
            'value_max':          max(values),
            'reading_count':      len(values),
            'unit':               first.get('unit'),
        }


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project_id',               required=True)
    parser.add_argument('--subscription',             required=True, default='sensor-readings-dataflow-sub')
    parser.add_argument('--bq_dataset',               required=True, default='iot_data')
    parser.add_argument('--bq_table',                 required=True, default='sensor_aggregated')
    parser.add_argument('--instance_connection_name', required=True)
    parser.add_argument('--db_user',                  required=True)
    parser.add_argument('--db_password',              required=True)
    parser.add_argument('--db_name',                  required=True)

    known_args, beam_args = parser.parse_known_args()

    options = PipelineOptions(beam_args)
    options.view_as(StandardOptions).streaming = True
    options.view_as(SetupOptions).save_main_session = True

    sub      = f"projects/{known_args.project_id}/subscriptions/{known_args.subscription}"
    bq_table = f"{known_args.project_id}:{known_args.bq_dataset}.{known_args.bq_table}"
    bq_schema = (
        "sensor_id:STRING,sensor_type:STRING,parcela_usuario_id:INTEGER,"
        "parcela_id:STRING,user_id:INTEGER,cultivo:STRING,lat:FLOAT,lng:FLOAT,"
        "provincia:INTEGER,municipio:INTEGER,superficie:FLOAT,"
        "window_start:TIMESTAMP,window_end:TIMESTAMP,"
        "value_avg:FLOAT,value_min:FLOAT,value_max:FLOAT,"
        "reading_count:INTEGER,unit:STRING"
    )

    with beam.Pipeline(options=options) as p:

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
            | "ClaveSensor"       >> beam.Map(lambda x: (x['sensor_id'], x))
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


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    logging.info("Arrancando pipeline sensores IoT...")
    run()
