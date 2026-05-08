import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions, StandardOptions, SetupOptions
from apache_beam.transforms.window import FixedWindows
from apache_beam.transforms.periodicsequence import PeriodicImpulse
from apache_beam.transforms import trigger
from apache_beam.transforms import window
import logging
import json
import os
import argparse
from geopy.distance import geodesic
from google.cloud import firestore
import math
from dotenv import load_dotenv
from google.cloud import secretmanager

load_dotenv()

### FUNCIONES
def parsePubSubMessage(message):
    try:
        message_str = message.decode('utf-8')
        message_dict = json.loads(message_str)

        logging.info(f"Parsed message: {message_dict}")

        return message_dict
    except Exception as e:
        logging.error(f"Error parsing message: {e}")
        return None


def normalizeVictimas(event):
    coords = event["coordinates"]
    if isinstance(coords, list):
        coords = f"{coords[0]},{coords[1]}"
   
    return {
        "user_id": event["user_id"],
        "coordinates": str(coords),
        "timestamp": event["timestamp"],
        "tipo": "victima",
    }

def normalizeAgresores(event):
    coords = event["coordinates"]
    if isinstance(coords, list):
        coords = f"{coords[0]},{coords[1]}"
  
    return {
        "user_id": event["user_id"],
        "coordinates": str(coords),
        "timestamp": event["timestamp"],
        "tipo": "agresor",
    }

def cruzar_datos_en_memoria(datos_victima, datos_maestros):
    if not datos_victima: return
    
    uid = str(datos_victima['user_id'])
    info_victima_db = datos_maestros.get(uid)
    
    if info_victima_db:
        datos_victima['safe_zones'] = info_victima_db['zonas']
        
        for id_agresor, dist in info_victima_db['agresores'].items():

            victima_datos = datos_victima.copy()
            victima_datos['dist_seguridad'] = dist           
            yield (id_agresor, victima_datos)

def calcular_direccion_escape(coords_victima, coords_agresor):
    coordv_limpias = str(coords_victima).replace('[', '').replace(']', '')
    coorda_limpias = str(coords_agresor).replace('[', '').replace(']', '')
    lat_v, lon_v = map(float, coordv_limpias.split(','))
    lat_a, lon_a = map(float, coorda_limpias.split(','))


    d_lat = lat_a - lat_v
    d_lon = lon_a - lon_v

    angulo = math.degrees(math.atan2(d_lat, d_lon))
    if angulo < 0:
        angulo += 360


    if 22.5 <= angulo < 67.5: return "Noreste"
    elif 67.5 <= angulo < 112.5: return "Norte"
    elif 112.5 <= angulo < 157.5: return "Noroeste"
    elif 157.5 <= angulo < 202.5: return "Oeste"
    elif 202.5 <= angulo < 247.5: return "Suroeste"
    elif 247.5 <= angulo < 292.5: return "Sur"
    elif 292.5 <= angulo < 337.5: return "Sureste"
    else: return "Este"

def detectar_match(elemento):

    id_agresor, usuarios = elemento

    datos_agresor = None
    victimas = []

    for e in usuarios:
        if e['tipo'] == 'agresor':
            datos_agresor = e
        elif e['tipo'] == 'victima':
            victimas.append(e)

    if not datos_agresor or not victimas:
        return []

    # Calcular distancias
    alertas_json = []
    for vic in victimas:
        distancia_configurada = vic.get('dist_seguridad', 500)
        dist_fisica = round(geodesic(datos_agresor['coordinates'], vic['coordinates']).meters,2)
        
        if dist_fisica < distancia_configurada:
                direccion_escape = calcular_direccion_escape(vic['coordinates'], datos_agresor['coordinates'])
                alerta = {
                    "alerta": "fisica",
                    "activa": True,
                    "id_victima": vic['user_id'],
                    "id_agresor": id_agresor,
                    "distancia_metros": dist_fisica,
                    "direccion_escape": direccion_escape,
                    "coordenadas_agresor": datos_agresor['coordinates'], 
                    "coordenadas_victima": vic['coordinates'],
                    "timestamp": datos_agresor['timestamp'],
                    "dist_seguridad": distancia_configurada,
                }

                alertas_json.append(alerta)
                print(f"🚨 JSON ALERTA GENERADO (FISICA): {alerta}")
            
    #matches de zona
        for zona in vic.get('safe_zones', []):
                    
                    dist_zona = geodesic(datos_agresor['coordinates'], zona['place_coordinates']).meters
                    
                    if dist_zona < (distancia_configurada + zona['radius']):
                        direccion_escape = calcular_direccion_escape(zona['place_coordinates'], datos_agresor['coordinates'])
                        alerta = {
                            "alerta": "place",
                            "activa": True,
                            "id_victima": vic['user_id'],
                            "id_agresor": id_agresor,
                            "id_place": zona['id_place'],
                            "nombre_place": zona['place_name'], 
                            "distancia_metros": round(dist_zona, 2),
                            "direccion_escape": direccion_escape,
                            "radio_zona": zona['radius'],
                            "coordenadas_agresor": datos_agresor['coordinates'],
                            "coordenadas_place": str(zona['place_coordinates']),
                            "timestamp": datos_agresor['timestamp'],
                            "dist_seguridad": distancia_configurada,
                        }
                        alertas_json.append(alerta)
                        print(f"🏰 JSON ALERTA GENERADO (Place): {alerta}") 
            
    return alertas_json


