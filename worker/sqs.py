# worker/sqs.py
# Stage 1: Polls the S3-event parse queue, calls parser, then sends the
# parsed S3 key to the chunk queue for Stage 2.

import boto3
import json
import os
from parser import process_document
from dotenv import load_dotenv

load_dotenv()

PARSE_QUEUE_URL = os.getenv("SQS_URL")
CHUNK_QUEUE_URL = os.getenv("SQS_CHUNK_URL")
AWS_REGION      = os.getenv("AWS_REGION", "us-east-1")


def poll_queue():
    sqs = boto3.client("sqs", region_name=AWS_REGION)
    print(f"[START] Parser polling: {PARSE_QUEUE_URL}")

    while True:
        print("[POLL] Waiting for messages...")
        response = sqs.receive_message(
            QueueUrl=PARSE_QUEUE_URL,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=10,
        )

        for msg in response.get("Messages", []):
            body = json.loads(msg["Body"])

            if "Message" in body:
                body = json.loads(body["Message"])

            if body.get("Event") == "s3:TestEvent":
                print("[SKIP] S3 test event.")
                sqs.delete_message(QueueUrl=PARSE_QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
                continue

            process_event(sqs, body)
            sqs.delete_message(QueueUrl=PARSE_QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])


def process_event(sqs, event):
    if "Records" not in event:
        print(f"[SKIP] No 'Records' in event.")
        return

    for record in event["Records"]:
        if "s3" not in record:
            continue

        bucket = record["s3"]["bucket"]["name"]
        key    = record["s3"]["object"]["key"]

        print(f"[PARSE] s3://{bucket}/{key}")
        parsed_key = process_document(bucket, key)

        if parsed_key and CHUNK_QUEUE_URL:
            sqs.send_message(
                QueueUrl=CHUNK_QUEUE_URL,
                MessageBody=json.dumps({"parsed_key": parsed_key, "bucket": bucket}),
            )
            print(f"[QUEUE] Sent to chunk-queue: {parsed_key}")


if __name__ == "__main__":
    poll_queue()
