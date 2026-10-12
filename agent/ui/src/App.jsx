import { useEffect, useRef, useState } from "react";

async function readResponse(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return body;
}

export default function App() {
  const [session, setSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(new URLSearchParams(window.location.search).get("error") || "");
  const bottom = useRef(null);

  useEffect(() => {
    fetch("/api/session", { credentials: "same-origin" })
      .then(readResponse)
      .then(setSession)
      .catch((reason) => {
        setError(reason.message);
        setSession({ authenticated: false });
      });
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function sendMessage(event) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || busy) return;

    setDraft("");
    setError("");
    setMessages((current) => [...current, { role: "user", text: message }]);
    setBusy(true);
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-Requested-With": "graphbase" },
        body: JSON.stringify({ message }),
      });
      const data = await readResponse(response);
      setMessages((current) => [...current, { role: "assistant", text: data.answer }]);
    } catch (reason) {
      setError(reason.message);
      if (reason.message.toLowerCase().includes("sign in")) setSession({ authenticated: false });
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    try {
      await fetch("/api/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Requested-With": "graphbase" },
      }).then(readResponse);
    } catch (reason) {
      setError(reason.message);
    }
    setSession({ authenticated: false });
    setMessages([]);
  }

  if (!session) {
    return (
      <main className="page loading">
        <div className="brand-mark">KF</div>
        <p>Connecting to TCS Knowledge Fabric…</p>
      </main>
    );
  }

  if (!session.authenticated) {
    return (
      <main className="page login-page">
        <section className="login-card">
          <div className="brand-mark">KF</div>
          <p className="eyebrow">TCS KNOWLEDGE FABRIC</p>
          <h1>Your knowledge, in conversation.</h1>
          <p className="intro">Sign in with your organization account to chat with the knowledge bases you can access.</p>
          {error && <div className="error" role="alert">{error}</div>}
          <a className="primary-button sign-in" href="/auth/login">Continue with Keycloak</a>
          <p className="privacy-note">Your sign-in stays on the server. Tokens are never stored in this browser.</p>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">KF</div>
          <div>
            <strong>TCS Knowledge Fabric</strong>
            <span>Agent chat</span>
          </div>
        </div>
        <div className="account">
          <span className="account-name">{session.user.display_name}</span>
          <button className="quiet-button" onClick={signOut}>Sign out</button>
        </div>
      </header>
      <section className="chat-panel">
        <div className="chat-heading">
          <div className="status-dot" />
          <div>
            <h1>Knowledge assistant</h1>
            <p>Answers are grounded in the knowledge bases you can access.</p>
          </div>
        </div>
        <div className="messages" aria-live="polite">
          {messages.length === 0 && (
            <div className="welcome">
              <span className="sparkle">✦</span>
              <h2>What would you like to know?</h2>
              <p>Ask a question about your graph and document knowledge bases.</p>
            </div>
          )}
          {messages.map((message, index) => (
            <article className={`message ${message.role}`} key={`${index}-${message.role}`}>
              <div className="message-label">{message.role === "user" ? "You" : "Knowledge assistant"}</div>
              <div className="message-text">{message.text}</div>
            </article>
          ))}
          {busy && <div className="thinking"><span /> Looking through your knowledge bases…</div>}
          <div ref={bottom} />
        </div>
        {error && <div className="error chat-error" role="alert">{error}</div>}
        <form className="composer" onSubmit={sendMessage}>
          <textarea
            aria-label="Message"
            placeholder="Ask a question…"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form.requestSubmit();
              }
            }}
            maxLength={2000}
            rows={1}
          />
          <button className="send-button" type="submit" disabled={busy || !draft.trim()} aria-label="Send message">
            <span aria-hidden="true">↑</span>
          </button>
        </form>
        <p className="composer-hint">Enter to send · Shift + Enter for a new line</p>
      </section>
    </main>
  );
}
