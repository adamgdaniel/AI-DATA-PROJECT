from flask import Flask, request, jsonify
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import psycopg2
import requests
import os

load_dotenv()

app = Flask(__name__)

def _encrypt(value: str) -> str:
    return Fernet(os.environ['ENCRYPTION_KEY'].encode()).encrypt(value.encode()).decode()

def _decrypt(value: str) -> str:
    return Fernet(os.environ['ENCRYPTION_KEY'].encode()).decrypt(value.encode()).decode()

DEVICE_CLASS_MAP = {
    'moisture': 'soil_moisture',
    'temperature': 'temperature',
    'humidity': 'ambient_humidity'
}


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
    required = ['sensor_id', 'connection_id', 'user_id', 'parcela_usuario_id', 'sensor_type']
    if not all(data.get(k) for k in required):
        return jsonify({'error': f'Campos requeridos: {", ".join(required)}'}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT id FROM parcelas_usuario WHERE id = %s AND usuario_id = %s",
        (data['parcela_usuario_id'], data['user_id'])
    )
    if not cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({'error': 'Parcela no encontrada o no pertenece al usuario'}), 403

    try:
        cur.execute("""
            INSERT INTO sensors (sensor_id, connection_id, user_id, parcela_usuario_id, sensor_type, display_name)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            data['sensor_id'], data['connection_id'], data['user_id'],
            data['parcela_usuario_id'], data['sensor_type'], data.get('display_name')
        ))
        conn.commit()
        return jsonify({'success': True}), 201
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({'error': 'Este sensor ya está registrado'}), 409
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
            FROM sensors WHERE parcela_usuario_id = %s AND active = TRUE
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

    if not sensor_id or not user_id:
        return jsonify({'error': 'sensor_id y user_id requeridos'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM sensors WHERE sensor_id = %s AND user_id = %s", (sensor_id, user_id))
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()

    if not deleted:
        return jsonify({'error': 'Sensor no encontrado'}), 404
    return jsonify({'success': True})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
