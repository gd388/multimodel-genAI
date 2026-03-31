# worker/embedder.py
# Stage 3: Polls the embed-queue SQS, reads chunks from S3 (staging),
# extracts doc metadata from parsed markdown, generates BGE embeddings,
# upserts into Qdrant with full metadata payload, then deletes S3 staging files.
# Qdrant is the single source of truth — no permanent intermediate S3 data.

import boto3
import json
import os
import re
import uuid
from dotenv import load_dotenv
from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

load_dotenv()

BUCKET          = "genai-rag-bucket-gd"
CHUNKS_PREFIX   = "dev/chunks/"
PARSED_PREFIX   = "dev/parsed/"
EMBED_QUEUE_URL = os.getenv("SQS_EMBED_URL")
AWS_REGION      = os.getenv("AWS_REGION", "us-east-1")
BGE_MODEL       = "BAAI/bge-base-en-v1.5"
DIMENSION       = 768
COLLECTION      = "documents"

BATCH_SIZE = 32

print(f"[INIT] Loading BGE model: {BGE_MODEL} (fastembed/ONNX, batch={BATCH_SIZE})")
model = TextEmbedding(BGE_MODEL)
print(f"[INIT] Model loaded. Embedding dim: {DIMENSION}")


# ── Qdrant client ─────────────────────────────────────────────────────────────
qdrant = QdrantClient(
    host=os.getenv("QDRANT_HOST", "localhost"),
    port=int(os.getenv("QDRANT_PORT", 6333)),
)

existing = [c.name for c in qdrant.get_collections().collections]
if COLLECTION not in existing:
    qdrant.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=DIMENSION, distance=Distance.COSINE),
    )
    print(f"[QDRANT] Created collection '{COLLECTION}'")
else:
    print(f"[QDRANT] Collection '{COLLECTION}' ready")


# ── Metadata extraction ───────────────────────────────────────────────────────
_DATE_RE = re.compile(
    r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)'
    r'\s+\d{1,2},?\s+\d{4}'
    r'|\b\d{4}-\d{2}-\d{2}\b'
    r'|\bQ[1-4]\s+\d{4}\b',
    re.IGNORECASE,
)

def extract_doc_metadata(markdown: str, source_key: str) -> dict:
    lines = markdown.splitlines()
    title = ""
    for line in lines:
        s = line.strip()
        if s.startswith("#"):
            title = s.lstrip("#").strip(); break
        elif s:
            title = s; break
    sections = [l.lstrip("#").strip() for l in lines if l.startswith("## ")]
    dates    = list(dict.fromkeys(_DATE_RE.findall(markdown)))[:10]
    return {
        "source_key": source_key,
        "title":      title,
        "sections":   sections,
        "dates":      dates,
        "word_count": len(markdown.split()),
    }


# ── Embedding ─────────────────────────────────────────────────────────────────
def embed_in_batches(texts: list[str]) -> list[list[float]]:
    all_vecs = []
    total    = (len(texts) - 1) // BATCH_SIZE + 1
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        vecs  = list(model.embed(batch))
        all_vecs.extend([v.tolist() for v in vecs])
        print(f"[EMBED] Batch {i // BATCH_SIZE + 1}/{total}: {len(batch)} chunks")
    return all_vecs


# ── Main processor ────────────────────────────────────────────────────────────
def process_message(s3, msg):
    body       = json.loads(msg["Body"])
    chunks_key = body["chunks_key"]
    bucket     = body.get("bucket", BUCKET)

    print(f"[READ]   s3://{bucket}/{chunks_key}")
    chunks_obj = s3.get_object(Bucket=bucket, Key=chunks_key)
    data       = json.loads(chunks_obj["Body"].read())
    chunks     = data.get("chunks", [])

    if not chunks:
        print(f"[SKIP] No chunks in {chunks_key}")
        return

    # Load parsed markdown to extract doc-level metadata
    doc_meta   = {}
    parsed_key = chunks_key.replace(CHUNKS_PREFIX, PARSED_PREFIX)
    try:
        parsed_obj  = s3.get_object(Bucket=bucket, Key=parsed_key)
        parsed_data = json.loads(parsed_obj["Body"].read())
        doc_meta    = extract_doc_metadata(parsed_data.get("markdown", ""), chunks_key)
        print(f"[META]  title='{doc_meta.get('title', '')}' | "
              f"dates={doc_meta.get('dates', [])} | "
              f"sections={len(doc_meta.get('sections', []))}")
    except Exception as e:
        print(f"[META]  Could not load parsed markdown: {e}")

    print(f"[EMBED] Embedding {len(chunks)} chunks ...")
    texts   = [c["content"] for c in chunks]
    vectors = embed_in_batches(texts)

    # ── Qdrant upsert — chunk content + doc metadata as payload ──────────────
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vectors[i],
            payload={
                "chunk_index":    c["chunk_index"],
                "section":        c["section"],
                "type":           c["type"],
                "content":        c["content"],
                "source_key":     chunks_key,
                "doc_title":      doc_meta.get("title", ""),
                "doc_sections":   doc_meta.get("sections", []),
                "doc_dates":      doc_meta.get("dates", []),
                "doc_word_count": doc_meta.get("word_count", 0),
            },
        )
        for i, c in enumerate(chunks)
    ]
    qdrant.upsert(collection_name=COLLECTION, points=points)
    print(f"[QDRANT] Upserted {len(points)} points into '{COLLECTION}'")

    # ── Delete S3 staging files — Qdrant is now source of truth ──────────────
    for key in [chunks_key, parsed_key]:
        try:
            s3.delete_object(Bucket=bucket, Key=key)
            print(f"[CLEAN] Deleted staging: s3://{bucket}/{key}")
        except Exception as e:
            print(f"[WARN]  Could not delete {key}: {e}")

    print(f"[DONE]  {chunks_key} embedded and staging cleaned\n")


# ── Polling loop ──────────────────────────────────────────────────────────────
def poll():
    s3  = boto3.client("s3", region_name=AWS_REGION)
    sqs = boto3.client("sqs", region_name=AWS_REGION)
    print(f"[START] Embedder polling embed-queue: {EMBED_QUEUE_URL}")

    while True:
        response = sqs.receive_message(
            QueueUrl=EMBED_QUEUE_URL,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=10,
        )
        for msg in response.get("Messages", []):
            try:
                process_message(s3, msg)
            except Exception as e:
                print(f"[ERROR] {e}")
            finally:
                sqs.delete_message(
                    QueueUrl=EMBED_QUEUE_URL,
                    ReceiptHandle=msg["ReceiptHandle"],
                )


if __name__ == "__main__":
    poll()
