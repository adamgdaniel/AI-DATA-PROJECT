from flask import Flask, request, jsonify
from dotenv import load_dotenv
import psycopg2
import json
import os

load_dotenv()

app = Flask(__name__)


def get_db():
    return psycopg2.connect(
        host=f"/cloudsql/{os.environ['INSTANCE_CONNECTION_NAME']}",
        database=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD']
    )


# --- Parcelas ---

@app.route('/parcelas', methods=['POST'])
def registrar_parcela():
    data = request.json
    usuario_id = data.get('user_id')
    if not usuario_id:
        return jsonify({'error': 'user_id requerido'}), 400

    parcela_id = "{}-{}-{}-{}-{}".format(
        data.get('provincia'), data.get('municipio'),
        data.get('poligono'), data.get('parcela'), data.get('recinto')
    )

    conn = get_db()
    cur = conn.cursor()
    try:
        geometria = data.get('geometria')
        nombre = data.get('nombre')
        if nombre is not None:
            nombre = str(nombre).strip() or None
        cur.execute("""
            INSERT INTO parcelas_usuario
                (usuario_id, parcela_id, provincia, municipio, poligono, parcela, recinto,
                nombre, cultivo, variedad, superficie, lat, lng, geometria)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            usuario_id, parcela_id,
            data.get('provincia'), data.get('municipio'), data.get('poligono'),
            data.get('parcela'), data.get('recinto'),
            nombre,
            data.get('cultivo'), data.get('variedad'), data.get('superficie'),
            data.get('lat'), data.get('lng'),
            json.dumps(geometria) if geometria else None
        ))
        conn.commit()
        return jsonify({'success': True, 'parcela_id': parcela_id}), 201
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({'error': 'Parcela ya registrada para este usuario'}), 409
    finally:
        cur.close()
        conn.close()


@app.route('/parcelas/<int:parcela_id>', methods=['DELETE'])
def eliminar_parcela(parcela_id):
    usuario_id = request.args.get('user_id')
    if not usuario_id:
        return jsonify({'error': 'user_id requerido'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM parcelas_usuario WHERE id = %s AND usuario_id = %s", (parcela_id, usuario_id))
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if deleted == 0:
        return jsonify({'error': 'Parcela no encontrada'}), 404
    return jsonify({'success': True})


@app.route('/parcelas', methods=['GET'])
def obtener_parcelas():
    usuario_id = request.args.get('user_id')
    if not usuario_id:
        return jsonify({'error': 'user_id requerido'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, parcela_id, provincia, municipio, poligono, parcela, recinto,
            nombre, cultivo, variedad, superficie, lat, lng, geometria, fecha_registro
        FROM parcelas_usuario
        WHERE usuario_id = %s
        ORDER BY fecha_registro DESC
    """, (usuario_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    def _geom(val):
        if val is None:
            return None
        return val if isinstance(val, dict) else json.loads(val)

    return jsonify([
        {
            'id': r[0],
            'parcela_id': r[1],
            'provincia': r[2], 'municipio': r[3], 'poligono': r[4],
            'parcela': r[5], 'recinto': r[6],
            'nombre': r[7],
            'cultivo': r[8],
            'variedad': r[9],
            'superficie': float(r[10]) if r[10] else None,
            'lat': float(r[11]) if r[11] else None,
            'lng': float(r[12]) if r[12] else None,
            'geometria': _geom(r[13]),
            'fecha_registro': r[14].isoformat()
        }
        for r in rows
    ])


# --- Invernaderos ---

@app.route('/invernaderos', methods=['GET'])
def get_invernaderos():
    usuario_id = request.args.get('user_id')
    if not usuario_id:
        return jsonify({'error': 'user_id requerido'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, nombre, temperatura_entity_id, hum_amb_entity_id, created_at FROM invernaderos
        WHERE usuario_id = %s ORDER BY created_at ASC
    """, (usuario_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{
        'id': r[0], 'nombre': r[1],
        'temperatura_entity_id': r[2], 'hum_amb_entity_id': r[3],
        'created_at': r[4].isoformat()
    } for r in rows])


@app.route('/invernaderos', methods=['POST'])
def crear_invernadero():
    data = request.json
    usuario_id = data.get('user_id')
    nombre = (data.get('nombre') or '').strip()
    if not usuario_id or not nombre:
        return jsonify({'error': 'user_id y nombre requeridos'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO invernaderos (usuario_id, nombre) VALUES (%s, %s) RETURNING id
    """, (usuario_id, nombre))
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'id': new_id, 'nombre': nombre}), 201


@app.route('/invernaderos/<int:invernadero_id>/sensor', methods=['PUT'])
def update_invernadero_sensor(invernadero_id):
    data = request.json
    sensor_type = data.get('sensor_type')  # 'temperatura' o 'hum_amb'
    entity_id = data.get('sensor_entity_id')

    col = 'temperatura_entity_id' if sensor_type == 'temperatura' else 'hum_amb_entity_id'

    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"UPDATE invernaderos SET {col} = %s WHERE id = %s", (entity_id, invernadero_id))

    if entity_id and data.get('connection_id') and data.get('user_id'):
        db_type = 'temperature' if sensor_type == 'temperatura' else 'ambient_humidity'
        cur.execute("""
            INSERT INTO sensors (sensor_id, connection_id, user_id, location_id, location_type, sensor_type, display_name)
            VALUES (%s, %s, %s, %s, 'invernadero', %s, %s)
            ON CONFLICT (sensor_id) DO UPDATE SET
                location_id = EXCLUDED.location_id,
                location_type = EXCLUDED.location_type,
                sensor_type = EXCLUDED.sensor_type,
                connection_id = EXCLUDED.connection_id,
                display_name = EXCLUDED.display_name
        """, (entity_id, data['connection_id'], data['user_id'], invernadero_id, db_type, data.get('display_name')))

    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})