### CLASES

class CargarDatosMaestros(beam.DoFn):

    def __init__(self, project_id, db_host, db_user, secret_pass, db_name):
            self.project_id = project_id
            self.db_host = db_host
            self.db_user = db_user
            self.db_name = db_name
            self.secret_pass = secret_pass
            self.conn = None
            

    def setup(self):
        client = secretmanager.SecretManagerServiceClient()
        ruta_secreto = f"projects/{self.project_id}/secrets/{self.secret_pass}/versions/latest"
        respuesta = client.access_secret_version(request={"name": ruta_secreto})
        db_pass_seguro = respuesta.payload.data.decode("UTF-8")
        import psycopg2
        self.conn = psycopg2.connect(
            host=self.db_host, 
            user=self.db_user,
            password=db_pass_seguro,
            dbname=self.db_name
        )

    def process(self, element):
        cursor = self.conn.cursor()
        datos_maestros = {}

        #Cargar Agrersores-victimas
        try:
    
            cursor.execute("SELECT id_victima, id_agresor, dist_seguridad FROM rel_victimas_agresores")
            for vic, agr, dist in cursor.fetchall():
                vic, agr = str(vic).strip(), str(agr).strip()
                dist_seguridad = float(dist) if dist is not None else 500.0
                if vic not in datos_maestros:
                    datos_maestros[vic] = {'agresores': {}, 'zonas': []}
                datos_maestros[vic]['agresores'][agr] = dist_seguridad

        #Cargar Safe Places
            query_zonas = """
                        SELECT r.id_victima, s.place_name, s.place_coordinates, s.radius, s.id_place 
                        FROM safe_places s
                        JOIN rel_places_victimas r ON s.id_place = r.id_place
                    """
            cursor.execute(query_zonas)

            for row in cursor.fetchall():
                        vic = row[0]
                        
                        if vic in datos_maestros:

                            datos_maestros[vic]['zonas'].append({
                                "place_name": row[1],
                                "id_place": row[4],
                                "place_coordinates": row[2],
                                "radius": float(row[3])
                            })
            yield datos_maestros

        except Exception as e:
            logging.error(f"❌ Error cargando DB: {e}. Forzando reintento...")
            raise e
    #aqui tenemos: { "vic_001": {"agresores": ["ag_001", "ag_002"], "zonas": [{"place_name": "Casa Alfredo", "id_place": "place_001", "place_coordinates": (39.4700, -0.3765), "radius": 300}

    def teardown(self):
        if self.conn:
            self.conn.close()


class FormatFirestoreDocument(beam.DoFn):
    def __init__(self, project_id, firestore_collection, firestore_database):
        self.project_id = project_id
        self.collection = firestore_collection
        self.database = firestore_database

    def setup(self):
        from google.cloud import firestore
        self.db = firestore.Client(project=self.project_id, database=self.database)

    def process(self, element):

        if element.get('alerta') == 'place':
            doc_id = f"{element['id_place']}_{element['id_agresor']}"
        else:
            doc_id = f"{element['id_victima']}_{element['id_agresor']}"
        try:
            self.db.collection(self.collection).document(doc_id).set(element, merge=True)
        except Exception as e:
            import logging
            logging.error(f"Error guardando en Firestore: {e}")
        yield element  

    def teardown(self):
        if hasattr(self, 'db'):
            self.db.close()



### PIPELINE

