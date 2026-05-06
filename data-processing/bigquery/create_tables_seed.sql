-- ================================================================
-- BigQuery: creación de tablas e inserción de datos de prueba
-- Período: 2026-03-13 → 2026-05-01 (50 días, resolución horaria)
--
-- Reemplaza antes de ejecutar:
--   <PROJECT_ID>  →  id del proyecto de GCP
--   <DATASET>     →  nombre del dataset en BigQuery
-- ================================================================


-- ----------------------------------------------------------------
-- 1. TABLAS
-- ----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `<PROJECT_ID>.<DATASET>.lecturas_parcelas` (
  user_id              STRING    NOT NULL,
  parcel_id            STRING    NOT NULL,
  timestamp            DATETIME  NOT NULL,
  temperatura          FLOAT64,
  humedad_ambiental    FLOAT64,
  humedad_suelo        FLOAT64,           -- null si no hay sensor IoT
  precipitacion_mm     FLOAT64,
  et0                  FLOAT64,
  radiacion_solar      FLOAT64,
  fuente_temperatura   STRING,            -- 'sensor' | 'openmeteo'
  tipo_cultivo         STRING,
  variedad             STRING,
  fecha_plantacion_aprox DATE
)
PARTITION BY DATE(timestamp)
CLUSTER BY parcel_id;


CREATE TABLE IF NOT EXISTS `<PROJECT_ID>.<DATASET>.lecturas_plantas` (
  user_id           STRING   NOT NULL,
  greenhouse_id     STRING   NOT NULL,
  plant_id          STRING   NOT NULL,
  timestamp         DATETIME NOT NULL,
  temperatura       FLOAT64,              -- nivel de invernadero (desnormalizado)
  humedad_ambiental FLOAT64,              -- nivel de invernadero (desnormalizado)
  humedad_suelo     FLOAT64,              -- null si no hay sensor IoT en la planta
  tipo_cultivo      STRING,
  variedad          STRING,
  fecha_plantacion  DATE
)
PARTITION BY DATE(timestamp)
CLUSTER BY plant_id;


CREATE TABLE IF NOT EXISTS `<PROJECT_ID>.<DATASET>.eventos_agricolas` (
  user_id      STRING   NOT NULL,
  entity_type  STRING   NOT NULL,         -- 'parcela' | 'planta'
  entity_id    STRING   NOT NULL,
  timestamp    DATETIME NOT NULL,
  tipo_evento  STRING   NOT NULL,         -- 'riego' | 'poda' | 'abonado'
  valor        STRING                     -- tipo de abono cuando aplica, null en otros casos
);


-- ----------------------------------------------------------------
-- 2. LECTURAS PARCELAS  (3 600 filas)
--
-- Configuración:
--   parcela_001 | Naranjo Navelina        | user_001 | sensor IoT ✓
--   parcela_002 | Maíz híbrido ciclo largo| user_001 | sin sensor
--   parcela_003 | Mandarino Clemenules    | user_002 | sin sensor
--
-- Temperatura exterior: base 14-15 °C, sube ~8 °C en 50 días,
--   ciclo diario ±4 °C (mínimo ~5am, máximo ~15pm).
-- Humedad ambiental: inversamente correlada con temperatura.
-- Humedad del suelo (solo parcela_001): base 40%, baja con el tiempo,
--   recupera tras eventos de lluvia y riego manual.
--
-- Eventos de lluvia (offset desde hora 0 = 2026-03-13 00:00):
--   día  8 → horas 192-195   (~4 mm total, lluvia ligera)
--   día 18 → horas 432-437   (~12 mm total, lluvia moderada)
--   día 33 → horas 792-799   (~25 mm total, lluvia fuerte)
--   día 45 → horas 1080-1082 (~6 mm total, lluvia ligera)
--
-- Riego manual parcela_001:
--   día  2 (2026-03-15) y día 38 (2026-04-20)
-- ----------------------------------------------------------------

