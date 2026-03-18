FROM python:3.11-slim

LABEL maintainer="Lee Fuhr"
LABEL description="Memeta — intelligent memory system for Claude Code"

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Copy dependency spec first for layer caching
COPY pyproject.toml README.md ./

# Install base + test dependencies
RUN pip install --no-cache-dir -e ".[test]"

# Copy source
COPY src/ src/
COPY tests/ tests/
COPY scripts/ scripts/
COPY dashboard/ dashboard/
COPY hooks/ hooks/
COPY examples/ examples/

# Default data directory
ENV MEMORY_SYSTEM_BASE_DIR=/data/memory
RUN mkdir -p /data/memory

EXPOSE 8766

ENTRYPOINT ["memeta"]
CMD ["--help"]
