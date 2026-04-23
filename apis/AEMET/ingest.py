import os
import json
import logging
import urllib.request
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

AEMET_API_KEY = os.environ["AEMET_API_KEY"]
DATABASE_URL  = os.environ["DATABASE_URL"]

AEMET_URL      = "https://opendata.aemet.es/opendata/api/prediccion/especifica/municipio/diaria/{codigo}?api_key={key}"
OPENMETEO_URL  = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,rain_sum,"
    "precipitation_probability_max,wind_speed_10m_max,wind_direction_10m_dominant,"
    "wind_gusts_10m_max,uv_index_max,et0_fao_evapotranspiration,weather_code,shortwave_radiation_sum"
    "&forecast_days=16&timezone=Europe%2FMadrid"
)


def http_get(url, encoding="utf-8"):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode(encoding))


def fetch_openmeteo(lat, lon):
    data = http_get(OPENMETEO_URL.format(lat=lat, lon=lon))
    daily = data["daily"]
    keys = [k for k in daily if k != "time"]
    return {
        date: {k: daily[k][i] for k in keys}
        for i, date in enumerate(daily["time"])
    }


def fetch_aemet(codigo_ine):
    meta = http_get(AEMET_URL.format(codigo=codigo_ine, key=AEMET_API_KEY))
    if meta.get("estado") != 200:
        raise RuntimeError(f"AEMET {meta.get('estado')}: {meta.get('descripcion')}")
    data = http_get(meta["datos"], encoding="latin-1")
    result = {}
    for dia in data[0]["prediccion"]["dia"]:
        fecha = dia["fecha"][:10]
        result[fecha] = {
            "humedad_max":       dia.get("humedadRelativa", {}).get("maxima"),
            "humedad_min":       dia.get("humedadRelativa", {}).get("minima"),
            "estado_cielo_cod":  _get_period(dia.get("estadoCielo", [])) or None,
            "estado_cielo_desc": _get_period(dia.get("estadoCielo", []), key="descripcion") or None,
        }
    return result


def _get_period(items, periodo="00-24", key="value"):
    if not items:
        return None
    if "periodo" not in items[0]:
        return items[0].get(key)
    for item in items:
        if item.get("periodo") == periodo:
            return item.get(key)
    return None


def _int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def build_rows(om_data, aemet_data, fecha_consulta, codigo_ine):
    rows = []
    for fecha, om in om_data.items():
        aemet = aemet_data.get(fecha, {})
        rows.append((
            codigo_ine, fecha, fecha_consulta,
            om.get("temperature_2m_max"),
            om.get("temperature_2m_min"),
            om.get("precipitation_sum"),
            om.get("rain_sum"),
            om.get("precipitation_probability_max"),
            om.get("wind_speed_10m_max"),
            om.get("wind_direction_10m_dominant"),
            om.get("wind_gusts_10m_max"),
            om.get("uv_index_max"),
            om.get("et0_fao_evapotranspiration"),
            om.get("shortwave_radiation_sum"),
            om.get("weather_code"),
            _int_or_none(aemet.get("humedad_max")),
            _int_or_none(aemet.get("humedad_min")),
            aemet.get("estado_cielo_cod"),
            aemet.get("estado_cielo_desc"),
            json.dumps(om),
        ))
    return rows


def upsert(conn, rows):
    sql = """
        INSERT INTO prevision_meteorologica (
            codigo_ine, fecha_prevision, fecha_consulta,
            tmax, tmin,
            precipitacion_mm, lluvia_mm, prob_precipitacion,
            viento_velocidad, viento_direccion, racha_max,
            uv_max, et0_evapotranspiracion, radiacion_solar, weather_code,
            humedad_max, humedad_min,
            estado_cielo_cod, estado_cielo_desc,
            datos_raw
        ) VALUES %s
        ON CONFLICT (codigo_ine, fecha_prevision) DO UPDATE SET
            fecha_consulta         = EXCLUDED.fecha_consulta,
            tmax                   = EXCLUDED.tmax,
            tmin                   = EXCLUDED.tmin,
            precipitacion_mm       = EXCLUDED.precipitacion_mm,
            lluvia_mm              = EXCLUDED.lluvia_mm,
            prob_precipitacion     = EXCLUDED.prob_precipitacion,
            viento_velocidad       = EXCLUDED.viento_velocidad,
            viento_direccion       = EXCLUDED.viento_direccion,
            racha_max              = EXCLUDED.racha_max,
            uv_max                 = EXCLUDED.uv_max,
            et0_evapotranspiracion = EXCLUDED.et0_evapotranspiracion,
            radiacion_solar        = EXCLUDED.radiacion_solar,
            weather_code           = EXCLUDED.weather_code,
            humedad_max            = EXCLUDED.humedad_max,
            humedad_min            = EXCLUDED.humedad_min,
            estado_cielo_cod       = EXCLUDED.estado_cielo_cod,
            estado_cielo_desc      = EXCLUDED.estado_cielo_desc,
            datos_raw              = EXCLUDED.datos_raw
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows)
    conn.commit()


def main():
    conn = psycopg2.connect(DATABASE_URL)

    with conn.cursor() as cur:
        cur.execute("SELECT codigo_ine, lat, lon FROM municipios_monitorizados WHERE activo = TRUE")
        municipios = cur.fetchall()

    if not municipios:
        log.warning("No hay municipios activos.")
        return

    fecha_consulta = datetime.now(timezone.utc)

    for codigo_ine, lat, lon in municipios:
        try:
            om_data   = fetch_openmeteo(lat, lon)
            aemet_data = fetch_aemet(codigo_ine)
            rows = build_rows(om_data, aemet_data, fecha_consulta, codigo_ine)
            upsert(conn, rows)
            log.info(f"{codigo_ine}: {len(rows)} días insertados/actualizados")
        except Exception as e:
            conn.rollback()
            log.error(f"{codigo_ine}: {e}")

    conn.close()


if __name__ == "__main__":
    main()
