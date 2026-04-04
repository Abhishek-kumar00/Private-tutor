import os
import instructor
import google.generativeai as genai
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

client = instructor.from_gemini(
    client=genai.GenerativeModel(
        model_name="gemini-1.5-flash",
    ),
    mode=instructor.Mode.GEMINI_JSON,
)

print("Client type:", type(client))
print("Client dir:", dir(client))

try:
    class User(BaseModel):
        name: str
        age: int

    resp = client.messages.create(
        messages=[{"role": "user", "content": "Extract: Jason is 25."}],
        response_model=User,
    )
    print("Messages create success:", resp)
except Exception as e:
    print("Messages create failed:", e)

try:
    resp = client.chat.completions.create(
        messages=[{"role": "user", "content": "Extract: Jason is 25."}],
        response_model=User,
    )
    print("Chat completions success:", resp)
except Exception as e:
    print("Chat completions failed:", e)
