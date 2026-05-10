# llm_router.py
"""
Multi-LLM Router
================
Priority order:
  1. Gemini (primary)
  2. Groq – llama-3.3-70b-versatile          (GROQ_API_KEY_1 or GROQ_API_KEY)
  3. Groq – llama-3.1-8b-instant             (GROQ_API_KEY_2 or GROQ_API_KEY)
  4. Groq – llama-4-scout-17b-16e-instruct   (GROQ_API_KEY_3 or GROQ_API_KEY)

For Groq: if you have a single API key, just set GROQ_API_KEY.
          For multiple keys, set GROQ_API_KEY_1, GROQ_API_KEY_2, GROQ_API_KEY_3.
          If a specific numbered key is missing, the router falls back to GROQ_API_KEY.
"""

import os
import json
import logging
from typing import Optional

from google import genai
from google.genai import types
from groq import Groq, APIError

from schemas import LessonPlan

logger = logging.getLogger(__name__)

# ─── JSON schema hint injected into every Groq prompt ───────────────────────
GROQ_JSON_SCHEMA = """
OUTPUT FORMAT: Respond with ONLY valid JSON. No markdown. No explanation. Pure JSON only.

CRITICAL RULES:
1. Every rectangle/ellipse MUST have a text element positioned inside it (text x = shape_x+10, text y = shape_y+shape_height/2-10)
2. Text content must be SPECIFIC — NOT "Concept","Box","Item". GOOD: "F=ma","Step 1: Evaporation","9.8 m/s²"
3. Each slide needs AT LEAST 15 elements total
4. Use the full canvas (1000x800) — spread elements across all areas
5. Include a large TITLE text element at top-center of every slide (fontSize: 22)
6. SPATIAL DIAGRAM: If the topic has a known physical layout (Water Cycle, Black Holes,
   Solar System, Earth Layers, Cell, Atom, etc.), include one slide that recreates
   the actual spatial/geographic layout using positioned ellipses and rects — NOT flow boxes.
   Example for Water Cycle: sun top-right, clouds top-center, mountains left,
   ocean bottom-right, arrows for evaporation/precipitation/runoff.

JSON STRUCTURE:
{
  "topic": "string",
  "slides": [
    {
      "title": "string",
      "voiceover": "4-5 sentence explanation with specific facts",
      "scene": {
        "elements": [
          // TITLE (required on every slide):
          {"id":"s1_title","type":"text","x":280,"y":20,"strokeColor":"#212529","backgroundColor":"transparent","fillStyle":"solid","strokeWidth":1,"width":440,"height":40,"text":"FULL TOPIC: Key Formula Here","fontSize":22,"points":null},

          // LABELED RECTANGLE (shape + text inside = 2 elements, always paired):
          {"id":"s1_box1","type":"rectangle","x":50,"y":120,"strokeColor":"#1971c2","backgroundColor":"#dbe4ff","fillStyle":"solid","strokeWidth":2,"width":210,"height":90,"text":null,"fontSize":null,"points":null},
          {"id":"s1_box1_lbl","type":"text","x":60,"y":150,"strokeColor":"#1971c2","backgroundColor":"transparent","fillStyle":"solid","strokeWidth":1,"width":190,"height":30,"text":"Specific Label Here","fontSize":14,"points":null},

          // ARROW with nearby text label:
          {"id":"s1_arr1","type":"arrow","x":265,"y":165,"strokeColor":"#000000","backgroundColor":"transparent","fillStyle":"solid","strokeWidth":2,"width":null,"height":null,"text":null,"fontSize":null,"points":[[0,0],[140,0]]},
          {"id":"s1_arr1_lbl","type":"text","x":295,"y":145,"strokeColor":"#495057","backgroundColor":"transparent","fillStyle":"solid","strokeWidth":1,"width":80,"height":20,"text":"causes","fontSize":12,"points":null},

          // LABELED ELLIPSE (shape + text inside = 2 elements):
          {"id":"s1_el1","type":"ellipse","x":450,"y":320,"strokeColor":"#2f9e44","backgroundColor":"#d3f9d8","fillStyle":"solid","strokeWidth":2,"width":160,"height":80,"text":null,"fontSize":null,"points":null},
          {"id":"s1_el1_lbl","type":"text","x":460,"y":350,"strokeColor":"#2f9e44","backgroundColor":"transparent","fillStyle":"solid","strokeWidth":1,"width":140,"height":20,"text":"Result: Specific Fact","fontSize":13,"points":null},

          // SUMMARY RECTANGLE at bottom:
          {"id":"s1_summary","type":"rectangle","x":100,"y":700,"strokeColor":"#e67700","backgroundColor":"#fff3bf","fillStyle":"solid","strokeWidth":2,"width":800,"height":60,"text":null,"fontSize":null,"points":null},
          {"id":"s1_summary_lbl","type":"text","x":110,"y":720,"strokeColor":"#e67700","backgroundColor":"transparent","fillStyle":"solid","strokeWidth":1,"width":780,"height":30,"text":"KEY INSIGHT: Most important takeaway here","fontSize":15,"points":null}

          // ... add more elements to reach 15-20 total
        ]
      }
    }
    // ... N slides total (2–8, depending on complexity)
  ]
}

MANDATORY PER SLIDE:
- 1 title text (top center, fontSize 22)
- 4+ labeled rectangles (rectangle + inner text = 2 elements each)
- 2+ labeled ellipses (ellipse + inner text = 2 elements each)
- 2+ arrows, each with a nearby text label explaining the relationship
- 1 summary/insight rectangle at bottom (y~700) with inner text
- TOTAL: 15-20 elements minimum

COLOR GUIDE:
  Blue   (stroke #1971c2, bg #dbe4ff): Given / Input / Cause
  Green  (stroke #2f9e44, bg #d3f9d8): Result / Output / Effect
  Orange (stroke #e67700, bg #fff3bf): Key formula / Insight
  Purple (stroke #7048e8, bg #f3d9fa): Process / Mechanism
  Red    (stroke #c92a2a, bg #ffe3e3): Exception / Contrast

All element IDs must be globally unique (prefix with slide number: s1_, s2_, s3_, ... sN_).
"""



