FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency installation
RUN pip install uv --no-cache-dir

# Copy dependency manifests first (layer cache)
COPY pyproject.toml uv.lock* ./

# Install runtime dependencies (no dev extras)
RUN uv sync --frozen --no-dev

# Copy the rest of the backend source
COPY backend/ ./

# Expose the FastAPI port
EXPOSE 8000

# Run uvicorn via uv's managed environment
CMD ["uv", "run", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
