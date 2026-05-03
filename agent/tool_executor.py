import os
import requests

RAG_API_URL       = os.environ.get("RAG_API_URL",       "http://rag-api:8080")
MODEL_SERVING_URL = os.environ.get("MODEL_SERVING_URL", "http://model-serving:8080")


def execute_tool(tool_name: str, tool_args: dict) -> dict:
    if tool_name == "search_documentation":
        return _search_docs(tool_args)
    if tool_name == "predict_irrigation":
        return _predict_irrigation(tool_args)
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


def _predict_irrigation(args: dict) -> dict:
    try:
        resp = requests.post(
            f"{MODEL_SERVING_URL}/recomendar",
            json={
                "parcela_id": args["parcela_id"],
                "cultivo":    args["cultivo"],
                "fase":       args["fase"],
                "codigo_ine": args.get("codigo_ine", ""),
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": f"Error obteniendo predicción de riego: {e}"}
