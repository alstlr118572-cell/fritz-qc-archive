FROM python:3.12-slim

WORKDIR /app
COPY . /app/production_ai

ENV PORT=8765
EXPOSE 8765

CMD ["python3", "production_ai/mira_archive_server.py"]
