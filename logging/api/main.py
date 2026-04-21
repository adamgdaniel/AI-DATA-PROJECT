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



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
