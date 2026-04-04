# main.py
import os
import json
import shutil
import tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from google import genai
from google.genai import types

from schemas import LessonPlan
from rag import RAG

# Load environment variables
load_dotenv()

app = FastAPI()

# Configure the google-genai client
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY not found in environment variables")

client = genai.Client(api_key=api_key)

# Global RAG instance (singleton — shared across all requests)
rag = RAG()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# Input Models
# -------------------------
class UserQuery(BaseModel):
    topic: str

# -------------------------
# System Prompts
# -------------------------
BASE_PROMPT = """
You are an expert technical educator and visual illustrator.
Your goal is to teach complex concepts using "Mental Models" and detailed diagrams.

### 1. CONTENT RULES (Make it informative)
- **Voiceover:** This is your lecture script. It must be engaging, descriptive, and at least 3-4 sentences long per slide. Do not be vague. Explain "Why" and "How."
- **Labels:** Do not just label objects (e.g., "Box"). Use descriptive labels (e.g., "Input Layer: Receives raw data").
- **Analogy:** Whenever possible, use an analogy in Slide 1 to make the concept click (e.g., "Voltage is like water pressure").

### 2. VISUAL RULES (Excalidraw)
- **Canvas:** 1000x800. Start drawing from top-left (x=50, y=50) flowing rightwards or downwards.
- **Shapes:**
  - Use 'rectangle' for main components/boxes.
  - Use 'arrow' (with labels) to show the flow of data or energy.
  - Use 'ellipse' for start/end points or highlights.
  - Use 'text' for standalone labels.
- **Layout:** Avoid clutter. Give shapes at least 50px breathing room. Align items logically.
- **IMPORTANT:** For rectangles and ellipses you MUST supply width and height. For text only supply x, y, text, fontSize. For arrows supply points as [[x1,y1],[x2,y2]].

### 3. LESSON STRUCTURE (3 Slides)
- **Slide 1: The "What" & The Analogy** – Define the concept with a real-world analogy. Visual: high-level diagram.
- **Slide 2: The "How" (The Mechanism)** – Explain internal mechanics step-by-step. Visual: flowchart with arrows.
- **Slide 3: The "Why" (Implication/Summary)** – Explain real-world applications. Visual: summary diagram.
"""

def build_prompt(topic: str, rag_context: str | None) -> str:
    if rag_context:
        return f"""{BASE_PROMPT}

### 4. STUDENT'S UPLOADED DOCUMENT (PRIMARY SOURCE)
The student has uploaded their own study material. Use the following excerpts as the PRIMARY source of truth for facts, definitions, and examples. Your lesson MUST be grounded in this content — refer to the specific details, terminology, and examples found here. Do not invent information that contradicts this material.

--- BEGIN DOCUMENT CONTEXT ---
{rag_context}
--- END DOCUMENT CONTEXT ---

Now create a 3-slide lesson grounded in the above document to explain: "{topic}"
"""
    else:
        return BASE_PROMPT + f'\n\nExplain and draw: "{topic}"'

# -------------------------
# Endpoints
# -------------------------

@app.get("/rag-status")
async def rag_status():
    """Check if a PDF has been ingested."""
    return {"has_pdf": rag.has_data()}


@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    """Accept a PDF, ingest it into the RAG system."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # Save to a temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        # Reset previous PDF data and ingest the new one
        rag.reset()
        rag.ingest_pdf(tmp_path)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to ingest PDF: {str(e)}")
    finally:
        os.unlink(tmp_path)  # clean up temp file

    return {
        "message": f"✅ PDF '{file.filename}' ingested successfully.",
        "has_pdf": True
    }


@app.delete("/clear-pdf")
async def clear_pdf():
    """Remove all ingested PDF data."""
    rag.reset()
    return {"message": "PDF data cleared.", "has_pdf": False}


@app.post("/generate-lesson")
async def generate_lesson(query: UserQuery):
    try:
        # Fetch RAG context if a PDF has been uploaded
        rag_context = None
        if rag.has_data():
            rag_context = rag.query(query.topic)

        prompt = build_prompt(query.topic, rag_context)

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=LessonPlan,
                temperature=0.7,
            ),
        )
        lesson_plan_data = json.loads(response.text)
        return {
            "lesson_plan": lesson_plan_data,
            "used_rag": rag_context is not None
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}