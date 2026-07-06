# CourseLens — containerized deploy (beyond Streamlit Cloud).
#
#   docker build -t courselens .
#   docker run -p 8501:8501 -e GROQ_API_KEY=gsk_your_key courselens
#
# Persist the library across restarts by mounting volumes:
#   docker run -p 8501:8501 -e GROQ_API_KEY=gsk_your_key \
#     -v courselens-vectors:/app/chroma_store \
#     -v courselens-media:/app/media_store courselens
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
COPY frontend/ frontend/
COPY .streamlit/config.toml .streamlit/config.toml

# yt-dlp is blocked from datacenter IPs — hide YouTube ingestion in containers
# by default (override with -e ENABLE_YOUTUBE=1 when running from a home IP).
ENV ENABLE_YOUTUBE=0

VOLUME ["/app/chroma_store", "/app/media_store"]

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "frontend/app.py", "--server.address=0.0.0.0", "--server.port=8501"]
