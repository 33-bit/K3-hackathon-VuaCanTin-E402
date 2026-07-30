import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  AtSign,
  Check,
  ChevronDown,
  FileText,
  FolderOpen,
  Highlighter,
  Library,
  LoaderCircle,
  Maximize2,
  Menu,
  MessageSquareText,
  MoreHorizontal,
  Paperclip,
  Pencil,
  Plus,
  Search,
  Send,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { baseSlides, starterMessages } from "./mockData";

const API_BASE = import.meta.env.VITE_API_BASE || "";

function LogoMark() {
  return <span className="logo-mark">F</span>;
}

function SlideContent({ slide, compact = false }) {
  return (
    <div className={`slide-design slide-${slide.type} ${compact ? "is-compact" : ""}`}>
      <div className="slide-kicker">{slide.eyebrow}</div>
      <h2>{slide.title}</h2>
      {slide.subtitle && <p className="slide-subtitle">{slide.subtitle}</p>}
      {slide.body && <p className="slide-body">{slide.body}</p>}

      {slide.type === "cover" && (
        <div className="cover-orbit" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      )}

      {slide.note && <blockquote>{slide.note}</blockquote>}

      {slide.stats && (
        <div className="capacity-grid">
          {slide.stats.map(([lead, label]) => (
            <div key={lead}>
              <strong>{lead}</strong>
              <span>{label}</span>
            </div>
          ))}
        </div>
      )}

      {slide.type === "process" && (
        <div className="process-row">
          {slide.steps.map((step, index) => (
            <div className="process-step" key={step}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <b>{step}</b>
            </div>
          ))}
        </div>
      )}

      {slide.chart && (
        <div className="chart-area" aria-label="Retrieval strength increases over practice sessions">
          <div className="chart-bars">
            {slide.chart.map((value, index) => (
              <div className="bar-wrap" key={value}>
                <span className="bar-value">{value}%</span>
                <div className="bar" style={{ height: `${value}%` }} />
                <small>{index + 1}</small>
              </div>
            ))}
          </div>
          <div className="chart-caption">RECALL STRENGTH · PRACTICE SESSION</div>
        </div>
      )}

      {slide.type === "loop" && (
        <div className="study-loop">
          {slide.steps.map((step, index) => (
            <div key={step}>
              <span>{index + 1}</span>
              <b>{step}</b>
            </div>
          ))}
        </div>
      )}

      <div className="slide-number">{String(slide.number).padStart(2, "0")}</div>
    </div>
  );
}

