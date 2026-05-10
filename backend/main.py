# main.py
import os
import json
import shutil
import tempfile
import logging
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from schemas import LessonPlan
from rag import RAG
from llm_router import MultiLLMClient

# -------------------------
# Load environment variables
# -------------------------
load_dotenv()

# -------------------------
# Logging
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI()

# -------------------------
# Multi-LLM Client (Gemini → Groq fallback)
# -------------------------
llm = MultiLLMClient()

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
You are a master teacher creating visual blackboard-style lessons.
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

For the Spatial Diagram slide, recreate the ACTUAL physical/spatial layout:
  Water Cycle: sun ellipse top-right (yellow), cloud ellipses top-center (light blue),
    mountain rects left side (grey/green), ocean rect bottom-right (blue), river rect
    bottom-center; arrows: evaporation up, precipitation down, runoff right, label each.
  Black Hole: large dark ellipse center=event horizon, surrounding orange ellipses=
    accretion disk, blue arrow jets top+bottom, labels: "Singularity",
    "Schwarzschild radius", "No escape"; small star ellipses being pulled in.
  Solar System: large orange ellipse=Sun (left side), planet ellipses at increasing
    x-positions labeled with name+distance from Sun.
  Earth Layers: 4 concentric ellipses center-canvas: inner core(red), outer core
    (orange), mantle(purple), crust(blue) — each labeled with temp & composition.
  Cell: large ellipse=membrane, inner ellipses: nucleus, mitochondria, vacuole —
    each labeled with function text.
  Use the FULL 1000x800 canvas spatially. Do NOT compress into flow boxes.

========================================================
SLIDE COUNT & ARCHETYPES
========================================================
Assess complexity, then pick slide count:
  SIMPLE (2-3): single concept/formula  MEDIUM (4-5): 2-3 sub-topics
  COMPLEX (6-8): multi-layered/interconnected systems

Slide archetypes to pick from:
  "What Is It?"      — analogy + definition + formula       [always FIRST]
  "Spatial Diagram"  — physical layout (if detected above) [slide 2 if applicable]
  "How Does It Work?"— numbered steps, arrows
  "Deep Dive"        — one sub-concept with equations
  "Mechanism/Cycle" — cyclic arrows, loop stages
  "Comparison"       — side-by-side columns
  "Key Numbers"      — values, constants, units
  "Why It Matters"   — applications radiating from center ellipse
  "Summary & Recap"  — key points, mnemonics               [always LAST]

========================================================
RULE 1 — EVERY SHAPE MUST HAVE A TEXT LABEL INSIDE IT
========================================================
For EVERY rectangle or ellipse you draw at position (x, y, width, height),
you MUST immediately add a text element INSIDE it like this:
  Shape: { "id":"box1", "type":"rectangle", "x":50, "y":100, "width":200, "height":80, ... }
  Label: { "id":"box1_lbl", "type":"text", "x":60, "y":125, "width":180, "height":30, "text":"SPECIFIC CONTENT HERE", "fontSize":14, ... }
  (text x = shape_x + 10, text y = shape_y + shape_height/2 - 10)

Text inside shapes must contain REAL information:
  GOOD: "F = ma", "Mass = 10 kg", "Step 1: Input Signal", "CPU: 3.2 GHz", "Na+ ions rush in"
  BAD:  "Concept", "Box", "Real World", "Item", "Element"

========================================================
RULE 2 — REQUIRED ELEMENTS PER SLIDE
========================================================
Each slide MUST have AT LEAST 15 elements:
  - 1x large TITLE text at top (x:300-500, y:20-40, fontSize:22, full topic name or key formula)
  - 4+ labeled rectangles (each rectangle + its inner text label = 2 elements)
  - 2+ labeled ellipses (each ellipse + its inner text = 2 elements)
  - 2+ arrows with short text labels near them (describing what the arrow means)
  - 2+ standalone annotation texts (small callouts, notes, formulas, or facts)

