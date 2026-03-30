# worker/embedder.py
# Polls S3 for embed trigger files written by chunker.py.
# For each trigger:
#   1. Reads chunks JSON from S3 (dev/chunks/)
#   2. Generates 768-dim BGE embeddings via sentence-transformers
#   3. Stores in ChromaDB (persistent, one collection per doc)
#   4. Saves embedding vectors + metadata to S3 (dev/embeddings/)

import boto3
import chromadb
import json
import os
import time
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

load_dotenv()

BUCKET          = "genai-rag-bucket-gd"
TRIGGER_PREFIX  = "dev/triggers/embed/"
CHUNKS_PREFIX   = "dev/chunks/"
EMBEDDINGS_PREFIX = "dev/embeddings/"
AWS_REGION      = os.getenv("AWS_REGION", "us-east-1")
CHROMA_PATH     = os.getenv("CHROMA_PATH", "./chroma_db")
POLL_INTERVAL   = 10
BATCH_SIZE      = 64   # chunks per embedding batch
BGE_MODEL       = "BAAI/bge-base-en-v1.5"

print(f"[INIT] Loading BGE model: {BGE_MODEL}")
model = SentenceTransformer(BGE_MODEL)
print(f"[INIT] Model loaded. Embedding dim: {model.get_sentence_embedding_dimension()}")

chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
print(f"[INIT] ChromaDB initialized at: {CHROMA_PATH}")


# ── Helpers ──────────────────────────────────────────────────────────────────

def collection_name_from_key(chunks_key: str) -> str:
    """Derive a safe ChromaDB collection name from S3 key."""
    name = chunks_key.removeprefix(CHUNKS_PREFIX).replace("/", "_").replace(" ", "_")
    # ChromaDB collection names: 3-63 chars, alphanumeric + underscore + hyphen
    name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in name)
    return name[:63] if len(name) > 63 else name


def embed_in_batches(texts: list[str]) -> list[list[float]]:
    """Embed texts in batches, return list of vectors."""
    all_vectors = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        # BGE instruction prefix improves retrieval quality
        prefixed = [f"Represent this financial document passage: {t}" for t in batch]
        vecs = model.encode(prefixed, normalize_embeddings=True)
        all_vectors.extend(vecs.tolist())
        print(f"[EMBED] Batch {i // BATCH_SIZE + 1}: {len(batch)} chunks embedded")
    return all_vectors


# ── Main processor ────────────────────────────────────────────────────────────

def process_trigger(s3, trigger_key: str):
    print(f"[TRIGGER] Found: s3://{BUCKET}/{trigger_key}")

    obj = s3.get_object(Bucket=BUCKET, Key=trigger_key)
    chunks_key = obj["Body"].read().decode("utf-8").strip()

    print(f"[READ]  s3://{BUCKET}/{chunks_key}")
    chunks_obj = s3.get_object(Bucket=BUCKET, Key=chunks_key)
    data = json.loads(chunks_obj["Body"].read())
    chunks = data.get("chunks", [])

    if not chunks:
        print(f"[SKIP] No chunks in {chunks_key}")
        s3.delete_object(Bucket=BUCKET, Key=trigger_key)
        return

    print(f"[EMBED] Embedding {len(chunks)} chunks from {chunks_key}")

    texts    = [c["content"] for c in chunks]
    vectors  = embed_in_batches(texts)

    # ── ChromaDB ──────────────────────────────────────────────────────────────
    col_name = collection_name_from_key(chunks_key)
    collection = chroma_client.get_or_create_collection(
        name=col_name,
        metadata={"hnsw:space": "cosine"}
    )

    collection.upsert(
        ids=[f"{col_name}_{c['chunk_index']}" for c in chunks],
        embeddings=vectors,
        documents=texts,
        metadatas=[{
            "section":     c["section"],
            "type":        c["type"],
            "chunk_index": c["chunk_index"],
            "source_key":  chunks_key,
        } for c in chunks],
    )
    print(f"[CHROMA] Upserted {len(chunks)} chunks → collection '{col_name}'")

    # ── S3 embeddings backup ──────────────────────────────────────────────────
    embeddings_payload = {
        "source_chunks_key": chunks_key,
        "chroma_collection":  col_name,
        "model": BGE_MODEL,
        "dimensions": 768,
        "count": len(chunks),
        "embeddings": [
            {
                "chunk_index": c["chunk_index"],
                "section":     c["section"],
                "type":        c["type"],
                "content":     c["content"],
                "vector":      vectors[i],
            }
            for i, c in enumerate(chunks)
        ]
    }

    embeddings_key = chunks_key.replace(CHUNKS_PREFIX, EMBEDDINGS_PREFIX)
    s3.put_object(
        Bucket=BUCKET,
        Key=embeddings_key,
        Body=json.dumps(embeddings_payload, ensure_ascii=False),
    )
    print(f"[SAVED] s3://{BUCKET}/{embeddings_key}")

    s3.delete_object(Bucket=BUCKET, Key=trigger_key)
    print(f"[DONE]  Trigger deleted: {trigger_key}\n")


# ── Polling loop ──────────────────────────────────────────────────────────────

def poll():
    s3 = boto3.client("s3", region_name=AWS_REGION)
    print(f"[START] Embedder polling s3://{BUCKET}/{TRIGGER_PREFIX} every {POLL_INTERVAL}s")

    while True:
        paginator = s3.get_paginator("list_objects_v2")
        found = False
        for page in paginator.paginate(Bucket=BUCKET, Prefix=TRIGGER_PREFIX):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".txt"):
                    found = True
                    try:
                        process_trigger(s3, key)
                    except Exception as e:
                        print(f"[ERROR] {key}: {e}")

        if not found:
            print(f"[POLL]  No embed triggers, sleeping {POLL_INTERVAL}s ...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    poll()
