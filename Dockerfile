FROM python:3.11-slim AS builder
WORKDIR /build
COPY pyproject.toml .
COPY app/ app/
RUN pip install --no-cache-dir -e .

FROM python:3.11-slim
WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY app/ app/
COPY config.yaml config.yaml

# Default: CLI scan using config.yaml
# Mount your own config.yaml: docker run --rm -v $(pwd)/config.yaml:/app/config.yaml project-orion
CMD ["python", "-m", "app", "scan"]

# To run the API instead:
#   docker run --rm -p 8000:8000 -v $(pwd)/config.yaml:/app/config.yaml \
#     project-orion uvicorn app.main:app --host 0.0.0.0 --port 8000
