"""
backfill_embeddings.py
Reads all existing chunk JSONs from S3 (dev/chunks/),
generates BGE embeddings, stores in ChromaDB and S3 (dev/embeddings/).
Skips files already embedded.
"""
import boto3
import json
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from embedder import process_trigger, BUCKET, CHUNKS_PREFIX, EMBEDDINGS_PREFIX, AWS_REGION


def run():
    s3 = boto3.client("s3", region_name=AWS_REGION)
    paginator = s3.get_paginator("list_objects_v2")

    embedded = 0
    skipped  = 0

    for page in paginator.paginate(Bucket=BUCKET, Prefix=CHUNKS_PREFIX):
        for obj in page.get("Contents", []):
            chunks_key = obj["Key"]
            if not chunks_key.endswith(".json"):
                continue

            embeddings_key = chunks_key.replace(CHUNKS_PREFIX, EMBEDDINGS_PREFIX)

            # Skip if already embedded
            try:
                s3.head_object(Bucket=BUCKET, Key=embeddings_key)
                print(f"[SKIP] Already embedded: {embeddings_key}")
                skipped += 1
                continue
            except Exception:
                pass

            # Synthesize a fake trigger: put the chunks_key as the trigger body
            fake_trigger_key = "dev/triggers/embed/backfill_" + chunks_key.removeprefix(CHUNKS_PREFIX)
            s3.put_object(Bucket=BUCKET, Key=fake_trigger_key, Body=chunks_key)

            try:
                process_trigger(s3, fake_trigger_key)
                embedded += 1
            except Exception as e:
                print(f"[ERROR] {chunks_key}: {e}")
                # Clean up fake trigger on error
                try:
                    s3.delete_object(Bucket=BUCKET, Key=fake_trigger_key)
                except Exception:
                    pass

    print(f"\nDone. Embedded: {embedded}, Skipped: {skipped}")


if __name__ == "__main__":
    load_dotenv()
    run()