def _pick_groq_key(preferred_env_var: str) -> Optional[str]:
    """Return a Groq API key: try the numbered var first, then the generic one."""
    key = os.getenv(preferred_env_var) or os.getenv("GROQ_API_KEY")
    return key if key else None


def _call_groq(api_key: str, model: str, prompt: str) -> dict:
    """
    Call a Groq model with JSON-mode enforced.
    Returns parsed JSON dict.
    Raises on failure.
    """
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert technical educator and visual illustrator. "
                    "You always respond with pure JSON according to the given schema."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    raw = response.choices[0].message.content
    return json.loads(raw)


def _validate_lesson_plan(data: dict, topic: str) -> dict:
    """Validate/repair the JSON so it matches LessonPlan schema."""
    # Ensure topic is present
    if "topic" not in data or not data["topic"]:
        data["topic"] = topic

    # Ensure slides is a list of 2–8 slides
    slides = data.get("slides", [])
    if not isinstance(slides, list):
        raise ValueError("'slides' is not a list")
    if len(slides) == 0:
        raise ValueError("No slides were generated")
    if len(slides) > 8:
        logger.warning(f"LLM generated {len(slides)} slides (>8). Trimming to 8.")
        data["slides"] = slides[:8]

    # Validate via Pydantic (raises ValidationError on bad data)
    LessonPlan(**data)
    return data


# ─── Groq model definitions ──────────────────────────────────────────────────
GROQ_MODELS = [
    # (model_id, preferred_env_var_for_key)
    ("llama-3.3-70b-versatile",                  "GROQ_API_KEY_1"),
    ("llama-3.1-8b-instant",                     "GROQ_API_KEY_2"),
    ("meta-llama/llama-4-scout-17b-16e-instruct", "GROQ_API_KEY_3"),
]


