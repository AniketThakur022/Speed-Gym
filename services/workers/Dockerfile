# Celery worker + beat. The worker is repo-scoped by design (it imports the
# RAG factory lanes as top-level `factory.*` and the API's pure modules as
# `app.*`), so the image carries BOTH requirement sets and the code arrives
# via the repo volume mounted at /workspace (see docker-compose.prod.yml).
FROM python:3.12-slim

WORKDIR /workspace
COPY services/api/requirements.txt /tmp/api-requirements.txt
COPY services/workers/requirements.txt /tmp/worker-requirements.txt
RUN pip install --no-cache-dir -r /tmp/api-requirements.txt -r /tmp/worker-requirements.txt

ENV PYTHONPATH=/workspace/services/workers:/workspace/services/api:/workspace
WORKDIR /workspace/services/workers
CMD ["celery", "-A", "worker.app", "worker", "--beat", "--loglevel=info"]
