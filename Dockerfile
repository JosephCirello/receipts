# Receipts: one container, the web app, the MCP endpoint and PayPal's official MCP server.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY requirements.txt package.json package-lock.json ./
RUN pip install --no-cache-dir fastapi uvicorn openai requests "mcp>=2.3" pydantic && npm ci --omit=dev

COPY receipts ./receipts
COPY static ./static
COPY scenarios ./scenarios
COPY results ./results
COPY examples ./examples
COPY app.py run_batch.py regrade.py sandbox_check.py ./

# Live model runs are off on a public demo by default (recorded real runs replay through PayPal now).
ENV RECEIPTS_LIVE=0 PAYPAL_MODE=auto PORT=8090
EXPOSE 8090
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
