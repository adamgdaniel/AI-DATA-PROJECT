from flask import Flask, request, jsonify
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from google.cloud import pubsub_v1
import psycopg2
import requests
import json
import os
from datetime import datetime, timezone, timedelta

load_dotenv()

app = Flask(__name__)

_publisher = None
_tasks_client = None

def _get_publisher():
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def _get_tasks_client():
    global _tasks_client
    if _tasks_client is None:
        from google.cloud import tasks_v2
        _tasks_client = tasks_v2.CloudTasksClient()
    return _tasks_client

def _encrypt(value: str) -> str:
    return Fernet(os.environ['ENCRYPTION_KEY'].encode()).encrypt(value.encode()).decode()

def _decrypt(value: str) -> str:
    return Fernet(os.environ['ENCRYPTION_KEY'].encode()).decrypt(value.encode()).decode()

DEVICE_CLASS_MAP = {
    'moisture': 'soil_moisture',
    'temperature': 'temperature',
    'humidity': 'ambient_humidity'
}

VALVE_DOMAINS = ('switch', 'valve', 'light', 'input_boolean')


def get_db():
    return psycopg2.connect(
        host=f"/cloudsql/{os.environ['INSTANCE_CONNECTION_NAME']}",
        database=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD']
    )


@app.route('/ha/connect', methods=['POST'])
def ha_connect():
    data = request.json
    user_id = data.get('user_id')
    ha_url = data.get('ha_url', '').rstrip('/')
    ha_token = data.get('ha_token')
    display_name = data.get('display_name')

    if not all([user_id, ha_url, ha_token]):
        return jsonify({'error': 'user_id, ha_url y ha_token son requeridos'}), 400

    try:
        resp = requests.get(
            f"{ha_url}/api/",
            headers={"Authorization": f"Bearer {ha_token}"},
            timeout=10
        )
        if resp.status_code != 200:
            return jsonify({'error': 'No se pudo conectar a Home Assistant. Verifica la URL y el token.'}), 400
    except requests.exceptions.RequestException:
        return jsonify({'error': 'No se pudo conectar a Home Assistant. Verifica la URL y el token.'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ha_connections (user_id, ha_url, ha_token, display_name, last_seen_at)
        VALUES (%s, %s, %s, %s, NOW())
        RETURNING id
    """, (user_id, _encrypt(ha_url), _encrypt(ha_token), display_name))
    connection_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'connection_id': connection_id}), 201


@app.route('/ha/connections', methods=['GET'])
def ha_get_connections():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id requerido'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, ha_url, display_name, created_at, last_seen_at
        FROM ha_connections WHERE user_id = %s ORDER BY created_at DESC
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([{
        'connection_id': r[0],
        'ha_url': _decrypt(r[1]),
        'display_name': r[2],
        'created_at': r[3].isoformat(),
        'last_seen_at': r[4].isoformat() if r[4] else None
    } for r in rows])


@app.route('/ha/connections/<int:connection_id>', methods=['DELETE'])
def ha_delete_connection(connection_id):
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id requerido'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM ha_connections WHERE id = %s AND user_id = %s", (connection_id, user_id))
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()

    if not deleted:
        return jsonify({'error': 'Conexión no encontrada'}), 404
    return jsonify({'success': True})


@app.route('/ha/sensores/discover', methods=['GET'])
def ha_discover():
    connection_id = request.args.get('connection_id')
    if not connection_id:
        return jsonify({'error': 'connection_id requerido'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT ha_url, ha_token FROM ha_connections WHERE id = %s", (connection_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return jsonify({'error': 'Conexión no encontrada'}), 404

    ha_url, ha_token = _decrypt(row[0]), _decrypt(row[1])

    try:
        resp = requests.get(
            f"{ha_url}/api/states",
            headers={"Authorization": f"Bearer {ha_token}"},
            timeout=15
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException:
        return jsonify({'error': 'No se pudo contactar con Home Assistant'}), 502

    sensores = []
    for entity in resp.json():
        device_class = entity.get('attributes', {}).get('device_class')
        if device_class in DEVICE_CLASS_MAP:
            sensores.append({
                'sensor_id': entity['entity_id'],
                'display_name': entity['attributes'].get('friendly_name', entity['entity_id']),
                'sensor_type': DEVICE_CLASS_MAP[device_class],
                'state': entity['state'],
                'unit': entity['attributes'].get('unit_of_measurement')
            })

    return jsonify(sensores)


@app.route('/ha/sensores', methods=['POST'])
def ha_registrar_sensor():
    data = request.json
    required = ['sensor_id', 'connection_id', 'user_id', 'location_id', 'sensor_type']
    if not all(data.get(k) for k in required):
        return jsonify({'error': f'Campos requeridos: {", ".join(required)}'}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT id FROM parcelas_usuario WHERE id = %s AND usuario_id = %s",
        (data['location_id'], data['user_id'])
    )
    if not cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({'error': 'Parcela no encontrada o no pertenece al usuario'}), 403

    try:
        cur.execute("""
            INSERT INTO sensors (sensor_id, connection_id, user_id, location_id, location_type, sensor_type, display_name)
            VALUES (%s, %s, %s, %s, 'parcela', %s, %s)
        """, (
            data['sensor_id'], data['connection_id'], data['user_id'],
            data['location_id'], data['sensor_type'], data.get('display_name')
        ))
        conn.commit()
        return jsonify({'success': True}), 201
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({'error': 'Este sensor ya está registrado en esta parcela'}), 409
    finally:
        cur.close()
        conn.close()


@app.route('/ha/sensores', methods=['GET'])
def ha_get_sensores():
    user_id = request.args.get('user_id')
    parcela_usuario_id = request.args.get('parcela_usuario_id')

    if not user_id and not parcela_usuario_id:
        return jsonify({'error': 'user_id o parcela_usuario_id requerido'}), 400

    conn = get_db()
    cur = conn.cursor()

    if parcela_usuario_id:
        cur.execute("""
            SELECT sensor_id, sensor_type, display_name, active, created_at
            FROM sensors WHERE location_id = %s AND location_type = 'parcela' AND active = TRUE
        """, (parcela_usuario_id,))
    else:
        cur.execute("""
            SELECT sensor_id, sensor_type, display_name, active, created_at
            FROM sensors WHERE user_id = %s AND active = TRUE
        """, (user_id,))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([{
        'sensor_id': r[0],
        'sensor_type': r[1],
        'display_name': r[2],
        'active': r[3],
        'created_at': r[4].isoformat()
    } for r in rows])


@app.route('/ha/sensores', methods=['DELETE'])
def ha_eliminar_sensor():
    sensor_id = request.args.get('sensor_id')
    user_id = request.args.get('user_id')
    location_id = request.args.get('location_id')

    if not all([sensor_id, user_id, location_id]):
        return jsonify({'error': 'sensor_id, user_id y location_id requeridos'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM sensors 
        WHERE sensor_id = %s AND user_id = %s AND location_id = %s AND location_type = 'parcela'
    """, (sensor_id, user_id, location_id))
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()

    if not deleted:
        return jsonify({'error': 'Sensor no encontrado en esta parcela'}), 404
    return jsonify({'success': True})


@app.route('/ha/valvulas/discover', methods=['GET'])
def ha_valvulas_discover():
    connection_id = request.args.get('connection_id')
    if not connection_id:
        return jsonify({'error': 'connection_id requerido'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT ha_url, ha_token FROM ha_connections WHERE id = %s", (connection_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return jsonify({'error': 'Conexión no encontrada'}), 404

    ha_url, ha_token = _decrypt(row[0]), _decrypt(row[1])

    try:
        resp = requests.get(
            f"{ha_url}/api/states",
            headers={"Authorization": f"Bearer {ha_token}"},
            timeout=15
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException:
        return jsonify({'error': 'No se pudo contactar con Home Assistant'}), 502

    valvulas = []
    for entity in resp.json():
        entity_id = entity.get('entity_id', '')
        domain = entity_id.split('.', 1)[0] if '.' in entity_id else ''
        if domain not in VALVE_DOMAINS:
            continue
        attrs = entity.get('attributes', {}) or {}
        valvulas.append({
            'sensor_id':    entity_id,
            'display_name': attrs.get('friendly_name', entity_id),
            'state':        entity.get('state'),
            'domain':       domain
        })

    return jsonify(valvulas)


@app.route('/ha/valvulas', methods=['POST'])
def ha_registrar_valvula():
    data = request.json or {}
    required = ['sensor_id', 'connection_id', 'user_id', 'location_id']
    if not all(data.get(k) for k in required):
        return jsonify({'error': f'Campos requeridos: {", ".join(required)}'}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT id FROM parcelas_usuario WHERE id = %s AND usuario_id = %s",
        (data['location_id'], data['user_id'])
    )
    if not cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({'error': 'Parcela no encontrada o no pertenece al usuario'}), 403

    try:
        cur.execute("""
            INSERT INTO sensors (sensor_id, connection_id, user_id, location_id, location_type, sensor_type, display_name)
            VALUES (%s, %s, %s, %s, 'parcela', 'valve', %s)
        """, (
            data['sensor_id'], data['connection_id'], data['user_id'],
            data['location_id'], data.get('display_name')
        ))
        conn.commit()
        return jsonify({'success': True}), 201
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({'error': 'Esta válvula ya está registrada en esta parcela'}), 409
    finally:
        cur.close()
        conn.close()


@app.route('/ha/valvulas', methods=['GET'])
def ha_get_valvulas():
    user_id = request.args.get('user_id')
    parcela_usuario_id = request.args.get('parcela_usuario_id')

    if not user_id and not parcela_usuario_id:
        return jsonify({'error': 'user_id o parcela_usuario_id requerido'}), 400

    conn = get_db()
    cur = conn.cursor()

    if parcela_usuario_id:
        cur.execute("""
            SELECT sensor_id, display_name, active, created_at
            FROM sensors
            WHERE location_id = %s AND location_type = 'parcela'
              AND sensor_type = 'valve' AND active = TRUE
        """, (parcela_usuario_id,))
    else:
        cur.execute("""
            SELECT sensor_id, display_name, active, created_at
            FROM sensors
            WHERE user_id = %s AND sensor_type = 'valve' AND active = TRUE
        """, (user_id,))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([{
        'sensor_id':    r[0],
        'display_name': r[1],
        'active':       r[2],
        'created_at':   r[3].isoformat()
    } for r in rows])


@app.route('/ha/valvulas', methods=['DELETE'])
def ha_eliminar_valvula():
    sensor_id = request.args.get('sensor_id')
    user_id = request.args.get('user_id')
    location_id = request.args.get('location_id')

    if not all([sensor_id, user_id, location_id]):
        return jsonify({'error': 'sensor_id, user_id y location_id requeridos'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM sensors 
        WHERE sensor_id = %s AND user_id = %s AND location_id = %s 
          AND sensor_type = 'valve' AND location_type = 'parcela'
    """, (sensor_id, user_id, location_id))
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()

    if not deleted:
        return jsonify({'error': 'Válvula no encontrada en esta parcela'}), 404
    return jsonify({'success': True})


def _ha_call_service(ha_url, ha_token, domain, service, entity_id):
    return requests.post(
        f"{ha_url}/api/services/{domain}/{service}",
        headers={
            "Authorization": f"Bearer {ha_token}",
            "Content-Type": "application/json"
        },
        json={"entity_id": entity_id},
        timeout=10
    )


def _enqueue_off_task(user_id, sensor_id, delay_minutes):
    """Programa una llamada diferida a /ha/comando con action=off."""
    queue_name = os.environ.get('CLOUD_TASKS_QUEUE')
    location   = os.environ.get('CLOUD_TASKS_LOCATION')
    project    = os.environ.get('GCP_PROJECT')
    self_url   = os.environ.get('IOT_API_URL')
    secret     = os.environ.get('TASKS_SHARED_SECRET', '')
    if not all([queue_name, location, project, self_url]):
        print('[Cloud Tasks] no configurado — turn_off automático deshabilitado')
        return False

    from google.cloud import tasks_v2
    from google.protobuf import timestamp_pb2

    client = _get_tasks_client()
    parent = client.queue_path(project, location, queue_name)

    body = json.dumps({
        'user_id':   user_id,
        'sensor_id': sensor_id,
        'action':    'off',
        'tasks_secret': secret
    }).encode('utf-8')

    schedule_ts = timestamp_pb2.Timestamp()
    schedule_ts.FromDatetime(datetime.utcnow() + timedelta(minutes=int(delay_minutes)))

    task = {
        'http_request': {
            'http_method': tasks_v2.HttpMethod.POST,
            'url':         f"{self_url.rstrip('/')}/ha/comando",
            'headers':     {'Content-Type': 'application/json'},
            'body':        body,
        },
        'schedule_time': schedule_ts,
    }
    client.create_task(parent=parent, task=task)
    return True


@app.route('/ha/comando', methods=['POST'])
def ha_comando():
    """
    Envía orden on/off a una válvula registrada.
    Body: {user_id, sensor_id, action: 'on'|'off', duration_minutes?: int, tasks_secret?: str}
    Si duration_minutes está presente con action='on', programa un off automático.
    """
    data = request.json or {}
    sensor_id = data.get('sensor_id')
    action    = data.get('action')
    user_id   = data.get('user_id')
    duration  = data.get('duration_minutes')
    tasks_secret = data.get('tasks_secret', '')

    if not sensor_id or action not in ('on', 'off') or not user_id:
        return jsonify({'error': 'sensor_id, user_id y action (on|off) son requeridos'}), 400

    expected = os.environ.get('TASKS_SHARED_SECRET', '')
    is_task_callback = bool(tasks_secret) and tasks_secret == expected

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.sensor_id, c.ha_url, c.ha_token, s.user_id
        FROM sensors s
        JOIN ha_connections c ON c.id = s.connection_id
        WHERE s.sensor_id = %s AND s.sensor_type = 'valve' AND s.active = TRUE
        LIMIT 1
    """, (sensor_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return jsonify({'error': 'Válvula no encontrada'}), 404

    _, enc_url, enc_token, owner_id = row
    if not is_task_callback and int(owner_id) != int(user_id):
        return jsonify({'error': 'La válvula no pertenece al usuario'}), 403

    ha_url, ha_token = _decrypt(enc_url), _decrypt(enc_token)
    domain = sensor_id.split('.', 1)[0] if '.' in sensor_id else 'switch'
    service = 'turn_on' if action == 'on' else 'turn_off'

    try:
        resp = _ha_call_service(ha_url, ha_token, domain, service, sensor_id)
        if resp.status_code >= 400:
            return jsonify({'error': f'Home Assistant rechazó la orden ({resp.status_code})'}), 502
    except requests.exceptions.RequestException:
        return jsonify({'error': 'No se pudo contactar con Home Assistant'}), 502

    scheduled_off = False
    if action == 'on' and duration:
        try:
            duration = int(duration)
            if duration > 0 and duration <= 240:
                scheduled_off = _enqueue_off_task(owner_id, sensor_id, duration)
        except (TypeError, ValueError):
            pass

    return jsonify({
        'success':       True,
        'action':        action,
        'scheduled_off': scheduled_off,
        'duration_minutes': duration if scheduled_off else None
    }), 200


@app.route('/ingest', methods=['POST'])
def ingest():
    """
    Endpoint push: Home Assistant llama aquí cada vez que un sensor cambia.
    Body: {"sensor_id": "sensor.soil_moisture_1", "value": "52.3"}
    """
    data = request.json or {}
    sensor_id = data.get('sensor_id')
    value = data.get('value')

    if not sensor_id or value is None:
        return jsonify({'error': 'sensor_id y value son requeridos'}), 400

    gcp_project = os.environ.get('GCP_PROJECT')
    pubsub_topic = os.environ.get('PUBSUB_TOPIC')
    if not gcp_project or not pubsub_topic:
        return jsonify({'error': 'Pub/Sub no configurado'}), 503

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT sensor_type, parcela_usuario_id, user_id
        FROM sensors
        WHERE sensor_id = %s AND active = TRUE
        LIMIT 1
    """, (sensor_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return jsonify({'error': 'Sensor no registrado o inactivo'}), 404

    sensor_type, parcela_usuario_id, user_id = row

    message = {
        'sensor_id':          sensor_id,
        'sensor_type':        sensor_type,
        'parcela_usuario_id': parcela_usuario_id,
        'user_id':            user_id,
        'value':              str(value),
        'timestamp':          datetime.now(timezone.utc).isoformat(),
    }

    topic_path = _get_publisher().topic_path(gcp_project, pubsub_topic)
    _get_publisher().publish(topic_path, json.dumps(message).encode('utf-8'))

    return jsonify({'ok': True}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
