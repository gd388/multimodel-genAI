# parser.py
# Uses AWS Textract (async) to parse PDFs directly from S3.
# Handles text, scanned pages, and complex tables — no local PDF libraries needed.
import boto3
import json
import os
import time
from dotenv import load_dotenv
from urllib.parse import unquote_plus

load_dotenv()

AWS_REGION  = os.getenv("AWS_REGION", "us-east-1")
_POLL_DELAY = 5    # seconds between Textract status checks
_MAX_WAIT   = 600  # 10 min timeout for very large PDFs


# ── Textract job helpers ──────────────────────────────────────────────────────

def _start_job(textract, bucket: str, key: str) -> str:
    resp = textract.start_document_analysis(
        DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}},
        FeatureTypes=["TABLES"],   # TABLES enables table + plain text detection
    )
    return resp["JobId"]


def _collect_blocks(textract, job_id: str) -> list:
    """Poll until the job finishes, then page through all result blocks."""
    deadline = time.time() + _MAX_WAIT
    while True:
        resp   = textract.get_document_analysis(JobId=job_id)
        status = resp["JobStatus"]
        pages  = resp.get("DocumentMetadata", {}).get("Pages", "?")
        print(f"[TEXTRACT] status={status} pages={pages}")

        if status == "SUCCEEDED":
            break
        if status == "FAILED":
            raise RuntimeError(f"Textract job failed: {resp.get('StatusMessage')}")
        if time.time() > deadline:
            raise TimeoutError(f"Textract job {job_id} timed out after {_MAX_WAIT}s")
        time.sleep(_POLL_DELAY)

    # Collect all blocks (Textract paginates at ~1000 blocks per call)
    blocks = []
    next_token = None
    while True:
        kwargs = {"JobId": job_id}
        if next_token:
            kwargs["NextToken"] = next_token
        resp       = textract.get_document_analysis(**kwargs)
        blocks    += resp["Blocks"]
        next_token = resp.get("NextToken")
        if not next_token:
            break
    return blocks


# ── Block → Markdown converter ────────────────────────────────────────────────

def _blocks_to_markdown(blocks: list) -> str:
    """
    Convert Textract blocks to readable Markdown.
    - LINE blocks → plain text (in reading order via BoundingBox.Top)
    - TABLE blocks → GitHub-flavoured Markdown tables
    Words that belong to table cells are skipped in the LINE pass to avoid
    printing the same text twice.
    """
    block_map = {b["Id"]: b for b in blocks}

    # Group blocks by page
    pages: dict[int, list] = {}
    for b in blocks:
        pages.setdefault(b.get("Page", 1), []).append(b)

    doc_parts = []

    for page_num in sorted(pages.keys()):
        page_blocks = pages[page_num]

        # ── Build tables and track which word IDs they consumed ──────────────
        table_word_ids: set[str] = set()
        table_by_top:   list[tuple] = []  # (top_pos, markdown_str)

        for block in page_blocks:
            if block["BlockType"] != "TABLE":
                continue

            # Gather all CELLs for this TABLE
            cells: dict[tuple, str] = {}
            max_row = max_col = 0

            for rel in block.get("Relationships", []):
                if rel["Type"] != "CHILD":
                    continue
                for cell_id in rel["Ids"]:
                    cell = block_map.get(cell_id)
                    if not cell or cell["BlockType"] != "CELL":
                        continue
                    row = cell["RowIndex"]
                    col = cell["ColumnIndex"]
                    max_row = max(max_row, row)
                    max_col = max(max_col, col)

                    # Collect words inside cell
                    cell_words = []
                    for inner in cell.get("Relationships", []):
                        if inner["Type"] != "CHILD":
                            continue
                        for wid in inner["Ids"]:
                            w = block_map.get(wid)
                            if w and w["BlockType"] == "WORD":
                                cell_words.append(w.get("Text", ""))
                                table_word_ids.add(wid)
                    cells[(row, col)] = " ".join(cell_words)

            if max_row == 0 or max_col == 0:
                continue

            # Render table as Markdown
            tbl_rows = []
            for r in range(1, max_row + 1):
                row_vals = [cells.get((r, c), "") for c in range(1, max_col + 1)]
                tbl_rows.append("| " + " | ".join(row_vals) + " |")
                if r == 1:  # header separator
                    tbl_rows.append("| " + " | ".join(["---"] * max_col) + " |")

            top = block.get("Geometry", {}).get("BoundingBox", {}).get("Top", 0)
            table_by_top.append((top, "\n".join(tbl_rows)))

        # ── Collect LINE blocks, filter out table words ───────────────────────
        line_by_top: list[tuple] = []
        for block in page_blocks:
            if block["BlockType"] != "LINE":
                continue
            # Check if this line's words were consumed by a table
            word_ids = set()
            for rel in block.get("Relationships", []):
                if rel["Type"] == "CHILD":
                    word_ids.update(rel["Ids"])
            if word_ids & table_word_ids:   # overlap → belongs to a table cell
                continue
            top = block.get("Geometry", {}).get("BoundingBox", {}).get("Top", 0)
            line_by_top.append((top, block.get("Text", "")))

        # ── Merge lines + tables in reading order (by vertical position) ──────
        items = [(top, "line",  txt) for top, txt in line_by_top]
        items += [(top, "table", md)  for top, md  in table_by_top]
        items.sort(key=lambda x: x[0])

        page_parts = [f"<!-- Page {page_num} -->"]
        for _, kind, content in items:
            page_parts.append(content)

        doc_parts.append("\n".join(page_parts))

    return "\n\n".join(doc_parts)


# ── Main entry point ──────────────────────────────────────────────────────────

def process_document(bucket, key):
    key = unquote_plus(key)
    s3        = boto3.client("s3",        region_name=AWS_REGION)
    textract  = boto3.client("textract",  region_name=AWS_REGION)
    try:
        # Textract reads directly from S3 — no local download needed
        print(f"[TEXTRACT] Starting analysis: s3://{bucket}/{key}")
        job_id = _start_job(textract, bucket, key)
        print(f"[TEXTRACT] Job ID: {job_id}")

        blocks   = _collect_blocks(textract, job_id)
        markdown = _blocks_to_markdown(blocks)

        print(f"[RESULT] --- Parsed content of '{key}' ---")
        print(markdown[:2000])
        print(f"[RESULT] --- End (total chars: {len(markdown)}) ---")

        parsed_data = {"markdown": markdown}

        # Save to dev/parsed/ staging (embedder deletes this after Qdrant upsert)
        parsed_key = key.replace("dev/raw/", "dev/parsed/") + ".json"
        s3.put_object(
            Bucket=bucket,
            Key=parsed_key,
            Body=json.dumps(parsed_data, ensure_ascii=False),
        )
        print(f"[SAVED] s3://{bucket}/{parsed_key}")
        return parsed_key

    except Exception as e:
        print(f"[ERROR] {e}")
        failed_key = key.replace("dev/raw/", "dev/failed/")
        s3.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": key},
            Key=failed_key,
        )
        return None
