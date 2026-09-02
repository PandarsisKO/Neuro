FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY neurosearch ./neurosearch
RUN pip install --no-cache-dir . && pip install --no-cache-dir -U yt-dlp

ENV NEUROSEARCH_DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 8000

CMD ["neurosearch", "serve", "--host", "0.0.0.0", "--port", "8000"]