@app.route('/invernaderos/<int:invernadero_id>', methods=['DELETE'])
def eliminar_invernadero(invernadero_id):
    usuario_id = request.args.get('user_id')
    if not usuario_id:
        return jsonify({'error': 'user_id requerido'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM invernaderos WHERE id = %s AND usuario_id = %s", (invernadero_id, usuario_id))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})


@app.route('/invernaderos/<int:invernadero_id>/plantas', methods=['GET'])
def get_plantas(invernadero_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, tipo, variedad, grid_col, grid_row, soil_entity_id
        FROM plantas_invernadero WHERE invernadero_id = %s ORDER BY id ASC
    """, (invernadero_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{
        'id': r[0], 'tipo': r[1], 'variedad': r[2], 'grid_col': r[3], 'grid_row': r[4], 'soil_entity_id': r[5]
    } for r in rows])


@app.route('/invernaderos/<int:invernadero_id>/plantas', methods=['POST'])
def anadir_planta(invernadero_id):
    data = request.json
    tipo = data.get('tipo')
    variedad = data.get('variedad')
    grid_col = data.get('grid_col')
    grid_row = data.get('grid_row')
    if tipo is None or grid_col is None or grid_row is None:
        return jsonify({'error': 'tipo, grid_col y grid_row requeridos'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO plantas_invernadero (invernadero_id, tipo, variedad, grid_col, grid_row)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
    """, (invernadero_id, tipo, variedad, grid_col, grid_row))
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'id': new_id, 'tipo': tipo, 'variedad': variedad, 'grid_col': grid_col, 'grid_row': grid_row}), 201


@app.route('/invernaderos/<int:invernadero_id>/plantas/<int:planta_id>', methods=['DELETE'])
def eliminar_planta(invernadero_id, planta_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM plantas_invernadero WHERE id = %s AND invernadero_id = %s",
                (planta_id, invernadero_id))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})


@app.route('/invernaderos/<int:invernadero_id>/plantas/<int:planta_id>/sensor', methods=['PUT'])
def update_planta_sensor(invernadero_id, planta_id):
    data = request.json
    entity_id = data.get('soil_entity_id')
    conn = get_db()
    cur = conn.cursor()

    # Commit the plant update independently so it always persists
    try:
        cur.execute("""
            UPDATE plantas_invernadero SET soil_entity_id = %s
            WHERE id = %s AND invernadero_id = %s
        """, (entity_id, planta_id, invernadero_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({'error': str(e)}), 500

    # Register in sensors table as a separate best-effort commit
    if entity_id and data.get('connection_id') and data.get('user_id'):
        try:
            cur.execute("""
                INSERT INTO sensors (sensor_id, connection_id, user_id, location_id, location_type, sensor_type, display_name)
                VALUES (%s, %s, %s, %s, 'planta', 'soil_moisture', %s)
                ON CONFLICT (sensor_id) DO UPDATE SET
                    location_id = EXCLUDED.location_id,
                    location_type = EXCLUDED.location_type,
                    sensor_type = EXCLUDED.sensor_type,
                    connection_id = EXCLUDED.connection_id,
                    display_name = EXCLUDED.display_name
            """, (entity_id, data['connection_id'], data['user_id'], planta_id, data.get('display_name')))
            conn.commit()
        except Exception:
            conn.rollback()

    cur.close()
    conn.close()
    return jsonify({'success': True})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, threaded=True)