# ─── Main Router ─────────────────────────────────────────────────────────────
class MultiLLMClient:
    """
    Unified LLM client with automatic failover.
    Tries Gemini first; falls back to Groq models one by one.
    """

    def __init__(self):
        # ── Gemini ──
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            logger.warning("GEMINI_API_KEY not set – Gemini will be skipped.")
        self.gemini_client = genai.Client(api_key=gemini_key) if gemini_key else None

        # ── Groq ──
        # Check that at least one Groq key is available
        any_groq = any(
            _pick_groq_key(env_var) for _, env_var in GROQ_MODELS
        )
        if not any_groq:
            logger.warning(
                "No Groq API key found. Set GROQ_API_KEY (or GROQ_API_KEY_1/2/3) "
                "in your .env file to enable Groq fallback."
            )

    # ── compress context (Gemini first, then Groq) ───────────────────────────
    def compress_context(self, topic: str, context: str) -> str:
        """Compress/summarise RAG context. Falls back gracefully."""
        prompt = (
            f"Extract ONLY the most relevant information.\n\n"
            f"Topic: {topic}\n\nContext:\n{context}\n\n"
            f"Return concise, useful content only."
        )

        # Try Gemini
        if self.gemini_client:
            try:
                resp = self.gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.2),
                )
                return resp.text.strip()
            except Exception as e:
                logger.warning(f"[compress_context] Gemini failed: {e}")

        # Try Groq models for compression
        for model_id, env_var in GROQ_MODELS:
            key = _pick_groq_key(env_var)
            if not key:
                continue
            try:
                client = Groq(api_key=key)
                resp = client.chat.completions.create(
                    model=model_id,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                logger.warning(f"[compress_context] Groq {model_id} failed: {e}")

        # All failed – return original context uncompressed
        logger.warning("[compress_context] All LLMs failed, using raw context.")
        return context

    # ── generate lesson (Gemini first, then Groq) ────────────────────────────
    def generate_lesson(self, prompt: str, topic: str) -> dict:
        """
        Generate a lesson plan JSON dict.
        Tries Gemini (structured output), then each Groq model.
        Returns validated JSON dict matching LessonPlan schema.
        Raises RuntimeError if all providers fail.
        """
        errors = []

        # ── 1. Try Gemini ──────────────────────────────────────────────────
        if self.gemini_client:
            try:
                logger.info("[LLM] Trying Gemini...")
                response = self.gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=LessonPlan,
                        temperature=0.7,
                    ),
                )
                data = json.loads(response.text)
                _validate_lesson_plan(data, topic)
                logger.info("[LLM] ✅ Gemini succeeded.")
                return data
            except Exception as e:
                msg = f"Gemini: {e}"
                logger.warning(f"[LLM] ⚠️ {msg} – trying Groq fallback...")
                errors.append(msg)

        # ── 2. Try Groq models one by one ─────────────────────────────────
        groq_prompt = prompt + "\n\n" + GROQ_JSON_SCHEMA
        for model_id, env_var in GROQ_MODELS:
            key = _pick_groq_key(env_var)
            if not key:
                logger.info(f"[LLM] Skipping Groq {model_id}: no API key.")
                continue
            try:
                logger.info(f"[LLM] Trying Groq {model_id}...")
                data = _call_groq(key, model_id, groq_prompt)
                _validate_lesson_plan(data, topic)
                logger.info(f"[LLM] ✅ Groq {model_id} succeeded.")
                return data
            except Exception as e:
                msg = f"Groq/{model_id}: {e}"
                logger.warning(f"[LLM] ⚠️ {msg}")
                errors.append(msg)

        # ── All failed ─────────────────────────────────────────────────────
        all_errors = " | ".join(errors)
        raise RuntimeError(
            f"All LLM providers failed. Errors: {all_errors}"
        )
