PYTHON = .venv/bin/python
PIP = .venv/bin/pip
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

# ── Docker ────────────────────────────────────────────────────────────────────
up:
	docker compose up --build

up-detach:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

restart:
	docker compose restart

prune:
	docker system prune -a

# ── Local dev (no Docker) ─────────────────────────────────────────────────────
api:
	$(PYTHON) -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

worker:
	$(PYTHON) worker/sqs.py

chunker:
	$(PYTHON) worker/chunker.py

embedder:
	$(PYTHON) worker/embedder.py

# ── Setup ─────────────────────────────────────────────────────────────────────
install:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

# ── Helpers ───────────────────────────────────────────────────────────────────
check-queue:
	$(PYTHON) -c "\
import boto3, os; \
from dotenv import load_dotenv; \
load_dotenv(); \
sqs = boto3.client('sqs', region_name=os.getenv('AWS_REGION')); \
attrs = sqs.get_queue_attributes(QueueUrl=os.getenv('SQS_URL'), AttributeNames=['ApproximateNumberOfMessages','ApproximateNumberOfMessagesNotVisible']); \
print(attrs['Attributes'])"

backfill-metadata:
	$(PYTHON) worker/backfill_metadata.py

backfill-chunks:
	$(PYTHON) worker/backfill_chunks.py

backfill-embeddings:
	$(PYTHON) worker/backfill_embeddings.py



.PHONY: up up-detach down logs restart api worker chunker embedder install check-queue backfill-metadata backfill-chunks backfill-embeddings
