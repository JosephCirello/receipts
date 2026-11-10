# Receipts: one container, the web app, the MCP endpoint and PayPal's official MCP server.
# Python and every library pinned to the versions the 44 tests and the recorded runs were checked with.
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY requirements.txt package.json package-lock.json ./
RUN pip install --no-cache-dir fastapi==0.162.2 uvicorn==0.54.0 openai==3.46.0 requests==2.34.2 mcp==2.3.0 pydantic==2.14.3
# PayPal's MCP server is needed only in sandbox mode; if it fails to install, the stand-in still serves the demo
RUN npm ci --omit=dev || echo "npm install failed: sandbox mode unavailable in this image; the stand-in works"

COPY receipts ./receipts
COPY static ./static
COPY scenarios ./scenarios
COPY results ./results
COPY examples ./examples
COPY app.py run_batch.py regrade.py sandbox_check.py ./

# Live model runs are off on a public demo by default (recorded real runs replay through Receipts now).
ENV RECEIPTS_LIVE=0 PAYPAL_MODE=auto PORT=8090
EXPOSE 8090
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
