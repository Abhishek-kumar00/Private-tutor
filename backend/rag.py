# rag.py
"""
LangChain-based RAG with persistent ChromaDB.

Architecture:
  NCERTStore  — reads pre-ingested NCERT textbooks (./chroma_db/ncert/)
  UserStore   — manages runtime PDF uploads   (./chroma_db/user/)
  combine_context() — merges both stores for generation queries
"""

import os
import re
from pathlib import Path
import logging
import torch
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Paths ────────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).parent
NCERT_DB_PATH = str(_BACKEND_DIR / "chroma_db" / "ncert")
USER_DB_PATH  = str(_BACKEND_DIR / "chroma_db" / "user")

# ─── Equation-safe regex (preserved from previous version) ───────────────────
EQUATION_PATTERN = re.compile(
    r"[=∫∂∑∏√±×÷²³⁰¹⁽⁾∞≈≠≤≥α-ωΑ-Ω]"
    r"|[A-Za-z]\s*=\s*[-\d(]"
    r"|\d+\s*[+\-*/]\s*\d+"
    r"|(?:sin|cos|tan|log|ln|exp|lim)\s*[\(\[]"
    r"|\d+\s*(?:m/s|kg|N·|J\b|Pa|mol|Hz|rad)"
)


def _protect_equations(text: str) -> str:
    """Surround equation lines with blank lines so the splitter won't cut them."""
    lines = text.split("\n")
    protected = []
    for line in lines:
        stripped = line.strip()
        if stripped and EQUATION_PATTERN.search(stripped):
            protected.append(f"\n{stripped}\n")
        else:
            protected.append(line)
    return "\n".join(protected)


# ─── Singleton embedding model ────────────────────────────────────────────────
# Lazy-loaded to keep server startup fast; shared by both stores.

_EMBEDDINGS = None


def get_embeddings():
    """Return (and cache) the HuggingFace embedding model."""
    global _EMBEDDINGS
    if _EMBEDDINGS is None:
        # Import here so startup is fast even if langchain_huggingface is slow to load
        from langchain_huggingface import HuggingFaceEmbeddings
        import torch

        # Monkeypatch to fix DirectML crash with transformers (RuntimeError: Cannot set version_counter for inference tensor)
        if hasattr(torch, "inference_mode"):
            torch.inference_mode = torch.no_grad

        # Auto-detect best device for inference
        device = "cpu"
        if torch.cuda.is_available():
            device = "cuda"
        # Note: torch-directml is intentionally excluded here because it currently has a critical bug 
        # (Cannot set version_counter for inference tensor) when running BERT models on Windows Intel GPUs.

        logger.info(f"Loading embedding model BAAI/bge-base-en-v1.5 on {device} …")
        _EMBEDDINGS = HuggingFaceEmbeddings(
            model_name="BAAI/bge-base-en-v1.5",
            model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": True},
        )
        logger.info("Embedding model ready.")
    return _EMBEDDINGS


# ─── NCERT Store (persistent, read-only at runtime) ──────────────────────────

class NCERTStore:
    """
    Wraps the persistent ChromaDB collection that was built by ingest.py.
    Read-only during server runtime — only ingest.py writes to it.
    """

    COLLECTION = "ncert_pcm"

    def __init__(self):
        self._store = None
        self._count = 0
        self._open()

    def _open(self):
        from langchain_chroma import Chroma
        ncert_path = Path(NCERT_DB_PATH)
        if not ncert_path.exists():
            logger.warning(
                "[NCERT] No persistent store found at %s. "
                "Run `python ingest.py` after placing PDFs in ./textbooks/",
                NCERT_DB_PATH,
            )
            return
        try:
            self._store = Chroma(
                collection_name=self.COLLECTION,
                embedding_function=get_embeddings(),
                persist_directory=NCERT_DB_PATH,
            )
            self._count = self._store._collection.count()
            logger.info("[NCERT] Opened store — %d chunks available", self._count)
        except Exception as exc:
            logger.error("[NCERT] Failed to open store: %s", exc)
            self._store = None

    # ── Public API ────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return self._store is not None and self._count > 0

    def chunk_count(self) -> int:
        return self._count

    def retrieve(self, query: str, k: int = 4) -> list:
        if not self.is_available():
            return []
        try:
            return self._store.similarity_search(query, k=k)
        except Exception as exc:
            logger.error("[NCERT] Retrieval error: %s", exc)
            return []


# ─── User Store (session-persistent uploads) ─────────────────────────────────

