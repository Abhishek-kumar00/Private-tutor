import { useState, useEffect, useRef, useCallback } from "react";
import { Excalidraw, convertToExcalidrawElements } from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";

// ─── Types ────────────────────────────────────────────────────────────────────
type ExcalidrawAPI = {
  updateScene: (sceneData: { elements?: any[]; appState?: any; scrollToContent?: boolean }) => void;
};

interface Scene { elements: any[] }
interface Slide { title: string; voiceover: string; scene: Scene }
interface LessonPlan { topic: string; slides: Slide[] }

type PdfStatus = "idle" | "uploading" | "ready" | "error";

// ─── App ──────────────────────────────────────────────────────────────────────
function App() {
  const [excalidrawAPI, setExcalidrawAPI] = useState<ExcalidrawAPI | null>(null);
  const [topic, setTopic] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [lessonPlan, setLessonPlan] = useState<LessonPlan | null>(null);
  const [currentSlideIndex, setCurrentSlideIndex] = useState(0);
  const [usedRag, setUsedRag] = useState(false);

  // TTS
  const [isMuted, setIsMuted] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);

  // PDF & Drag States
  const [pdfStatus, setPdfStatus] = useState<PdfStatus>("idle");
  const [pdfName, setPdfName] = useState<string | null>(null);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [isHoveringPdf, setIsHoveringPdf] = useState(false);
  const [dragCounter, setDragCounter] = useState(0);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const isDraggingGlobal = dragCounter > 0;
  const isPdfExpanded = isHoveringPdf || isDraggingGlobal;

  // ── TTS helpers ─────────────────────────────────────────────────────────────
  const speak = (text: string) => {
    if (isMuted) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.onstart = () => setIsSpeaking(true);
    utterance.onend = () => setIsSpeaking(false);
    utterance.onerror = () => setIsSpeaking(false);
    window.speechSynthesis.speak(utterance);
  };

  useEffect(() => () => { window.speechSynthesis.cancel(); }, []);

  useEffect(() => {
    if (lessonPlan?.slides[currentSlideIndex]) {
      const slide = lessonPlan.slides[currentSlideIndex];
      if (excalidrawAPI) {
        const sanitized = slide.scene.elements.map((el: any) => {
          const clean = { ...el };
          Object.keys(clean).forEach(k => { if (clean[k] === null) delete clean[k]; });
          return clean;
        });
        excalidrawAPI.updateScene({
          elements: convertToExcalidrawElements(sanitized),
          appState: { viewBackgroundColor: "#ffffff" },
          scrollToContent: true,
        });
      }
      setTimeout(() => speak(slide.voiceover), 500);
    }
  }, [currentSlideIndex, lessonPlan, excalidrawAPI, isMuted]);

  useEffect(() => {
    if (isMuted) { window.speechSynthesis.cancel(); setIsSpeaking(false); }
  }, [isMuted]);

  // ── PDF upload ───────────────────────────────────────────────────────────────
  const uploadPdf = useCallback(async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setPdfError("Only PDF files are accepted.");
      setPdfStatus("error");
      return;
    }
    setPdfStatus("uploading");
    setPdfError(null);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch("http://127.0.0.1:8000/upload-pdf", {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Upload failed");
      }
      setPdfName(file.name);
      setPdfStatus("ready");
    } catch (e: any) {
      setPdfError(e.message ?? "Upload failed");
      setPdfStatus("error");
    }
  }, []);

  const clearPdf = async () => {
    await fetch("http://127.0.0.1:8000/clear-pdf", { method: "DELETE" });
    setPdfStatus("idle");
    setPdfName(null);
    setPdfError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // Global Drag Events
  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    setDragCounter(prev => prev + 1);
  };
  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setDragCounter(prev => Math.max(0, prev - 1));
  };
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };
  const handleDropGlobal = (e: React.DragEvent) => {
    e.preventDefault();
    setDragCounter(0);
    const file = e.dataTransfer.files?.[0];
    if (file) uploadPdf(file);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadPdf(file);
  };

  // ── Lesson generation ────────────────────────────────────────────────────────
  const handleAskTutor = async () => {
    if (!excalidrawAPI || !topic) return;
    setIsLoading(true);
    setLessonPlan(null);
    setCurrentSlideIndex(0);
    setUsedRag(false);
    window.speechSynthesis.cancel();
    try {
      const res = await fetch("http://127.0.0.1:8000/generate-lesson", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.lesson_plan) {
        setLessonPlan(data.lesson_plan);
        setUsedRag(!!data.used_rag);
      } else {
        alert("Unexpected response from backend: " + JSON.stringify(data));
      }
    } catch (err) {
      console.error(err);
      alert("Error connecting to backend. Is it running?");
    } finally {
      setIsLoading(false);
    }
  };

  const handleNextSlide = () => {
    if (lessonPlan && currentSlideIndex < lessonPlan.slides.length - 1)
      setCurrentSlideIndex(i => i + 1);
  };
  const handlePrevSlide = () => {
    if (currentSlideIndex > 0) setCurrentSlideIndex(i => i - 1);
  };
  const handleReplayAudio = () => {
    if (lessonPlan) speak(lessonPlan.slides[currentSlideIndex].voiceover);
  };

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDropGlobal}
      style={{ height: "100vh", width: "100vw", position: "relative", fontFamily: "Inter, system-ui, sans-serif" }}
    >

      {/* ── Query Panel (top-left, aligned with Excalidraw toolbar) ── */}
      <div style={{
        position: "absolute",
        top: 12, // Aligns vertically with the center Excalidraw toolbar
        left: 72, // Clears the Excalidraw hamburger menu perfectly
        zIndex: 10,
        background: "white",
        padding: "6px 8px", // Slimmer padding to match native tools
        borderRadius: 8,
        boxShadow: "0 2px 6px rgba(0,0,0,0.1)", // Subtler shadow to match Excalidraw
        display: "flex", gap: 8, alignItems: "center",
      }}>
        <input
          id="topic-input"
          type="text"
          placeholder="What do you want to learn?"
          value={topic}
          onChange={e => setTopic(e.target.value)}
          onKeyDown={e => e.key === "Enter" && handleAskTutor()}
          style={{
            padding: "8px 12px", width: 220, borderRadius: 6,
            border: "1px solid #e9ecef", outline: "none",
            fontSize: 14, background: "#f8f9fa",
          }}
        />
        <button
          id="teach-me-btn"
          onClick={handleAskTutor}
          disabled={isLoading || !topic}
          style={{
            padding: "8px 16px", cursor: isLoading ? "not-allowed" : "pointer",
            background: isLoading ? "#ced4da" : "#40c057",
            color: "white", border: "none", borderRadius: 6,
            fontWeight: 600, fontSize: 14, whiteSpace: "nowrap",
            transition: "background 0.2s",
          }}
        >
          {isLoading ? "Thinking…" : "Teach Me"}
        </button>

        {/* RAG badge */}
        {pdfStatus === "ready" && (
          <span style={{
            fontSize: 11, background: "#d3f9d8", color: "#2f9e44",
            padding: "3px 8px", borderRadius: 20, fontWeight: 600,
            whiteSpace: "nowrap", // Prevents wrapping if space gets tight
          }}>
            📄 Loaded
          </span>
        )}
        {usedRag && (
          <span style={{
            fontSize: 11, background: "#e7f5ff", color: "#1971c2",
            padding: "3px 8px", borderRadius: 20, fontWeight: 600,
            whiteSpace: "nowrap",
          }}>
            🔍 RAG
          </span>
        )}
      </div>

      {/* ── PDF Upload Panel (top-right, Collapsible) ── */}
      <div
        onMouseEnter={() => setIsHoveringPdf(true)}
        onMouseLeave={() => setIsHoveringPdf(false)}
        style={{
          position: "absolute", top: 80, right: 16, zIndex: 10,
          background: "white", padding: isPdfExpanded ? "14px 16px" : "10px 16px",
          borderRadius: 12,
          boxShadow: "0 4px 20px rgba(0,0,0,0.12)",
          width: isPdfExpanded ? 240 : 130, // Slightly narrower when collapsed to stay neat
          transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
          overflow: "hidden",
        }}>
        {/* Header - Always visible */}
        <div style={{
          fontSize: 13, fontWeight: 700, color: "#343a40",
          display: "flex", alignItems: "center", justifyContent: isPdfExpanded ? "flex-start" : "center",
          gap: 6, marginBottom: isPdfExpanded ? 10 : 0, transition: "margin 0.3s ease"
        }}>
          <span>📑</span> {isPdfExpanded ? "Study PDF" : (pdfStatus === "ready" ? "PDF Ready" : "Upload PDF")}
        </div>

        {/* Expandable Content */}
        <div style={{
          maxHeight: isPdfExpanded ? "500px" : "0px",
          opacity: isPdfExpanded ? 1 : 0,
          transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
          display: "flex", flexDirection: "column"
        }}>
          <div
            id="pdf-clickzone"
            onClick={() => fileInputRef.current?.click()}
            style={{
              border: `2px dashed ${isDraggingGlobal ? "#339af0" : pdfStatus === "ready" ? "#2f9e44" : "#ced4da"}`,
              borderRadius: 10,
              padding: "18px 10px",
              textAlign: "center",
              cursor: "pointer",
              background: isDraggingGlobal ? "#e7f5ff" : pdfStatus === "ready" ? "#ebfbee" : "#f8f9fa",
              transition: "all 0.2s",
            }}
          >
            {pdfStatus === "idle" && (
              <>
                <div style={{ fontSize: 28, marginBottom: 6 }}>📂</div>
                <div style={{ fontSize: 12, color: "#868e96" }}>
                  Drag & drop a PDF<br />or <span style={{ color: "#339af0", textDecoration: "underline" }}>browse</span>
                </div>
              </>
            )}
            {pdfStatus === "uploading" && (
              <>
                <div style={{ fontSize: 28, marginBottom: 6 }}>⏳</div>
                <div style={{ fontSize: 12, color: "#f08c00", fontWeight: 600 }}>Ingesting PDF…</div>
              </>
            )}
            {pdfStatus === "ready" && (
              <>
                <div style={{ fontSize: 28, marginBottom: 6 }}>✅</div>
                <div style={{ fontSize: 12, color: "#2f9e44", fontWeight: 600, wordBreak: "break-word" }}>
                  {pdfName}
                </div>
              </>
            )}
            {pdfStatus === "error" && (
              <>
                <div style={{ fontSize: 28, marginBottom: 6 }}>❌</div>
                <div style={{ fontSize: 12, color: "#e03131", fontWeight: 600 }}>
                  {pdfError ?? "Upload failed"}<br />
                  <span style={{ color: "#339af0", textDecoration: "underline" }}>Try again</span>
                </div>
              </>
            )}
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            style={{ display: "none" }}
            onChange={handleFileChange}
          />

          {/* Clear button */}
          {(pdfStatus === "ready" || pdfStatus === "error") && (
            <button
              id="clear-pdf-btn"
              onClick={clearPdf}
              style={{
                marginTop: 8, width: "100%",
                padding: "6px", fontSize: 12, cursor: "pointer",
                background: "none", border: "1px solid #dee2e6",
                borderRadius: 6, color: "#868e96",
              }}
            >
              🗑 Remove PDF
            </button>
          )}

          <div style={{ marginTop: 8, fontSize: 11, color: "#adb5bd", textAlign: "center" }}>
            The AI will cite your document when answering.
          </div>
        </div>
      </div>

      {/* ── Slide Controls + Voiceover (bottom-center) ── */}
      {lessonPlan && (
        <div style={{
          position: "absolute", bottom: 20, left: "50%",
          transform: "translateX(-50%)", zIndex: 10,
          display: "flex", flexDirection: "column", gap: 10,
          alignItems: "center", width: "62%", pointerEvents: "none",
        }}>
          {/* Voiceover box */}
          <div style={{
            background: "rgba(255,255,255,0.97)", padding: "20px 24px",
            borderRadius: 14, boxShadow: "0 4px 24px rgba(0,0,0,0.13)",
            width: "100%", textAlign: "center", pointerEvents: "auto",
            border: "1px solid #e9ecef", position: "relative",
          }}>
            {/* Audio controls */}
            <div style={{ position: "absolute", top: 10, right: 10, display: "flex", gap: 5 }}>
              <button
                onClick={() => setIsMuted(m => !m)}
                style={{
                  background: "none", border: "1px solid #dee2e6", borderRadius: 4,
                  cursor: "pointer", fontSize: 12, padding: "2px 6px",
                  color: isMuted ? "#e03131" : "#2f9e44",
                }}
              >
                {isMuted ? "🔇 Unmute" : "🔊 Mute"}
              </button>
              <button
                onClick={handleReplayAudio}
                disabled={isMuted || isSpeaking}
                style={{
                  background: "none", border: "1px solid #dee2e6", borderRadius: 4,
                  cursor: "pointer", fontSize: 12, padding: "2px 6px",
                  opacity: isMuted || isSpeaking ? 0.4 : 1,
                }}
              >
                🔄 Replay
              </button>
            </div>

            <h3 style={{ margin: "0 0 10px 0", color: "#212529", fontSize: 16 }}>
              {lessonPlan.slides[currentSlideIndex].title}
            </h3>
            <p style={{ margin: 0, fontSize: 15, lineHeight: 1.6, color: "#495057" }}>
              {lessonPlan.slides[currentSlideIndex].voiceover}
            </p>
          </div>

          {/* Navigation buttons */}
          <div style={{
            pointerEvents: "auto", display: "flex", gap: 20,
            background: "white", padding: "10px 24px", borderRadius: 30,
            boxShadow: "0 2px 12px rgba(0,0,0,0.1)",
          }}>
            <button
              id="prev-slide-btn"
              onClick={handlePrevSlide}
              disabled={currentSlideIndex === 0}
              style={{
                padding: "8px 22px", border: "none", borderRadius: 20, fontWeight: 700,
                cursor: currentSlideIndex === 0 ? "not-allowed" : "pointer",
                background: currentSlideIndex === 0 ? "#e9ecef" : "#228be6",
                color: currentSlideIndex === 0 ? "#adb5bd" : "white",
              }}
            >
              ← Prev
            </button>
            <span style={{ display: "flex", alignItems: "center", fontWeight: 700, color: "#868e96", fontSize: 14 }}>
              {currentSlideIndex + 1} / {lessonPlan.slides.length}
            </span>
            <button
              id="next-slide-btn"
              onClick={handleNextSlide}
              disabled={currentSlideIndex === lessonPlan.slides.length - 1}
              style={{
                padding: "8px 22px", border: "none", borderRadius: 20, fontWeight: 700,
                cursor: currentSlideIndex === lessonPlan.slides.length - 1 ? "not-allowed" : "pointer",
                background: currentSlideIndex === lessonPlan.slides.length - 1 ? "#e9ecef" : "#228be6",
                color: currentSlideIndex === lessonPlan.slides.length - 1 ? "#adb5bd" : "white",
              }}
            >
              Next →
            </button>
          </div>
        </div>
      )}

      {/* ── Excalidraw Canvas ── */}
      <Excalidraw excalidrawAPI={(api) => setExcalidrawAPI(api as any)} />
    </div>
  );
}

export default App;