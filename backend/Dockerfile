FROM python:3.12-slim

# curl: usado pelo healthcheck do compose (GET /health)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Processo não roda como root (porta 8000 é não-privilegiada; logs vão a stdout,
# nada é escrito em disco).
RUN useradd --uid 1000 --create-home appuser
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
