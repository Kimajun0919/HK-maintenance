FROM python:3.12-slim

WORKDIR /app

COPY rag_chatbot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY rag_chatbot/app.py .
COPY rag_chatbot/web/ web/

ENV APP_PORT=8080
EXPOSE 8080

CMD ["python", "app.py"]
