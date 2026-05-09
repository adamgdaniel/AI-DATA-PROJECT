import os
import json
import psycopg2
import requests
from cryptography.fernet import Fernet
from google.cloud import pubsub_v1
from datetime import datetime, timezone


def _decrypt(value: str) -> str:
    return Fernet(os.environ['ENCRYPTION_KEY'].encode()).decrypt(value.encode()).decode()

# La BD guarda sensor_type en inglés; el Dataflow espera español en el atributo sensor_tipo
SENSOR_TYPE_ES = {
    'temperature':        'temperatura',
    'ambient_humidity':   'humedad_ambiental',
    'soil_moisture':      'humedad_suelo',
}

TASK_INDEX = int(os.environ.get('CLOUD_RUN_TASK_INDEX', 0))
TASK_COUNT = int(os.environ.get('CLOUD_RUN_TASK_COUNT', 1))


def get_db():
    return psycopg2.connect(
        host=f"/cloudsql/{os.environ['INSTANCE_CONNECTION_NAME']}",
        database=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD']
    )


def run():
    conn = get_db()
    cur = conn.cursor()

    # Todos los tipos: parcela, invernadero, planta
    cur.execute("""
        SELECT s.sensor_id, s.sensor_type, s.location_id, s.location_type, s.user_id,
               h.ha_url, h.ha_token, h.id
        FROM sensors s
        JOIN ha_connections h ON s.connection_id = h.id
        WHERE s.active = TRUE AND h.id %% %s = %s
    """, (TASK_COUNT, TASK_INDEX))

    rows = cur.fetchall()

    # Agrupar por conexión HA para hacer una sola llamada a /api/states por instancia
    connections = {}
    for row in rows:
        conn_id = row[7]
        if conn_id not in connections:
            connections[conn_id] = {
                'ha_url': _decrypt(row[5]),
                'ha_token': _decrypt(row[6]),
                'sensors': []
            }
        connections[conn_id]['sensors'].append({
            'sensor_id': row[0],       # entity_id de HA
            'sensor_type': row[1],     # temperatura / humedad_ambiental / humedad_suelo
            'location_id': str(row[2]),
            'location_type': row[3],   # parcela / invernadero / planta
            'user_id': str(row[4])
        })

    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(os.environ['GCP_PROJECT'], os.environ['PUBSUB_TOPIC'])
    timestamp = datetime.now(timezone.utc).isoformat()
    futures = []

    for conn_id, connection in connections.items():
        try:
            resp = requests.get(
                f"{connection['ha_url']}/api/states",
                headers={"Authorization": f"Bearer {connection['ha_token']}"},
                timeout=15
            )
            resp.raise_for_status()
            states = {entity['entity_id']: entity for entity in resp.json()}

            cur.execute("UPDATE ha_connections SET last_seen_at = NOW() WHERE id = %s", (conn_id,))

            for sensor in connection['sensors']:
                entity = states.get(sensor['sensor_id'])
                if not entity or entity['state'] in ('unavailable', 'unknown'):
                    continue

                try:
                    valor = float(entity['state'])
                except (ValueError, TypeError):
                    print(f"Valor no numérico para {sensor['sensor_id']}: {entity['state']}")
                    continue

                # Body del mensaje
                body = {
                    'valor': valor,
                    'unidad': entity['attributes'].get('unit_of_measurement'),
                    'sensor_entity_id': sensor['sensor_id'],
                    'timestamp_lectura': timestamp
                }

                # Atributos Pub/Sub — usados por los Dataflows para filtrar y enrutar
                attributes = {
                    'entity_type': sensor['location_type'],
                    'entity_id': sensor['location_id'],
                    'usuario_id': sensor['user_id'],
                    'sensor_tipo': SENSOR_TYPE_ES.get(sensor['sensor_type'], sensor['sensor_type'])
                }

                futures.append(
                    publisher.publish(
                        topic_path,
                        json.dumps(body).encode('utf-8'),
                        **attributes
                    )
                )

        except requests.exceptions.RequestException as e:
            print(f"Error HA connection {conn_id}: {e}")
            continue

    published = 0
    for future in futures:
        try:
            future.result()
            published += 1
        except Exception as e:
            print(f"Error confirmando publicación en Pub/Sub: {e}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"Task {TASK_INDEX}/{TASK_COUNT}: {published} lecturas confirmadas en Pub/Sub")


if __name__ == '__main__':
    run()
