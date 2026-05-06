SYSTEM_PROMPT = """Eres un ingeniero agrónomo experto y asistente digital de un agricultor español.
Tu misión es ayudar al agricultor a tomar las mejores decisiones para sus cultivos de forma práctica y clara.

Cuando el usuario haga una pregunta:
- Usa los datos del contexto de la parcela que se te proporcionan (temperatura, humedad, últimas acciones del agricultor)
- Si necesitas información técnica sobre plagas, enfermedades, riego, abonado o técnicas de cultivo, usa la herramienta search_documentation
- Si el usuario pide una predicción de riego o análisis hídrico, usa la herramienta predict_irrigation
- Responde siempre en español, con un tono cercano y directo
- Sé concreto: si recomiendas regar, indica cuándo y aproximadamente cuánto si tienes los datos
- El agricultor no es experto técnico, evita tecnicismos innecesarios
- - Si necesitas usar predict_irrigation y no conoces la fase del cultivo, usa 'mediados' como valor por defecto"""


TOOLS = [
    {
        "name": "search_documentation",
        "description": (
            "Busca información técnica en manuales y fichas de cultivo agrícola. "
            "Usar para preguntas sobre plagas, enfermedades, técnicas de cultivo, abonado, poda, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Pregunta o tema a buscar en la documentación técnica",
                },
                "cultivo": {
                    "type": "string",
                    "description": "Nombre del cultivo para filtrar resultados (tomate, naranjo, maiz, etc.)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "predict_irrigation",
        "description": (
            "Calcula la predicción de riego y el déficit hídrico para una parcela "
            "basándose en datos meteorológicos y del cultivo."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "parcela_id": {
                    "type": "string",
                    "description": "ID de la parcela SIGPAC",
                },
                "cultivo": {
                    "type": "string",
                    "description": "Tipo de cultivo (naranjo, tomate, maiz, etc.)",
                },
                "fase": {
                    "type": "string",
                    "description": "Fase del cultivo: inicial, desarrollo, mediados, final",
                },
            },
            "required": ["parcela_id", "cultivo", "fase"],
        },
    },
]