INSERT INTO `<PROJECT_ID>.<DATASET>.lecturas_parcelas`
WITH
hours AS (
  SELECT
    h,
    DATETIME_ADD(DATETIME '2026-03-13 00:00:00', INTERVAL h HOUR) AS ts,
    CAST(h AS FLOAT64) / 24.0              AS day_num,
    CAST(MOD(h, 24) AS FLOAT64)            AS hf
  FROM UNNEST(GENERATE_ARRAY(0, 1199)) AS h
),
parcelas_cfg AS (
  SELECT * FROM UNNEST([
    STRUCT(
      'user_001'    AS user_id,
      'parcela_001' AS parcel_id,
      'Naranjo'     AS tipo_cultivo,
      'Navelina'    AS variedad,
      DATE '2018-01-01' AS fecha_plantacion_aprox,
      TRUE          AS has_sensor,
      14.5          AS base_temp,
      0.0           AS temp_offset
    ),
    STRUCT(
      'user_001', 'parcela_002',
      'Maiz', 'Híbrida ciclo largo',
      DATE '2026-03-20',
      FALSE, 15.0, 1.5
    ),
    STRUCT(
      'user_002', 'parcela_003',
      'Mandarino', 'Clemenules',
      DATE '2014-01-01',
      FALSE, 14.0, 0.5
    )
  ])
)
SELECT
  p.user_id,
  p.parcel_id,
  h.ts AS timestamp,

  -- Temperatura: sube ~8 °C en 50 días, ciclo diario ±4 °C
  ROUND(
    p.base_temp + p.temp_offset
    + (h.day_num / 50.0) * 8.0
    + 4.0 * COS(ACOS(-1.0) * 2.0 * (h.hf - 15.0) / 24.0)
    + 0.3 * SIN(ACOS(-1.0) * CAST(h.h AS FLOAT64) * 0.137),
  1) AS temperatura,

  -- Humedad ambiental: 72% base, baja 10 pp en 50 días, ciclo inverso a temp
  ROUND(GREATEST(28.0,
    72.0
    - (h.day_num / 50.0) * 10.0
    - 12.0 * COS(ACOS(-1.0) * 2.0 * (h.hf - 15.0) / 24.0)
    + 0.6 * SIN(ACOS(-1.0) * CAST(h.h AS FLOAT64) * 0.113)
  ), 1) AS humedad_ambiental,

  -- Humedad del suelo: solo parcela_001 (sensor IoT)
  -- Cada evento (lluvia o riego) aporta una contribución que decae exponencialmente
  CASE WHEN p.parcel_id = 'parcela_001' THEN
    ROUND(GREATEST(15.0, LEAST(88.0,
      40.0 - h.day_num * 0.22
      + IF(h.day_num >=  2.0, 10.0 * EXP(-(h.day_num -  2.0) * 0.28), 0.0)  -- riego 15-mar
      + IF(h.day_num >=  8.0, 14.0 * EXP(-(h.day_num -  8.0) * 0.20), 0.0)  -- lluvia día 8
      + IF(h.day_num >= 18.0, 16.0 * EXP(-(h.day_num - 18.0) * 0.20), 0.0)  -- lluvia día 18
      + IF(h.day_num >= 33.0, 22.0 * EXP(-(h.day_num - 33.0) * 0.18), 0.0)  -- lluvia día 33
      + IF(h.day_num >= 38.0, 10.0 * EXP(-(h.day_num - 38.0) * 0.28), 0.0)  -- riego 20-abr
      + IF(h.day_num >= 45.0,  8.0 * EXP(-(h.day_num - 45.0) * 0.22), 0.0)  -- lluvia día 45
      - 1.0 * COS(ACOS(-1.0) * 2.0 * (h.hf - 15.0) / 24.0)
    )), 1)
  ELSE NULL END AS humedad_suelo,

  -- Precipitación por eventos de lluvia
  CASE
    WHEN h.h BETWEEN 192  AND 195  THEN 1.0
    WHEN h.h BETWEEN 432  AND 434  THEN 3.0
    WHEN h.h BETWEEN 435  AND 437  THEN 1.0
    WHEN h.h BETWEEN 792  AND 795  THEN 5.0
    WHEN h.h BETWEEN 796  AND 799  THEN 2.5
    WHEN h.h BETWEEN 1080 AND 1082 THEN 2.0
    ELSE 0.0
  END AS precipitacion_mm,

  -- ET₀: solo horas diurnas (8-18h), sube con el avance de temporada
  CASE
    WHEN MOD(h.h, 24) BETWEEN 8 AND 18 THEN
      ROUND(GREATEST(0.0,
        0.14 + (h.day_num / 50.0) * 0.09
        + 0.22 * SIN(ACOS(-1.0) * (h.hf - 8.0) / 10.0)
      ), 3)
    ELSE 0.0
  END AS et0,

  -- Radiación solar: ciclo sinusoidal diurno (7-19h), sube con la temporada
  CASE
    WHEN MOD(h.h, 24) BETWEEN 7 AND 19 THEN
      ROUND(GREATEST(0.0,
        (120.0 + h.day_num * 3.2)
        * SIN(ACOS(-1.0) * (h.hf - 7.0) / 12.0)
      ), 1)
    ELSE 0.0
  END AS radiacion_solar,

  IF(p.has_sensor, 'sensor', 'openmeteo') AS fuente_temperatura,
  p.tipo_cultivo,
  p.variedad,
  p.fecha_plantacion_aprox
