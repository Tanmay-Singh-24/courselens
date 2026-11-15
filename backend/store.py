"""CourseLens — vector store.

One shared Chroma collection holds chunks from every modality (audio, youtube,
and — from V2 — pdf text/figures). Each chunk carries metadata that powers
citations and actionable deep links; retrieval is naturally cross-modal.
"""
import os

from fastembed import TextEmbedding
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from backend.config import CHROMA_DIR, COLLECTION_NAME, EMBED_MODEL_NAME, TOP_K


class FastEmbedEmbeddings(Embeddings):
    """all-MiniLM-L6-v2 via fastembed (ONNX Runtime) instead of PyTorch.

    Same model, same vectors: measured cosine similarity 1.0 against the
    sentence-transformers output, including for chunks already in the store, so
    no re-indexing was needed. Dropping PyTorch took peak memory from ~540 MB to
    a size that fits a 512 MB free host, and shrank the Docker image by ~2 GB."""

    def __init__(self, model_name):
        # fastembed's default cache is the OS temp dir, which macOS clears on
        # reboot (a 90 MB re-download). Keep it with the other model caches.
        cache = os.environ.get("FASTEMBED_CACHE_PATH") or os.path.expanduser("~/.cache/fastembed")
        self.model = TextEmbedding(model_name, cache_dir=cache)

    def embed_documents(self, texts):
        return [v.tolist() for v in self.model.embed(list(texts))]

    def embed_query(self, text):
        return self.embed_documents([text])[0]


# Shared embedder — the same instance embeds stored chunks and the query, so both
# live in one vector space.
embeddings = FastEmbedEmbeddings(EMBED_MODEL_NAME)

# Persistent collection; created empty if missing (the library starts empty and
# fills as the user ingests material).
vectorstore = Chroma(
    collection_name=COLLECTION_NAME,
    persist_directory=CHROMA_DIR,
    embedding_function=embeddings,
)


def _clean_metadata(meta):
    """Chroma rejects None metadata values — drop those keys entirely."""
    return {k: v for k, v in meta.items() if v is not None}


# Embedding is the memory peak of ingestion. A long PDF can produce hundreds of
# chunks, and embedding them in one call spikes RAM well past what a small hosted
# instance (Streamlit Cloud ≈ 1 GB, already holding PyTorch) can absorb. Batching
# keeps the peak flat and costs nothing in speed.
EMBED_BATCH = 64


def add_chunks(chunks):
    """Add chunk dicts to the collection, embedding in batches.

    Each chunk is {"text": str, "metadata": dict}. Returns the number added.
    """
    docs = [
        Document(page_content=c["text"], metadata=_clean_metadata(c["metadata"]))
        for c in chunks
        if c["text"].strip()
    ]
    for i in range(0, len(docs), EMBED_BATCH):
        vectorstore.add_documents(docs[i:i + EMBED_BATCH])
    return len(docs)


def similarity_search(query, k=TOP_K):
    """Return the top-k chunks most similar to the query."""
    return vectorstore.similarity_search(query, k=k)


def has_documents():
    """True if the collection holds at least one chunk."""
    return vectorstore._collection.count() > 0


def doc_hash_exists(h):
    """True if a chunk tagged with this content hash is already in the collection —
    used to make ingestion idempotent (re-adding the same file is a no-op)."""
    try:
        got = vectorstore.get(where={"doc_hash": h}, limit=1)
        return len(got.get("ids", [])) > 0
    except Exception:
        return False


def list_sources():
    """Distinct source names in the collection (for the 'not in your library'
    message, so the user sees what IS covered)."""
    try:
        data = vectorstore.get(include=["metadatas"])
        names = {m.get("source_name") for m in data.get("metadatas", []) if m}
        return sorted(n for n in names if n)
    except Exception:
        return []
