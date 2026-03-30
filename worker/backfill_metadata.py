"""
backfill_metadata.py
Reads all existing parsed JSONs from S3 (dev/parsed/),
extracts metadata from stored markdown, saves it to dev/metadata/,
and removes 'metadata' from parsed files if it was previously added.
"""
import boto3
import json
import os
from dotenv import load_dotenv
from parser import extract_metadata

load_dotenv()

BUCKET = "genai-rag-bucket-gd"
PARSED_PREFIX = "dev/parsed/"
METADATA_PREFIX = "dev/metadata/"
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def run():
    s3 = boto3.client("s3", region_name=AWS_REGION)

    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=BUCKET, Prefix=PARSED_PREFIX)

    updated = 0
    skipped = 0

    for page in pages:
        for obj in page.get("Contents", []):
            parsed_key = obj["Key"]
            if not parsed_key.endswith(".json"):
                continue

            print(f"[READ] s3://{BUCKET}/{parsed_key}")
            response = s3.get_object(Bucket=BUCKET, Key=parsed_key)
            data = json.loads(response["Body"].read())

            markdown = data.get("markdown", "")
            source_key = data.get("key", parsed_key.replace(PARSED_PREFIX, "dev/raw/").removesuffix(".json"))

            # Build metadata key: dev/parsed/foo.pdf.json -> dev/metadata/foo.pdf.json
            metadata_key = parsed_key.replace(PARSED_PREFIX, METADATA_PREFIX)

            # Check if metadata already saved separately
            try:
                s3.head_object(Bucket=BUCKET, Key=metadata_key)
                print(f"[SKIP] Metadata already exists: {metadata_key}")
                skipped += 1
            except s3.exceptions.ClientError:
                metadata = extract_metadata(markdown, source_key)
                print(f"[META] {json.dumps(metadata, indent=2)}")

                # Write metadata to dev/metadata/
                s3.put_object(
                    Bucket=BUCKET,
                    Key=metadata_key,
                    Body=json.dumps(metadata, ensure_ascii=False)
                )
                print(f"[SAVED META] s3://{BUCKET}/{metadata_key}")
                updated += 1

            # Strip 'metadata' from parsed file if it was previously embedded
            if "metadata" in data or "key" in data:
                data.pop("metadata", None)
                data.pop("key", None)
                s3.put_object(
                    Bucket=BUCKET,
                    Key=parsed_key,
                    Body=json.dumps(data, ensure_ascii=False)
                )
                print(f"[CLEANED] Removed embedded metadata from s3://{BUCKET}/{parsed_key}")

    print(f"\nDone. Metadata written: {updated}, Already existed: {skipped}")


if __name__ == "__main__":
    run()
