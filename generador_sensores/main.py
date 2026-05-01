import os
import json
import math
import random
from datetime import datetime, timezone
from google.cloud import pubsub_v1, firestore

GCP_PROJECT = os.environ['GCP_PROJECT']
PUBSUB_TOPIC = os.environ['PUBSUB_TOPIC']
USER_ID = int(os.environ['USER_ID'])

# FS-EXT: exterior mediterráneo (16-26°C)
# FS-GH:  invernadero (22-30°C, humedad alta)
SENSORS = [
    {'id': 'FS001', 'type': 'exterior',   'parcela_usuario_id': int(os.environ['PARCELA_EXT_1_ID']), 'variant': 0},
    {'id': 'FS002', 'type': 'exterior',   'parcela_usuario_id': int(os.environ['PARCELA_EXT_2_ID']), 'variant': 1},
    {'id': 'FS003', 'type': 'greenhouse', 'parcela_usuario_id': int(os.environ['PARCELA_GH_1_ID']),  'variant': 0},
    {'id': 'FS004', 'type': 'greenhouse', 'parcela_usuario_id': int(os.environ['PARCELA_GH_2_ID']),  'variant': 1},
]


def exterior_targets(hour: float):
    """Temperatura 16-26°C (máx 14h), humedad ambiente 40-85%, humedad suelo 37-53%."""
    angle = 2 * math.pi * (hour - 14) / 24
    temperatura = 21.0 + 5.0 * math.sin(angle)
    humedad_ambiental = 62.5 - 22.5 * math.sin(angle)
    soil_angle = 2 * math.pi * (hour - 8) / 24
    humedad_suelo = 45.0 - 8.0 * math.sin(soil_angle)
    return temperatura, humedad_ambiental, humedad_suelo


def greenhouse_targets(hour: float):
    """Temperatura 22-30°C (más estable), humedad ambiente 65-80%, humedad suelo 61-69%."""
    angle = 2 * math.pi * (hour - 14) / 24
    temperatura = 26.0 + 4.0 * math.sin(angle)
    humedad_ambiental = 72.5 - 7.5 * math.sin(angle)
    humedad_suelo = 65.0 - 4.0 * math.sin(angle)
    return temperatura, humedad_ambiental, humedad_suelo


def smooth_move(current: float, target: float, max_step: float, noise_std: float) -> float:
    """Mueve current hacia target un máximo de max_step, con ruido gaussiano pequeño."""
    diff = target - current
    step = max(-max_step, min(max_step, diff * 0.25))
    return round(current + step + random.gauss(0, noise_std), 2)


def run():
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60.0
    timestamp = now.isoformat()

    publisher = pubsub_v1.PublisherClient()
    db = firestore.Client(project=GCP_PROJECT)
    topic_path = publisher.topic_path(GCP_PROJECT, PUBSUB_TOPIC)
    published = 0

    for sensor in SENSORS:
        target_fn = exterior_targets if sensor['type'] == 'exterior' else greenhouse_targets
        t_target, h_target, s_target = target_fn(hour)

        # Pequeña diferencia entre los dos sensores del mismo tipo
        offset = (sensor['variant'] - 0.5)
        t_target += offset * 0.6
        h_target += offset * 1.0
        s_target += offset * 0.8

        doc_ref = db.collection('fake_sensors').document(sensor['id'])
        doc = doc_ref.get()

        if doc.exists:
            last = doc.to_dict()
            temperatura       = smooth_move(last['temperatura'],       t_target, max_step=0.8,  noise_std=0.15)
            humedad_ambiental = smooth_move(last['humedad_ambiental'], h_target, max_step=1.5,  noise_std=0.30)
            humedad_suelo     = smooth_move(last['humedad_suelo'],     s_target, max_step=0.5,  noise_std=0.10)
        else:
            # Primera ejecución: inicializar cerca del valor objetivo
            temperatura       = round(t_target + random.gauss(0, 0.3), 2)
            humedad_ambiental = round(h_target + random.gauss(0, 0.5), 2)
            humedad_suelo     = round(s_target + random.gauss(0, 0.3), 2)

        doc_ref.set({
            'temperatura':       temperatura,
            'humedad_ambiental': humedad_ambiental,
            'humedad_suelo':     humedad_suelo,
            'updated_at':        timestamp,
        })

        metrics = [
            ('temperature',      temperatura,       '°C'),
            ('ambient_humidity', humedad_ambiental, '%'),
            ('soil_moisture',    humedad_suelo,     '%'),
        ]

        for sensor_type, value, unit in metrics:
            msg = {
                'sensor_id':          sensor['id'],
                'sensor_type':        sensor_type,
                'parcela_usuario_id': sensor['parcela_usuario_id'],
                'user_id':            USER_ID,
                'value':              str(value),
                'unit':               unit,
                'timestamp':          timestamp,
            }
            publisher.publish(topic_path, json.dumps(msg).encode('utf-8'))
            published += 1

        print(f"{sensor['id']}: temp={temperatura}°C  hum_amb={humedad_ambiental}%  hum_suelo={humedad_suelo}%")

    print(f"Total: {published} lecturas publicadas en Pub/Sub")


if __name__ == '__main__':
    run()
