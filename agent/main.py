import logging
import os
import requests
from datetime import datetime
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, List
from google import genai
from google.genai import types

from agent_config import SYSTEM_PROMPT, TOOLS
from tool_executor import execute_tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

GCP_PROJECT = os.environ.get("GCP_PROJECT_ID", "project-7f8b4dee-2b72-40f2-941")

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



class ChatRequest(BaseModel):
    user_id: str
    parcela_id: Optional[str] = None
    parcelas_usuario: Optional[List[dict]] = None
    mensaje: str


@app.post("/agent/chat")
def chat(req: ChatRequest):
    partes = []
    if req.parcelas_usuario:
        lista = "\n".join(
            f"- {p.get('nombre', '?')} ({p.get('cultivo', '?')}) → ID: {p.get('parcela_id', '?')}"
            for p in req.parcelas_usuario
        )
        partes.append(f"[Parcelas del usuario]\n{lista}")
    partes.append(f"[Pregunta del agricultor]\n{req.mensaje}")
    prompt = "\n\n".join(partes)

    today = datetime.now().strftime("%Y-%m-%d")
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT + f"\n\nFecha actual: {today}.",
        tools=_build_tools(),
    )

    chat_session = client.chats.create(model=MODEL, config=config)
    logger.info(
        "agent.chat input user_id=%s parcela_id=%s prompt=%s",
        req.user_id,
        req.parcela_id,
        prompt,
    )
    response = chat_session.send_message(prompt)

    for _ in range(3):
        parts = response.candidates[0].content.parts if response.candidates[0].content else []
        tool_parts = [
            p for p in parts
            if hasattr(p, "function_call") and p.function_call and p.function_call.name
        ]
        if not tool_parts:
            break

        tool_responses = []
        for p in tool_parts:
            fc = p.function_call
            tool_args = dict(fc.args)
            logger.info(
                "agent.chat tool_request name=%s args=%s",
                fc.name,
                tool_args,
            )
            tool_payload = execute_tool(fc.name, tool_args)
            logger.info("agent.chat tool_response payload=%s", tool_payload)
            tool_responses.append(
                types.Part.from_function_response(
                    name=fc.name,
                    response=tool_payload,
                )
            )
        response = chat_session.send_message(tool_responses)

    final_parts = response.candidates[0].content.parts if response.candidates[0].content else []
    texto_final = "".join(
        p.text for p in final_parts
        if hasattr(p, "text") and p.text
    )
    out = texto_final.strip()
    logger.info("agent.chat output respuesta=%s", out)
    return {"respuesta": out}


@app.get("/health")
def health():
    return {"status": "ok"}