from flask import Flask, request, jsonify
from dotenv import load_dotenv
from google.cloud import bigquery, firestore
import psycopg2
import bcrypt
import json
import uuid
import os
from datetime import datetime, timezone

load_dotenv()

app = Flask(__name__)

GCP_PROJECT_ID = os.environ.get('GCP_PROJECT_ID', '')

_bq = None
_fs = None

def _bq_client():
    global _bq
    if _bq is None and GCP_PROJECT_ID:
        _bq = bigquery.Client(project=GCP_PROJECT_ID)
    return _bq

def _fs_client():
    global _fs
    if _fs is None:
        _fs = firestore.Client()
    return _fs


def get_db():
    return psycopg2.connect(
        host=f"/cloudsql/{os.environ['INSTANCE_CONNECTION_NAME']}",
        database=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD']
    )


@app.route('/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, password_hash FROM users WHERE username = %s", (data['username'],))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and bcrypt.checkpw(data['password'].encode(), row[1].encode()):
        return jsonify({'success': True, 'user_id': row[0]})
    return jsonify({'success': False}), 401


@app.route('/register', methods=['POST'])
def register():
    data = request.json
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = %s", (data['username'],))
    if cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({'field': 'username', 'error': 'Este usuario ya existe'}), 409
    cur.execute("SELECT id FROM users WHERE email = %s", (data['email'],))
    if cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({'field': 'email', 'error': 'Este email ya existe'}), 409
    password_hash = bcrypt.hashpw(data['password'].encode(), bcrypt.gensalt()).decode()
    cur.execute(
        "INSERT INTO users (username, password_hash, email) VALUES (%s, %s, %s)",
        (data['username'], password_hash, data['email'])
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})



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
                nombre, cultivo, variedad, edad_cultivo, superficie, lat, lng, geometria)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            usuario_id, parcela_id,
            data.get('provincia'), data.get('municipio'), data.get('poligono'),
            data.get('parcela'), data.get('recinto'),
            nombre,
            data.get('cultivo'), data.get('variedad'), data.get('edad_cultivo'),
            data.get('superficie'),
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


@app.route('/parcelas', methods=['GET'])
def obtener_parcelas():
    usuario_id = request.args.get('user_id')
    if not usuario_id:
        return jsonify({'error': 'user_id requerido'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT parcela_id, provincia, municipio, poligono, parcela, recinto,
            nombre, cultivo, variedad, edad_cultivo, superficie, lat, lng, geometria, zonas, grid, fecha_registro
        FROM parcelas_usuario
        WHERE usuario_id = %s
        ORDER BY fecha_registro DESC
    """, (usuario_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    def _json(val):
        if val is None:
            return None
        return val if isinstance(val, (dict, list)) else json.loads(val)

    parcelas = [
        {
            'parcela_id': r[0],
            'provincia': r[1], 'municipio': r[2], 'poligono': r[3],
            'parcela': r[4], 'recinto': r[5],
            'nombre': r[6],
            'cultivo': r[7], 'variedad': r[8], 'edad_cultivo': r[9],
            'superficie': float(r[10]) if r[10] else None,
            'lat': float(r[11]) if r[11] else None,
            'lng': float(r[12]) if r[12] else None,
            'geometria': _json(r[13]),
            'zonas': _json(r[14]) or [],
            'grid': _json(r[15]) or {},
            'fecha_registro': r[16].isoformat()
        }
        for r in rows
    ]
    return jsonify(parcelas)


@app.route('/parcelas/<parcela_id>/grid', methods=['POST'])
def update_grid(parcela_id):
    data = request.json
    usuario_id = data.get('user_id')
    if not usuario_id:
        return jsonify({'error': 'user_id requerido'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE parcelas_usuario SET grid = %s::jsonb
        WHERE parcela_id = %s AND usuario_id = %s
    """, (json.dumps(data.get('grid', {})), parcela_id, usuario_id))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})


