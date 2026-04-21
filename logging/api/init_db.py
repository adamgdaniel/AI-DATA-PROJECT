from dotenv import load_dotenv
import psycopg2
import bcrypt
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
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        email VARCHAR(255) UNIQUE
    )
""")
cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255) UNIQUE")

password_hash = bcrypt.hashpw(os.environ['TEST_PASSWORD'].encode(), bcrypt.gensalt()).decode()
cur.execute(
    "INSERT INTO users (username, password_hash) VALUES (%s, %s) ON CONFLICT (username) DO NOTHING",
    (os.environ['TEST_USERNAME'], password_hash)
)

conn.commit()
cur.close()
conn.close()
