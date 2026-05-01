FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py agent_config.py tool_executor.py ./
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
