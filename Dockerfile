# syntax=docker/dockerfile:1
FROM python:3.11-slim

# System deps: libgomp1 for ONNX Runtime (fastembed)
# Textract is a managed AWS API — no local OCR/PDF libs needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Layer 1: heavy ML deps (cached until these lines change) ──────────────────
# fastembed: ONNX-based BGE embeddings (no torch, ~150MB)
# Textract is pure AWS API — boto3 (in requirements.txt) is the only dep
RUN pip install fastembed qdrant-client

# ── Layer 2: lightweight app deps ─────────────────────────────────────────────
COPY requirements.txt .
RUN pip install -r requirements.txt

# ── Layer 3: app code (changes most often, always fast) ───────────────────────
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
