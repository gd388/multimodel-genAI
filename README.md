# FinSight AI — Financial Document RAG Platform

A production-ready, multi-model Retrieval-Augmented Generation (RAG) platform for financial documents. Upload SEC filings, 10-Ks, or any financial PDF and get AI-powered answers and KPI dashboards extracted directly from the documents.

---

## Architecture Overview

```
PDF Upload
    │
    ▼
FastAPI (/upload)
    │
    └─► S3 (raw storage)
            │
            ▼  (S3 event → SQS)
        Worker (Stage 1: Textract)
            │  AWS Textract async document analysis
            ▼
        Chunker (Stage 2: Chunking)
            │  3-strategy: text / table / image chunks
            ▼
        Embedder (Stage 3: Embedding)
            │  fastembed BGE-base-en-v1.5 (ONNX)
            ▼
        Qdrant (Vector Store)
            │
            ▼
    FastAPI (/query, /analyze)
            │
            ▼
        LLM Router
        ├── Groq (LLaMA 3.3 70B)      ← primary fast
        ├── Gemini (2.0 Flash Lite)    ← structured/quality
        └── HuggingFace (Llama-3.1-8B) ← silent fallback
            │
            ▼
    Streamlit UI
    ├── Query Page  — ask questions, get sourced answers
    └── Dashboard   — KPI cards, charts, AI analysis
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI + Uvicorn |
| UI | Streamlit |
| OCR / Parsing | AWS Textract (async, table extraction) |
| Embedding | fastembed `BAAI/bge-base-en-v1.5` (ONNX, 768-dim) |
| Vector DB | Qdrant |
| Queue | AWS SQS (3-stage pipeline) |
| Storage | AWS S3 |
| LLM — Fast | Groq `llama-3.3-70b-versatile` |
| LLM — Quality | Google `gemini-2.0-flash-lite` |
| LLM — Fallback | HuggingFace `meta-llama/Llama-3.1-8B-Instruct` |
| Container | Docker + Docker Compose |

---

## Project Structure

```
├── main.py                  # FastAPI application (all REST endpoints)
├── streamlit_app.py         # Query page UI
├── pages/
│   └── 1_Dashboard.py       # Financial metrics dashboard
├── llm/
│   ├── router.py            # LLM routing logic (mode → provider chain)
│   ├── groq_client.py       # Groq provider
│   ├── gemini_client.py     # Gemini provider
│   ├── hf_client.py         # HuggingFace fallback provider
│   └── base.py              # Abstract BaseLLM + LLMResponse
├── worker/
│   ├── sqs.py               # Stage 1: polls SQS, triggers Textract
│   ├── parser.py            # Stage 1: AWS Textract async parser
│   ├── chunker.py           # Stage 2: text/table/image chunking
│   └── embedder.py          # Stage 3: fastembed + Qdrant upsert
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Prerequisites

- Docker & Docker Compose
- AWS account with:
  - S3 bucket
  - SQS queues (3): `doc-processing-queue`, `doc-chunk-queue`, `doc-embed-queue`
  - S3 event notification → `doc-processing-queue`
  - Textract access enabled
- API keys: Groq, Google Gemini, HuggingFace

---

## Setup

### 1. Clone and configure environment

```bash
git clone <repo-url>
cd multimodel-genAI
cp .env.example .env   # then fill in your values
```

### 2. Configure `.env`

```env
# AWS
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_REGION=us-east-1
S3_BUCKET=your-s3-bucket

# SQS
SQS_URL=https://sqs.us-east-1.amazonaws.com/<account>/doc-processing-queue
SQS_CHUNK_URL=https://sqs.us-east-1.amazonaws.com/<account>/doc-chunk-queue
SQS_EMBED_URL=https://sqs.us-east-1.amazonaws.com/<account>/doc-embed-queue

# LLM Keys
GROQ_API_KEY=your_groq_key
GEMINI_API_KEY=your_gemini_key
HF_TOKEN=your_huggingface_token
```

