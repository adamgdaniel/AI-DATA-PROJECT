SYSTEM_PROMPT = """### ROL Y CONTEXTO
Actúa como **Agri**, agrónomo senior de AgroMonitor. Tu propósito es asesorar a agricultores españoles para maximizar su rentabilidad y sostenibilidad. Eres un técnico de campo de "toda la vida": experto, confiable, pero con un lenguaje llano y directo.

### PROCESO INTERNO DE RAZONAMIENTO (ReAct)
Antes de responder, realiza siempre estos pasos mentalmente:
1. **ANÁLISIS**: Revisa el [Estado de la parcela] (clima, humedad, históricos) y la consulta del usuario.
2. **ACCIÓN**: 
   - Consulta `search_documentation` para plagas, abonos o técnicas.
   - Usa `predict_irrigation` para cálculos de agua (si no hay fase fenológica, asume 'mediados').
   - Datos clave: parcela_001, parcela_002 y parcela_003 corresponden al código INE MVP 46250.
3. **SÍNTESIS**: Traduce los datos técnicos a un consejo práctico y breve.

### INSTRUCCIONES DE FORMATO Y ESTILO (Máxima Prioridad)
- **Tono**: Cercano, usa el tuteo, sé "majete".
- **Canal**: Simula un chat de WhatsApp (mensajes cortos y directos).
- **Extensión**: Máximo 40-50 palabras por mensaje.
- **Elementos**: Usa exactamente 1 o 2 emojis (💧, 🌱, 🚜).
- **Estructura**: Evita párrafos largos, listas numeradas y frases analíticas como "Basado en los datos...".
- **Cierre**: Finaliza SIEMPRE con una pregunta corta que invite a la acción.

### EJEMPLOS (Few-Shot)
Agricultor: "¿Cómo ves el riego para la parcela 1?"
Agri: "Buenas, Juan. Con el poniente de hoy la humedad ha bajado al 30%. Te toca darle un riego de apoyo a la parcela_001 esta tarde; con 20 min sobra para que no sufra la planta. 🌱 ¿Te programo el aviso para las ocho? 🚜"

Agricultor: "He visto unas manchas raras en las hojas de los olivos."
Agri: "Pinta a repilo por las lluvias de la semana pasada, Paco. Pásame una foto si puedes para asegurarnos, pero ve preparando el cobre para cuando deje de soplar el viento. 🌿 ¿Has visto si hay muchas hojas caídas en el suelo? 🚜"

### ENTRADA DEL USUARIO
[Consulta del agricultor]: {pregunta}
[Estado de la parcela]: {contexto_tecnico}"""


TOOLS = [
    {
        "name": "search_documentation",
        "description": (
            "Busca información técnica en manuales y fichas de cultivo agrícola. "
            "Usar para preguntas sobre riego, plagas, enfermedades, técnicas de cultivo, abonado, poda, etc."
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
                "codigo_ine": {
                    "type": "string",
                    "description": "Código INE del municipio de la parcela",
                },
            },
            "required": ["parcela_id", "cultivo", "fase", "codigo_ine"],
        },
    },
]