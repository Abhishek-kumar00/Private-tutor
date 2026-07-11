#!/usr/bin/env python3
"""
ingest.py
=========
Offline ingestion pipeline — run once after downloading NCERT PDFs.

What it does:
  1. Walks ../textbooks/ for all *.pdf files
  2. Loads each with LangChain's PyPDFLoader
  3. Protects equation lines from being split
  4. Splits into 1000-token chunks with 200-token overlap
  5. Embeds with BAAI/bge-base-en-v1.5 (local, free)
  6. Stores in persistent ChromaDB at ./chroma_db/ncert/

Usage:
    cd backend
    python ingest.py

Options:
    --dir  PATH   Override the textbooks directory (default: ../textbooks)
    --reset       Clear the existing ChromaDB before ingesting
"""

import sys
import os
import time
import argparse
import logging
from pathlib import Path

# Force UTF-8 for Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add backend/ to path so we can import rag.py
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from rag import (
    get_embeddings,
    NCERT_DB_PATH,
    _protect_equations,
    NCERTStore,
)

CHUNK_SIZE    = 1000
CHUNK_OVERLAP = 200

# Subject / grade inferred from directory name  (physics_11, chemistry_12, …)
SUBJECT_MAP = {
    "physics":     "Physics",
    "chemistry":   "Chemistry",
    "mathematics": "Mathematics",
    "maths":       "Mathematics",
    "math":        "Mathematics",
    "biology":     "Biology",
}


def _infer_metadata(pdf_path: Path) -> dict:
    """Extract subject and grade from the folder name."""
    folder = pdf_path.parent.name.lower()   # e.g. "physics_11"
    parts  = folder.split("_")
    subject = SUBJECT_MAP.get(parts[0], parts[0].capitalize()) if parts else "Unknown"
    grade   = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return {"subject": subject, "grade": grade, "source": pdf_path.name}


def ingest_directory(textbooks_dir: Path, reset: bool = False):
    from pypdf import PdfReader
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_chroma import Chroma

    pdf_files = sorted(textbooks_dir.rglob("*.pdf"))
    if not pdf_files:
        print(f"\n  ✗ No PDFs found in {textbooks_dir}")
        print("  Run `python download_ncert.py` first, or manually place PDFs there.")
        sys.exit(1)

    print(f"\n  Found {len(pdf_files)} PDF file(s) across all subjects.")

    # ── Initialise (or reset) ChromaDB ────────────────────────────────────────
    Path(NCERT_DB_PATH).mkdir(parents=True, exist_ok=True)
    embeddings = get_embeddings()

    vector_store = Chroma(
        collection_name=NCERTStore.COLLECTION,
        embedding_function=embeddings,
        persist_directory=NCERT_DB_PATH,
    )

    if reset:
        print("  Resetting existing ChromaDB …")
        existing_ids = vector_store._collection.get()["ids"]
        if existing_ids:
            vector_store._collection.delete(ids=existing_ids)
        print(f"  Deleted {len(existing_ids)} existing chunks.")
        processed_sources = set()
    else:
        # Find already processed files to skip them
        print("  Checking for already processed PDFs to resume ingestion…")
        existing_meta = vector_store._collection.get(include=["metadatas"])["metadatas"]
        processed_sources = set(m.get("source") for m in existing_meta if m and "source" in m)
        if processed_sources:
            print(f"  Found {len(processed_sources)} PDFs already ingested. Skipping them.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    # ── Process each PDF ──────────────────────────────────────────────────────
    total_chunks  = 0
    total_pages   = 0
    t0 = time.time()

    for pdf_path in pdf_files:
        meta = _infer_metadata(pdf_path)
        rel  = pdf_path.relative_to(textbooks_dir)

        if meta["source"] in processed_sources:
            print(f"\n  ⏩ Skipping {rel} (already ingested)")
            continue

        print(f"\n  ▶ {rel}  [{meta['subject']} | Class {meta['grade']}]")

        try:
            reader     = PdfReader(str(pdf_path))
            raw_docs   = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                if text.strip():
                    raw_docs.append(Document(
                        page_content=text,
                        metadata={**meta, "page": i + 1},
                    ))
            total_pages += len(raw_docs)

            # Equation protection — keep formula lines atomic
            for doc in raw_docs:
                doc.page_content = _protect_equations(doc.page_content)

            chunks = splitter.split_documents(raw_docs)
            total_chunks += len(chunks)

            # Batch-add in groups of 500 to avoid memory issues
            batch_size = 500
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i : i + batch_size]
                vector_store.add_documents(batch)
                print(f"    Stored chunks {i+1}–{min(i+batch_size, len(chunks))} / {len(chunks)}")

        except Exception as exc:
            print(f"    ✗ Error processing {pdf_path.name}: {exc}")
            logger.exception("Ingestion error")

    elapsed = time.time() - t0
    print("\n" + "=" * 60)
    print(f"  Ingestion complete!")
    print(f"    PDFs processed : {len(pdf_files)}")
    print(f"    Pages loaded   : {total_pages}")
    print(f"    Chunks stored  : {total_chunks}")
    print(f"    Time taken     : {elapsed:.1f}s")
    print(f"    ChromaDB path  : {NCERT_DB_PATH}")
    print("=" * 60)
    print("\n  The server will now use this knowledge base automatically.")
    print("  Start the backend:  uvicorn main:app --reload")


def main():
    parser = argparse.ArgumentParser(description="Ingest NCERT PDFs into ChromaDB")
    parser.add_argument(
        "--dir",
        default=str(Path(__file__).parent.parent / "textbooks"),
        help="Path to directory containing NCERT PDFs (default: ../textbooks)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear existing ChromaDB before ingesting",
    )
    args = parser.parse_args()

    textbooks_dir = Path(args.dir)
    print("=" * 60)
    print("  NCERT Ingestion Pipeline  |  Private Tutor v2.0")
    print("=" * 60)
    print(f"  Textbooks dir : {textbooks_dir}")
    print(f"  ChromaDB path : {NCERT_DB_PATH}")
    print(f"  Reset store   : {args.reset}")

    if not textbooks_dir.exists():
        print(f"\n  ✗ Directory not found: {textbooks_dir}")
        print("  Run `python download_ncert.py` first.")
        sys.exit(1)

    ingest_directory(textbooks_dir, reset=args.reset)


if __name__ == "__main__":
    main()
