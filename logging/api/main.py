from flask import Flask, request, jsonify
from dotenv import load_dotenv
import psycopg2
import bcrypt
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
    cur.execute("SELECT password_hash FROM users WHERE username = %s", (data['username'],))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and bcrypt.checkpw(data['password'].encode(), row[0].encode()):
        return jsonify({'success': True})
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



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
