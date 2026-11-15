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
# Hosts that assign the port themselves (Render, Railway, Fly, HF Spaces) set
# $PORT; the server listens on it, falling back to 8000.
FROM python:3.12-slim

WORKDIR /app

# Dependencies first — cached as their own layer, so source edits don't
# re-install PyTorch.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image so the first boot doesn't spend
# minutes downloading it.
RUN python -c "from langchain_huggingface import HuggingFaceEmbeddings; \
    HuggingFaceEmbeddings(model_name='all-MiniLM-L6-v2')"

COPY backend/ backend/
COPY api/ api/
COPY web/ web/
# The demo library (indexed lectures + slides, their audio/figures, and the
# cached concept list) so a new deploy opens with something to ask about.
COPY chroma_store/ chroma_store/
COPY media_store/ media_store/

# yt-dlp is blocked from datacenter IPs — hide YouTube ingestion in containers
# by default (override with -e ENABLE_YOUTUBE=1 when running from a home IP).
ENV ENABLE_YOUTUBE=0 PORT=8000

VOLUME ["/app/chroma_store", "/app/media_store"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/api/health')" || exit 1

CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
