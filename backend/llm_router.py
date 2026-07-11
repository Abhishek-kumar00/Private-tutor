# llm_router.py
"""
Multi-LLM Router — Production Grade
====================================
Priority order:
  1. HuggingFace Inference API  (primary — free tier)
       a. Qwen/Qwen2.5-72B-Instruct
       b. mistralai/Mistral-7B-Instruct-v0.3
  2. Gemini Flash               (fallback 1 — free tier)
  3. Groq                       (fallback 2 — free tier)
       a. llama-3.3-70b-versatile
       b. llama-3.1-8b-instant
       c. meta-llama/llama-4-scout-17b-16e-instruct
"""

import os
import json
import re
import time
import logging
from typing import Optional

from huggingface_hub import InferenceClient
from google import genai
from google.genai import types
from groq import Groq

from schemas import LessonPlan

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# MODEL LISTS
# ─────────────────────────────────────────────────────────────────────────────
HF_MODELS = [
    "Qwen/Qwen2.5-72B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
]

GROQ_MODELS = [
    ("llama-3.3-70b-versatile",                    "GROQ_API_KEY_1"),
    ("llama-3.1-8b-instant",                       "GROQ_API_KEY_2"),
    ("meta-llama/llama-4-scout-17b-16e-instruct",  "GROQ_API_KEY_3"),
]


