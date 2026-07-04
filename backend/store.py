"""CourseLens — vector store.

One shared Chroma collection holds chunks from every modality (audio, youtube,
and — from V2 — pdf text/figures). Each chunk carries metadata that powers
citations and actionable deep links; retrieval is naturally cross-modal.
"""
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

from backend.config import CHROMA_DIR, COLLECTION_NAME, EMBED_MODEL_NAME, TOP_K

# Shared embedder — the same instance embeds stored chunks and the query, so both
# live in one vector space.
embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL_NAME)

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


def add_chunks(chunks):
    """Add chunk dicts to the collection.

    Each chunk is {"text": str, "metadata": dict}. Returns the number added.
    """
    docs = [
        Document(page_content=c["text"], metadata=_clean_metadata(c["metadata"]))
        for c in chunks
        if c["text"].strip()
    ]
    if docs:
        vectorstore.add_documents(docs)
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
