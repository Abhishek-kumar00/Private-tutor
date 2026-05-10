# schemas.py
from pydantic import BaseModel, Field
from typing import List, Optional

class SceneElement(BaseModel):
    id: str
    type: str = Field(description="Must be 'rectangle', 'ellipse', 'text', or 'arrow'")
    x: float
    y: float
    strokeColor: str = Field(description="e.g. '#000000'")
    backgroundColor: str = Field(description="e.g. 'transparent'")
    fillStyle: str = Field(description="e.g. 'solid'")
    strokeWidth: int
    # Specific fields based on type – all optional with defaults
    width: Optional[float] = None
    height: Optional[float] = None
    text: Optional[str] = None
    fontSize: Optional[int] = None
    points: Optional[List[List[float]]] = None


class Scene(BaseModel):
    elements: List[SceneElement] = Field(
        description="List of all shapes to draw on this specific slide"
    )

class Slide(BaseModel):
    title: str = Field(description="Short title of this slide, e.g., 'Step 1: The Battery'")
    voiceover: str = Field(description="The script the tutor speaks for this slide.")
    scene: Scene = Field(description="The visual diagram for this slide.")

class LessonPlan(BaseModel):
    topic: str
    slides: List[Slide] = Field(
        description="A list of 2–8 slides (dynamically chosen based on topic complexity) representing the progression of the lesson."
    )