# ─────────────────────────────────────────────────────────────────────────────
# JSON SCHEMA HINT  (injected into HF + Groq prompts)
# ─────────────────────────────────────────────────────────────────────────────
JSON_SCHEMA_HINT = """
OUTPUT FORMAT: Respond with ONLY valid JSON. No markdown fences. No explanation. Pure JSON.

CRITICAL RULES:
1. Every rectangle/ellipse MUST have a text element inside (text x = shape_x+10, text y = shape_y+height/2-10)
2. Text content must be SPECIFIC — GOOD: "F=ma","9.8 m/s²","Step 1: Evaporation"  BAD: "Concept","Box"
3. Each slide: AT LEAST 18 elements, spread across the full 1000×800 canvas
4. Title text (fontSize 22) at top-center of every slide
5. SPATIAL DIAGRAM: If topic has a known layout (Water Cycle, Solar System, Cell, Atom…), one slide must
   recreate the actual spatial layout using positioned shapes — NOT just flow boxes.

EQUATION RULES (mandatory for quantitative topics):
- Every formula slide needs a standalone orange text element at fontSize 22+:
    {"id":"s1_eq1","type":"text","x":260,"y":80,"strokeColor":"#e67700","backgroundColor":"transparent",
     "fillStyle":"solid","strokeWidth":1,"width":480,"height":44,"text":"F = ma [Force=Mass×Acceleration]","fontSize":22,"points":null}
- DERIVATION slides: numbered purple rects (Step 1 → Step 2 → Step 3) connected by arrows
- Always include units: "g = 9.8 m/s²", "c = 3×10⁸ m/s"
- "equations" array: list all formulas for the slide, or [] if none

QUESTIONS RULES (mandatory — generate EXACTLY 3):
- Derive all questions strictly from the textbook context provided
- Each question has exactly 4 options: ["A) ...", "B) ...", "C) ...", "D) ..."]
- correct_answer is a single letter: "A", "B", "C", or "D"
- explanation is one sentence citing the textbook concept

JSON STRUCTURE:
{
  "topic": "string",
  "subject": "Physics|Chemistry|Mathematics|null",
  "grade_level": 11|12|null,
  "slides": [
    {
      "title": "string",
      "voiceover": "4-5 sentence explanation with specific facts, equations, real numbers",
      "equations": ["F = ma", "p = mv"],
      "scene": {
        "elements": [
          {"id":"s1_title","type":"text","x":280,"y":20,"strokeColor":"#212529","backgroundColor":"transparent","fillStyle":"solid","strokeWidth":1,"width":440,"height":40,"text":"FULL TOPIC: Key Formula","fontSize":22,"points":null},
          {"id":"s1_eq1","type":"text","x":260,"y":75,"strokeColor":"#e67700","backgroundColor":"transparent","fillStyle":"solid","strokeWidth":1,"width":480,"height":44,"text":"F = ma  [Newton's 2nd Law]","fontSize":22,"points":null},
          {"id":"s1_box1","type":"rectangle","x":50,"y":140,"strokeColor":"#1971c2","backgroundColor":"#dbe4ff","fillStyle":"solid","strokeWidth":2,"width":210,"height":90,"text":null,"fontSize":null,"points":null},
          {"id":"s1_box1_lbl","type":"text","x":60,"y":170,"strokeColor":"#1971c2","backgroundColor":"transparent","fillStyle":"solid","strokeWidth":1,"width":190,"height":30,"text":"Specific Label Here","fontSize":14,"points":null},
          {"id":"s1_arr1","type":"arrow","x":265,"y":185,"strokeColor":"#000000","backgroundColor":"transparent","fillStyle":"solid","strokeWidth":2,"width":null,"height":null,"text":null,"fontSize":null,"points":[[0,0],[140,0]]},
          {"id":"s1_arr1_lbl","type":"text","x":295,"y":165,"strokeColor":"#495057","backgroundColor":"transparent","fillStyle":"solid","strokeWidth":1,"width":80,"height":20,"text":"causes","fontSize":12,"points":null},
          {"id":"s1_el1","type":"ellipse","x":450,"y":340,"strokeColor":"#2f9e44","backgroundColor":"#d3f9d8","fillStyle":"solid","strokeWidth":2,"width":160,"height":80,"text":null,"fontSize":null,"points":null},
          {"id":"s1_el1_lbl","type":"text","x":460,"y":370,"strokeColor":"#2f9e44","backgroundColor":"transparent","fillStyle":"solid","strokeWidth":1,"width":140,"height":20,"text":"Result: Specific Fact","fontSize":13,"points":null},
          {"id":"s1_summary","type":"rectangle","x":100,"y":700,"strokeColor":"#e67700","backgroundColor":"#fff3bf","fillStyle":"solid","strokeWidth":2,"width":800,"height":60,"text":null,"fontSize":null,"points":null},
          {"id":"s1_summary_lbl","type":"text","x":110,"y":720,"strokeColor":"#e67700","backgroundColor":"transparent","fillStyle":"solid","strokeWidth":1,"width":780,"height":30,"text":"KEY INSIGHT: Most important takeaway","fontSize":15,"points":null}
        ]
      }
    }
  ],
  "questions": [
    {
      "question": "What does Newton's Second Law state?",
      "options": ["A) F = ma", "B) F = mv", "C) F = m²a", "D) F = ma²"],
      "correct_answer": "A",
      "explanation": "Newton's Second Law states that net force equals mass times acceleration (F = ma)."
    },
    { "question": "...", "options": ["A) ...","B) ...","C) ...","D) ..."], "correct_answer": "B", "explanation": "..." },
    { "question": "...", "options": ["A) ...","B) ...","C) ...","D) ..."], "correct_answer": "C", "explanation": "..." }
  ]
}

MANDATORY PER SLIDE:
- 1 title (fontSize 22, top center)
- 1+ equation text (fontSize 22+, orange) IF topic has formulas
- 4+ labeled rectangles (rect + inner text = 2 elements each)
- 2+ labeled ellipses (ellipse + inner text = 2 elements each)
- 2+ arrows each with a nearby text label
- 1 summary rect at y~700
- TOTAL: 18-22 elements
- "equations" array on every slide

COLOR GUIDE:
  Blue   (#1971c2 / #dbe4ff): Input / Cause / Given
  Green  (#2f9e44 / #d3f9d8): Output / Effect / Result
  Orange (#e67700 / #fff3bf): Formula / Key Insight
  Purple (#7048e8 / #f3d9fa): Process / Derivation step
  Red    (#c92a2a / #ffe3e3): Warning / Exception

Slide IDs must be unique, prefixed by slide number: s1_, s2_, … sN_
Slide count: SIMPLE=2-3, MEDIUM=4-5, COMPLEX=6-10
"""

DOUBT_SYSTEM = (
    "You are an expert PCM (Physics, Chemistry, Mathematics) teacher for Class 11 & 12. "
    "Answer student questions clearly with encouragement, using specific numbers, "
    "equations, and real-world examples where relevant."
)


