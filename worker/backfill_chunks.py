"""
backfill_chunks.py
Reads all existing parsed JSONs from S3 (dev/parsed/),
chunks them using the same strategies as chunker.py,
and saves results to dev/chunks/.
Skips files that already have chunks.
"""
import boto3
import json
import os
import sys
from dotenv import load_dotenv

# chunker.py is in the same folder
sys.path.insert(0, os.path.dirname(__file__))
from chunker import chunk_markdown, CHUNKS_PREFIX

load_dotenv()

BUCKET        = "genai-rag-bucket-gd"
PARSED_PREFIX = "dev/parsed/"
AWS_REGION    = os.getenv("AWS_REGION", "us-east-1")


def run():
    s3 = boto3.client("s3", region_name=AWS_REGION)
    paginator = s3.get_paginator("list_objects_v2")

    chunked = 0
    skipped = 0

    for page in paginator.paginate(Bucket=BUCKET, Prefix=PARSED_PREFIX):
        for obj in page.get("Contents", []):
            parsed_key = obj["Key"]
            if not parsed_key.endswith(".json"):
                continue

            chunks_key = parsed_key.replace(PARSED_PREFIX, CHUNKS_PREFIX)

            # Skip if chunks already exist
            try:
                s3.head_object(Bucket=BUCKET, Key=chunks_key)
                print(f"[SKIP] Already chunked: {chunks_key}")
                skipped += 1
                continue
            except Exception:
                pass

            print(f"[READ] s3://{BUCKET}/{parsed_key}")
            response = s3.get_object(Bucket=BUCKET, Key=parsed_key)
            data = json.loads(response["Body"].read())
            markdown = data.get("markdown", "")

            if not markdown:
                print(f"[SKIP] No markdown in {parsed_key}")
                skipped += 1
                continue

            print(f"[CHUNK] Chunking {parsed_key} ...")
            chunks = chunk_markdown(markdown)

            text_count  = sum(1 for c in chunks if c["type"] == "text")
            table_count = sum(1 for c in chunks if c["type"] == "table")
            image_count = sum(1 for c in chunks if c["type"] == "image")
            print(f"[CHUNK] {len(chunks)} chunks — "
                  f"{text_count} text, {table_count} table, {image_count} image")

            s3.put_object(
                Bucket=BUCKET,
                Key=chunks_key,
                Body=json.dumps({"chunks": chunks}, ensure_ascii=False)
            )
            print(f"[SAVED] s3://{BUCKET}/{chunks_key}\n")
            chunked += 1

    print(f"Done. Chunked: {chunked}, Skipped: {skipped}")


if __name__ == "__main__":
    run()