========================================================
RULE 3 — CANVAS LAYOUT (1000 x 800)
========================================================
Use ALL 4 zones of the canvas. Do NOT cluster in one area:

  TOP BANNER   (y: 10–80):  Slide title + key formula/definition
  LEFT HALF    (x: 20–480): Primary concept / cause / input
  RIGHT HALF   (x: 520–980): Effect / result / comparison
  BOTTOM STRIP (y: 680–780): Summary row, key takeaway, or legend

Place arrows to connect LEFT to RIGHT to show flow/relationship.
Use the BOTTOM STRIP for a summary rectangle that ties everything together.

========================================================
RULE 4 — INFORMATIVE TEXT
========================================================
Every text element must carry REAL content:
  - Numbers and units: "9.8 m/s²", "λ = 450nm", "pH 7.4"
  - Short definitions: "Force = push/pull", "Catalyst speeds reaction"
  - Process labels: "Step 1: Oxidation", "Input → Process → Output"
  - Comparisons: "Series: same current", "Parallel: same voltage"
  - Cause-effect: "More mass → less acceleration"
  
AVOID purely abstract labels. Every label should teach something.

========================================================
RULE 5 — ARROW FORMAT (CRITICAL)
========================================================
Arrows use RELATIVE points from their (x, y) starting position:
  { "id":"arr1", "type":"arrow", "x":300, "y":200,
    "strokeColor":"#000000", "backgroundColor":"transparent",
    "fillStyle":"solid", "strokeWidth":2,
    "width":null, "height":null, "text":null, "fontSize":null,
    "points":[[0,0],[150,0]] }   ← goes 150px to the right
  
Right:  points [[0,0],[150,0]]
Down:   points [[0,0],[0,100]]
Diagonal: points [[0,0],[120,80]]

Add a text element NEAR each arrow (offset by ~10px from arrow midpoint) to label what the arrow means.
Example: arrow from Force box to Acceleration box → text label "causes"

========================================================
RULE 6 — COLOR CODING
========================================================
Use colors to organize meaning:
  Blue   (#1971c2 stroke, #dbe4ff bg): Input / Cause / Given
  Green  (#2f9e44 stroke, #d3f9d8 bg): Output / Result / Effect  
  Orange (#e67700 stroke, #fff3bf bg): Key formula / Important fact
  Purple (#7048e8 stroke, #f3d9fa bg): Process step / Mechanism
  Red    (#c92a2a stroke, #ffe3e3 bg): Warning / Exception / Contrast

========================================================
CONTENT RULES
========================================================
- Voiceover: 4-5 sentences. Explain WHY and HOW with specifics, not vague descriptions.
- If document context is provided, use ONLY facts from it. Quote key terms exactly.
- Keep text labels SHORT (max 5 words per text element) but SPECIFIC
- Total elements per slide: 15–20
"""


def build_prompt(topic: str, rag_context: str | None) -> str:
    tail = (
        f'Topic: "{topic}"\n'
        f"1. Check if a Spatial Diagram slide applies (see SPATIAL DIAGRAM DETECTION above).\n"
        f"2. Assess complexity → SIMPLE(2-3) / MEDIUM(4-5) / COMPLEX(6-8 slides).\n"
        f"3. Build slides using the correct archetypes. Each slide: 15-20 elements, "
        f"full 1000x800 canvas, every shape labeled inside. IDs: s1_, s2_, ...sN_.\n"
    )
    if rag_context:
        return f"""{BASE_PROMPT}

### DOCUMENT CONTEXT (use ONLY facts from this)
{rag_context}

{tail}"""
    else:
        return f"""{BASE_PROMPT}

{tail}"""




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
            compressed = llm.compress_context(query.topic, raw_context)

            # fallback safety
            if compressed and len(compressed) > 50:
                rag_context = compressed
            else:
                rag_context = raw_context

        prompt = build_prompt(query.topic, rag_context)

        lesson_plan_data = llm.generate_lesson(prompt, query.topic)

        return {
            "lesson_plan": lesson_plan_data,
            "used_rag": rag_context is not None
        }

    except RuntimeError as e:
        # All LLMs failed – surface a clear error to the frontend
        logger.error(f"All LLMs failed: {e}")
        return {"error": str(e)}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}