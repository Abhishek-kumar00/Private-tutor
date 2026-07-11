import traceback
from rag import RAG

try:
    rag = RAG()
    rag.reset()
    # Let's create a dummy pdf first or just text
    print("RAG instantiated")
    text = "Hello world. This is a test."
    rag.collection.add(
        documents=[text],
        embeddings=[[0.1]*384],
        ids=["test_1"]
    )
    print("Added to collection")
except Exception as e:
    traceback.print_exc()