# ─────────────────────────────────────────────────────────────────────────────
# JSON EXTRACTION UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """
    Robustly extract a JSON object from LLM output that may contain
    markdown fences, preamble text, or partial wrapping.
    """
    text = text.strip()

    # Strategy 1: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Strip markdown code fences
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Strategy 3: Find the outermost JSON object by brace matching
    depth, start = 0, -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    start = -1  # reset and try next

    raise ValueError(f"No valid JSON found. First 300 chars: {text[:300]}")


# ─────────────────────────────────────────────────────────────────────────────
# KEY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _pick_groq_key(preferred_env_var: str) -> Optional[str]:
    key = os.getenv(preferred_env_var) or os.getenv("GROQ_API_KEY")
    return key if key else None


def _validate_lesson_plan(data: dict, topic: str) -> dict:
    """Validate/repair the JSON so it matches the LessonPlan schema."""
    if "topic" not in data or not data["topic"]:
        data["topic"] = topic

    slides = data.get("slides", [])
    if not isinstance(slides, list) or len(slides) == 0:
        raise ValueError("'slides' is missing or empty")
    if len(slides) > 10:
        logger.warning("LLM produced %d slides (>10). Trimming.", len(slides))
        data["slides"] = slides[:10]

    # Ensure questions is a list if present
    if "questions" in data and data["questions"] is not None:
        qs = data["questions"]
        if not isinstance(qs, list):
            data["questions"] = None
        elif len(qs) > 3:
            data["questions"] = qs[:3]

    LessonPlan(**data)   # raises ValidationError on bad data
    return data


# ─────────────────────────────────────────────────────────────────────────────
# PROVIDER CALL WRAPPERS
# ─────────────────────────────────────────────────────────────────────────────

def _call_hf(token: str, model: str, system: str, user_prompt: str, max_tokens: int = 8192) -> dict:
    """Call HuggingFace Inference API (Chat Completions) and extract JSON."""
    client = InferenceClient(token=token)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.7,
    )
    raw = response.choices[0].message.content
    return _extract_json(raw)


def _call_hf_text(token: str, model: str, prompt: str, max_tokens: int = 512) -> str:
    """Call HuggingFace for a plain-text (non-JSON) response."""
    client = InferenceClient(token=token)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": DOUBT_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


def _call_groq(api_key: str, model: str, system: str, user_prompt: str) -> dict:
    """Call Groq with JSON mode enforced."""
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    return json.loads(response.choices[0].message.content)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ROUTER
# ─────────────────────────────────────────────────────────────────────────────

class MultiLLMClient:
    """
    Unified LLM client with automatic failover.
    Priority: HuggingFace → Gemini → Groq
    """

    def __init__(self):
        self.hf_token    = os.getenv("HF_TOKEN")
        gemini_key       = os.getenv("GEMINI_API_KEY")
        self.gemini      = genai.Client(api_key=gemini_key) if gemini_key else None

        if not self.hf_token:
            logger.warning("HF_TOKEN not set — HuggingFace will be skipped.")
        if not self.gemini:
            logger.warning("GEMINI_API_KEY not set — Gemini will be skipped.")

    # ── Lesson generation ──────────────────────────────────────────────────────

    def generate_lesson(self, prompt: str, topic: str) -> dict:
        """
        Generate a lesson plan JSON dict.
        HuggingFace → Gemini → Groq, returns validated LessonPlan dict.
        Raises RuntimeError if all providers fail.
        """
        system_msg = (
            "You are an expert Class 11/12 PCM teacher and visual illustrator. "
            "You always respond with pure JSON according to the given schema. "
            "Ground ALL facts in the provided textbook context."
        )
        full_prompt = prompt + "\n\n" + JSON_SCHEMA_HINT
        errors: list[str] = []

        # ── 1. HuggingFace ────────────────────────────────────────────────────
        if self.hf_token:
            for model in HF_MODELS:
                try:
                    logger.info("[LLM] Trying HuggingFace %s …", model)
                    data = _call_hf(self.hf_token, model, system_msg, full_prompt)
                    _validate_lesson_plan(data, topic)
                    logger.info("[LLM] HuggingFace %s succeeded.", model)
                    return data
                except Exception as exc:
                    msg = f"HF/{model}: {exc}"
                    logger.warning("[LLM] %s", msg)
                    errors.append(msg)
                    time.sleep(1)  # brief pause before retrying / next provider

        # ── 2. Gemini ─────────────────────────────────────────────────────────
        if self.gemini:
            try:
                logger.info("[LLM] Trying Gemini …")
                response = self.gemini.models.generate_content(
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
                logger.info("[LLM] Gemini succeeded.")
                return data
            except Exception as exc:
                msg = f"Gemini: {exc}"
                logger.warning("[LLM] %s — trying Groq …", msg)
                errors.append(msg)

        # ── 3. Groq ───────────────────────────────────────────────────────────
        groq_system = system_msg
        for model_id, env_var in GROQ_MODELS:
            key = _pick_groq_key(env_var)
            if not key:
                continue
            try:
                logger.info("[LLM] Trying Groq %s …", model_id)
                data = _call_groq(key, model_id, groq_system, full_prompt)
                _validate_lesson_plan(data, topic)
                logger.info("[LLM] Groq %s succeeded.", model_id)
                return data
            except Exception as exc:
                msg = f"Groq/{model_id}: {exc}"
                logger.warning("[LLM] %s", msg)
                errors.append(msg)

        raise RuntimeError("All LLM providers failed. Errors: " + " | ".join(errors))

    # ── Context compression ────────────────────────────────────────────────────

    def compress_context(self, topic: str, context: str) -> str:
        """Summarise RAG context to the most relevant excerpts."""
        compress_prompt = (
            f"Extract ONLY the most relevant information for the topic: '{topic}'.\n\n"
            f"Context:\n{context}\n\n"
            "Return concise, factual content only. Keep equations and numbers intact."
        )

        # HF
        if self.hf_token:
            for model in HF_MODELS:
                try:
                    client = InferenceClient(token=self.hf_token)
                    resp = client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": compress_prompt}],
                        max_tokens=1024,
                        temperature=0.2,
                    )
                    return resp.choices[0].message.content.strip()
                except Exception as exc:
                    logger.warning("[compress] HF/%s failed: %s", model, exc)

        # Gemini
        if self.gemini:
            try:
                resp = self.gemini.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=compress_prompt,
                    config=types.GenerateContentConfig(temperature=0.2),
                )
                return resp.text.strip()
            except Exception as exc:
                logger.warning("[compress] Gemini failed: %s", exc)

        return context  # fallback: return raw

    # ── Doubt answering ────────────────────────────────────────────────────────

    def answer_doubt(
        self,
        topic: str,
        slide_title: str,
        question: str,
        context: str = "",
    ) -> str:
        """
        Answer a student's in-lesson doubt, teacher style.
        Returns 2-4 sentence plain-text answer.
        """
        prompt_parts = [
            f"Topic being taught: '{topic}'",
            f"Current slide: '{slide_title}'",
        ]
        if context:
            prompt_parts.append(f"\nRelevant textbook context:\n{context}")
        prompt_parts.append(
            f"\nStudent's question: {question}\n\n"
            "Answer in 2-4 sentences as a knowledgeable teacher. "
            "Start with brief encouragement, then give a clear specific answer. "
            "Include the relevant equation or numerical value if applicable."
        )
        doubt_prompt = "\n".join(prompt_parts)

        # HF
        if self.hf_token:
            for model in HF_MODELS:
                try:
                    return _call_hf_text(self.hf_token, model, doubt_prompt)
                except Exception as exc:
                    logger.warning("[doubt] HF/%s failed: %s", model, exc)

        # Gemini
        if self.gemini:
            try:
                resp = self.gemini.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=doubt_prompt,
                    config=types.GenerateContentConfig(temperature=0.7),
                )
                return resp.text.strip()
            except Exception as exc:
                logger.warning("[doubt] Gemini failed: %s", exc)

        # Groq
        for model_id, env_var in GROQ_MODELS:
            key = _pick_groq_key(env_var)
            if not key:
                continue
            try:
                client = Groq(api_key=key)
                resp = client.chat.completions.create(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": DOUBT_SYSTEM},
                        {"role": "user",   "content": doubt_prompt},
                    ],
                    temperature=0.7,
                    max_tokens=350,
                )
                return resp.choices[0].message.content.strip()
            except Exception as exc:
                logger.warning("[doubt] Groq/%s failed: %s", model_id, exc)

        return "I'm having trouble connecting right now. Please try again!"
