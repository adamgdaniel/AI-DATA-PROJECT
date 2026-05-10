import os
import requests

RAG_API_URL        = os.environ.get("RAG_API_URL",        "http://rag-api:8080")
MODEL_SERVING_URL  = os.environ.get("MODEL_SERVING_URL",  "http://model-serving:8080")
SENSOR_API_URL     = os.environ.get("SENSOR_API_URL",     "http://sensor-api:8080")


def execute_tool(tool_name: str, tool_args: dict) -> dict:
    if tool_name == "search_documentation":
        return _search_docs(tool_args)
    if tool_name == "predict_irrigation":
        return _predict_irrigation(tool_args)
    if tool_name == "get_sensor_context":
        return _get_sensor_context(tool_args)
    return {"error": f"Herramienta desconocida: {tool_name}"}


def _search_docs(args: dict) -> dict:
    try:
        resp = requests.post(
            f"{RAG_API_URL}/rag/query",
            json={"query": args["query"], "cultivo": args.get("cultivo"), "top_k": 3},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        chunks = data.get("chunks", [])
        if not chunks:
            return {"resultado": "No se encontró documentación relevante para esta consulta."}
        texto = "\n\n---\n\n".join(c["texto"] for c in chunks)
        fuentes = list({c.get("doc_path", c.get("titulo", "")) for c in chunks})
        return {"resultado": texto, "fuentes": fuentes}
    except Exception as e:
        return {"error": f"Error consultando documentación: {e}"}


def _get_sensor_context(args: dict) -> dict:
    # Validación explícita: parcela_id es required pero protegemos el servidor
    parcela_id = args.get("parcela_id")
    if not parcela_id:
        return {"error": "parcela_id es obligatorio para consultar sensores."}
    try:
        resp = requests.get(
            f"{SENSOR_API_URL}/sensores/contexto",
            params={"parcela_id": parcela_id},
            timeout=10,
        )
        if resp.status_code != 200:
            return {"resultado": "No hay datos de sensores disponibles para esta parcela."}
        return resp.json()
    except Exception as e:
        return {"error": f"Error obteniendo datos del sensor: {e}"}


def _predict_irrigation(args: dict) -> dict:
    # Validación: los tres campos son required — fallamos limpio si faltan
    parcela_id = args.get("parcela_id")
    cultivo    = args.get("cultivo")
    fase       = args.get("fase")
    if not parcela_id or not cultivo or not fase:
        return {"error": "Faltan datos obligatorios: parcela_id, cultivo y fase son necesarios."}
    try:
        resp = requests.post(
            f"{MODEL_SERVING_URL}/recomendar",
            json={
                "parcela_id": parcela_id,
                "cultivo":    cultivo,
                "fase":       fase,
                "codigo_ine": args.get("codigo_ine", ""),
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": f"Error obteniendo predicción de riego: {e}"}
