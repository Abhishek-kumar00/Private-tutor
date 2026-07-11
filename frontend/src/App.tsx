import { useState, useEffect, useRef, useCallback } from "react";
import { Excalidraw, convertToExcalidrawElements } from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";

// ─── Types ────────────────────────────────────────────────────────────────────
type ExcalidrawAPI = {
  updateScene: (sceneData: { elements?: any[]; appState?: any; scrollToContent?: boolean }) => void;
};

interface Scene { elements: any[] }
interface Slide { title: string; voiceover: string; scene: Scene; equations?: string[] }

interface Question {
  question: string;
  options: string[];         // ["A) ...", "B) ...", "C) ...", "D) ..."]
  correct_answer: string;   // "A" | "B" | "C" | "D"
  explanation: string;
}

interface LessonPlan {
  topic: string;
  subject?: string;
  grade_level?: number;
  slides: Slide[];
  questions?: Question[];
}

type PdfStatus = "idle" | "uploading" | "ready" | "error";

interface ChatMessage {
  role: "user" | "ai";
  text: string;
}

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

  // Doubt Chat
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const chatBottomRef = useRef<HTMLDivElement>(null);

  // Quiz Panel
  const [quizOpen, setQuizOpen] = useState(false);
  const [quizAnswers, setQuizAnswers] = useState<Record<number, string>>({});
  const [quizSubmitted, setQuizSubmitted] = useState(false);
  const [quizScore, setQuizScore] = useState(0);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const isDraggingGlobal = dragCounter > 0;
  const isPdfExpanded = isHoveringPdf || isDraggingGlobal || pdfStatus === "uploading" || pdfStatus === "error";

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

  // Auto-scroll chat to bottom
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

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
  const handleDragEnter = (e: React.DragEvent) => { e.preventDefault(); setDragCounter(prev => prev + 1); };
  const handleDragLeave = (e: React.DragEvent) => { e.preventDefault(); setDragCounter(prev => Math.max(0, prev - 1)); };
  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); };
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
    setChatMessages([]);
    // Reset quiz state for new lesson
    setQuizAnswers({});
    setQuizSubmitted(false);
    setQuizScore(0);
    setQuizOpen(false);
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

  // ── Doubt Chat ───────────────────────────────────────────────────────────────
  const handleAskDoubt = async () => {
    const question = chatInput.trim();
    if (!question || chatLoading) return;
    setChatInput("");
    setChatMessages(prev => [...prev, { role: "user", text: question }]);
    setChatLoading(true);
    try {
      const currentSlide = lessonPlan?.slides[currentSlideIndex];
      const res = await fetch("http://127.0.0.1:8000/ask-doubt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: lessonPlan?.topic ?? topic,
          slide_title: currentSlide?.title ?? "General",
          question,
        }),
      });
      const data = await res.json();
      const answer = data.answer ?? "Sorry, I couldn't answer that right now.";
      setChatMessages(prev => [...prev, { role: "ai", text: answer }]);
      if (!isMuted) speak(answer);
    } catch {
      setChatMessages(prev => [...prev, { role: "ai", text: "Error connecting to tutor. Please try again." }]);
    } finally {
      setChatLoading(false);
    }
  };

  const currentSlide = lessonPlan?.slides[currentSlideIndex];
  const equations = currentSlide?.equations ?? [];

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDropGlobal}
      style={{ height: "100vh", width: "100vw", position: "relative", fontFamily: "Inter, system-ui, sans-serif" }}
    >

      {/* ── Query Panel (top-left) ── */}
      <div style={{
        position: "absolute",
        top: 12,
        left: 72,
        zIndex: 10,
        background: "white",
        padding: "6px 8px",
        borderRadius: 8,
        boxShadow: "0 2px 6px rgba(0,0,0,0.1)",
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

        {pdfStatus === "ready" && (
          <span style={{
            fontSize: 11, background: "#d3f9d8", color: "#2f9e44",
            padding: "3px 8px", borderRadius: 20, fontWeight: 600, whiteSpace: "nowrap",
          }}>
            📄 Loaded
          </span>
        )}
        {usedRag && (
          <span style={{
            fontSize: 11, background: "#e7f5ff", color: "#1971c2",
            padding: "3px 8px", borderRadius: 20, fontWeight: 600, whiteSpace: "nowrap",
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
          width: isPdfExpanded ? 240 : 130,
          transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
          overflow: "hidden",
        }}>
        <div style={{
          fontSize: 13, fontWeight: 700, color: "#343a40",
          display: "flex", alignItems: "center", justifyContent: isPdfExpanded ? "flex-start" : "center",
          gap: 6, marginBottom: isPdfExpanded ? 10 : 0, transition: "margin 0.3s ease",
        }}>
          <span>📑</span> {isPdfExpanded ? "Study PDF" : (pdfStatus === "ready" ? "PDF Ready" : "Upload PDF")}
        </div>

        <div style={{
          maxHeight: isPdfExpanded ? "500px" : "0px",
          opacity: isPdfExpanded ? 1 : 0,
          transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
          display: "flex", flexDirection: "column",
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
          {/* Voiceover + Equation box */}
          <div style={{
            background: "rgba(255,255,255,0.97)", padding: "16px 20px",
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

            <h3 style={{ margin: "0 0 6px 0", color: "#212529", fontSize: 16 }}>
              {currentSlide?.title}
            </h3>

            {/* Equation Strip */}
            {equations.length > 0 && (
              <div style={{
                display: "flex", flexWrap: "wrap", gap: 6,
                justifyContent: "center", margin: "6px 0 10px",
              }}>
                {equations.map((eq, i) => (
                  <code key={i} style={{
                    background: "#fff3bf", color: "#e67700",
                    border: "1px solid #ffd43b",
                    borderRadius: 6, padding: "3px 10px",
                    fontSize: 13, fontWeight: 700,
                    fontFamily: "'Courier New', monospace",
                    letterSpacing: "0.02em",
                    cursor: "default",
                  }}>
                    {eq}
                  </code>
                ))}
              </div>
            )}

            <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, color: "#495057" }}>
              {currentSlide?.voiceover}
            </p>
          </div>

          {/* Navigation + Progress dots */}
          <div style={{
            pointerEvents: "auto", display: "flex", gap: 16,
            alignItems: "center",
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

            {/* Progress dots */}
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              {lessonPlan.slides.map((_, i) => (
                <div
                  key={i}
                  onClick={() => setCurrentSlideIndex(i)}
                  title={lessonPlan.slides[i].title}
                  style={{
                    width: i === currentSlideIndex ? 12 : 8,
                    height: i === currentSlideIndex ? 12 : 8,
                    borderRadius: "50%",
                    flexShrink: 0,
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                    background:
                      i === currentSlideIndex
                        ? "#228be6"
                        : i < currentSlideIndex
                        ? "#74c0fc"
                        : "#dee2e6",
                    boxShadow: i === currentSlideIndex ? "0 0 0 3px rgba(34,139,230,0.25)" : "none",
                  }}
                />
              ))}
            </div>

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

      {/* ── Doubt Chat Toggle Button ── */}
      {lessonPlan && (
        <button
          id="doubt-chat-toggle"
          onClick={() => {
            setChatOpen(o => !o);
            setQuizOpen(false);  // close quiz if open
          }}
          title="Ask the tutor a question"
          style={{
            position: "absolute",
            bottom: 24,
            right: 20,
            zIndex: 20,
            width: 52,
            height: 52,
            borderRadius: "50%",
            border: "none",
            background: chatOpen ? "#e03131" : "#228be6",
            color: "white",
            fontSize: 22,
            cursor: "pointer",
            boxShadow: "0 4px 16px rgba(0,0,0,0.2)",
            transition: "background 0.2s, transform 0.15s",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            transform: chatOpen ? "rotate(45deg)" : "rotate(0deg)",
          }}
        >
          {chatOpen ? "✕" : "💬"}
        </button>
      )}

      {/* ── Doubt Chat Floating Panel ── */}
      {lessonPlan && chatOpen && (
        <div
          id="doubt-chat-panel"
          style={{
            position: "absolute",
            bottom: 86,
            right: 20,
            zIndex: 20,
            width: 350,
            height: 440,
            background: "white",
            borderRadius: 16,
            boxShadow: "0 8px 40px rgba(0,0,0,0.18)",
            border: "1px solid #e9ecef",
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            animation: "slideUp 0.2s ease",
          }}
        >
          {/* Panel header */}
          <div style={{
            padding: "12px 16px",
            background: "linear-gradient(135deg, #228be6, #339af0)",
            color: "white",
          }}>
            <div style={{ fontWeight: 700, fontSize: 15 }}>💬 Ask the Tutor</div>
            <div style={{
              fontSize: 11, marginTop: 2, opacity: 0.85,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              📍 {currentSlide?.title ?? "Current slide"}
            </div>
          </div>

          {/* Messages area */}
          <div style={{
            flex: 1,
            overflowY: "auto",
            padding: "12px",
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}>
            {chatMessages.length === 0 && (
              <div style={{
                textAlign: "center", color: "#adb5bd",
                fontSize: 13, marginTop: 40, lineHeight: 1.6,
              }}>
                <div style={{ fontSize: 32, marginBottom: 8 }}>🎓</div>
                Ask any question about this slide<br />or the topic in general!
              </div>
            )}

            {chatMessages.map((msg, i) => (
              <div key={i} style={{
                display: "flex",
                justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
              }}>
                <div style={{
                  maxWidth: "82%",
                  padding: "8px 12px",
                  borderRadius: msg.role === "user" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                  background: msg.role === "user" ? "#228be6" : "#f1f3f5",
                  color: msg.role === "user" ? "white" : "#212529",
                  fontSize: 13,
                  lineHeight: 1.55,
                  boxShadow: "0 1px 3px rgba(0,0,0,0.07)",
                }}>
                  {msg.role === "ai" && (
                    <span style={{ fontSize: 11, fontWeight: 700, color: "#868e96", display: "block", marginBottom: 3 }}>
                      🎓 Tutor
                    </span>
                  )}
                  {msg.text}
                </div>
              </div>
            ))}

            {chatLoading && (
              <div style={{ display: "flex", justifyContent: "flex-start" }}>
                <div style={{
                  padding: "8px 14px", borderRadius: "16px 16px 16px 4px",
                  background: "#f1f3f5", color: "#868e96", fontSize: 13,
                }}>
                  <span style={{ animation: "pulse 1.2s infinite" }}>🎓 Thinking…</span>
                </div>
              </div>
            )}
            <div ref={chatBottomRef} />
          </div>

          {/* Input area */}
          <div style={{
            padding: "10px 12px",
            borderTop: "1px solid #e9ecef",
            display: "flex",
            gap: 8,
            background: "#f8f9fa",
          }}>
            <input
              id="doubt-input"
              type="text"
              placeholder="Type your question…"
              value={chatInput}
              onChange={e => setChatInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleAskDoubt()}
              disabled={chatLoading}
              style={{
                flex: 1,
                padding: "8px 12px",
                border: "1px solid #dee2e6",
                borderRadius: 20,
                fontSize: 13,
                outline: "none",
                background: "white",
              }}
            />
            <button
              id="doubt-send-btn"
              onClick={handleAskDoubt}
              disabled={chatLoading || !chatInput.trim()}
              style={{
                padding: "8px 14px",
                background: chatLoading || !chatInput.trim() ? "#ced4da" : "#228be6",
                color: "white",
                border: "none",
                borderRadius: 20,
                cursor: chatLoading || !chatInput.trim() ? "not-allowed" : "pointer",
                fontWeight: 700,
                fontSize: 13,
                transition: "background 0.2s",
              }}
            >
              Send
            </button>
          </div>
        </div>
      )}

      {/* Slide-up animation */}
      <style>{`
        @keyframes slideUp {
          from { opacity: 0; transform: translateY(16px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.4; }
        }
        @keyframes quizPop {
          from { opacity: 0; transform: translateY(20px) scale(0.97); }
          to   { opacity: 1; transform: translateY(0) scale(1); }
        }
      `}</style>

      {/* ── Quiz Toggle Button ── */}
      {lessonPlan?.questions && lessonPlan.questions.length > 0 && (
        <button
          id="quiz-toggle-btn"
          onClick={() => {
            setQuizOpen(o => !o);
            setChatOpen(false);   // close chat if open
          }}
          title="Take the lesson quiz"
          style={{
            position: "absolute",
            bottom: 86,
            right: 20,
            zIndex: 20,
            width: 52,
            height: 52,
            borderRadius: "50%",
            border: "none",
            background: quizOpen ? "#e03131" : "#7048e8",
            color: "white",
            fontSize: 22,
            cursor: "pointer",
            boxShadow: "0 4px 16px rgba(0,0,0,0.2)",
            transition: "background 0.2s, transform 0.15s",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            transform: quizOpen ? "rotate(45deg)" : "rotate(0deg)",
          }}
        >
          {quizOpen ? "✕" : "📝"}
        </button>
      )}

      {/* ── Quiz Floating Panel ── */}
      {lessonPlan?.questions && quizOpen && (() => {
        const questions = lessonPlan.questions!;
        const handleSelect = (qi: number, letter: string) => {
          if (quizSubmitted) return;
          setQuizAnswers(prev => ({ ...prev, [qi]: letter }));
        };
        const handleSubmit = () => {
          const score = questions.reduce((acc, q, i) => {
            return acc + (quizAnswers[i] === q.correct_answer ? 1 : 0);
          }, 0);
          setQuizScore(score);
          setQuizSubmitted(true);
        };
        const handleReset = () => {
          setQuizAnswers({});
          setQuizSubmitted(false);
          setQuizScore(0);
        };
        const allAnswered = questions.every((_, i) => quizAnswers[i] !== undefined);

        return (
          <div
            id="quiz-panel"
            style={{
              position: "absolute",
              bottom: 148,
              right: 20,
              zIndex: 20,
              width: 380,
              maxHeight: 520,
              background: "white",
              borderRadius: 18,
              boxShadow: "0 8px 40px rgba(0,0,0,0.18)",
              border: "1px solid #e9ecef",
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
              animation: "quizPop 0.25s ease",
            }}
          >
            {/* Header */}
            <div style={{
              padding: "12px 16px",
              background: "linear-gradient(135deg, #7048e8, #9775fa)",
              color: "white",
            }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>📝 Quick Quiz</div>
              <div style={{ fontSize: 11, marginTop: 2, opacity: 0.9 }}>
                {lessonPlan.topic} — {questions.length} Questions
              </div>
            </div>

            {/* Score banner (after submit) */}
            {quizSubmitted && (
              <div style={{
                padding: "10px 16px",
                background: quizScore === questions.length ? "#d3f9d8" : quizScore >= 2 ? "#fff3bf" : "#ffe3e3",
                borderBottom: "1px solid #e9ecef",
                display: "flex", alignItems: "center", justifyContent: "space-between",
              }}>
                <span style={{ fontWeight: 700, fontSize: 15 }}>
                  {quizScore === questions.length
                    ? "🎉 Perfect score!"
                    : quizScore >= 2
                    ? "👍 Good effort!"
                    : "📚 Keep practising!"}
                  {" "}{quizScore}/{questions.length} correct
                </span>
                <button
                  onClick={handleReset}
                  style={{
                    padding: "4px 12px", fontSize: 12, border: "none",
                    borderRadius: 12, cursor: "pointer",
                    background: "#7048e8", color: "white", fontWeight: 600,
                  }}
                >Retry</button>
              </div>
            )}

            {/* Questions list */}
            <div style={{ flex: 1, overflowY: "auto", padding: "12px 14px", display: "flex", flexDirection: "column", gap: 18 }}>
              {questions.map((q, qi) => {
                const userAnswer  = quizAnswers[qi];
                const isCorrect   = userAnswer === q.correct_answer;
                const optionLetters = ["A", "B", "C", "D"];

                return (
                  <div key={qi}>
                    <p style={{ margin: "0 0 8px", fontWeight: 600, fontSize: 13, color: "#212529", lineHeight: 1.45 }}>
                      <span style={{ color: "#7048e8", marginRight: 4 }}>Q{qi + 1}.</span>
                      {q.question}
                    </p>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {q.options.map((opt, oi) => {
                        const letter = optionLetters[oi];
                        const isSelected = userAnswer === letter;
                        const isRight    = quizSubmitted && letter === q.correct_answer;
                        const isWrong    = quizSubmitted && isSelected && !isCorrect;

                        return (
                          <button
                            key={oi}
                            onClick={() => handleSelect(qi, letter)}
                            style={{
                              padding: "7px 12px",
                              border: `2px solid ${
                                isRight  ? "#2f9e44"
                                : isWrong ? "#e03131"
                                : isSelected ? "#7048e8"
                                : "#dee2e6"
                              }`,
                              borderRadius: 10,
                              background: isRight  ? "#d3f9d8"
                                        : isWrong  ? "#ffe3e3"
                                        : isSelected ? "#f3d9fa"
                                        : "#f8f9fa",
                              cursor: quizSubmitted ? "default" : "pointer",
                              fontSize: 13,
                              textAlign: "left",
                              color: "#212529",
                              fontWeight: isSelected || isRight ? 600 : 400,
                              transition: "all 0.15s",
                            }}
                          >
                            {opt}
                            {isRight && " ✓"}
                            {isWrong && " ✗"}
                          </button>
                        );
                      })}
                    </div>
                    {/* Explanation (shown after submit) */}
                    {quizSubmitted && (
                      <p style={{
                        margin: "8px 0 0", fontSize: 12, lineHeight: 1.5,
                        color: "#495057",
                        background: "#f1f3f5",
                        padding: "6px 10px",
                        borderRadius: 8,
                        borderLeft: `3px solid ${isCorrect ? "#2f9e44" : "#e67700"}`,
                      }}>
                        💡 {q.explanation}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Submit button */}
            {!quizSubmitted && (
              <div style={{ padding: "10px 14px", borderTop: "1px solid #e9ecef", background: "#f8f9fa" }}>
                <button
                  id="quiz-submit-btn"
                  onClick={handleSubmit}
                  disabled={!allAnswered}
                  style={{
                    width: "100%", padding: "10px",
                    background: allAnswered ? "#7048e8" : "#ced4da",
                    color: "white", border: "none",
                    borderRadius: 12, fontWeight: 700, fontSize: 14,
                    cursor: allAnswered ? "pointer" : "not-allowed",
                    transition: "background 0.2s",
                  }}
                >
                  {allAnswered ? "Submit Answers" : `Answer all ${questions.length} questions to submit`}
                </button>
              </div>
            )}
          </div>
        );
      })()}

      {/* ── Excalidraw Canvas ── */}
      <Excalidraw excalidrawAPI={(api) => setExcalidrawAPI(api as any)} />
    </div>
  );
}

export default App;