FROM hours h
CROSS JOIN parcelas_cfg p;


-- ----------------------------------------------------------------
-- 3. LECTURAS PLANTAS  (10 800 filas)
--
-- Configuración:
--   invernadero_001 | Tomate Rama/LongLife | user_001 | plant_inv1_001 con sensor
--   invernadero_002 | Pimiento California  | user_001 | plant_inv2_001 con sensor
--   invernadero_003 | Pepino Holandés      | user_002 | plant_inv3_001 con sensor
--   Plantas _002 y _003 de cada invernadero sin sensor (humedad_suelo NULL)
--
-- Temperatura de invernadero: ciclo diario más suave que exterior (±3-4 °C),
--   sube ~3 °C en 50 días. temperatura y humedad_ambiental son a nivel de
--   invernadero y se desnormalizan en cada fila de planta.
--
-- Humedad del suelo (plantas con sensor): riego automático cada 8 días.
--   Cada riego aporta +22 pp que decae a ~0 en ~8 días (tasa 0.40/día).
--   riego_d0 = día de inicio del ciclo de riego de esa planta.
-- ----------------------------------------------------------------

INSERT INTO `<PROJECT_ID>.<DATASET>.lecturas_plantas`
WITH
hours AS (
  SELECT
    h,
    DATETIME_ADD(DATETIME '2026-03-13 00:00:00', INTERVAL h HOUR) AS ts,
    CAST(h AS FLOAT64) / 24.0              AS day_num,
    CAST(MOD(h, 24) AS FLOAT64)            AS hf
  FROM UNNEST(GENERATE_ARRAY(0, 1199)) AS h
),
plantas_cfg AS (
  SELECT * FROM UNNEST([
    -- Invernadero 001 – Tomate Rama/LongLife
    STRUCT(
      'user_001'        AS user_id,
      'invernadero_001' AS greenhouse_id,
      'plant_inv1_001'  AS plant_id,
      'Tomate'          AS tipo_cultivo,
      'Rama/LongLife'   AS variedad,
      DATE '2026-02-10' AS fecha_plantacion,
      23.0 AS gh_base_temp, 3.0  AS gh_temp_amp,
      72.0 AS gh_base_hum,  10.0 AS gh_hum_amp,
      TRUE AS has_sensor,   0.0  AS riego_d0
    ),
    STRUCT('user_001', 'invernadero_001', 'plant_inv1_002',
           'Tomate', 'Rama/LongLife', DATE '2026-02-10',
           23.0, 3.0, 72.0, 10.0, FALSE, 0.0),
    STRUCT('user_001', 'invernadero_001', 'plant_inv1_003',
           'Tomate', 'Rama/LongLife', DATE '2026-02-10',
           23.0, 3.0, 72.0, 10.0, FALSE, 0.0),
    -- Invernadero 002 – Pimiento California
    STRUCT('user_001', 'invernadero_002', 'plant_inv2_001',
           'Pimiento', 'California', DATE '2026-02-20',
           22.0, 2.5, 68.0, 8.0, TRUE, 1.0),
    STRUCT('user_001', 'invernadero_002', 'plant_inv2_002',
           'Pimiento', 'California', DATE '2026-02-20',
           22.0, 2.5, 68.0, 8.0, FALSE, 0.0),
    STRUCT('user_001', 'invernadero_002', 'plant_inv2_003',
           'Pimiento', 'California', DATE '2026-02-20',
           22.0, 2.5, 68.0, 8.0, FALSE, 0.0),
    -- Invernadero 003 – Pepino Holandés
    STRUCT('user_002', 'invernadero_003', 'plant_inv3_001',
           'Pepino', 'Holandés', DATE '2026-03-01',
           24.0, 4.0, 75.0, 12.0, TRUE, 2.0),
    STRUCT('user_002', 'invernadero_003', 'plant_inv3_002',
           'Pepino', 'Holandés', DATE '2026-03-01',
           24.0, 4.0, 75.0, 12.0, FALSE, 0.0),
    STRUCT('user_002', 'invernadero_003', 'plant_inv3_003',
           'Pepino', 'Holandés', DATE '2026-03-01',
           24.0, 4.0, 75.0, 12.0, FALSE, 0.0)
  ])
)
SELECT
  p.user_id,
  p.greenhouse_id,
  p.plant_id,
  h.ts AS timestamp,

  -- Temperatura de invernadero: ciclo más suave que exterior
  ROUND(
    p.gh_base_temp
    + (h.day_num / 50.0) * 3.0
    + p.gh_temp_amp * COS(ACOS(-1.0) * 2.0 * (h.hf - 14.0) / 24.0)
    + 0.2 * SIN(ACOS(-1.0) * CAST(h.h AS FLOAT64) * 0.097),
  1) AS temperatura,

  -- Humedad ambiental del invernadero
  ROUND(GREATEST(40.0,
    p.gh_base_hum
    + (h.day_num / 50.0) * 4.0
    - p.gh_hum_amp * COS(ACOS(-1.0) * 2.0 * (h.hf - 14.0) / 24.0)
    + 0.5 * SIN(ACOS(-1.0) * CAST(h.h AS FLOAT64) * 0.109)
  ), 1) AS humedad_ambiental,

  -- Humedad del suelo: solo plantas con sensor, riego automático cada 8 días
  CASE WHEN p.has_sensor THEN
    ROUND(GREATEST(30.0, LEAST(90.0,
      52.0 - h.day_num * 0.08
      + IF(h.day_num >= p.riego_d0 +  0.0, 22.0 * EXP(-(h.day_num - (p.riego_d0 +  0.0)) * 0.40), 0.0)
      + IF(h.day_num >= p.riego_d0 +  8.0, 22.0 * EXP(-(h.day_num - (p.riego_d0 +  8.0)) * 0.40), 0.0)
      + IF(h.day_num >= p.riego_d0 + 16.0, 22.0 * EXP(-(h.day_num - (p.riego_d0 + 16.0)) * 0.40), 0.0)
      + IF(h.day_num >= p.riego_d0 + 24.0, 22.0 * EXP(-(h.day_num - (p.riego_d0 + 24.0)) * 0.40), 0.0)
      + IF(h.day_num >= p.riego_d0 + 32.0, 22.0 * EXP(-(h.day_num - (p.riego_d0 + 32.0)) * 0.40), 0.0)
      + IF(h.day_num >= p.riego_d0 + 40.0, 22.0 * EXP(-(h.day_num - (p.riego_d0 + 40.0)) * 0.40), 0.0)
      + IF(h.day_num >= p.riego_d0 + 48.0, 22.0 * EXP(-(h.day_num - (p.riego_d0 + 48.0)) * 0.40), 0.0)
      - 1.5 * COS(ACOS(-1.0) * 2.0 * (h.hf - 14.0) / 24.0)
    )), 1)
  ELSE NULL END AS humedad_suelo,

  p.tipo_cultivo,
  p.variedad,
  p.fecha_plantacion
