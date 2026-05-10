import os
import requests
from datetime import datetime
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from google import genai
from google.genai import types

from agent_config import SYSTEM_PROMPT, TOOLS
from tool_executor import execute_tool

app = FastAPI()

GCP_PROJECT   = os.environ.get("GCP_PROJECT_ID", "project-7f8b4dee-2b72-40f2-941")
SENSOR_API_URL = os.environ.get("SENSOR_API_URL", "http://sensor-api:8080")

client = genai.Client(enterprise=True, project=GCP_PROJECT, location="global")
MODEL = "gemini-3.1-flash-lite"


def _build_tools() -> list:
    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name=t["name"],
            description=t["description"],
            parameters=t["parameters"],
        )
        for t in TOOLS
    ])]


def _get_sensor_context(parcela_id: str) -> str:
    try:
        resp = requests.get(
            f"{SENSOR_API_URL}/sensores/contexto",
            params={"parcela_id": parcela_id},
            timeout=10,
        )
        if resp.status_code != 200:
            return ""
        ctx = resp.json()

        lines = [f"Parcela: {ctx.get('parcela_id', parcela_id)}"]
        lines.append(f"Cultivo: {ctx.get('cultivo', 'desconocido')}")

        h24 = ctx.get("ultimas_24h", {})
        if h24.get("temp_media") is not None:
            lines.append(f"Temperatura (24h): {h24['temp_media']}°C")
        if h24.get("humedad_suelo_media") is not None:
            lines.append(f"Humedad suelo (24h): {h24['humedad_suelo_media']}%")
        if h24.get("humedad_ambiental_media") is not None:
            lines.append(f"Humedad ambiental (24h): {h24['humedad_ambiental_media']}%")

        d7 = ctx.get("ultimos_7d", {})
        if d7.get("temp_media") is not None:
            lines.append(f"Temperatura media (7d): {d7['temp_media']}°C")
        if d7.get("precipitacion_acumulada") is not None:
            lines.append(f"Precipitación acumulada (7d): {d7['precipitacion_acumulada']} mm")
        if d7.get("et0_acumulado") is not None:
            lines.append(f"ET₀ acumulado (7d): {d7['et0_acumulado']} mm")

        acciones = ctx.get("acciones_recientes", [])
        if acciones:
            a = acciones[0]
            detalle = f" ({a['detalle']})" if a.get("detalle") else ""
            lines.append(f"Última acción: {a['tipo']} el {a['fecha'][:10]}{detalle}")

        return "\n".join(lines)
    except Exception:
        return ""


class ChatRequest(BaseModel):
    user_id: str
    parcela_id: Optional[str] = None
    mensaje: str


@app.post("/agent/chat")
def chat(req: ChatRequest):
    contexto = _get_sensor_context(req.parcela_id) if req.parcela_id else ""

    if contexto:
        prompt = f"[Estado actual de la parcela]\n{contexto}\n\n[Pregunta del agricultor]\n{req.mensaje}"
    else:
        prompt = req.mensaje

    today = datetime.now().strftime("%Y-%m-%d")
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT + f"\n\nFecha actual: {today}.",
        tools=_build_tools(),
        max_output_tokens=400,
    )

    chat_session = client.chats.create(model=MODEL, config=config)
    response = chat_session.send_message(prompt)

    for _ in range(3):
        parts = response.candidates[0].content.parts if response.candidates[0].content else []
        tool_parts = [
            p for p in parts
            if hasattr(p, "function_call") and p.function_call and p.function_call.name
        ]
        if not tool_parts:
            break

        tool_responses = [
            types.Part.from_function_response(
                name=p.function_call.name,
                response=execute_tool(p.function_call.name, dict(p.function_call.args)),
            )
            for p in tool_parts
        ]
        response = chat_session.send_message(tool_responses)

    final_parts = response.candidates[0].content.parts if response.candidates[0].content else []
    texto_final = "".join(
        p.text for p in final_parts
        if hasattr(p, "text") and p.text
    )
    return {"respuesta": texto_final.strip()}


@app.get("/health")
def health():
    return {"status": "ok"}