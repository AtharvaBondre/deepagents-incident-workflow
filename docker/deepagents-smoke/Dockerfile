FROM python:3.12-alpine@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df

ARG LOCK_FILE=requirements/deepagents-py312-universal.lock
COPY ${LOCK_FILE} /tmp/deepagents-runtime.lock
RUN PIP_CONFIG_FILE=/dev/null python -m pip --isolated install \
      --disable-pip-version-check \
      --index-url https://pypi.org/simple \
      --no-cache-dir \
      --only-binary=:all: \
      --require-hashes \
      --requirement /tmp/deepagents-runtime.lock \
    && python -m pip --isolated check \
    && rm /tmp/deepagents-runtime.lock

COPY scripts/deepagents_sdk_smoke.py /workspace/scripts/deepagents_sdk_smoke.py
COPY scripts/deepagents_worker.py /workspace/scripts/deepagents_worker.py

ENV HOME=/home/worker \
    LANGCHAIN_TRACING_V2=false \
    LANGSMITH_TRACING=false \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /workspace
ENTRYPOINT ["python"]
