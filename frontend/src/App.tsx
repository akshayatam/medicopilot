import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { ActionResponse, ConversationItem, Dashboard, Dose, PatientSummary, SourceMedication } from "./types";

const takenStatuses = new Set(["taken", "taken_late"]);

function formatTime(value?: string, timeZone?: string) {
  if (!value) return "Not recorded";
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", timeZone }).format(new Date(value));
}

function formatDay(value: string, timeZone: string) {
  return new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric", timeZone }).format(new Date(value));
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    taken: "✓ Taken",
    taken_late: "✓ Taken late",
    due: "! Due now",
    upcoming: "○ Upcoming",
    missed: "! Missed",
    skipped_by_user: "— Skipped",
    unknown: "? Unknown",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

function DashboardView({ data }: { data: Dashboard }) {
  const doses = Array.isArray(data.today) ? data.today : [];
  const emptyMessage = Array.isArray(data.today) ? "No scheduled doses are stored for today." : data.today.message;
  const ready = data.readiness.ready_for_medication_tracking;

  return (
    <main className="dashboard" aria-label="Medication dashboard">
      <section className="patient-card card">
        <div>
          <p className="eyebrow">MEDICATION COPILOT</p>
          <h1>{data.patient.display_name}</h1>
          <p className="muted">{formatDay(data.active_clock, data.patient.timezone)}</p>
        </div>
        <div className={`readiness ${ready ? "ready" : "review"}`} role="status">
          <strong>{ready ? "✓ Medication plan verified" : "! Medication plan needs review"}</strong>
          <span>{ready ? "Ready for dose tracking" : "Dose tracking is unavailable"}</span>
        </div>
      </section>

      <section className={`next-card card ${ready ? "" : "needs-review"}`}>
        <div className="card-heading">
          <p className="eyebrow">NEXT MEDICINE</p>
          {data.next_dose.status === "upcoming" && <span className="pill upcoming">○ Upcoming</span>}
        </div>
        {ready && data.next_dose.status === "upcoming" ? (
          <>
            <h2>{data.next_dose.medication}</h2>
            <p className="hero-time">{formatTime(data.next_dose.scheduled_at, data.patient.timezone)}</p>
            {data.purposes[data.next_dose.medication ?? ""] && <p className="purpose">Saved purpose: {data.purposes[data.next_dose.medication ?? ""]}</p>}
            <p className="muted">According to the saved medication plan</p>
          </>
        ) : (
          <>
            <h2>{ready ? "No upcoming dose" : "Review required"}</h2>
            <p className="muted">{data.next_dose.message}</p>
          </>
        )}
      </section>

      <section className="progress-card card" aria-label="Today's progress">
        <div className="section-title">
          <div>
            <p className="eyebrow">TODAY'S PROGRESS</p>
            <h2>{data.progress.completed} of {data.progress.total} doses completed</h2>
          </div>
          <strong>{data.progress.percent}%</strong>
        </div>
        <div
          className="progress-track"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={data.progress.total}
          aria-valuenow={data.progress.completed}
        >
          <div className="progress-fill" style={{ width: `${data.progress.percent}%` }} />
        </div>
        <div className="progress-meta"><span>{data.progress.percent}% complete</span><span>{data.progress.remaining} remaining</span></div>
      </section>

      <section className="schedule card">
        <div className="section-title">
          <div><p className="eyebrow">TODAY'S MEDICINES</p><h2>Your saved schedule</h2></div>
        </div>
        <div className="dose-list">
          {doses.length ? doses.map((dose: Dose) => (
            <article className={`dose-row status-${dose.status}`} key={dose.dose_id}>
              <strong className="dose-time">{formatTime(dose.scheduled_at, data.patient.timezone)}</strong>
              <div className="dose-detail">
                <h3>{dose.name}</h3>
                <p>{dose.strength || "Strength not recorded"}</p>
                {data.purposes[dose.name] && <p className="purpose">Saved purpose: {data.purposes[dose.name]}</p>}
              </div>
              <div className="dose-status">
                <span className={`pill ${dose.status}`}>{statusLabel(dose.status)}</span>
                {takenStatuses.has(dose.status) && <small>Taken at {formatTime(dose.taken_at, data.patient.timezone)}</small>}
              </div>
            </article>
          )) : <div className="empty-state">{emptyMessage}</div>}
        </div>
        {data.prn_medications.length > 0 && (
          <div className="prn-section">
            <h3>As-needed medicines</h3>
            <p className="muted">Shown separately; no fixed reminder is created.</p>
            {data.prn_medications.map((medication) => (
              <article className="dose-row prn" key={medication.name}>
                <div className="dose-detail"><h3>{medication.name}</h3><p>{medication.strength || "Strength not recorded"}</p></div>
                <strong>As needed</strong>
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

function App() {
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [patientId, setPatientId] = useState("");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [sourceRecord, setSourceRecord] = useState<SourceMedication[]>([]);
  const [health, setHealth] = useState<Record<string, unknown>>({});
  const [conversation, setConversation] = useState<ConversationItem[]>([]);
  const [lastAnswer, setLastAnswer] = useState("");
  const [debug, setDebug] = useState<Record<string, unknown>>({});
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [simplified, setSimplified] = useState(() => localStorage.getItem("medicopilot-simplified") === "true");
  const [largeText, setLargeText] = useState(() => localStorage.getItem("medicopilot-large-text") !== "false");
  const [highContrast, setHighContrast] = useState(() => localStorage.getItem("medicopilot-high-contrast") !== "false");
  const conversationEnd = useRef<HTMLDivElement>(null);

  const appClass = useMemo(() => [largeText ? "large-text" : "", highContrast ? "high-contrast" : ""].filter(Boolean).join(" "), [largeText, highContrast]);

  useEffect(() => {
    api.patients()
      .then((items) => {
        setPatients(items);
        const initial = items.find((item) => item.ready) ?? items[0];
        if (initial) setPatientId(initial.patient_id);
      })
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false));
    void refreshHealth();
  }, []);

  useEffect(() => {
    if (!patientId) return;
    setLoading(true);
    setError("");
    Promise.all([api.dashboard(patientId), api.sourceRecord(patientId)])
      .then(([dashboardData, sourceData]) => {
        setDashboard(dashboardData);
        setSourceRecord(sourceData);
        setConversation([]);
        setLastAnswer("");
        setDebug({});
      })
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false));
  }, [patientId]);

  useEffect(() => conversationEnd.current?.scrollIntoView({ behavior: "smooth" }), [conversation]);
  useEffect(() => localStorage.setItem("medicopilot-simplified", String(simplified)), [simplified]);
  useEffect(() => localStorage.setItem("medicopilot-large-text", String(largeText)), [largeText]);
  useEffect(() => localStorage.setItem("medicopilot-high-contrast", String(highContrast)), [highContrast]);

  async function refreshHealth() {
    try { setHealth(await api.health()); } catch (cause) { setHealth({ error: cause instanceof Error ? cause.message : "Health check failed" }); }
  }

  function appendResult(label: string, response: ActionResponse) {
    setDashboard(response.dashboard);
    setDebug(response.result);
    setLastAnswer(response.answer);
    setConversation((items) => [...items, { id: Date.now(), user: label, assistant: response.answer, timestamp: String(response.result.active_clock ?? "") }]);
  }

  async function run(task: () => Promise<ActionResponse>, label: string) {
    if (working) return;
    setWorking(true);
    setError("");
    try { appendResult(label, await task()); } catch (cause) { setError(cause instanceof Error ? cause.message : "The request failed."); }
    finally { setWorking(false); }
  }

  function submitQuestion(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text || !patientId) return;
    setQuestion("");
    void run(() => api.ask(patientId, text, simplified), text);
  }

  function repeatLast() {
    const answer = lastAnswer || "There is no previous answer to repeat yet.";
    setConversation((items) => [...items, { id: Date.now(), user: "Repeat last answer", assistant: answer, timestamp: dashboard?.active_clock }]);
  }

  async function confirmMarkTaken() {
    const doseId = dashboard?.next_dose.dose_id;
    if (!doseId || !patientId) return;
    setConfirming(false);
    await run(() => api.markTaken(patientId, doseId), "Confirm next dose taken");
  }

  if (loading && !dashboard) return <div className="loading-page"><div className="loader" /><p>Loading the verified medication plan…</p></div>;

  return (
    <div className={`app ${appClass}`}>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Medication Copilot home"><span className="brand-mark">M</span><span>Medication Copilot</span></a>
        <span className="local-badge"><i /> Local & private</span>
      </header>

      <div className="safety-banner" role="note"><strong>Synthetic data only · Runs locally</strong><span>Medication navigation and adherence support—not diagnosis, prescribing, or treatment advice.</span></div>

      <section className="patient-controls" id="top">
        <label><span>Choose a patient</span><select value={patientId} onChange={(event) => setPatientId(event.target.value)}>{patients.map((patient) => <option key={patient.patient_id} value={patient.patient_id}>{patient.label}</option>)}</select></label>
        <button className="button secondary" onClick={() => patientId && void api.dashboard(patientId).then(setDashboard).catch((cause: Error) => setError(cause.message))}>↻ Refresh dashboard</button>
      </section>

      {error && <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => setError("")} aria-label="Dismiss error">×</button></div>}

      <div className="layout">
        <div>{dashboard ? <DashboardView data={dashboard} /> : <div className="empty-state">No patient data is available.</div>}</div>
        <aside className="support-column">
          <section className="card quick-actions">
            <p className="eyebrow">QUICK ACTIONS</p><h2>What would you like to do?</h2>
            <button className="button primary mark-button" disabled={working || dashboard?.next_dose.status !== "upcoming"} onClick={() => setConfirming(true)}>✓ Mark next dose taken</button>
            <div className="button-grid">
              <button className="button secondary" disabled={working} onClick={() => void run(() => api.action(patientId, "next"), "What comes next?")}>What comes next?</button>
              <button className="button secondary" disabled={working} onClick={() => void run(() => api.action(patientId, "today"), "Show today's medicines")}>Today's medicines</button>
              <button className="button secondary" disabled={working} onClick={() => void run(() => api.action(patientId, "history"), "Show medication history")}>History</button>
              <button className="button secondary" disabled={working} onClick={repeatLast}>Repeat answer</button>
            </div>
          </section>

          <section className="card chat-card">
            <div className="chat-heading"><div><p className="eyebrow">ASK THE COPILOT</p><h2>Medication questions</h2></div><span className="model-dot" title="Natural-language questions use the configured local model" /></div>
            <div className="conversation" aria-live="polite">
              {conversation.length === 0 && <div className="chat-empty"><span>✦</span><p>Ask about your saved schedule, next dose, instructions, or history.</p></div>}
              {conversation.map((item) => <div className="exchange" key={item.id}><div className="bubble user">{item.user}</div><div className="bubble assistant">{item.assistant}<small>{formatTime(item.timestamp, dashboard?.patient.timezone)}</small></div></div>)}
              {working && <div className="bubble assistant thinking"><i /><i /><i /></div>}
              <div ref={conversationEnd} />
            </div>
            <form className="ask-form" onSubmit={submitQuestion}><label htmlFor="question" className="sr-only">Medication question</label><textarea id="question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Did I take my heart tablet this morning?" rows={2} /><button className="send-button" disabled={working || !question.trim()} aria-label="Ask">↑</button></form>
          </section>

          <details className="card settings"><summary>Accessibility settings</summary><div className="details-content"><label><span><strong>Simplified language</strong><small>Shorter answers for known results</small></span><input type="checkbox" checked={simplified} onChange={(event) => setSimplified(event.target.checked)} /></label><label><span><strong>Large text</strong><small>Increase text throughout the app</small></span><input type="checkbox" checked={largeText} onChange={(event) => setLargeText(event.target.checked)} /></label><label><span><strong>High contrast</strong><small>Use stronger borders and colors</small></span><input type="checkbox" checked={highContrast} onChange={(event) => setHighContrast(event.target.checked)} /></label></div></details>
          <details className="card developer"><summary>Source record review</summary><div className="details-content"><p>Read-only imported orders. They are not used as the daily plan.</p><pre>{JSON.stringify(sourceRecord, null, 2)}</pre></div></details>
          <details className="card developer"><summary>Developer debug information</summary><div className="details-content"><p>Routing metadata only. Chain-of-thought is never requested or displayed.</p><pre>{JSON.stringify(debug, null, 2)}</pre></div></details>
          <details className="card developer"><summary>System health</summary><div className="details-content"><pre>{JSON.stringify(health, null, 2)}</pre><button className="button secondary" onClick={() => void refreshHealth()}>Refresh health</button></div></details>
        </aside>
      </div>

      {confirming && dashboard?.next_dose.dose_id && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setConfirming(false)}>
          <div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title" onMouseDown={(event) => event.stopPropagation()}>
            <span className="confirm-icon">✓</span><p className="eyebrow">CONFIRM DOSE</p><h2 id="confirm-title">Record this dose as taken?</h2><div className="confirm-dose"><strong>{dashboard.next_dose.medication}</strong><span>{formatTime(dashboard.next_dose.scheduled_at, dashboard.patient.timezone)}</span></div><p>This updates the local adherence record for this exact scheduled dose.</p><div className="dialog-actions"><button className="button secondary" onClick={() => setConfirming(false)}>Cancel</button><button className="button primary" autoFocus onClick={() => void confirmMarkTaken()}>Yes, record as taken</button></div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
