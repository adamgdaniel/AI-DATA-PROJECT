-- Tablas para integración de sensores IoT via Home Assistant

-- Se tiene que crear en LOGINDB poirque si no Postgres no nos deja usar foreign keys entre bases de datos

-- Un usuario puede tener múltiples instancias de HA (casa, finca, etc.)
-- ha_url es siempre la URL pública de Nabu Casa: https://xxx.ui.nabu.casa
CREATE TABLE IF NOT EXISTS ha_connections (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ha_url          VARCHAR(255) NOT NULL,
    ha_token        TEXT NOT NULL,
    display_name    VARCHAR(100),
    created_at      TIMESTAMP DEFAULT NOW(),
    last_seen_at    TIMESTAMP
);


--sensor_id es el entity_id en Home Assistant (ej: sensor.soil_moisture_olivo)
CREATE TABLE IF NOT EXISTS sensors (
    sensor_id           VARCHAR(100) PRIMARY KEY,
    connection_id       INTEGER NOT NULL REFERENCES ha_connections(id) ON DELETE CASCADE,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    parcela_usuario_id  INTEGER NOT NULL REFERENCES parcelas_usuario(id) ON DELETE CASCADE,
    sensor_type         VARCHAR(50) NOT NULL CHECK (sensor_type IN ('soil_moisture', 'temperature', 'ambient_humidity')),
    display_name        VARCHAR(100),
    active              BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMP DEFAULT NOW()
);
