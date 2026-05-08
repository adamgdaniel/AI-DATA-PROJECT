import os
import json
import math
import random
from datetime import datetime, timezone
from google.cloud import pubsub_v1, firestore

GCP_PROJECT = os.environ['GCP_PROJECT']
PUBSUB_TOPIC = os.environ['PUBSUB_TOPIC']
USER_ID = str(os.environ['USER_ID'])

# Exterior: temperatura 16-26°C, humedad ambiente 40-85%, humedad suelo 37-53%
# Invernadero: temperatura 22-30°C (estable), humedad ambiente 65-80%, humedad suelo 61-69%
SENSORS = [
    {
        'id': 'FS-EXT-001',
        'type': 'exterior',
        'entity_type': 'parcela',
        'entity_id': str(os.environ['PARCELA_EXT_1_ID']),
        'variant': 0,
    },
    {
        'id': 'FS-EXT-002',
        'type': 'exterior',
        'entity_type': 'parcela',
        'entity_id': str(os.environ['PARCELA_EXT_2_ID']),
        'variant': 1,
    },
    {
        'id': 'FS-GH-001',
        'type': 'greenhouse',
        'invernadero_id': str(os.environ['INVERNADERO_1_ID']),
        'planta_id': str(os.environ['PLANTA_GH_1_ID']),
        'variant': 0,
    },
    {
        'id': 'FS-GH-002',
        'type': 'greenhouse',
        'invernadero_id': str(os.environ['INVERNADERO_2_ID']),
        'planta_id': str(os.environ['PLANTA_GH_2_ID']),
        'variant': 1,
    },
]


def exterior_targets(hour: float):
    angle = 2 * math.pi * (hour - 14) / 24
    temperatura = 21.0 + 5.0 * math.sin(angle)
    humedad_ambiental = 62.5 - 22.5 * math.sin(angle)
    soil_angle = 2 * math.pi * (hour - 8) / 24
    humedad_suelo = 45.0 - 8.0 * math.sin(soil_angle)
    return temperatura, humedad_ambiental, humedad_suelo


def greenhouse_targets(hour: float):
    angle = 2 * math.pi * (hour - 14) / 24
    temperatura = 26.0 + 4.0 * math.sin(angle)
    humedad_ambiental = 72.5 - 7.5 * math.sin(angle)
    humedad_suelo = 65.0 - 4.0 * math.sin(angle)
    return temperatura, humedad_ambiental, humedad_suelo


def smooth_move(current: float, target: float, max_step: float, noise_std: float) -> float:
    diff = target - current
    step = max(-max_step, min(max_step, diff * 0.25))
    return round(current + step + random.gauss(0, noise_std), 2)


def publish(publisher, topic_path, entity_type, entity_id, sensor_tipo, valor, unidad, timestamp):
    body = {
        'valor': valor,
        'unidad': unidad,
        'sensor_entity_id': f'sensor.fake_{entity_type}_{entity_id}_{sensor_tipo}',
        'timestamp_lectura': timestamp,
    }
    attrs = {
        'entity_type': entity_type,
        'entity_id': entity_id,
        'usuario_id': USER_ID,
        'sensor_tipo': sensor_tipo,
    }
    return publisher.publish(topic_path, json.dumps(body).encode('utf-8'), **attrs)


def run():
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60.0
    timestamp = now.isoformat()

    publisher = pubsub_v1.PublisherClient()
    db = firestore.Client(project=GCP_PROJECT)
    topic_path = publisher.topic_path(GCP_PROJECT, PUBSUB_TOPIC)
    futures = []

    for sensor in SENSORS:
        target_fn = exterior_targets if sensor['type'] == 'exterior' else greenhouse_targets
        t_target, h_target, s_target = target_fn(hour)

        offset = (sensor['variant'] - 0.5)
        t_target += offset * 0.6
        h_target += offset * 1.0
        s_target += offset * 0.8

        doc_ref = db.collection('fake_sensors').document(sensor['id'])
        doc = doc_ref.get()

        if doc.exists:
            last = doc.to_dict()
            temperatura       = smooth_move(last['temperatura'],       t_target, 0.8,  0.15)
            humedad_ambiental = smooth_move(last['humedad_ambiental'], h_target, 1.5,  0.30)
            humedad_suelo     = smooth_move(last['humedad_suelo'],     s_target, 0.5,  0.10)
        else:
            temperatura       = round(t_target + random.gauss(0, 0.3), 2)
            humedad_ambiental = round(h_target + random.gauss(0, 0.5), 2)
            humedad_suelo     = round(s_target + random.gauss(0, 0.3), 2)

        doc_ref.set({
            'temperatura':       temperatura,
            'humedad_ambiental': humedad_ambiental,
            'humedad_suelo':     humedad_suelo,
            'updated_at':        timestamp,
        })

        if sensor['type'] == 'exterior':
            entity_id = sensor['entity_id']
            futures.append(publish(publisher, topic_path, 'parcela', entity_id, 'temperatura',       temperatura,       '°C', timestamp))
            futures.append(publish(publisher, topic_path, 'parcela', entity_id, 'humedad_ambiental', humedad_ambiental, '%',  timestamp))
            futures.append(publish(publisher, topic_path, 'parcela', entity_id, 'humedad_suelo',     humedad_suelo,     '%',  timestamp))
        else:
            inv_id   = sensor['invernadero_id']
            plant_id = sensor['planta_id']
            # Temperatura y humedad ambiental son del invernadero
            futures.append(publish(publisher, topic_path, 'invernadero', inv_id,   'temperatura',       temperatura,       '°C', timestamp))
            futures.append(publish(publisher, topic_path, 'invernadero', inv_id,   'humedad_ambiental', humedad_ambiental, '%',  timestamp))
            # Humedad de suelo es de la planta
            futures.append(publish(publisher, topic_path, 'planta',      plant_id, 'humedad_suelo',     humedad_suelo,     '%',  timestamp))

        print(f"{sensor['id']}: temp={temperatura}°C  hum_amb={humedad_ambiental}%  hum_suelo={humedad_suelo}%")

    published = 0
    for f in futures:
        try:
            f.result()
            published += 1
        except Exception as e:
            print(f"Error publicando: {e}")

    print(f"Total: {published} lecturas publicadas en Pub/Sub")


if __name__ == '__main__':
    run()
