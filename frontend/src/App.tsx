import { useCallback, useEffect, useRef, useState } from "react";
import { api, isAbort, messageOf } from "./api";
import { AppHeader } from "./components/AppHeader";
import { AskPanel } from "./components/AskPanel";
import { ConfirmDialog, type MarkTarget } from "./components/ConfirmDialog";
import { Copy, SimplifiedContext } from "./components/Copy";
import { DayGrid } from "./components/DayGrid";
import { DisplayBar, type DisplaySettings } from "./components/DisplayBar";
import { NextDosePanel } from "./components/NextDosePanel";
import { Notice } from "./components/Notice";
import { ReviewerPanel } from "./components/ReviewerPanel";
import { SiteFooter } from "./components/SiteFooter";
import type {
  ActionResponse,
  ConversationItem,
  Dashboard,
  Health,
  PatientSummary,
  QuickAction,
  SourceMedication,
} from "./types";

const STORAGE = {
  largeText: "medicopilot-large-text",
  highContrast: "medicopilot-high-contrast",
  simplified: "medicopilot-simplified",
} as const;

const QUICK_ACTION_LABEL: Record<QuickAction, { plain: string; simple: string }> = {
  next: { plain: "What do I take next?", simple: "What is next?" },
  today: { plain: "What is on my plan for today?", simple: "What is today?" },
  history: { plain: "What has been recorded so far?", simple: "What did I take?" },
};

function storedFlag(key: string): boolean {
  return localStorage.getItem(key) === "true";
}

