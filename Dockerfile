# ---- Builder ----
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ---- Runtime ----
FROM python:3.11-slim

WORKDIR /app

# Copy installed dependencies from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY notifier/ ./notifier/
COPY task_notifier.py .

# Create log directory
RUN mkdir -p logs

ENTRYPOINT ["python", "task_notifier.py"]
CMD ["--help"]
