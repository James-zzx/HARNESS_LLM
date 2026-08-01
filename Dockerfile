# syntax=docker/dockerfile:1

# Stage 1: build a wheel from source
FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps --wheel-dir /wheels .

# Stage 2: minimal runtime image
FROM python:3.11-slim AS runtime

RUN groupadd --system appuser && useradd --system --gid appuser appuser
WORKDIR /app

COPY --from=builder /wheels/harness_llm-*.whl /tmp/harness.whl
RUN pip install --no-cache-dir /tmp/harness.whl \
    && rm /tmp/harness.whl \
    && chown -R appuser:appuser /app

USER appuser

HEALTHCHECK CMD python -c "import harness"

ENTRYPOINT ["python", "-m", "harness"]
CMD ["--help"]