class UserStore:
    """
    Manages PDFs uploaded at runtime via /upload-pdf.
    Backed by a persistent ChromaDB so it survives server restarts,
    but explicitly cleared via /clear-pdf.
    """

    COLLECTION    = "user_uploads"
    CHUNK_SIZE    = 1000
    CHUNK_OVERLAP = 200

    def __init__(self):
        from langchain_chroma import Chroma
        Path(USER_DB_PATH).mkdir(parents=True, exist_ok=True)
        self._store = Chroma(
            collection_name=self.COLLECTION,
            embedding_function=get_embeddings(),
            persist_directory=USER_DB_PATH,
        )
        self._filename: Optional[str] = None
        # Restore filename from metadata if data already exists
        if self.has_data():
            try:
                meta = self._store._collection.get(limit=1)["metadatas"]
                if meta:
                    self._filename = meta[0].get("source")
            except Exception:
                pass

    # ── Status ────────────────────────────────────────────────────────────────

    def has_data(self) -> bool:
        return self._store._collection.count() > 0

    def current_filename(self) -> Optional[str]:
        return self._filename

    def reset(self):
        try:
            ids = self._store._collection.get()["ids"]
            if ids:
                self._store._collection.delete(ids=ids)
        except Exception as exc:
            logger.error("[UserStore] Reset error: %s", exc)
        self._filename = None
        logger.info("[UserStore] Cleared.")

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest_pdf(self, pdf_path: str, filename: str = ""):
        from pypdf import PdfReader
        from langchain_core.documents import Document
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        # Load pages directly with pypdf (avoids langchain-community)
        reader   = PdfReader(pdf_path)
        fname    = filename or os.path.basename(pdf_path)
        raw_docs = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                raw_docs.append(Document(
                    page_content=text,
                    metadata={"source": fname, "page": i + 1},
                ))

        # Protect equations before splitting
        for doc in raw_docs:
            doc.page_content = _protect_equations(doc.page_content)

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.CHUNK_SIZE,
            chunk_overlap=self.CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        docs = splitter.split_documents(raw_docs)

        fname = filename or os.path.basename(pdf_path)
        for doc in docs:
            doc.metadata["source"] = fname

        self._store.add_documents(docs)
        self._filename = fname
        logger.info("[UserStore] Ingested %d chunks from '%s'", len(docs), fname)

    # ── Query (backwards-compatible interface) ────────────────────────────────

    def retrieve(self, query: str, k: int = 4) -> list:
        if not self.has_data():
            return []
        try:
            return self._store.similarity_search(query, k=k)
        except Exception as exc:
            logger.error("[UserStore] Retrieval error: %s", exc)
            return []

    def query(self, query_text: str, k: int = 8, final_k: int = 5) -> str:
        docs = self.retrieve(query_text, k=min(k, final_k))
        return _format_docs(docs)

    def query_for_slide(self, topic: str, slide_title: str, k: int = 4) -> str:
        docs = self.retrieve(f"{topic}: {slide_title}", k=k)
        return _format_docs(docs)


# ─── Backward-compat alias ────────────────────────────────────────────────────
# main.py does: from rag import RAG; rag = RAG()
RAG = UserStore


# ─── Singleton NCERT store ────────────────────────────────────────────────────
_NCERT: Optional[NCERTStore] = None


def get_ncert_store() -> NCERTStore:
    global _NCERT
    if _NCERT is None:
        _NCERT = NCERTStore()
    return _NCERT


# ─── Combined retrieval (primary entry point for generation) ─────────────────

def combine_context(
    query: str,
    user_store: UserStore,
    k_ncert: int = 4,
    k_user: int = 3,
) -> tuple[str, bool]:
    """
    Query both NCERT and user stores, merge results.
    Returns (formatted_context, used_rag_flag).
    used_rag is True only when at least one source returned results.
    """
    ncert_docs = get_ncert_store().retrieve(query, k=k_ncert)
    user_docs  = user_store.retrieve(query, k=k_user) if user_store.has_data() else []

    all_docs = ncert_docs + user_docs
    if not all_docs:
        return "", False

    return _format_docs(all_docs), True


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _format_docs(docs: list) -> str:
    """Format LangChain Documents into a readable context string."""
    parts = []
    for doc in docs:
        src  = doc.metadata.get("source", "")
        page = doc.metadata.get("page", "?")
        if src:
            label = f"[Source: {src}, Page {page}]"
        else:
            label = f"[Page {page}]"
        parts.append(f"{label}\n{doc.page_content.strip()}")
    return "\n\n---\n\n".join(parts)