FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY vu-qa-bot/ ./vu-qa-bot/
COPY api/ ./api/
COPY web/ ./web/

ENV PYTHONPATH=/app/vu-qa-bot
ENV PROFILES_PATH=/data/profiles.json

VOLUME /data

EXPOSE 8080

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
