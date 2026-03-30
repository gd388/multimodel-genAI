# parser.py
import boto3
import json
import os
from dotenv import load_dotenv
from urllib.parse import unquote_plus
from docling.document_converter import DocumentConverter

load_dotenv()

converter = DocumentConverter()


def extract_metadata(markdown: str, key: str) -> dict:
    import re
    lines = markdown.splitlines()

    # Title: first non-empty heading or first non-empty line
    title = ""
    for line in lines:
        line = line.strip()
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            break
        elif line:
            title = line
            break

    # Sections: all H2 headings
    sections = [l.lstrip("#").strip() for l in lines if l.startswith("## ")]

    # Dates: patterns like Jan 2023, 2023-03-30, March 30 2026
    date_pattern = re.compile(
        r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)'
        r'\s+\d{1,2},?\s+\d{4}'
        r'|\b\d{4}-\d{2}-\d{2}\b'
        r'|\bQ[1-4]\s+\d{4}\b',
        re.IGNORECASE
    )
    dates = list(dict.fromkeys(date_pattern.findall(markdown)))[:10]  # deduplicated, max 10

    return {
        "source_key": key,
        "title": title,
        "sections": sections,
        "dates_mentioned": dates,
        "word_count": len(markdown.split()),
        "char_count": len(markdown),
    }


def process_document(bucket, key):
    key = unquote_plus(key)  # decode URL-encoded spaces/chars from S3 event
    s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))
    try:
        local_path = "/tmp/input.pdf"

        # Download file from S3
        print(f"[DOWNLOAD] s3://{bucket}/{key} -> {local_path}")
        s3.download_file(bucket, key, local_path)

        # Parse with Docling
        print(f"[PARSE] Running Docling on {key}")
        result = converter.convert(local_path)
        markdown = result.document.export_to_markdown()

        print(f"[RESULT] --- Parsed content of '{key}' ---")
        print(markdown[:2000])  # print first 2000 chars to terminal
        print(f"[RESULT] --- End (total chars: {len(markdown)}) ---")

        metadata = extract_metadata(markdown, key)
        print(f"[META] {json.dumps(metadata, indent=2)}")

        parsed_data = {
            "markdown": markdown
        }

        # Save markdown to dev/parsed/
        parsed_key = key.replace("dev/raw/", "dev/parsed/") + ".json"
        s3.put_object(
            Bucket=bucket,
            Key=parsed_key,
            Body=json.dumps(parsed_data, ensure_ascii=False)
        )
        print(f"[SAVED] s3://{bucket}/{parsed_key}")

        # Save metadata separately to dev/metadata/
        metadata_key = key.replace("dev/raw/", "dev/metadata/") + ".json"
        s3.put_object(
            Bucket=bucket,
            Key=metadata_key,
            Body=json.dumps(metadata, ensure_ascii=False)
        )
        print(f"[SAVED] s3://{bucket}/{metadata_key}")

        # Write trigger file to signal chunker that parsing is complete
        trigger_key = key.replace("dev/raw/", "dev/triggers/") + ".txt"
        s3.put_object(
            Bucket=bucket,
            Key=trigger_key,
            Body=parsed_key  # tells chunker which parsed file to process
        )
        print(f"[TRIGGER] s3://{bucket}/{trigger_key}")

    except Exception as e:
        print("Error:", str(e))

        failed_key = key.replace("dev/raw/", "dev/failed/")

        s3.copy_object(
            Bucket=bucket,
            CopySource={'Bucket': bucket, 'Key': key},
            Key=failed_key
        )