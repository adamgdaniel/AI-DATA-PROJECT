import os
import json
import psycopg2
import requests
from cryptography.fernet import Fernet
from google.cloud import pubsub_v1
from datetime import datetime, timezone


def _decrypt(value: str) -> str:
    return Fernet(os.environ['ENCRYPTION_KEY'].encode()).decrypt(value.encode()).decode()

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

    cur.execute("""
        SELECT s.id, s.sensor_id, s.sensor_type, s.parcela_usuario_id, s.user_id,
               h.ha_url, h.ha_token, h.id
        FROM sensors s
        JOIN ha_connections h ON s.connection_id = h.id
        WHERE s.active = TRUE AND s.id %% %s = %s
    """, (TASK_COUNT, TASK_INDEX))

    rows = cur.fetchall()

    # Agrupar por conexión HA para hacer una sola llamada por instancia
    connections = {}
    for row in rows:
        conn_id = row[7]
        if conn_id not in connections:
            connections[conn_id] = {
                'ha_url': row[5],
                'ha_token': _decrypt(row[6]),
                'sensors': []
            }
        connections[conn_id]['sensors'].append({
            'sensor_id': row[1],
            'sensor_type': row[2],
            'parcela_usuario_id': row[3],
            'user_id': row[4]
        })

    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(os.environ['GCP_PROJECT'], os.environ['PUBSUB_TOPIC'])
    timestamp = datetime.now(timezone.utc).isoformat()
    published = 0

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

                message = {
                    'sensor_id': sensor['sensor_id'],
                    'sensor_type': sensor['sensor_type'],
                    'parcela_usuario_id': sensor['parcela_usuario_id'],
                    'user_id': sensor['user_id'],
                    'value': entity['state'],
                    'unit': entity['attributes'].get('unit_of_measurement'),
                    'timestamp': timestamp
                }
                publisher.publish(topic_path, json.dumps(message).encode('utf-8'))
                published += 1

        except requests.exceptions.RequestException as e:
            print(f"Error HA connection {conn_id}: {e}")
            continue

    conn.commit()
    cur.close()
    conn.close()
    print(f"Task {TASK_INDEX}/{TASK_COUNT}: {published} lecturas publicadas en Pub/Sub")


if __name__ == '__main__':
    run()
