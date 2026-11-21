import React, { useEffect, useRef, useState } from "react";

const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

// A new session starts on every page load.
const newSessionId = () => "s-" + Math.random().toString(36).slice(2, 10);

function describeError(status, body) {
  if (status === 503) return "All AI providers are unavailable right now. Please try again shortly.";
  if (status === 422) {
    const d = body && body.detail;
    const text = Array.isArray(d) ? d.map((e) => e.msg).join("; ") : typeof d === "string" ? d : "";
    return "Invalid request" + (text ? ": " + text : ".");
  }
  if (body && typeof body.detail === "string") return body.detail;
  return `Something went wrong (HTTP ${status}).`;
}

export default function App() {
  const [sessionId] = useState(newSessionId);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [simulate, setSimulate] = useState("");
  const [loading, setLoading] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: text }]);
    setLoading(true);
    try {
      const payload = { session_id: sessionId, message: text };
      if (systemPrompt.trim()) payload.system_prompt = systemPrompt.trim();
      const headers = { "Content-Type": "application/json" };
      if (simulate.trim()) headers["X-Simulate-Failure"] = simulate.trim();
      const res = await fetch(`${API_URL}/chat`, { method: "POST", headers, body: JSON.stringify(payload) });
      let body = null;
      try {
        body = await res.json();
      } catch (_) {}
      if (res.ok && body && body.reply) {
        setMessages((m) => [...m, { role: "assistant", content: body.reply, meta: body.metadata }]);
      } else {
        setMessages((m) => [...m, { role: "error", content: describeError(res.status, body) }]);
      }
    } catch (_) {
      setMessages((m) => [...m, { role: "error", content: "Cannot reach the server. Check your connection." }]);
    } finally {
      setLoading(false);
    }
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="app">
      <header>
        <h1>Lyftr Chat</h1>
        <span className="sid">session {sessionId}</span>
      </header>

      <details className="settings">
        <summary>Settings</summary>
        <label>
          System prompt (optional)
          <textarea
            data-testid="system-prompt-input"
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            rows={2}
            placeholder="e.g. You are a pirate."
          />
        </label>
        <label>
          Simulate failure header (demo only)
          <input value={simulate} onChange={(e) => setSimulate(e.target.value)} placeholder="key_1=429  or  *=429" />
        </label>
      </details>

      <main className="chat">
        {messages.length === 0 && <p className="empty">Say something to start the conversation.</p>}
        {messages.map((m, i) => {
          if (m.role === "user") return <div key={i} className="bubble user">{m.content}</div>;
          if (m.role === "error")
            return (
              <div key={i} className="bubble error" role="alert">
                {m.content}
              </div>
            );
          const x = m.meta;
          return (
            <div key={i} className="bubble assistant" data-testid="assistant-message">
              <div className="text">{m.content}</div>
              <div className="meta">
                <span className={"chip " + (x.resolution_source === "LLM_CACHE" ? "cache" : "live")}>
                  <b>Source:</b> <span data-testid="meta-source">{x.resolution_source}</span>
                </span>
                <span className="chip">
                  <b>Model:</b> <span data-testid="meta-model">{x.model}</span>
                </span>
                <span className="chip">
                  <b>Latency:</b> <span data-testid="meta-latency">{x.latency_ms} ms</span>
                </span>
                <span className="chip">
                  <b>In:</b> <span data-testid="meta-input-tokens">{x.input_tokens}</span>
                </span>
                <span className="chip">
                  <b>Out:</b> <span data-testid="meta-output-tokens">{x.output_tokens}</span>
                </span>
                {x.key_id && (
                  <span className="chip">
                    <b>Key:</b> {x.key_id}
                    {x.fallback_attempts > 0 ? ` (after ${x.fallback_attempts} failed)` : ""}
                  </span>
                )}
              </div>
            </div>
          );
        })}
        {loading && <div className="bubble assistant thinking">Thinking…</div>}
        <div ref={endRef} />
      </main>

      <footer>
        <textarea
          data-testid="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          placeholder="Type a message (Enter to send, Shift+Enter for a new line)"
        />
        <button data-testid="send-button" onClick={send} disabled={loading}>
          Send
        </button>
      </footer>
    </div>
  );
}
