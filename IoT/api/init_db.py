from dotenv import load_dotenv
import psycopg2
import os

load_dotenv()

conn = psycopg2.connect(
    host=f"/cloudsql/{os.environ['INSTANCE_CONNECTION_NAME']}",
    database=os.environ['DB_NAME'],
    user=os.environ['DB_USER'],
    password=os.environ['DB_PASSWORD']
)
cur = conn.cursor()

cur.execute("""
    CREATE TABLE IF NOT EXISTS ha_connections (
        id              SERIAL PRIMARY KEY,
        user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        ha_url          VARCHAR(255) NOT NULL,
        ha_token        TEXT NOT NULL,
        display_name    VARCHAR(100),
        created_at      TIMESTAMP DEFAULT NOW(),
        last_seen_at    TIMESTAMP
    )
""")

cur.execute("""
    CREATE TABLE IF NOT EXISTS sensors (
        sensor_id           VARCHAR(100) PRIMARY KEY,
        connection_id       INTEGER NOT NULL REFERENCES ha_connections(id) ON DELETE CASCADE,
        user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        parcela_usuario_id  INTEGER NOT NULL REFERENCES parcelas_usuario(id) ON DELETE CASCADE,
        sensor_type         VARCHAR(50) NOT NULL CHECK (sensor_type IN ('soil_moisture', 'temperature', 'ambient_humidity')),
        display_name        VARCHAR(100),
        active              BOOLEAN DEFAULT TRUE,
        created_at          TIMESTAMP DEFAULT NOW()
    )
""")

conn.commit()
cur.close()
conn.close()
print("IoT tables ready")