@app.route('/parcelas/<parcela_id>/zona', methods=['POST'])
def añadir_zona(parcela_id):
    data = request.json
    usuario_id = data.get('user_id')
    if not usuario_id:
        return jsonify({'error': 'user_id requerido'}), 400
    zona = {
        'id': uuid.uuid4().hex[:8],
        'lat': data['lat'], 'lng': data['lng'],
        'cultivo': data['cultivo'], 'emoji': data['emoji']
    }
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE parcelas_usuario
        SET zonas = COALESCE(zonas, '[]'::jsonb) || %s::jsonb
        WHERE parcela_id = %s AND usuario_id = %s
        RETURNING zonas
    """, (json.dumps([zona]), parcela_id, usuario_id))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    if not row:
        return jsonify({'error': 'Parcela no encontrada'}), 404
    zonas = row[0] if isinstance(row[0], list) else json.loads(row[0])
    return jsonify({'success': True, 'zonas': zonas})


@app.route('/parcelas/<parcela_id>/zona/<zona_id>', methods=['DELETE'])
def eliminar_zona(parcela_id, zona_id):
    data = request.json or {}
    usuario_id = data.get('user_id')
    if not usuario_id:
        return jsonify({'error': 'user_id requerido'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE parcelas_usuario
        SET zonas = (
            SELECT COALESCE(jsonb_agg(z), '[]'::jsonb)
            FROM jsonb_array_elements(COALESCE(zonas, '[]'::jsonb)) z
            WHERE z->>'id' != %s
        )
        WHERE parcela_id = %s AND usuario_id = %s
        RETURNING zonas
    """, (zona_id, parcela_id, usuario_id))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    zonas = (row[0] if isinstance(row[0], list) else json.loads(row[0])) if row else []
    return jsonify({'success': True, 'zonas': zonas})


@app.route('/eventos', methods=['POST'])
def registrar_evento():
    data = request.json or {}
    user_id = data.get('user_id')
    entity_type = data.get('entity_type', 'parcela')
    entity_id = data.get('entity_id')
    tipo_evento = data.get('tipo_evento')

    if not all([user_id, entity_id, tipo_evento]):
        return jsonify({'error': 'user_id, entity_id y tipo_evento son requeridos'}), 400

    if tipo_evento not in ('riego', 'abonado', 'poda'):
        return jsonify({'error': 'tipo_evento debe ser riego, abonado o poda'}), 400

    # Timestamp: si el cliente envía 'fecha' (YYYY-MM-DD) o 'timestamp' (ISO), lo usamos.
    # Si no, NOW() en UTC. Aceptamos solo fecha porque el agricultor indica el día,
    # no la hora exacta — fijamos hora a 12:00 para que caiga claro dentro del día.
    ts_str = None
    fecha = data.get('fecha')
    timestamp_in = data.get('timestamp')
    if fecha:
        try:
            d = datetime.strptime(fecha, '%Y-%m-%d')
            ts_str = d.strftime('%Y-%m-%dT12:00:00')
        except ValueError:
            return jsonify({'error': "fecha debe tener formato YYYY-MM-DD"}), 400
    elif timestamp_in:
        try:
            d = datetime.fromisoformat(timestamp_in.replace('Z', '+00:00'))
            ts_str = d.strftime('%Y-%m-%dT%H:%M:%S')
        except ValueError:
            return jsonify({'error': "timestamp inválido (ISO 8601)"}), 400
    else:
        ts_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')

    client = _bq_client()
    if not client:
        return jsonify({'error': 'BigQuery no configurado'}), 503

    row = {
        'user_id':     str(user_id),
        'entity_type': entity_type,
        'entity_id':   entity_id,
        'timestamp':   ts_str,
        'tipo_evento': tipo_evento,
        'valor':       data.get('valor'),
    }
    table_id = f"{GCP_PROJECT_ID}.agri_data.eventos_agricolas"
    errors = client.insert_rows_json(table_id, [row])
    if errors:
        return jsonify({'error': str(errors)}), 500

    # Actualizar estado actual en Firestore (best-effort, no bloquea si falla)
    if entity_type == 'parcela':
        try:
            campo_map = {'riego': 'ultimo_riego', 'abonado': 'ultimo_abonado', 'poda': 'ultima_poda'}
            fs_update = {campo_map[tipo_evento]: ts_str}
            if tipo_evento == 'abonado' and data.get('valor'):
                fs_update['tipo_abono'] = data['valor']
            _fs_client().document(f'usuarios/{user_id}/parcelas/{entity_id}').set(fs_update, merge=True)
        except Exception as e:
            app.logger.warning(f"Firestore update skipped: {e}")

    return jsonify({'success': True}), 201


if __name__ == '__main__':
  app.run(host='0.0.0.0', port=8080)
