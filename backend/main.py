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

# -------------------------
# Load environment variables
# -------------------------
load_dotenv()

app = FastAPI()

# -------------------------
# Configure Gemini
# -------------------------
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY not found")

client = genai.Client(api_key=api_key)

# -------------------------
# Global RAG instance
# -------------------------
rag = RAG()

# -------------------------
# CORS
# -------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# Input Model
# -------------------------
class UserQuery(BaseModel):
    topic: str


# -------------------------
# PROMPT
# -------------------------
BASE_PROMPT = """
You are an expert technical educator and visual illustrator.

Your goal is to teach concepts using clear explanations and structured diagrams.

### STRICT RULES:
- You MUST strictly rely on the provided document context (if given).
- DO NOT invent facts outside the context.
- If something is unclear, say it clearly instead of guessing.

### CONTENT RULES:
- Voiceover must be 3–4 sentences minimum per slide.
- Explain WHY and HOW, not just WHAT.
- Use simple analogies in Slide 1.

### VISUAL RULES:
- Canvas: 1000x800
- Use rectangle, arrow, ellipse, text
- Maintain spacing (≥50px)
- No overlapping elements
- Logical layout (left→right or top→bottom)
- Arrows must connect meaningful elements

### LESSON STRUCTURE:
1. What + Analogy
2. How (mechanism)
3. Why (applications)
"""


def build_prompt(topic: str, rag_context: str | None) -> str:
    if rag_context:
        return f"""{BASE_PROMPT}

### DOCUMENT CONTEXT (PRIMARY SOURCE)
{rag_context}

Create a 3-slide lesson to explain:
"{topic}"
"""
    else:
        return BASE_PROMPT + f'\n\nExplain: "{topic}"'


# -------------------------
# CONTEXT COMPRESSION
# -------------------------
def compress_context(topic: str, context: str) -> str:
    prompt = f"""
Extract ONLY the most relevant information.

Topic: {topic}

Context:
{context}

Return concise, useful content only.
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2
        ),
    )

    return response.text.strip()


# -------------------------
# ENDPOINTS
# -------------------------

@app.get("/rag-status")
async def rag_status():
    return {"has_pdf": rag.has_data()}


@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF allowed")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        rag.reset()
        rag.ingest_pdf(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)

    return {"message": "PDF ingested", "has_pdf": True}


@app.delete("/clear-pdf")
async def clear_pdf():
    rag.reset()
    return {"message": "PDF cleared", "has_pdf": False}


@app.post("/generate-lesson")
async def generate_lesson(query: UserQuery):
    try:
        rag_context = None

        if rag.has_data():
            raw_context = rag.query(query.topic)
            compressed = compress_context(query.topic, raw_context)

            # fallback safety
            if compressed and len(compressed) > 50:
                rag_context = compressed
            else:
                rag_context = raw_context

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

        # Safe JSON parsing
        try:
            lesson_plan_data = json.loads(response.text)
        except:
            return {
                "error": "Invalid JSON from model",
                "raw_output": response.text
            }

        return {
            "lesson_plan": lesson_plan_data,
            "used_rag": rag_context is not None
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}