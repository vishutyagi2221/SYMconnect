FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8765

WORKDIR /app

COPY requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt \
    && useradd --create-home --uid 10001 symconnect

COPY symconnect ./symconnect

USER symconnect
EXPOSE 8765

CMD ["sh", "-c", "python -m symconnect.server --host 0.0.0.0 --port ${PORT}"]
