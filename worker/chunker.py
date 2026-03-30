# worker/chunker.py
# Polls S3 for trigger files written by parser.py after parsing is complete.
# For each trigger, reads the parsed markdown and applies three chunking strategies:
#   1. Section-aware  — splits on headings
#   2. Type-aware     — separates text / tables / images into typed chunks
#   3. Sliding window — overlapping windows on long text blocks

import boto3
import json
import os
import re
import time
from dotenv import load_dotenv

load_dotenv()

BUCKET       = "genai-rag-bucket-gd"
TRIGGER_PREFIX = "dev/triggers/"
CHUNKS_PREFIX  = "dev/chunks/"
AWS_REGION   = os.getenv("AWS_REGION", "us-east-1")
POLL_INTERVAL = 10       # seconds between scans
CHUNK_SIZE    = 500      # words per sliding-window chunk
CHUNK_OVERLAP = 50       # words of overlap between windows


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


# ── S3 polling loop ───────────────────────────────────────────────────────────

def process_trigger(s3, trigger_key: str):
    print(f"[TRIGGER] Found: s3://{BUCKET}/{trigger_key}")

    # Trigger file content = the parsed S3 key
    obj = s3.get_object(Bucket=BUCKET, Key=trigger_key)
    parsed_key = obj["Body"].read().decode("utf-8").strip()

    print(f"[READ]    s3://{BUCKET}/{parsed_key}")
    parsed_obj = s3.get_object(Bucket=BUCKET, Key=parsed_key)
    data = json.loads(parsed_obj["Body"].read())
    markdown = data.get("markdown", "")

    print(f"[CHUNK]   Chunking {parsed_key} ...")
    chunks = chunk_markdown(markdown)
    print(f"[CHUNK]   Produced {len(chunks)} chunks "
          f"({sum(1 for c in chunks if c['type']=='text')} text, "
          f"{sum(1 for c in chunks if c['type']=='table')} table, "
          f"{sum(1 for c in chunks if c['type']=='image')} image)")

    chunks_key = parsed_key.replace("dev/parsed/", CHUNKS_PREFIX)
    s3.put_object(
        Bucket=BUCKET,
        Key=chunks_key,
        Body=json.dumps({"chunks": chunks}, ensure_ascii=False),
    )
    print(f"[SAVED]   s3://{BUCKET}/{chunks_key}")

    # Write trigger for embedder
    embed_trigger_key = "dev/triggers/embed/" + trigger_key.removeprefix(TRIGGER_PREFIX)
    s3.put_object(Bucket=BUCKET, Key=embed_trigger_key, Body=chunks_key)
    print(f"[TRIGGER] Embed trigger: s3://{BUCKET}/{embed_trigger_key}")

    # Delete trigger so it's not processed again
    s3.delete_object(Bucket=BUCKET, Key=trigger_key)
    print(f"[DONE]    Trigger deleted: {trigger_key}\n")


def poll():
    s3 = boto3.client("s3", region_name=AWS_REGION)
    print(f"[START] Chunker polling s3://{BUCKET}/{TRIGGER_PREFIX} every {POLL_INTERVAL}s")

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
