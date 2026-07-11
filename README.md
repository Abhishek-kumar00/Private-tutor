# Private Tutor — Setup & Usage Guide

## 🚀 Quick Start (First Time)

### Step 1 — Install Python dependencies
```powershell
cd backend
pip install -r requirements.txt
```

### Step 2 — Download NCERT textbooks
```powershell
cd backend
python download_ncert.py
```
This downloads Class 11 & 12 Physics, Chemistry, and Mathematics PDFs from ncert.nic.in
into `textbooks/physics_11/`, `textbooks/chemistry_12/`, etc.

> If any download fails (NCERT site may block automation), manually download from  
> **https://ncert.nic.in/textbook.php** and place PDFs in the matching folder.

### Step 3 — Ingest textbooks into ChromaDB
```powershell
cd backend
python ingest.py
```
This builds the persistent knowledge base at `backend/chroma_db/ncert/`.
Only run this once (or when you add new PDFs).

> To rebuild from scratch:  `python ingest.py --reset`

### Step 4 — Start the backend server
```powershell
cd backend
uvicorn main:app --reload
```

### Step 5 — Start the frontend
```powershell
cd frontend
npm run dev
```

Open **http://localhost:5173** in your browser.

---

## 📁 Project Structure

```
Private-tutor/
├── backend/
│   ├── main.py            # FastAPI server
│   ├── rag.py             # LangChain RAG (NCERTStore + UserStore)
│   ├── llm_router.py      # HuggingFace → Gemini → Groq fallback
│   ├── schemas.py         # Pydantic models
│   ├── ingest.py          # 🆕 Offline ingestion pipeline
│   ├── download_ncert.py  # 🆕 NCERT PDF downloader
│   ├── requirements.txt   # 🆕 Full dependency list
│   ├── .env               # API keys (HF_TOKEN, GEMINI_API_KEY, GROQ_API_KEY)
│   ├── chroma_db/
│   │   ├── ncert/         # 🆕 Persistent NCERT knowledge base
│   │   └── user/          # User-uploaded PDF store
│   └── textbooks/
│       ├── physics_11/    # NCERT Class 11 Physics PDFs
│       ├── physics_12/    # NCERT Class 12 Physics PDFs
│       ├── chemistry_11/
│       ├── chemistry_12/
│       ├── mathematics_11/
│       └── mathematics_12/
└── frontend/
    └── src/
        └── App.tsx         # 🆕 + MCQ Quiz panel
```

---

## 🔑 API Keys (.env)

| Variable | Where to get it | Used for |
|----------|----------------|---------|
| `HF_TOKEN` | huggingface.co/settings/tokens | Primary LLM (free) |
| `GEMINI_API_KEY` | aistudio.google.com | Fallback LLM (free) |
| `GROQ_API_KEY` | console.groq.com | Fallback LLM (free) |

---

## 🧠 LLM Priority Chain

```
1. HuggingFace Inference API  ← Primary (your HF_TOKEN)
   a. Qwen/Qwen2.5-72B-Instruct
   b. mistralai/Mistral-7B-Instruct-v0.3

2. Gemini Flash               ← Fallback 1 (free tier)

3. Groq                       ← Fallback 2 (free tier)
   a. llama-3.3-70b-versatile
   b. llama-3.1-8b-instant
   c. llama-4-scout-17b-16e-instruct
```

---

## 🌐 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Liveness check |
| `/rag-status` | GET | NCERT + user PDF status |
| `/generate-lesson` | POST | Generate lesson with MCQs |
| `/ask-doubt` | POST | Answer student question |
| `/upload-pdf` | POST | Upload supplementary PDF |
| `/clear-pdf` | DELETE | Remove user PDF |

### `/generate-lesson` request body:
```json
{
  "topic": "Newton's Laws of Motion",
  "subject": "Physics",
  "grade_level": 11
}
```

---

## 🎓 Features

- **RAG-grounded lessons** — All content grounded in NCERT textbooks
- **Visual diagrams** — Excalidraw blackboard-style illustrations
- **Interactive quiz** — 3 MCQs per lesson with instant feedback
- **Doubt chat** — Ask questions mid-lesson, answered by the AI tutor
- **Equation strip** — Key formulas displayed below each slide
- **Slide navigation** — Clickable progress dots
- **PDF upload** — Upload your own notes/books for extra context

---

## 🔄 Adding New PDFs

1. Place PDF(s) in the appropriate `textbooks/{subject}_{grade}/` folder
2. Run `python ingest.py` again (it will add new chunks without duplicating)
3. Restart the backend server

---

## 🛠️ Troubleshooting

**"No textbook data found"** → Run `python download_ncert.py` then `python ingest.py`

**HuggingFace timeout** → The free tier rate-limits after ~10 requests/hour.
The system auto-falls back to Gemini → Groq.

**ChromaDB error on first start** → Normal — NCERT store opens as empty until `ingest.py` is run.
The server still works using LLM knowledge as fallback.
