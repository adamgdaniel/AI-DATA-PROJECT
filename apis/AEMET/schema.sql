-- Municipios que tienen al menos una parcela reclamada por un usuario

CREATE TABLE IF NOT EXISTS municipios_monitorizados (
    codigo_ine   VARCHAR(5)   PRIMARY KEY,
    nombre       VARCHAR(100) NOT NULL,
    provincia    VARCHAR(100),
    lat          NUMERIC(9,6),
    lon          NUMERIC(9,6),
    activo       BOOLEAN      NOT NULL DEFAULT TRUE
);

-- Previsión meteorológica diaria por municipio
CREATE TABLE IF NOT EXISTS prevision_meteorologica (
    id                   SERIAL PRIMARY KEY,
    codigo_ine           VARCHAR(5)   NOT NULL REFERENCES municipios_monitorizados(codigo_ine),
    fecha_prevision      DATE         NOT NULL,
    fecha_consulta       TIMESTAMP    NOT NULL,

    -- Temperatura (°C)
    tmax                 SMALLINT,
    tmin                 SMALLINT,

    -- Humedad relativa (%)
    humedad_max          SMALLINT,
    humedad_min          SMALLINT,

    -- Precipitación
    prob_precipitacion   SMALLINT,    -- % probabilidad (periodo 00-24)

    -- Viento (periodo 00-24 o resumen diario)
    viento_velocidad     SMALLINT,    -- km/h
    viento_direccion     VARCHAR(2),  -- N, NE, E, SE, S, SO, O, NO, C

    -- Racha máxima (km/h) — frecuentemente nulo en previsión AEMET
    racha_max            SMALLINT,

    -- Estado del cielo (periodo 00-24 o resumen diario)
    estado_cielo_cod     VARCHAR(5),
    estado_cielo_desc    VARCHAR(100),

    -- Índice UV máximo (ausente en días 6-7 de previsión)
    uv_max               SMALLINT,

    -- Payload completo 
    datos_raw            JSONB        NOT NULL,

    -- Solo guardamos la previsión más reciente por municipio y día
    UNIQUE (codigo_ine, fecha_prevision)
);
