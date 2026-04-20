FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY main.py .
COPY init_db.py .
CMD ["sh", "-c", "python init_db.py && python main.py"]
