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
DATABASE_URL   = os.environ["DATABASE_URL"]  # postgres://user:pass@host:5432/dbname

FORECAST_URL = "https://opendata.aemet.es/opendata/api/prediccion/especifica/municipio/diaria/{codigo}?api_key={key}"


def aemet_get(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("latin-1"))


def fetch_forecast(codigo_ine):
    meta = aemet_get(FORECAST_URL.format(codigo=codigo_ine, key=AEMET_API_KEY))
    if meta.get("estado") != 200:
        raise RuntimeError(f"AEMET error {meta.get('estado')} para {codigo_ine}: {meta.get('descripcion')}")
    data = aemet_get(meta["datos"])
    return data[0]["prediccion"]["dia"]


def _get_period(items, periodo="00-24"):
    """Devuelve el value del periodo indicado, o el único valor si no hay campo periodo."""
    if not items:
        return None
    if "periodo" not in items[0]:
        return items[0].get("value")
    for item in items:
        if item.get("periodo") == periodo:
            return item.get("value")
    return None


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_day(dia):
    tmax = _int_or_none(dia.get("temperatura", {}).get("maxima"))
    tmin = _int_or_none(dia.get("temperatura", {}).get("minima"))

    humedad_max = _int_or_none(dia.get("humedadRelativa", {}).get("maxima"))
    humedad_min = _int_or_none(dia.get("humedadRelativa", {}).get("minima"))

    prob_precip = _int_or_none(_get_period(dia.get("probPrecipitacion", [])))

    viento_items = dia.get("viento", [])
    viento = None
    if "periodo" not in (viento_items[0] if viento_items else {}):
        viento = viento_items[0] if viento_items else None
    else:
        for v in viento_items:
            if v.get("periodo") == "00-24":
                viento = v
                break
    viento_vel = _int_or_none(viento.get("velocidad") if viento else None)
    viento_dir = (viento.get("direccion") or None) if viento else None

    racha_raw = _get_period(dia.get("rachaMax", []))
    racha = _int_or_none(racha_raw)

    cielo_items = dia.get("estadoCielo", [])
    cielo = None
    if "periodo" not in (cielo_items[0] if cielo_items else {}):
        cielo = cielo_items[0] if cielo_items else None
    else:
        for c in cielo_items:
            if c.get("periodo") == "00-24":
                cielo = c
                break
    cielo_cod  = (cielo.get("value") or None) if cielo else None
    cielo_desc = (cielo.get("descripcion") or None) if cielo else None

    uv_max = _int_or_none(dia.get("uvMax"))

    fecha_prevision = dia["fecha"][:10]  # "2026-04-22T00:00:00" → "2026-04-22"

    return {
        "fecha_prevision":    fecha_prevision,
        "tmax":               tmax,
        "tmin":               tmin,
        "humedad_max":        humedad_max,
        "humedad_min":        humedad_min,
        "prob_precipitacion": prob_precip,
        "viento_velocidad":   viento_vel,
        "viento_direccion":   viento_dir,
        "racha_max":          racha,
        "estado_cielo_cod":   cielo_cod,
        "estado_cielo_desc":  cielo_desc,
        "uv_max":             uv_max,
    }


def upsert_forecast(conn, codigo_ine, rows, fecha_consulta):
    sql = """
        INSERT INTO prevision_meteorologica (
            codigo_ine, fecha_prevision, fecha_consulta,
            tmax, tmin,
            humedad_max, humedad_min,
            prob_precipitacion,
            viento_velocidad, viento_direccion, racha_max,
            estado_cielo_cod, estado_cielo_desc,
            uv_max, datos_raw
        ) VALUES %s
        ON CONFLICT (codigo_ine, fecha_prevision)
        DO UPDATE SET
            fecha_consulta       = EXCLUDED.fecha_consulta,
            tmax                 = EXCLUDED.tmax,
            tmin                 = EXCLUDED.tmin,
            humedad_max          = EXCLUDED.humedad_max,
            humedad_min          = EXCLUDED.humedad_min,
            prob_precipitacion   = EXCLUDED.prob_precipitacion,
            viento_velocidad     = EXCLUDED.viento_velocidad,
            viento_direccion     = EXCLUDED.viento_direccion,
            racha_max            = EXCLUDED.racha_max,
            estado_cielo_cod     = EXCLUDED.estado_cielo_cod,
            estado_cielo_desc    = EXCLUDED.estado_cielo_desc,
            uv_max               = EXCLUDED.uv_max,
            datos_raw            = EXCLUDED.datos_raw
    """
    values = [
        (
            codigo_ine, r["fecha_prevision"], fecha_consulta,
            r["tmax"], r["tmin"],
            r["humedad_max"], r["humedad_min"],
            r["prob_precipitacion"],
            r["viento_velocidad"], r["viento_direccion"], r["racha_max"],
            r["estado_cielo_cod"], r["estado_cielo_desc"],
            r["uv_max"], json.dumps(r["datos_raw"]),
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        execute_values(cur, sql, values)
    conn.commit()


def get_municipios(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT codigo_ine FROM municipios_monitorizados WHERE activo = TRUE")
        return [row[0] for row in cur.fetchall()]


def main():
    conn = psycopg2.connect(DATABASE_URL)
    fecha_consulta = datetime.now(timezone.utc)

    municipios = get_municipios(conn)
    if not municipios:
        log.warning("No hay municipios activos. Nada que ingestar.")
        return

    log.info(f"Municipios a consultar: {municipios}")

    for codigo_ine in municipios:
        try:
            dias = fetch_forecast(codigo_ine)
            rows = []
            for dia in dias:
                parsed = parse_day(dia)
                parsed["datos_raw"] = dia
                rows.append(parsed)
            upsert_forecast(conn, codigo_ine, rows, fecha_consulta)
            log.info(f"{codigo_ine}: {len(rows)} días insertados/actualizados")
        except Exception as e:
            log.error(f"{codigo_ine}: error → {e}")

    conn.close()


if __name__ == "__main__":
    main()
