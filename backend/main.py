# main.py
import os
import sys

# Force UTF-8 encoding to fix Windows emoji/charmap crashes
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import json
import shutil
import tempfile
import logging
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from schemas import LessonPlan, DoubtRequest
from rag import RAG, combine_context, get_ncert_store
from llm_router import MultiLLMClient

# ─── Bootstrap ───────────────────────────────────────────────────────────────
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Private Tutor API",
    description="RAG-powered Class 11/12 PCM tutor — grounded in NCERT textbooks",
    version="2.0.0",
)

# ─── Singletons ───────────────────────────────────────────────────────────────
llm = MultiLLMClient()
rag = RAG()          # UserStore instance (session uploads)

# ─── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Request models ───────────────────────────────────────────────────────────

class UserQuery(BaseModel):
    topic: str
    subject: Optional[str] = None       # "Physics" | "Chemistry" | "Mathematics"
    grade_level: Optional[int] = None   # 11 or 12


# ─────────────────────────────────────────────────────────────────────────────
# MASTER PROMPT  (BASE_PROMPT unchanged — kept for Gemini structured-output)
# ─────────────────────────────────────────────────────────────────────────────
BASE_PROMPT = """
You are a master Class 11/12 PCM teacher creating visual blackboard-style lessons.
Ground ALL content strictly in the provided NCERT textbook context.
Every diagram must be INFORMATION-DENSE — every element must teach something.

========================================================
SPATIAL DIAGRAM DETECTION (CHECK THIS FIRST)
========================================================
Some topics have a well-known physical layout students must SEE to understand.
If the topic matches any of these categories, include a dedicated SPATIAL DIAGRAM slide:
  - Natural cycles: Water Cycle, Carbon Cycle, Nitrogen Cycle, Rock Cycle
  - Astronomy: Solar System, Black Holes, Big Bang, Moon Phases, Eclipses
  - Earth science: Earth Layers, Plate Tectonics, Volcanoes, Atmosphere
  - Biology structures: Cell, Heart, Eye, Brain, Leaf cross-section
  - Physics structures: Atom model, Wave anatomy, EM Spectrum
  - Engineering: Circuit, Engine cross-section, Bridge types

For the Spatial Diagram slide, recreate the ACTUAL physical/spatial layout using
positioned ellipses and rects across the FULL 1000×800 canvas.

========================================================
SLIDE COUNT & ARCHETYPES
========================================================
Assess complexity, then pick slide count:
  SIMPLE (2-3): single concept/formula  MEDIUM (4-5): 2-3 sub-topics
  COMPLEX (6-10): multi-layered/interconnected systems

Slide archetypes to pick from:
  "What Is It?"      — analogy + definition + formula       [always FIRST]
  "Spatial Diagram"  — physical layout (if detected above) [slide 2 if applicable]
  "How Does It Work?"— numbered steps, arrows
  "Deep Dive"        — one sub-concept with equations
  "Mechanism/Cycle"  — cyclic arrows, loop stages
  "Comparison"       — side-by-side columns
  "Key Numbers"      — values, constants, units
  "Why It Matters"   — applications radiating from center ellipse
  "Summary & Recap"  — key points, mnemonics               [always LAST]

========================================================
RULE 1 — EVERY SHAPE MUST HAVE A TEXT LABEL INSIDE IT
========================================================
For EVERY rectangle or ellipse at position (x, y, width, height),
immediately add a text element INSIDE it:
  Shape: {"id":"box1","type":"rectangle","x":50,"y":100,"width":200,"height":80,...}
  Label: {"id":"box1_lbl","type":"text","x":60,"y":125,"width":180,"height":30,"text":"SPECIFIC CONTENT","fontSize":14,...}
  (text x = shape_x+10, text y = shape_y + shape_height/2 - 10)

Text inside shapes must contain REAL information:
  GOOD: "F = ma", "Mass = 10 kg", "Step 1: Input Signal", "Na⁺ ions rush in"
  BAD:  "Concept", "Box", "Real World", "Item", "Element"

========================================================
RULE 2 — REQUIRED ELEMENTS PER SLIDE (18-22)
========================================================
  - 1× large TITLE text at top (x:300-500, y:20-40, fontSize:22)
  - 1+ standalone EQUATION text (fontSize:22+, orange #e67700) IF formulae apply
  - 4+ labeled rectangles (rect + inner text = 2 elements each)
  - 2+ labeled ellipses (ellipse + inner text = 2 elements each)
  - 2+ arrows with short text labels near them
  - 1 summary rectangle at bottom (y~700) with inner text

========================================================
RULE 3 — CANVAS LAYOUT (1000 × 800)
========================================================
Use ALL 4 zones:
  TOP BANNER   (y: 10–80):  Slide title + key formula
  LEFT HALF    (x: 20–480): Primary concept / cause / input
  RIGHT HALF   (x: 520–980): Effect / result / comparison
  BOTTOM STRIP (y: 680–780): Summary, key takeaway, or legend

========================================================
RULE 4 — INFORMATIVE TEXT
========================================================
  - Numbers & units: "9.8 m/s²", "λ = 450 nm", "pH 7.4"
  - Definitions: "Force = push/pull", "Catalyst speeds reaction"
  - Process labels: "Step 1: Oxidation", "Input → Process → Output"
AVOID purely abstract labels.

========================================================
RULE 5 — ARROW FORMAT
========================================================
Arrows use RELATIVE points from their (x, y) starting position:
  Right:    points [[0,0],[150,0]]
  Down:     points [[0,0],[0,100]]
  Diagonal: points [[0,0],[120,80]]
Add a text element NEAR each arrow describing the relationship.

========================================================
RULE 6 — COLOR CODING
========================================================
  Blue   (#1971c2 / #dbe4ff): Input / Cause / Given
  Green  (#2f9e44 / #d3f9d8): Output / Result / Effect
  Orange (#e67700 / #fff3bf): Key formula / Important fact
  Purple (#7048e8 / #f3d9fa): Process step / Mechanism
  Red    (#c92a2a / #ffe3e3): Warning / Exception / Contrast

========================================================
EQUATION_RULES — MANDATORY FOR QUANTITATIVE TOPICS
========================================================
1. EQUATION ELEMENT: Standalone text, fontSize 22+, strokeColor "#e67700",
   placed near top area (y: 70-200):
   {"id":"s2_eq1","type":"text","x":250,"y":80,"strokeColor":"#e67700",
    "backgroundColor":"transparent","fillStyle":"solid","strokeWidth":1,
    "width":500,"height":44,"text":"F = ma  [Force = Mass × Acceleration]","fontSize":22,"points":null}

2. CONSTANTS & UNITS: Always state value + unit:
   GOOD: "g = 9.8 m/s²", "c = 3×10⁸ m/s"  BAD: "g = constant"

3. DERIVATION LADDER: Numbered purple rects stacked vertically, connected by arrows.

4. EQUATIONS FIELD: Every slide must include "equations": ["F=ma"] or []

========================================================
QUESTIONS RULES — GENERATE EXACTLY 3 MCQs
========================================================
- Derive questions ONLY from the textbook context provided
- Each question: 4 options ["A) ...","B) ...","C) ...","D) ..."]
- correct_answer: single letter "A"/"B"/"C"/"D"
- explanation: 1 sentence citing the textbook concept
"""


