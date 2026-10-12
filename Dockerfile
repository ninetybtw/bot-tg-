FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
COPY webapp ./webapp
EXPOSE 8080
CMD ["python", "-m", "bot"]
