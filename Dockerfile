FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN useradd -m -u 1000 botuser && \
    mkdir -p /app/logs /app/downloads && \
    chown -R botuser:botuser /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=botuser:botuser . .

USER botuser

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
    CMD pgrep -f "python.*bot.py" || exit 1

CMD ["python", "bot.py"]

