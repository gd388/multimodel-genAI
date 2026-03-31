# worker/chunker.py
# Stage 2: Polls the chunk-queue SQS, reads parsed markdown from S3,
# applies chunking strategies, saves chunks to S3 (staging), then sends
# the chunks S3 key to the embed-queue for Stage 3.

import boto3
import json
import os
import re
from dotenv import load_dotenv

load_dotenv()

BUCKET          = "genai-rag-bucket-gd"
CHUNKS_PREFIX   = "dev/chunks/"
PARSED_PREFIX   = "dev/parsed/"
CHUNK_QUEUE_URL = os.getenv("SQS_CHUNK_URL")
EMBED_QUEUE_URL = os.getenv("SQS_EMBED_URL")
AWS_REGION      = os.getenv("AWS_REGION", "us-east-1")
CHUNK_SIZE      = 500
CHUNK_OVERLAP   = 50


# ── Typing ────────────────────────────────────────────────────────────────────

def detect_block_type(line: str) -> str:
    if line.startswith("|"):
        return "table"
    if line.startswith("![") or "<!-- image" in line.lower():
        return "image"
    return "text"


def split_into_typed_blocks(content: str) -> list[dict]:
    """Split a section body into contiguous text / table / image blocks."""
    blocks: list[dict] = []
    current_type = "text"
    current_lines: list[str] = []

    for line in content.splitlines():
        t = detect_block_type(line)

        if t == "image":
            if current_lines:
                blocks.append({"type": current_type, "content": "\n".join(current_lines)})
                current_lines = []
            blocks.append({"type": "image", "content": line})
            current_type = "text"
            continue

        if t != current_type:
            if current_lines:
                blocks.append({"type": current_type, "content": "\n".join(current_lines)})
                current_lines = []
            current_type = t

        current_lines.append(line)

    if current_lines:
        blocks.append({"type": current_type, "content": "\n".join(current_lines)})

    return blocks


# ── Sliding window ────────────────────────────────────────────────────────────

def sliding_window(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks = []
    i = 0
    while i < len(words):
        chunks.append(" ".join(words[i : i + size]))
        i += size - overlap
    return chunks


# ── Main chunker ──────────────────────────────────────────────────────────────

def chunk_markdown(markdown: str) -> list[dict]:
    """
    1. Section-aware split on H1/H2/H3 headings.
    2. Type-aware split each section into text / table / image blocks.
    3. Sliding window applied to text blocks; tables/images kept as single chunks.
    """
    heading_re = re.compile(r"^(#{1,3} .+)$", re.MULTILINE)
    parts = heading_re.split(markdown)

    chunks: list[dict] = []
    chunk_idx = 0
    current_section = "Introduction"

    for part in parts:
        part = part.strip()
        if not part:
            continue

        if heading_re.match(part):
            current_section = part.lstrip("#").strip()
            continue

        for block in split_into_typed_blocks(part):
            content = block["content"].strip()
            if not content:
                continue

            if block["type"] in ("table", "image"):
                chunks.append({
                    "chunk_index": chunk_idx,
                    "section": current_section,
                    "type": block["type"],
                    "content": content,
                })
                chunk_idx += 1
            else:
                for window in sliding_window(content):
                    chunks.append({
                        "chunk_index": chunk_idx,
                        "section": current_section,
                        "type": "text",
                        "content": window,
                    })
                    chunk_idx += 1

    return chunks


# ── SQS loop ──────────────────────────────────────────────────────────────────

def process_message(s3, sqs, msg):
    body       = json.loads(msg["Body"])
    parsed_key = body["parsed_key"]
    bucket     = body.get("bucket", BUCKET)

    print(f"[READ]    s3://{bucket}/{parsed_key}")
    parsed_obj = s3.get_object(Bucket=bucket, Key=parsed_key)
    data       = json.loads(parsed_obj["Body"].read())
    markdown   = data.get("markdown", "")

    print(f"[CHUNK]   Chunking {parsed_key} ...")
    chunks = chunk_markdown(markdown)
    print(f"[CHUNK]   Produced {len(chunks)} chunks "
          f"({sum(1 for c in chunks if c['type']=='text')} text, "
          f"{sum(1 for c in chunks if c['type']=='table')} table, "
          f"{sum(1 for c in chunks if c['type']=='image')} image)")

    chunks_key = parsed_key.replace(PARSED_PREFIX, CHUNKS_PREFIX)
    s3.put_object(
        Bucket=bucket,
        Key=chunks_key,
        Body=json.dumps({"chunks": chunks}, ensure_ascii=False),
    )
    print(f"[SAVED]   s3://{bucket}/{chunks_key}")

    sqs.send_message(
        QueueUrl=EMBED_QUEUE_URL,
        MessageBody=json.dumps({"chunks_key": chunks_key, "bucket": bucket}),
    )
    print(f"[QUEUE]   Sent to embed-queue: {chunks_key}\n")


def poll():
    s3  = boto3.client("s3", region_name=AWS_REGION)
    sqs = boto3.client("sqs", region_name=AWS_REGION)
    print(f"[START] Chunker polling chunk-queue: {CHUNK_QUEUE_URL}")

    while True:
        response = sqs.receive_message(
            QueueUrl=CHUNK_QUEUE_URL,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=10,
        )
        for msg in response.get("Messages", []):
            try:
                process_message(s3, sqs, msg)
            except Exception as e:
                print(f"[ERROR] {e}")
            finally:
                sqs.delete_message(QueueUrl=CHUNK_QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])


if __name__ == "__main__":
    poll()


    while True:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=BUCKET, Prefix=TRIGGER_PREFIX):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".txt"):
                    try:
                        process_trigger(s3, key)
                    except Exception as e:
                        print(f"[ERROR] {key}: {e}")

        print(f"[POLL]  No triggers found, sleeping {POLL_INTERVAL}s ...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    poll()
