-- ============================================================
-- MIGRACIÓN: Reestructuración de tablas IoT y sensores
-- Ejecutar en Cloud SQL Studio sobre logindb
-- ============================================================


-- 1. invernaderos: separar sensor único en temperatura y humedad ambiental
ALTER TABLE invernaderos RENAME COLUMN sensor_entity_id TO temperatura_entity_id;
ALTER TABLE invernaderos ADD COLUMN hum_amb_entity_id VARCHAR(200);


-- 2. plantas_invernadero: renombrar sensor genérico a soil_entity_id
ALTER TABLE plantas_invernadero RENAME COLUMN sensor_entity_id TO soil_entity_id;


-- 3. sensors: convertir en registro central de todos los sensores
--    (antes solo almacenaba sensores de parcelas)
ALTER TABLE sensors DROP CONSTRAINT sensors_parcela_usuario_id_fkey;
ALTER TABLE sensors RENAME COLUMN parcela_usuario_id TO location_id;
ALTER TABLE sensors ALTER COLUMN location_id DROP NOT NULL;
ALTER TABLE sensors ADD COLUMN location_type VARCHAR(20)
    CHECK (location_type IN ('parcela', 'invernadero', 'planta'));
UPDATE sensors SET location_type = 'parcela' WHERE location_type IS NULL;
ALTER TABLE sensors ALTER COLUMN location_type SET NOT NULL;
