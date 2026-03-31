import os
import uuid
import logging
import boto3
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchText, MatchValue, Distance, VectorParams

from llm.router import get_router, QueryMode

load_dotenv()
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Financial RAG API")

# ── Shared clients (initialised once at startup) ──────────────────────────────
AWS_REGION  = os.getenv("AWS_REGION", "us-east-1")
BUCKET      = os.getenv("S3_BUCKET", "genai-rag-bucket-gd")
RAW_PREFIX  = "dev/raw/"
COLLECTION  = "documents"
TOP_K       = 5

_embedder = TextEmbedding("BAAI/bge-base-en-v1.5")
_qdrant   = QdrantClient(
    host=os.getenv("QDRANT_HOST", "localhost"),
    port=int(os.getenv("QDRANT_PORT", 6333)),
)
_s3  = boto3.client("s3",  region_name=AWS_REGION)
_sqs = boto3.client("sqs", region_name=AWS_REGION)


# ── Request / Response models ────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question:  str
    mode:      QueryMode = QueryMode.GROQ    # groq | gemini (HF is auto-fallback)
    top_k:     int       = TOP_K
    filter_doc: str | None = None            # optional: restrict to one doc title


class QueryResponse(BaseModel):
    answer:   str
    provider: str                           # which LLM answered
    model:    str
    sources:  list[dict]                    # chunks used as context


# ── Helpers ───────────────────────────────────────────────────────────────────

def _embed(text: str) -> list[float]:
    return list(_embedder.embed([text]))[0].tolist()


def _build_prompt(question: str, chunks: list[dict]) -> tuple[str, str]:
    """Returns (system, user_prompt) with retrieved context injected."""
    context = "\n\n---\n\n".join(
        f"[Source: {c['payload'].get('doc_title', 'unknown')} | "
        f"Section: {c['payload'].get('section', '')}]\n"
        f"{c['payload'].get('content', '')}"
        for c in chunks
    )
    system = (
        "You are a financial analyst assistant. Answer questions strictly based on "
        "the provided document excerpts. If the answer is not in the context, say "
        "'The provided documents do not contain enough information to answer this.'"
    )
    user_prompt = (
        f"Context:\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer:"
    )
    return system, user_prompt


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "service": "Financial RAG API",
        "endpoints": ["/upload", "/query", "/status/{job_id}"],
        "llm_providers": get_router().available_providers,
    }


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    """
    Accept a PDF, upload to S3 dev/raw/, return a job_id.
    S3 event notification automatically triggers the parse → chunk → embed pipeline.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    job_id   = str(uuid.uuid4())
    s3_key   = f"{RAW_PREFIX}{job_id}_{file.filename}"
    contents = await file.read()

    _s3.put_object(Bucket=BUCKET, Key=s3_key, Body=contents)

    return {"job_id": job_id, "s3_key": s3_key, "status": "processing"}


@app.get("/status/{job_id}")
def status(job_id: str):
    """
    Check if a document has been fully embedded.
    Searches Qdrant for any chunk whose source_key contains the job_id.
    """
    results = _qdrant.scroll(
        collection_name=COLLECTION,
        scroll_filter=Filter(
            must=[FieldCondition(key="source_key", match=MatchText(text=job_id))]
        ),
        limit=1,
        with_payload=False,
    )
    points = results[0]
    if points:
        return {"job_id": job_id, "status": "completed", "chunks_found": len(points)}
    return {"job_id": job_id, "status": "processing"}


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    """
    RAG query:
      1. Embed the question (fastembed / BGE)
      2. Search Qdrant for top-k similar chunks
      3. Build prompt with retrieved context
      4. Route to the appropriate LLM (Groq / Gemini / HF)
      5. Return answer + sources
    """
    # 1. Embed question
    q_vector = _embed(req.question)

    # 2. Qdrant search (optional per-doc filter)
    search_filter = None
    if req.filter_doc:
        search_filter = Filter(
            must=[FieldCondition(key="doc_title", match=MatchValue(value=req.filter_doc))]
        )

    result = _qdrant.query_points(
        collection_name=COLLECTION,
        query=q_vector,
        limit=req.top_k,
        query_filter=search_filter,
        with_payload=True,
    )
    hits = result.points

    if not hits:
        raise HTTPException(status_code=404, detail="No relevant documents found in the knowledge base.")

    chunks = [{"score": h.score, "payload": h.payload} for h in hits]

    # 3. Build prompt
    system, user_prompt = _build_prompt(req.question, chunks)

    # 4. Route to LLM
    router   = get_router()
    llm_resp = router.generate(user_prompt, mode=req.mode, system=system)

    # 5. Return
    sources = [
        {
            "score":     round(c["score"], 4),
            "doc_title": c["payload"].get("doc_title", ""),
            "section":   c["payload"].get("section", ""),
            "snippet":   c["payload"].get("content", "")[:300],
        }
        for c in chunks
    ]

    return QueryResponse(
        answer=llm_resp.content,
        provider=llm_resp.provider,
        model=llm_resp.model,
        sources=sources,
    )


@app.post("/analyze")
def analyze(mode: QueryMode = QueryMode.GROQ, filter_doc: str | None = None):
    """
    Pull all indexed financial chunks, summarise key numbers, then ask the
    LLM to compute the 4 KPIs and return structured JSON + narrative.
    """
    scroll_filter = None
    if filter_doc:
        scroll_filter = Filter(
            must=[FieldCondition(key="doc_title", match=MatchValue(value=filter_doc))]
        )

    pts, offset = [], None
    while True:
        result, offset = _qdrant.scroll(
            collection_name=COLLECTION,
            scroll_filter=scroll_filter,
            limit=250,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        pts.extend(result)
        if offset is None:
            break

    if not pts:
        raise HTTPException(status_code=404, detail="No documents indexed.")

    # Collect table chunks (pipes = markdown tables from Textract)
    table_chunks = [
        p.payload.get("content", "")
        for p in pts
        if "|" in p.payload.get("content", "")
    ][:40]  # cap to avoid token overflow

    if not table_chunks:
        # Fall back to all chunks
        table_chunks = [p.payload.get("content", "") for p in pts][:30]

    financial_data = "\n\n---\n\n".join(table_chunks)

    system = "You are a senior financial analyst. Always follow the exact output format requested."

    prompt = f"""You are a financial analyst.