FROM hours h
CROSS JOIN plantas_cfg p;


-- ----------------------------------------------------------------
-- 4. EVENTOS AGRÍCOLAS  (12 eventos)
-- ----------------------------------------------------------------

INSERT INTO `<PROJECT_ID>.<DATASET>.eventos_agricolas`
SELECT t.*
FROM UNNEST([
  -- Parcelas
  STRUCT('user_001' AS user_id, 'parcela' AS entity_type, 'parcela_001' AS entity_id,
         DATETIME '2026-03-15 08:30:00' AS timestamp, 'riego'   AS tipo_evento, CAST(NULL AS STRING) AS valor),
  STRUCT('user_001' AS user_id, 'parcela' AS entity_type, 'parcela_002' AS entity_id,
         DATETIME '2026-03-25 09:00:00' AS timestamp, 'riego'   AS tipo_evento, CAST(NULL AS STRING) AS valor),
  STRUCT('user_001' AS user_id, 'parcela' AS entity_type, 'parcela_001' AS entity_id,
         DATETIME '2026-04-02 07:45:00' AS timestamp, 'abonado' AS tipo_evento, 'NPK 15-15-15' AS valor),
  STRUCT('user_002' AS user_id, 'parcela' AS entity_type, 'parcela_003' AS entity_id,
         DATETIME '2026-04-10 10:00:00' AS timestamp, 'poda'    AS tipo_evento, CAST(NULL AS STRING) AS valor),
  STRUCT('user_001' AS user_id, 'parcela' AS entity_type, 'parcela_001' AS entity_id,
         DATETIME '2026-04-20 08:00:00' AS timestamp, 'riego'   AS tipo_evento, CAST(NULL AS STRING) AS valor),
  STRUCT('user_001' AS user_id, 'parcela' AS entity_type, 'parcela_002' AS entity_id,
         DATETIME '2026-04-25 09:30:00' AS timestamp, 'abonado' AS tipo_evento, 'Urea 46%' AS valor),
  STRUCT('user_002' AS user_id, 'parcela' AS entity_type, 'parcela_003' AS entity_id,
         DATETIME '2026-05-01 07:00:00' AS timestamp, 'riego'   AS tipo_evento, CAST(NULL AS STRING) AS valor),
  -- Plantas
  STRUCT('user_001' AS user_id, 'planta' AS entity_type, 'plant_inv1_001' AS entity_id,
         DATETIME '2026-03-20 07:30:00' AS timestamp, 'riego'   AS tipo_evento, CAST(NULL AS STRING) AS valor),
  STRUCT('user_001' AS user_id, 'planta' AS entity_type, 'plant_inv1_001' AS entity_id,
         DATETIME '2026-04-05 07:30:00' AS timestamp, 'riego'   AS tipo_evento, CAST(NULL AS STRING) AS valor),
  STRUCT('user_001' AS user_id, 'planta' AS entity_type, 'plant_inv2_001' AS entity_id,
         DATETIME '2026-04-18 08:00:00' AS timestamp, 'abonado' AS tipo_evento, 'Abono líquido 8-4-8' AS valor),
  STRUCT('user_002' AS user_id, 'planta' AS entity_type, 'plant_inv3_001' AS entity_id,
         DATETIME '2026-04-01 07:00:00' AS timestamp, 'riego'   AS tipo_evento, CAST(NULL AS STRING) AS valor),
  STRUCT('user_002' AS user_id, 'planta' AS entity_type, 'plant_inv3_001' AS entity_id,
         DATETIME '2026-04-22 07:00:00' AS timestamp, 'riego'   AS tipo_evento, CAST(NULL AS STRING) AS valor)
]) AS t;