def build_prompt(
    topic: str,
    rag_context: Optional[str],
    subject: Optional[str] = None,
    grade_level: Optional[int] = None,
) -> str:
    meta = ""
    if subject:
        meta += f"Subject: {subject}\n"
    if grade_level:
        meta += f"Grade: Class {grade_level}\n"

    tail = (
        f'Topic: "{topic}"\n'
        f"{meta}"
        f"1. Check if a Spatial Diagram slide applies.\n"
        f"2. Assess complexity → SIMPLE(2-3) / MEDIUM(4-5) / COMPLEX(6-10).\n"
        f"3. Build slides: 18-22 elements, full 1000×800 canvas, every shape labeled.\n"
        f"   Use slide ID prefixes: s1_, s2_, … sN_\n"
        f"4. Generate EXACTLY 3 MCQ questions grounded in the textbook context.\n"
    )

    if rag_context:
        return f"""{BASE_PROMPT}

### NCERT TEXTBOOK CONTEXT (ground ALL facts in this)
{rag_context}

{tail}"""
    else:
        return f"""{BASE_PROMPT}

{tail}"""


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Quick liveness check."""
    return {"status": "ok", "version": "2.0.0"}


@app.get("/rag-status")
async def rag_status():
    """Return detailed status of both NCERT and user RAG stores."""
    ncert = get_ncert_store()
    return {
        # NCERT knowledge base
        "has_ncert":     ncert.is_available(),
        "ncert_chunks":  ncert.chunk_count(),
        # User upload
        "has_user_pdf":  rag.has_data(),
        "user_pdf_name": rag.current_filename(),
        # Legacy field (frontend compatibility)
        "has_pdf":       rag.has_data() or ncert.is_available(),
    }


@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    """Upload a supplementary PDF. It is layered on top of the NCERT knowledge base."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        rag.reset()
        rag.ingest_pdf(tmp_path, filename=file.filename)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        os.unlink(tmp_path)

    return {"message": "PDF ingested", "has_pdf": True, "filename": file.filename}


@app.delete("/clear-pdf")
async def clear_pdf():
    """Remove the user-uploaded PDF from the store."""
    rag.reset()
    return {"message": "PDF cleared", "has_pdf": False}


@app.post("/generate-lesson")
async def generate_lesson(query: UserQuery):
    """
    Generate a full lesson plan with diagrams and MCQs.
    Grounded in NCERT textbooks when available; falls back to LLM knowledge.
    """
    try:
        # ── Retrieve combined RAG context ─────────────────────────────────────
        search_query = f"{query.topic}"
        if query.subject:
            search_query += f" {query.subject}"
        if query.grade_level:
            search_query += f" class {query.grade_level}"

        rag_context, used_rag = combine_context(search_query, rag)

        # Compress if very long
        if rag_context and len(rag_context) > 4000:
            compressed = llm.compress_context(query.topic, rag_context)
            if compressed and len(compressed) > 50:
                rag_context = compressed

        prompt = build_prompt(
            query.topic,
            rag_context or None,
            query.subject,
            query.grade_level,
        )

        lesson_plan_data = llm.generate_lesson(prompt, query.topic)

        return {
            "lesson_plan": lesson_plan_data,
            "used_rag":    used_rag,
        }

    except RuntimeError as exc:
        logger.error("All LLMs failed: %s", exc)
        return {"error": str(exc)}
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return {"error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# DOUBT / Q&A
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/ask-doubt")
async def ask_doubt(request: DoubtRequest):
    """
    Answer a student's in-lesson doubt, grounded in textbook context.
    """
    try:
        # Pull context from both stores
        context, _ = combine_context(request.question, rag, k_ncert=3, k_user=2)

        answer = llm.answer_doubt(
            topic=request.topic,
            slide_title=request.slide_title,
            question=request.question,
            context=context,
        )
        return {"answer": answer}

    except Exception as exc:
        logger.error("[ask_doubt] Error: %s", exc)
        return {"answer": "Sorry, I'm having trouble answering right now. Please try again!"}