def run():

    parser = argparse.ArgumentParser(description=('Input arguments for the Dataflow Streaming Pipeline.'),allow_abbrev=False)

    parser.add_argument(
                '--project_id',
                required=True,
                default=os.getenv("PROJECT_ID"),
                help='GCP cloud project name.')
    
    parser.add_argument(
                '--victimas_pubsub_subscription_name',
                required=True,
                default= "victimas-datos-sub",
                help='Pub/Sub subscription for victim events.')
    
    parser.add_argument(
                '--agresores_pubsub_subscription_name',
                required=True,
                default= "agresores-datos-sub",
                help='Pub/Sub subscription for engagement events.')
    
    parser.add_argument(
            '--firestore_db',
            required=True,
            help='Firestore database name.')

    parser.add_argument(
            '--firestore_collection',
            required=True,
            help='Firestore collection name.')

    
    parser.add_argument(
                '--bigquery_dataset',
                required=False,
                default="analitical_dataset5",
                help='BigQuery dataset name.')    
    
    parser.add_argument(
                '--alertas_bigquery_table',
                required=True,
                help='Alertas BigQuery table name.')
    
    #info de la db
    parser.add_argument('--db_host', required=True)
    parser.add_argument('--db_user', required=True)
    parser.add_argument('--db_pass', required=False, default="db-password-dp") 
    parser.add_argument('--db_name', required=True)
    
    # Parseamos
    known_args, beam_args = parser.parse_known_args()
    # Pipeline Options
    options = PipelineOptions(beam_args)
    options.view_as(StandardOptions).streaming = True

    options.view_as(SetupOptions).save_main_session = True
    

    sub_v = f"projects/{known_args.project_id}/subscriptions/{known_args.victimas_pubsub_subscription_name}"
    sub_a = f"projects/{known_args.project_id}/subscriptions/{known_args.agresores_pubsub_subscription_name}"
    firestore_database = known_args.firestore_db
    ruta_bq = f"{known_args.project_id}:{known_args.bigquery_dataset}.{known_args.alertas_bigquery_table}"
    esquema_alertas = "alerta:STRING, activa:BOOLEAN, nivel:STRING, id_victima:STRING, id_agresor:STRING, distancia_metros:FLOAT, direccion_escape:STRING, coordenadas_agresor:STRING, coordenadas_victima:STRING, coordenadas_place:STRING, timestamp:TIMESTAMP, dist_seguridad:FLOAT, distancia_limite:FLOAT, id_place:STRING, nombre_place:STRING, radio_zona:FLOAT"
   
    with beam.Pipeline(options=options) as p:
        datos_side_input = (
            p
            | "Reloj" >> PeriodicImpulse(fire_interval=900, apply_windowing=True)
            | "VentanaGlobal" >> beam.WindowInto(window.GlobalWindows(), trigger=trigger.Repeatedly(trigger.AfterCount(1)), accumulation_mode=trigger.AccumulationMode.DISCARDING)
            | "CargarDB" >> beam.ParDo(CargarDatosMaestros(project_id=known_args.project_id,db_host=known_args.db_host, db_user=known_args.db_user, secret_pass=known_args.db_pass, db_name=known_args.db_name))
            )

        vista_datos_maestros = beam.pvalue.AsSingleton(datos_side_input, default_value={})

        victimas = (
            p 
            | "LeerVictimas" >> beam.io.ReadFromPubSub(subscription=sub_v)
            | "ParsearV" >> beam.Map(parsePubSubMessage)
            | "FormatearV" >> beam.Map(normalizeVictimas)
            | "CruzarDB" >> beam.FlatMap(cruzar_datos_en_memoria, datos_maestros=vista_datos_maestros)

        )
        agresores = (
            p 
            | "LeerAgresores" >> beam.io.ReadFromPubSub(subscription=sub_a)
            | "ParsearA" >> beam.Map(parsePubSubMessage)
            | "FormatearA" >> beam.Map(normalizeAgresores)
            | "ClaveAgresor" >> beam.Map(lambda x: (x['user_id'], x))

        )

        # Match
        alertas = (
            (victimas, agresores)
            | "UnirTodo" >> beam.Flatten()
            | "Ventana15s" >> beam.WindowInto(FixedWindows(15))
            | "Agrupar" >> beam.GroupByKey()
            | "Calcular" >> beam.FlatMap(detectar_match)
        )


        (alertas
         | "EnviarFirestore" >> beam.ParDo(FormatFirestoreDocument(firestore_collection=known_args.firestore_collection, project_id=known_args.project_id, firestore_database=firestore_database))
         )


        (alertas
         | "EscribirBQ" >> beam.io.WriteToBigQuery(
                table=ruta_bq,
                schema=esquema_alertas,
                write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
                create_disposition=beam.io.BigQueryDisposition.CREATE_IF_NEEDED
            ))


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    print("🚀 Arrancando Pipeline...")
    run()