function App() {
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [patientId, setPatientId] = useState("");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [sourceRecord, setSourceRecord] = useState<SourceMedication[]>([]);
  const [health, setHealth] = useState<Health>({});
  const [conversation, setConversation] = useState<ConversationItem[]>([]);
  const [lastAnswer, setLastAnswer] = useState("");
  const [debug, setDebug] = useState<Record<string, unknown>>({});
  const [question, setQuestion] = useState("");
  const [captureNote, setCaptureNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [markTarget, setMarkTarget] = useState<MarkTarget | null>(null);
  const [reviewerOpen, setReviewerOpen] = useState(false);
  const [settings, setSettings] = useState<DisplaySettings>(() => ({
    largeText: storedFlag(STORAGE.largeText),
    highContrast: storedFlag(STORAGE.highContrast),
    simplified: storedFlag(STORAGE.simplified),
  }));

  /** Bumped on every patient change so a slower in-flight response can never overwrite newer data. */
  const loadToken = useRef(0);

  const refreshHealth = useCallback(async (signal?: AbortSignal) => {
    try {
      setHealth(await api.health(signal));
    } catch (cause) {
      if (isAbort(cause)) return;
      setHealth({ error: messageOf(cause, "The health check failed.") });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    api
      .patients(controller.signal)
      .then((items) => {
        setPatients(items);
        const initial = items.find((item) => item.ready) ?? items[0];
        if (initial) setPatientId(initial.patient_id);
        else setLoading(false);
      })
      .catch((cause) => {
        if (isAbort(cause)) return;
        setError(messageOf(cause, "The local service did not return a patient list."));
        setLoading(false);
      });
    void refreshHealth(controller.signal);
    return () => controller.abort();
  }, [refreshHealth]);

  useEffect(() => {
    if (!patientId) return;
    const token = ++loadToken.current;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setMarkTarget(null);
    Promise.all([api.dashboard(patientId, controller.signal), api.sourceRecord(patientId, controller.signal)])
      .then(([dashboardData, sourceData]) => {
        if (token !== loadToken.current) return;
        setDashboard(dashboardData);
        setSourceRecord(sourceData);
        setConversation([]);
        setLastAnswer("");
        setDebug({});
        setQuestion("");
        setCaptureNote("");
      })
      .catch((cause) => {
        if (token !== loadToken.current || isAbort(cause)) return;
        setDashboard(null);
        setSourceRecord([]);
        setError(messageOf(cause, "The saved medication plan could not be loaded."));
      })
      .finally(() => {
        if (token === loadToken.current) setLoading(false);
      });
    return () => controller.abort();
  }, [patientId]);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("big-text", settings.largeText);
    root.classList.toggle("high-contrast", settings.highContrast);
    localStorage.setItem(STORAGE.largeText, String(settings.largeText));
    localStorage.setItem(STORAGE.highContrast, String(settings.highContrast));
    localStorage.setItem(STORAGE.simplified, String(settings.simplified));
  }, [settings]);

  function toggleSetting(key: keyof DisplaySettings) {
    setSettings((current) => ({ ...current, [key]: !current[key] }));
  }

  async function run(task: (id: string) => Promise<ActionResponse>, label: string) {
    if (working || !patientId) return;
    const token = loadToken.current;
    const activePatient = patientId;
    setWorking(true);
    setError("");
    try {
      const response = await task(activePatient);
      if (token !== loadToken.current) return;
      setDashboard(response.dashboard);
      setDebug(response.result);
      setLastAnswer(response.answer);
      setConversation((items) => [
        ...items,
        {
          id: Date.now(),
          user: label,
          assistant: response.answer,
          timestamp: typeof response.result.active_clock === "string" ? response.result.active_clock : undefined,
        },
      ]);
    } catch (cause) {
      if (token === loadToken.current) {
        setError(messageOf(cause, "The local service could not complete that request."));
      }
    } finally {
      setWorking(false);
    }
  }

  function submitQuestion() {
    const text = question.trim();
    if (!text) return;
    setQuestion("");
    setCaptureNote("");
    void run((id) => api.ask(id, text, settings.simplified), text);
  }

  /**
   * Dictated or uploaded words are placed in the question box and left there. Choosing Ask
   * is the explicit confirmation rules.md requires before spoken input can reach an action
   * that records a dose.
   */
  function receiveTranscript(text: string, note: string) {
    if (text) setQuestion(text);
    setCaptureNote(note);
  }

  function runQuickAction(action: QuickAction) {
    const label = QUICK_ACTION_LABEL[action];
    void run((id) => api.action(id, action), settings.simplified ? label.simple : label.plain);
  }

  function repeatLastAnswer() {
    const answer =
      lastAnswer ||
      (settings.simplified
        ? "There is no answer to repeat yet."
        : "There is no previous answer to repeat yet.");
    setConversation((items) => [
      ...items,
      {
        id: Date.now(),
        user: settings.simplified ? "Say that again" : "Repeat the last answer",
        assistant: answer,
        timestamp: dashboard?.active_clock,
      },
    ]);
  }

  function confirmMark() {
    const target = markTarget;
    if (!target) return;
    setMarkTarget(null);
    void run(
      (id) => api.markTaken(id, target.doseId),
      settings.simplified ? `I took ${target.name}` : `Record ${target.name} as taken`,
    );
  }

  const timeZone = dashboard?.patient.timezone ?? "UTC";
  const canAsk = Boolean(patientId) && !loading;

  if (loading && !dashboard) {
    return (
      <SimplifiedContext.Provider value={settings.simplified}>
        <div className="loading-page">
          <h1>Medication Copilot</h1>
          <p>
            <Copy plain="Loading the verified medication plan…" simple="Getting your plan…" />
          </p>
          <div className="loading-bar" role="progressbar" aria-label="Loading the verified medication plan">
            <i />
          </div>
        </div>
      </SimplifiedContext.Provider>
    );
  }

  return (
    <SimplifiedContext.Provider value={settings.simplified}>
      <div className="app">
        <AppHeader
          patients={patients}
          patientId={patientId}
          busy={loading || working}
          reviewerOpen={reviewerOpen}
          onSelectPatient={setPatientId}
          onToggleReviewer={() => setReviewerOpen((open) => !open)}
        />

        <DisplayBar
          activeClock={dashboard?.active_clock}
          timeZone={timeZone}
          ready={dashboard?.readiness.ready_for_medication_tracking}
          settings={settings}
          onToggle={toggleSetting}
        />

        <main>
          {error && (
            <div className="band">
              <div className="shell">
                <Notice
                  icon="alert"
                  tone="alert"
                  title={error}
                  body="Nothing on your medication plan was changed."
                  onDismiss={() => setError("")}
                />
              </div>
            </div>
          )}

          {dashboard ? (
            <>
              <NextDosePanel data={dashboard} busy={working} onMark={setMarkTarget} />
              <DayGrid data={dashboard} busy={working} onMark={setMarkTarget} />
              <AskPanel
                question={question}
                conversation={conversation}
                lastResult={debug}
                timeZone={timeZone}
                language={dashboard.patient.preferred_language ?? "en-US"}
                busy={working}
                canAsk={canAsk}
                modelOffline={health.ollama_reachable === false}
                hasLastAnswer={Boolean(lastAnswer)}
                captureNote={captureNote}
                onQuestionChange={setQuestion}
                onTranscript={receiveTranscript}
                onSubmit={submitQuestion}
                onQuickAction={runQuickAction}
                onRepeat={repeatLastAnswer}
              />
            </>
          ) : (
            <section className="band-ground">
              <div className="shell section">
                <p className="empty-cell">
                  <Copy
                    plain="No patient data is available from the local service."
                    simple="I cannot find any plan right now."
                  />
                </p>
              </div>
            </section>
          )}

          {reviewerOpen && (
            <ReviewerPanel
              dashboard={dashboard}
              sourceRecord={sourceRecord}
              health={health}
              debug={debug}
              busy={working}
              onRefreshHealth={() => void refreshHealth()}
            />
          )}

          <SiteFooter dashboard={dashboard} />
        </main>

        {markTarget && (
          <ConfirmDialog
            target={markTarget}
            timeZone={timeZone}
            busy={working}
            onConfirm={confirmMark}
            onCancel={() => setMarkTarget(null)}
          />
        )}
      </div>
    </SimplifiedContext.Provider>
  );
}

export default App;
