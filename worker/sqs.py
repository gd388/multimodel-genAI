# main.py
import boto3
import json
from parser import process_document
from dotenv import load_dotenv
import os
load_dotenv()

sqs = boto3.client("sqs")

QUEUE_URL = os.getenv("SQS_URL")

def poll_queue():
    while True:
        response = sqs.receive_message(
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=10  # long polling
        )

        messages = response.get("Messages", [])

        for msg in messages:
            body = json.loads(msg["Body"])

            # S3 event is inside "Message" sometimes
            if "Message" in body:
                body = json.loads(body["Message"])

            process_event(body)

            sqs.delete_message(
                QueueUrl=QUEUE_URL,
                ReceiptHandle=msg["ReceiptHandle"]
            )


def process_event(event):
    record = event["Records"][0]

    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"]

    print(f"Processing: {key}")

    process_document(bucket, key)


if __name__ == "__main__":
    poll_queue()