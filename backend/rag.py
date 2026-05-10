# rag.py
import numpy as np
import chromadb
import nltk
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

# Download punkt tokenizer data if not already present
nltk.download("punkt", quiet=True)


class RAG:
    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self.chroma_client = chromadb.Client()
        self._create_collection()

    def _create_collection(self):
        self.collection = self.chroma_client.get_or_create_collection(
            name="pdf_store"
        )

    # -------------------------
    # Status helpers
    # -------------------------
    def has_data(self) -> bool:
        """Returns True if at least one document has been ingested."""
        return self.collection.count() > 0

    def reset(self):
        """Clear all ingested data so a new PDF can be uploaded fresh."""
        self.chroma_client.delete_collection("pdf_store")
        self._create_collection()

    # -------------------------
    # Extract text
    # -------------------------
    def extract_text(self, pdf_path: str) -> str:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text

    # -------------------------
    # Chunking (sentence-aware)
    # -------------------------
    def chunk_text(self, text: str, sentences_per_chunk: int = 5, overlap: int = 1):
        """Split text into chunks of N sentences with sentence-level overlap."""
        sentences = nltk.sent_tokenize(text)
        if not sentences:
            return []

        chunks = []
        start = 0
        while start < len(sentences):
            end = start + sentences_per_chunk
            chunk = " ".join(sentences[start:end])
            chunks.append(chunk)
            start += max(1, sentences_per_chunk - overlap)
        return chunks

    # -------------------------
    # Ingest PDF
    # -------------------------
    def ingest_pdf(self, pdf_path: str):
        print("Extracting text from PDF...")
        text = self.extract_text(pdf_path)

        print("Chunking text...")
        chunks = self.chunk_text(text)

        print("Creating embeddings...")
        embeddings = self.model.encode(chunks)

        print("Storing in ChromaDB...")
        for i, chunk in enumerate(chunks):
            self.collection.add(
                documents=[chunk],
                embeddings=[embeddings[i].tolist()],
                ids=[f"chunk_{i}"]
            )
        print(f"✅ Ingestion complete — {len(chunks)} chunks stored")

    # -------------------------
    # Query (with re-ranking)
    # -------------------------
    def query(self, query_text: str, k: int = 5, final_k: int = 3) -> str:
        # Step 1: embed the query
        query_embedding = self.model.encode([query_text])[0]

        # Step 2: retrieve top-k candidates from ChromaDB
        n = min(k, self.collection.count())
        results = self.collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=n
        )
        documents = results["documents"][0]

        # Step 3: re-rank using cosine similarity
        doc_embeddings = self.model.encode(documents)
        scores = []
        for emb in doc_embeddings:
            score = np.dot(emb, query_embedding) / (
                np.linalg.norm(emb) * np.linalg.norm(query_embedding)
            )
            scores.append(float(score))

        ranked_docs = [
            doc for _, doc in sorted(zip(scores, documents), reverse=True)
        ]

        # Step 4: return top clean chunks joined by blank lines
        return "\n\n".join(ranked_docs[:final_k])