# main.py
import boto3
import json
from parser import process_document
from dotenv import load_dotenv
import os
load_dotenv()

QUEUE_URL = os.getenv("SQS_URL")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

def poll_queue():
    sqs = boto3.client("sqs", region_name=AWS_REGION)
    print(f"[START] Polling queue: {QUEUE_URL}")

    while True:
        print("[POLL] Waiting for messages...")
        response = sqs.receive_message(
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=10  # long polling
        )

        messages = response.get("Messages", [])

        for msg in messages:
            body = json.loads(msg["Body"])

            # S3 event is inside "Message" sometimes (SNS-wrapped)
            if "Message" in body:
                body = json.loads(body["Message"])

            # Ignore S3 test events
            if body.get("Event") == "s3:TestEvent":
                print("[SKIP] S3 test event, ignoring.")
                sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
                continue

            process_event(body)

            sqs.delete_message(
                QueueUrl=QUEUE_URL,
                ReceiptHandle=msg["ReceiptHandle"]
            )


def process_event(event):
    if "Records" not in event:
        print(f"[SKIP] No 'Records' in event. Payload: {json.dumps(event, indent=2)}")
        return

    for record in event["Records"]:
        if "s3" not in record:
            print(f"[SKIP] Not an S3 record: {record.get('eventSource')}")
            continue

        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]

        print(f"Processing: s3://{bucket}/{key}")
        process_document(bucket, key)


if __name__ == "__main__":
    poll_queue()