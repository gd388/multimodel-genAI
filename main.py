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

