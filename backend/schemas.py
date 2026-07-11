# schemas.py
from pydantic import BaseModel, Field
from typing import List, Optional


# ─── Excalidraw elements ──────────────────────────────────────────────────────

class SceneElement(BaseModel):
    id: str
    type: str = Field(description="Must be 'rectangle', 'ellipse', 'text', or 'arrow'")
    x: float
    y: float
    strokeColor: str = Field(description="e.g. '#000000'")
    backgroundColor: str = Field(description="e.g. 'transparent'")
    fillStyle: str = Field(description="e.g. 'solid'")
    strokeWidth: int
    width: Optional[float] = None
    height: Optional[float] = None
    text: Optional[str] = None
    fontSize: Optional[int] = None
    points: Optional[List[List[float]]] = None


class Scene(BaseModel):
    elements: List[SceneElement] = Field(
        description="List of all shapes to draw on this specific slide"
    )


# ─── Lesson slides ────────────────────────────────────────────────────────────

class Slide(BaseModel):
    title: str = Field(description="Short title, e.g. 'Step 1: The Battery'")
    voiceover: str = Field(description="Script the tutor speaks for this slide.")
    scene: Scene = Field(description="Visual diagram for this slide.")
    equations: Optional[List[str]] = Field(
        default=None,
        description=(
            "Key equations shown on this slide. "
            "e.g. ['F = ma', 'p = mv']. Empty list [] if no equations."
        ),
    )


# ─── MCQ Questions ────────────────────────────────────────────────────────────

class Question(BaseModel):
    question: str = Field(description="The MCQ question text")
    options: List[str] = Field(
        description=(
            "Exactly 4 answer options, each prefixed: "
            "['A) ...', 'B) ...', 'C) ...', 'D) ...']"
        )
    )
    correct_answer: str = Field(
        description="Single letter: 'A', 'B', 'C', or 'D'"
    )
    explanation: str = Field(
        description="One-sentence explanation grounded in the textbook context"
    )


# ─── Full lesson plan ─────────────────────────────────────────────────────────

class LessonPlan(BaseModel):
    topic: str
    subject: Optional[str] = Field(
        default=None, description="e.g. 'Physics', 'Chemistry', 'Mathematics'"
    )
    grade_level: Optional[int] = Field(
        default=None, description="11 or 12"
    )
    slides: List[Slide] = Field(
        description=(
            "2-10 slides based on complexity. "
            "SIMPLE: 2-3, MEDIUM: 4-5, COMPLEX: 6-10."
        )
    )
    questions: Optional[List[Question]] = Field(
        default=None,
        description=(
            "Exactly 3 MCQ questions derived strictly from the textbook context. "
            "Each with 4 options (A/B/C/D) and a correct_answer letter."
        ),
    )


# ─── Doubt / Q&A ─────────────────────────────────────────────────────────────

class DoubtRequest(BaseModel):
    topic: str
    slide_title: str
    question: str
    rag_context: Optional[str] = None


class DoubtResponse(BaseModel):
    answer: str