Given the following financial data, calculate and present insights for the following 4 KPIs:

1. Revenue
2. Net Profit Margin
3. Operating Cash Flow
4. Return on Investment (ROI)

### Instructions:
* Extract relevant values from the data
* Compute each KPI using correct formulas
* Show step-by-step calculations
* Provide final values clearly

### Output Format:

#### 1. KPI Summary Table

| KPI | Value | Insight |
| --- | ----- | ------- |

#### 2. Detailed Calculations

* Revenue:
* Net Profit Margin:
* Operating Cash Flow:
* ROI:

#### 3. Insights

* Explain trends
* Highlight risks or growth

#### 4. Charts

Represent chart data in JSON format inside a ```json code block.
Return exactly this structure with real numbers extracted from the data:

```json
[
  {{"chart_type": "line", "title": "Revenue Trend", "x_axis": [], "y_axis": []}},
  {{"chart_type": "bar", "title": "Profit Margin Comparison (%)", "x_axis": [], "y_axis": []}},
  {{"chart_type": "line", "title": "Operating Cash Flow Over Time", "x_axis": [], "y_axis": []}},
  {{"chart_type": "bar", "title": "ROI Comparison (%)", "x_axis": [], "y_axis": []}}
]
```

### Financial Data:

{financial_data}

Ensure accurate calculations, clean structured output, and business-friendly explanations.
"""

    router   = get_router()
    llm_resp = router.generate(prompt, mode=mode, system=system)

    return {
        "analysis": llm_resp.content,
        "provider": llm_resp.provider,
        "model":    llm_resp.model,
    }


@app.delete("/remove")
def remove_all():
    """
    Delete all vectors from the Qdrant collection (recreate it).
    This clears the dashboard so old data doesn't persist.
    """
    _qdrant.recreate_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=768, distance=Distance.COSINE),
    )
    return {"status": "cleared", "collection": COLLECTION}


@app.delete("/remove/{doc_title}")
def remove_document(doc_title: str):
    """Delete all vectors for a specific document by doc_title."""
    _qdrant.delete(
        collection_name=COLLECTION,
        points_selector=Filter(
            must=[FieldCondition(key="doc_title", match=MatchValue(value=doc_title))]
        ),
    )
    return {"status": "removed", "doc_title": doc_title}

