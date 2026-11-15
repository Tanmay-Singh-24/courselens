# CourseLens — containerized deploy (FastAPI + the static web frontend).
#
#   docker build -t courselens .
#   docker run -p 8000:8000 -e GROQ_API_KEY=gsk_your_key courselens
#
# Persist the library across restarts by mounting volumes (a fresh named volume
# starts out with the demo library baked into the image):
#   docker run -p 8000:8000 -e GROQ_API_KEY=gsk_your_key \
#     -v courselens-vectors:/app/chroma_store \
#     -v courselens-media:/app/media_store courselens
#
# Hosts that assign the port themselves (Render, Railway, Fly, Cloud Run) set
# $PORT; the server listens on it, falling back to 8000.
FROM python:3.12-slim

# Run as a normal user (uid 1000): most hosts expect it, and it's the
# safer default anywhere. The model cache lives inside /app so that user owns it.
RUN useradd -m -u 1000 user
ENV FASTEMBED_CACHE_PATH=/app/.cache/fastembed
WORKDIR /app

# Dependencies first — cached as their own layer, so source edits don't
# re-install everything.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image so the first boot doesn't spend
# minutes downloading it.
RUN python -c "from fastembed import TextEmbedding; \
    TextEmbedding('sentence-transformers/all-MiniLM-L6-v2')"

COPY backend/ backend/
COPY api/ api/
COPY web/ web/
# The demo library (indexed lectures + slides, their audio/figures, and the
# cached concept list) so a new deploy opens with something to ask about.
COPY chroma_store/ chroma_store/
COPY media_store/ media_store/
RUN chown -R user:user /app
USER user

# yt-dlp is blocked from datacenter IPs — hide YouTube ingestion in containers
# by default (override with -e ENABLE_YOUTUBE=1 when running from a home IP).
ENV ENABLE_YOUTUBE=0 PORT=8000

VOLUME ["/app/chroma_store", "/app/media_store"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/api/health')" || exit 1

CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