function UploadModal({ onClose, onUpload }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);

  const acceptFile = (file) => {
    if (file) onUpload(file);
  };

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="modal upload-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <button className="icon-button modal-close" onClick={onClose} aria-label="Close upload dialog"><X size={18} /></button>
        <div className="modal-eyebrow">ADD MATERIAL</div>
        <h2>Upload a slide deck</h2>
        <p>Bring in a PDF or PowerPoint. This prototype will create a mock preview without parsing the file.</p>
        <button
          className={`drop-zone ${dragging ? "is-dragging" : ""}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            acceptFile(event.dataTransfer.files?.[0]);
          }}
        >
          <span className="upload-icon"><Upload size={22} /></span>
          <strong>Drop a file here</strong>
          <span>or click to browse · PDF, PPT, PPTX</span>
        </button>
        <input ref={inputRef} type="file" accept=".pdf,.ppt,.pptx" hidden onChange={(event) => acceptFile(event.target.files?.[0])} />
        <div className="privacy-note"><Check size={14} /> Prototype mode—files are not stored.</div>
      </div>
    </div>
  );
}

function DeckMenu({ decks, currentDeckId, onSelect, onUpload, onRename, onDelete, onClose }) {
  return (
    <div className="deck-menu">
      <div className="deck-menu-header">
        <span>YOUR MATERIALS</span>
        <button className="icon-button tiny" onClick={onClose}><X size={14} /></button>
      </div>
      <div className="deck-list">
        {decks.map((deck) => (
          <button className={`deck-item ${deck.id === currentDeckId ? "active" : ""}`} key={deck.id} onClick={() => onSelect(deck.id)}>
            <span className="deck-file"><FileText size={17} /></span>
            <span className="deck-copy"><b>{deck.name}</b><small>{deck.slides.length} slides · {deck.updated}</small></span>
            {deck.id === currentDeckId && <Check size={15} />}
            <span className="deck-actions">
              <span role="button" tabIndex={0} aria-label="Rename deck" onClick={(event) => { event.stopPropagation(); onRename(deck.id); }}><Pencil size={13} /></span>
              {decks.length > 1 && <span role="button" tabIndex={0} aria-label="Delete deck" onClick={(event) => { event.stopPropagation(); onDelete(deck.id); }}><Trash2 size={13} /></span>}
            </span>
          </button>
        ))}
      </div>
      <button className="menu-upload" onClick={onUpload}><Plus size={16} /> Add slide deck</button>
    </div>
  );
}

function MentionMenu({ slideCount, onInsert, onClose }) {
  const [rangeMode, setRangeMode] = useState(false);
  const [from, setFrom] = useState(1);
  const [to, setTo] = useState(Math.min(5, slideCount));

  if (rangeMode) {
    return (
      <div className="mention-menu range-menu">
        <div className="mention-heading"><span>Select a slide range</span><button onClick={onClose}><X size={14} /></button></div>
        <div className="range-fields">
          <label>FROM<select value={from} onChange={(event) => { const value = Number(event.target.value); setFrom(value); if (value > to) setTo(value); }}>{Array.from({ length: slideCount }, (_, i) => <option key={i + 1}>{i + 1}</option>)}</select></label>
          <span>to</span>
          <label>TO<select value={to} onChange={(event) => setTo(Number(event.target.value))}>{Array.from({ length: slideCount - from + 1 }, (_, i) => <option key={i + from}>{i + from}</option>)}</select></label>
        </div>
        <button className="insert-range" onClick={() => onInsert(`@${from}–@${to}`)}>Reference slides {from}–{to}</button>
      </div>
    );
  }

  return (
    <div className="mention-menu">
      <div className="mention-heading"><span>REFERENCE A SLIDE</span><kbd>@</kbd></div>
      <button className="range-option" onClick={() => setRangeMode(true)}><span><Library size={16} /></span><div><b>Select a range</b><small>Ask across multiple slides</small></div><ArrowRight size={14} /></button>
      <div className="mention-slides">
        {Array.from({ length: slideCount }, (_, i) => i + 1).map((n) => (
          <button key={n} onClick={() => onInsert(`@${n}`)}><span>{n}</span> Slide {n}</button>
        ))}
      </div>
    </div>
  );
}

function ChatMessage({ message, onCitation, onSuggestion }) {
  return (
    <div className={`message ${message.role}`}>
      {message.role === "assistant" && <div className="assistant-avatar"><Sparkles size={14} /></div>}
      <div className="message-content">
        {message.quote && <div className="message-quote">“{message.quote}”</div>}
        <p>{message.text}</p>
        {message.citations?.length > 0 && (
          <div className="citation-row">
            {message.citations.map((citation) => (
              <button key={citation.slide} onClick={() => onCitation(citation.slide)}><FileText size={12} /> {citation.label}</button>
            ))}
          </div>
        )}
        {message.suggestions && (
          <div className="suggestion-list">
            {message.suggestions.map((suggestion) => <button key={suggestion} onClick={() => onSuggestion(suggestion)}>{suggestion}<ArrowRight size={13} /></button>)}
          </div>
        )}
        {message.role === "assistant" && !message.suggestions && <div className="mock-label">Mock response · no AI connected</div>}
      </div>
    </div>
  );
}

function App() {
  const [decks, setDecks] = useState([{ id: "learning-memory", name: "Learning that lasts", slides: baseSlides, updated: "Just now" }]);
  const [currentDeckId, setCurrentDeckId] = useState("learning-memory");
  const [activeSlide, setActiveSlide] = useState(1);
  const [messages, setMessages] = useState(starterMessages);
  const [draft, setDraft] = useState("");
  const [selectedText, setSelectedText] = useState("");
  const [selectionMenu, setSelectionMenu] = useState(null);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [deckMenuOpen, setDeckMenuOpen] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const composerRef = useRef(null);
  const messagesRef = useRef(null);

  const currentDeck = useMemo(() => decks.find((deck) => deck.id === currentDeckId) || decks[0], [decks, currentDeckId]);
  const slide = currentDeck.slides[activeSlide - 1];

  useEffect(() => {
    const node = messagesRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, isSending]);

  useEffect(() => {
    const onKeyDown = (event) => {
      if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
      if (event.key === "ArrowRight") setActiveSlide((n) => Math.min(currentDeck.slides.length, n + 1));
      if (event.key === "ArrowLeft") setActiveSlide((n) => Math.max(1, n - 1));
      if (event.key === "Escape") setIsFullscreen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [currentDeck.slides.length]);

  const handleSelection = (event) => {
    const stage = event.currentTarget;
    const { clientX, clientY } = event;
    window.setTimeout(() => {
      const selection = window.getSelection();
      const text = selection?.toString().trim();
      if (text && text.length > 2 && stage.contains(selection.anchorNode)) {
        setSelectionMenu({ x: Math.min(clientX, window.innerWidth - 220), y: Math.max(72, clientY - 48), text });
      } else {
        setSelectionMenu(null);
      }
    }, 0);
  };

  const attachSelection = () => {
    setSelectedText(selectionMenu.text);
    setSelectionMenu(null);
    window.getSelection()?.removeAllRanges();
    composerRef.current?.focus();
  };

  const insertReference = (reference) => {
    setDraft((value) => {
      const stripped = value.replace(/@[^\s]*$/, "").trimEnd();
      return `${stripped}${stripped ? " " : ""}${reference} `;
    });
    setMentionOpen(false);
    composerRef.current?.focus();
  };

  const parseReferences = (value) => {
    const ranges = [...value.matchAll(/@(\d+)(?:\s*(?:–|-|to)\s*@?(\d+))?/gi)];
    return ranges.map((match) => ({ start: Number(match[1]), end: Number(match[2] || match[1]) }));
  };

  const sendMessage = async (forcedText) => {
    const text = (forcedText || draft).trim();
    if (!text || isSending) return;
    const quote = selectedText;
    const references = parseReferences(text);
    const userMessage = { id: crypto.randomUUID(), role: "user", text, quote };
    setMessages((items) => [...items, userMessage]);
    setDraft("");
    setSelectedText("");
    setMentionOpen(false);
    setIsSending(true);

    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, deck_id: currentDeck.id, references, selected_text: quote || null }),
      });
      if (!response.ok) throw new Error("Mock API unavailable");
      const data = await response.json();
      setMessages((items) => [...items, { id: crypto.randomUUID(), role: "assistant", text: data.answer, citations: data.citations }]);
    } catch {
      await new Promise((resolve) => window.setTimeout(resolve, 550));
      const fallback = quote
        ? "The selected passage is about the limit of active attention. In simpler terms: new information becomes easier to learn when you group related details and connect them to something you already know."
        : "Across the referenced slides, the idea develops from limited attention, to meaningful chunking, to active retrieval. The study strategy is: reduce load, organize the idea, then practise recalling it without looking.";
      const cited = references.length ? Array.from({ length: references[0].end - references[0].start + 1 }, (_, i) => references[0].start + i).slice(0, 4) : [activeSlide];
      setMessages((items) => [...items, { id: crypto.randomUUID(), role: "assistant", text: fallback, citations: cited.map((n) => ({ slide: n, label: `Slide ${n}` })) }]);
    } finally {
      setIsSending(false);
    }
  };

  const uploadDeck = async (file) => {
    const valid = /\.(pdf|ppt|pptx)$/i.test(file.name);
    if (!valid) return;
    const newDeck = { id: `deck-${Date.now()}`, name: file.name.replace(/\.[^.]+$/, ""), slides: baseSlides.map((item) => ({ ...item })), updated: "Just now" };
    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: formData });
      if (response.ok) {
        const data = await response.json();
        newDeck.id = data.deck_id;
        newDeck.name = data.name;
      }
    } catch {
      // UI remains intentionally useful when the mock backend is not running.
    }
    setDecks((items) => [...items, newDeck]);
    setCurrentDeckId(newDeck.id);
    setActiveSlide(1);
    setUploadOpen(false);
  };

  const renameDeck = (id) => {
    const deck = decks.find((item) => item.id === id);
    const name = window.prompt("Rename slide deck", deck?.name || "");
    if (name?.trim()) setDecks((items) => items.map((item) => item.id === id ? { ...item, name: name.trim() } : item));
  };

  const deleteDeck = (id) => {
    setDecks((items) => items.filter((item) => item.id !== id));
    if (id === currentDeckId) {
      const next = decks.find((item) => item.id !== id);
      if (next) setCurrentDeckId(next.id);
    }
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand"><LogoMark /><span>Folio</span></div>
        <div className="deck-switcher-wrap">
          <button className="deck-switcher" onClick={() => setDeckMenuOpen((open) => !open)}>
            <span><b>{currentDeck.name}</b><small>{currentDeck.slides.length} slides</small></span><ChevronDown size={16} />
          </button>
          {deckMenuOpen && <DeckMenu decks={decks} currentDeckId={currentDeckId} onSelect={(id) => { setCurrentDeckId(id); setActiveSlide(1); setDeckMenuOpen(false); }} onUpload={() => { setDeckMenuOpen(false); setUploadOpen(true); }} onRename={renameDeck} onDelete={deleteDeck} onClose={() => setDeckMenuOpen(false)} />}
        </div>
        <div className="top-actions">
          <button className="quiet-button" onClick={() => setUploadOpen(true)}><Upload size={15} /> Upload</button>
          <button className="avatar-button" aria-label="Account menu">HK</button>
        </div>
      </header>

      <main className="workspace">
        <section className={`slide-workspace ${isFullscreen ? "is-fullscreen" : ""}`}>
          <aside className="thumbnail-rail">
            <div className="rail-title"><span>SLIDES</span><button className="icon-button tiny" onClick={() => setUploadOpen(true)} aria-label="Add deck"><Plus size={14} /></button></div>
            <div className="thumbnail-list">
              {currentDeck.slides.map((item) => (
                <button key={item.number} className={`thumbnail ${activeSlide === item.number ? "active" : ""}`} onClick={() => setActiveSlide(item.number)} aria-label={`Open slide ${item.number}`}>
                  <span className="thumb-number">{item.number}</span>
                  <div className="thumb-canvas"><SlideContent slide={item} compact /></div>
                </button>
              ))}
            </div>
          </aside>

          <div className="stage-column">
            <div className="stage-toolbar">
              <div className="slide-position"><span>Slide {activeSlide}</span><span className="divider-dot">·</span><span>{currentDeck.slides.length}</span></div>
              <div className="stage-actions">
                <button className="icon-button" onClick={() => setActiveSlide((n) => Math.max(1, n - 1))} disabled={activeSlide === 1} aria-label="Previous slide"><ArrowLeft size={16} /></button>
                <button className="icon-button" onClick={() => setActiveSlide((n) => Math.min(currentDeck.slides.length, n + 1))} disabled={activeSlide === currentDeck.slides.length} aria-label="Next slide"><ArrowRight size={16} /></button>
                <span className="toolbar-separator" />
                <button className="icon-button" onClick={() => setIsFullscreen((value) => !value)} aria-label="Toggle slide focus"><Maximize2 size={16} /></button>
                <button className="icon-button" aria-label="More options"><MoreHorizontal size={17} /></button>
              </div>
            </div>

            <div className="slide-stage" onMouseUp={handleSelection}>
              <div className="slide-canvas"><SlideContent slide={slide} /></div>
              <div className="selection-hint"><Highlighter size={13} /> Select any text to ask the tutor</div>
            </div>
          </div>
        </section>

        <section className="chat-panel">
          <div className="chat-header">
            <div><span className="tutor-symbol"><Sparkles size={15} /></span><span><b>Tutor</b><small>Grounded in this deck</small></span></div>
            <button className="icon-button" aria-label="Chat options"><MoreHorizontal size={18} /></button>
          </div>

          <div className="messages" ref={messagesRef}>
            <div className="context-banner"><FileText size={14} /><span>Using <b>{currentDeck.name}</b></span><span>{currentDeck.slides.length} slides</span></div>
            {messages.map((message) => <ChatMessage key={message.id} message={message} onCitation={(n) => setActiveSlide(Math.min(currentDeck.slides.length, n))} onSuggestion={sendMessage} />)}
            {isSending && <div className="message assistant typing"><div className="assistant-avatar"><Sparkles size={14} /></div><div className="typing-dots"><span /><span /><span /></div></div>}
          </div>

          <div className="composer-area">
            {selectedText && (
              <div className="selection-attachment"><div><Highlighter size={14} /><span><b>Selected from slide {activeSlide}</b><small>“{selectedText}”</small></span></div><button onClick={() => setSelectedText("")}><X size={14} /></button></div>
            )}
            <div className="composer-wrap">
              {mentionOpen && <MentionMenu slideCount={currentDeck.slides.length} onInsert={insertReference} onClose={() => setMentionOpen(false)} />}
              <textarea
                ref={composerRef}
                value={draft}
                rows={2}
                placeholder="Ask about these slides…"
                onChange={(event) => {
                  setDraft(event.target.value);
                  setMentionOpen(/@[^\s]*$/.test(event.target.value));
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); }
                }}
              />
              <div className="composer-tools">
                <div>
                  <button className="tool-button" onClick={() => setMentionOpen((open) => !open)} title="Reference slides"><AtSign size={16} /></button>
                  <button className="tool-button" onClick={() => setUploadOpen(true)} title="Attach a deck"><Paperclip size={16} /></button>
                </div>
                <button className="send-button" disabled={!draft.trim() || isSending} onClick={() => sendMessage()} aria-label="Send message"><Send size={16} /></button>
              </div>
            </div>
            <div className="composer-footnote"><span>Type <kbd>@</kbd> to reference slides</span><span>Mock tutor · answers may be inaccurate</span></div>
          </div>
        </section>
      </main>

      {selectionMenu && <button className="selection-menu" style={{ left: selectionMenu.x, top: selectionMenu.y }} onClick={attachSelection}><MessageSquareText size={15} /> Ask about selection</button>}
      {uploadOpen && <UploadModal onClose={() => setUploadOpen(false)} onUpload={uploadDeck} />}
    </div>
  );
}

export default App;
