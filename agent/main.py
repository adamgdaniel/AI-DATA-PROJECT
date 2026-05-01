import os
import requests
import vertexai
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from vertexai.generative_models import (
    GenerativeModel, Tool, FunctionDeclaration, Part
)

from agent_config import SYSTEM_PROMPT, TOOLS
from tool_executor import execute_tool

app = FastAPI()

GCP_PROJECT    = os.environ.get("GCP_PROJECT_ID", "project-7f8b4dee-2b72-40f2-941")
GCP_REGION     = os.environ.get("GCP_REGION", "europe-west1")
SENSOR_API_URL = os.environ.get("SENSOR_API_URL", "http://sensor-api:8080")

vertexai.init(project=GCP_PROJECT, location=GCP_REGION)


def _build_tools() -> list[Tool]:
    return [Tool(function_declarations=[
        FunctionDeclaration(
            name=t["name"],
            description=t["description"],
            parameters=t["parameters"],
        )
        for t in TOOLS
    ])]


def _get_sensor_context(parcela_usuario_id: int) -> str:
    """Llama a sensor-api y formatea el contexto como texto para el prompt."""
    try:
        resp = requests.get(
            f"{SENSOR_API_URL}/sensores/contexto",
            params={"parcela_id": parcela_usuario_id},
            timeout=10,
        )
        if resp.status_code != 200:
            return ""
        ctx = resp.json()
        lines = [f"Cultivo: {ctx['parcela_info'].get('cultivo', 'desconocido')}"]
        for var, vals in ctx.get("ultimas_24h", {}).items():
            lines.append(f"{var} (24h): media={vals['avg']}, min={vals['min']}, max={vals['max']}")
        acciones = ctx.get("ultimas_acciones", [])
        if acciones:
            a = acciones[0]
            lines.append(f"Última acción: {a['tipo']} el {a['fecha'][:10]}")
        return "\n".join(lines)
    except Exception:
        return ""


class ChatRequest(BaseModel):
    user_id: int
    parcela_usuario_id: Optional[int] = None
    mensaje: str


@app.post("/agent/chat")
def chat(req: ChatRequest):
    # 1. Obtener contexto de la parcela desde sensor-api
    contexto = _get_sensor_context(req.parcela_usuario_id) if req.parcela_usuario_id else ""

    # 2. Construir prompt enriquecido con el contexto
    if contexto:
        prompt = f"[Estado actual de la parcela]\n{contexto}\n\n[Pregunta del agricultor]\n{req.mensaje}"
    else:
        prompt = req.mensaje

    # 3. Llamar a Gemini con las tools definidas
    model = GenerativeModel(
        model_name="gemini-1.5-pro",
        system_instruction=SYSTEM_PROMPT,
        tools=_build_tools(),
    )
    session = model.start_chat()
    response = session.send_message(prompt)

    # 4. Resolver tool calls en bucle (máximo 3 turnos)
    for _ in range(3):
        tool_parts = [
            p for p in response.candidates[0].content.parts
            if hasattr(p, "function_call") and p.function_call.name
        ]
        if not tool_parts:
            break

        responses = [
            Part.from_function_response(
                name=p.function_call.name,
                response=execute_tool(p.function_call.name, dict(p.function_call.args)),
            )
            for p in tool_parts
        ]
        response = session.send_message(responses)

    # 5. Extraer texto final de la respuesta
    texto_final = "".join(
        p.text for p in response.candidates[0].content.parts if hasattr(p, "text")
    )
    return {"respuesta": texto_final.strip()}


@app.get("/health")
def health():
    return {"status": "ok"}
