CREATE TABLE IF NOT EXISTS municipios_monitorizados (
    codigo_ine   VARCHAR(5)   PRIMARY KEY,
    nombre       VARCHAR(100) NOT NULL,
    provincia    VARCHAR(100),
    lat          NUMERIC(9,6),
    lon          NUMERIC(9,6),
    activo       BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS prevision_meteorologica (
    id                       SERIAL PRIMARY KEY,
    codigo_ine               VARCHAR(5)    NOT NULL REFERENCES municipios_monitorizados(codigo_ine),
    fecha_prevision          DATE          NOT NULL,
    fecha_consulta           TIMESTAMP     NOT NULL,

    -- Open-Meteo (16 días)
    tmax                     NUMERIC(4,1),
    tmin                     NUMERIC(4,1),
    precipitacion_mm         NUMERIC(5,1),
    lluvia_mm                NUMERIC(5,1),
    prob_precipitacion       SMALLINT,
    viento_velocidad         NUMERIC(5,1),
    viento_direccion         SMALLINT,        -- grados (0-360)
    racha_max                NUMERIC(5,1),
    uv_max                   NUMERIC(4,2),
    et0_evapotranspiracion   NUMERIC(5,2),    -- mm, clave para FAO-56
    radiacion_solar          NUMERIC(6,2),    -- MJ/m²
    weather_code             SMALLINT,        -- código WMO

    -- AEMET (solo días 1-7, NULL para días 8-16)
    humedad_max              SMALLINT,
    humedad_min              SMALLINT,
    estado_cielo_cod         VARCHAR(5),
    estado_cielo_desc        VARCHAR(100),

    datos_raw                JSONB         NOT NULL,

    UNIQUE (codigo_ine, fecha_prevision)
);
