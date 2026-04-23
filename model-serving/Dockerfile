FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY data/cultivos_referencia.json ./data/cultivos_referencia.json

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]