### 3. Build and run

```bash
docker compose up -d --build
```

Services start in order:
1. `qdrant` — vector store
2. `api` — FastAPI (waits for healthcheck, ~30s first run while downloading embedding model)
3. `worker`, `chunker`, `embedder` — pipeline stages
4. `streamlit` — UI (waits for API to be healthy)

### 4. Access the app

| Service | URL |
|---|---|
| Streamlit UI | http://localhost:8501 |
| FastAPI docs | http://localhost:8000/docs |
| Qdrant UI | http://localhost:6333/dashboard |

---

## Usage

### Upload a Document

1. Open http://localhost:8501
2. Use the sidebar uploader to upload a financial PDF (10-K, annual report, etc.)
3. Wait for processing — pipeline runs: Textract → chunk → embed → Qdrant
4. Status polling shows "completed" when ready

### Query Documents

- Select model: **Groq** (fast) or **Gemini** (structured)
- Type a question: *"What was the total revenue in 2023?"*
- Get a sourced answer with document excerpts

### Dashboard (AI Analysis)

- Navigate to **Dashboard** page
- View auto-extracted KPI cards, charts, and financial tables
- Scroll to **AI-Powered KPI Analysis** and click **Generate AI Analysis**
- LLM computes Revenue, Net Profit Margin, Operating Cash Flow, ROI with step-by-step calculations and charts

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Health check + available providers |
| `POST` | `/upload` | Upload PDF → S3 → triggers pipeline |
| `GET` | `/status/{job_id}` | Check if document is fully indexed |
| `POST` | `/query` | RAG query with LLM answer |
| `POST` | `/analyze` | Full KPI analysis of all indexed documents |
| `DELETE` | `/remove` | Clear all indexed data |
| `DELETE` | `/remove/{doc_title}` | Remove a specific document |

### Query Request Body

```json
{
  "question": "What was operating income in 2023?",
  "mode": "groq",
  "top_k": 5,
  "filter_doc": "amazon 10-k 2023.pdf"
}
```

---

## LLM Routing

The router automatically falls back on failure:

| Mode | Primary | Fallback |
|---|---|---|
| `groq` | Groq LLaMA 3.3 70B | HuggingFace Llama 3.1 8B |
| `gemini` | Gemini 2.0 Flash Lite | HuggingFace Llama 3.1 8B |

To add a new provider:
1. Create `llm/your_client.py` — subclass `BaseLLM`
2. Add it to `_build_registry()` in `llm/router.py`
3. Add to `ROUTE_ORDER` for the desired mode

---

## Docker Services

```yaml
qdrant      # Vector database (port 6333)
api         # FastAPI backend (port 8000, healthchecked)
worker      # SQS poller → Textract parser
chunker     # Text/table chunking
embedder    # fastembed + Qdrant upsert
streamlit   # UI (port 8501, waits for api healthy)
```

**Volumes:**
- `qdrant_data` — persistent vector storage
- `fastembed_cache` — caches ONNX embedding model between restarts

---

## Troubleshooting

**Query returns "No relevant documents found"**
- Check the pipeline completed: `docker compose logs worker embedder --tail 20`
- Verify Qdrant has data: `curl http://localhost:6333/collections/documents`
- Worker may still be running Textract (large PDFs take 1–3 minutes)

**LLM errors (429 quota / 410 Gone)**
- Gemini free-tier has daily limits — switch to Groq mode
- HF fallback uses `router.huggingface.co` (new domain as of 2026)

**API takes long to start**
- First run downloads the BGE embedding model (~400MB) — subsequent starts use the `fastembed_cache` volume

**Worker not processing messages**
- Ensure `PYTHONUNBUFFERED=1` is set (already in docker-compose.yml)
- Check S3 → SQS event notification is configured on your bucket

---

## License

MIT
