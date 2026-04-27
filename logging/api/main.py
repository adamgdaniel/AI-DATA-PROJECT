from flask import Flask, request, jsonify
from dotenv import load_dotenv
import psycopg2
import bcrypt
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
        cur.execute("""
            INSERT INTO parcelas_usuario
                (usuario_id, parcela_id, provincia, municipio, poligono, parcela, recinto,
                cultivo, superficie, lat, lng, geometria)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            usuario_id, parcela_id,
            data.get('provincia'), data.get('municipio'), data.get('poligono'),
            data.get('parcela'), data.get('recinto'),
            data.get('cultivo'), data.get('superficie'),
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
        SELECT id, parcela_id, provincia, municipio, poligono, parcela, recinto,
            cultivo, superficie, lat, lng, geometria, fecha_registro
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

    parcelas = [
        {
            'id': r[0],
            'parcela_id': r[1],
            'provincia': r[2], 'municipio': r[3], 'poligono': r[4],
            'parcela': r[5], 'recinto': r[6],
            'cultivo': r[7],
            'superficie': float(r[8]) if r[8] else None,
            'lat': float(r[9]) if r[9] else None,
            'lng': float(r[10]) if r[10] else None,
            'geometria': _geom(r[11]),
            'fecha_registro': r[12].isoformat()
        }
        for r in rows
    ]
    return jsonify(parcelas)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
