import type { SubmitEvent } from "react";
import { Copy, useSimplified } from "./Copy";
import { Icon } from "./Icon";
import { VoicePanel } from "./VoicePanel";
import { formatTime, humanizeFlag } from "../format";
import type { ConversationItem, QuickAction } from "../types";

type AskPanelProps = {
  question: string;
  conversation: ConversationItem[];
  lastResult: Record<string, unknown>;
  timeZone: string;
  language: string;
  busy: boolean;
  canAsk: boolean;
  modelOffline: boolean;
  hasLastAnswer: boolean;
  captureNote: string;
  onQuestionChange: (value: string) => void;
  onTranscript: (text: string, note: string) => void;
  onSubmit: () => void;
  onQuickAction: (action: QuickAction) => void;
  onRepeat: () => void;
};

/** Titles restate the deterministic outcome the runtime service already reported. */
const OUTCOME_TITLE: Record<string, { plain: string; simple: string }> = {
  success: { plain: "From your saved plan", simple: "From your plan" },
  unsafe_request: { plain: "That is outside what I can answer", simple: "I cannot answer that one" },
  patient_not_ready: { plain: "This plan still needs review", simple: "This plan is not ready" },
  needs_clarification: { plain: "I need a little more detail", simple: "Tell me a bit more" },
  routing_error: { plain: "I could not route that safely", simple: "I did not understand that" },
};

export function AskPanel({
  question,
  conversation,
  lastResult,
  timeZone,
  language,
  busy,
  canAsk,
  modelOffline,
  hasLastAnswer,
  captureNote,
  onQuestionChange,
  onTranscript,
  onSubmit,
  onQuickAction,
  onRepeat,
}: AskPanelProps) {
  const simplified = useSimplified();
  const latest = conversation.length > 0 ? conversation[conversation.length - 1] : null;
  const earlier = conversation.slice(0, -1).reverse();
  const outcome = typeof lastResult.outcome === "string" ? lastResult.outcome : "";
  const source = typeof lastResult.response_source === "string" ? lastResult.response_source : "";
  const title = OUTCOME_TITLE[outcome];

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <section className="band" aria-labelledby="ask-heading">
      <div className="shell section">
        <div className="section-head">
          <h2 id="ask-heading">
            <Copy plain="Ask about your plan" simple="Ask a question" />
          </h2>
          <p>
            <Copy
              plain="Answers come only from your saved plan and what has been recorded on this device."
              simple="I only read your plan and today's record."
            />
          </p>
        </div>

        {latest && (
          <div className="answer" role="status" aria-live="polite">
            <p className="kicker answer-kicker">
              {simplified ? "You asked" : "You asked"}: {latest.user}
            </p>
            {title && <p className="answer-title">{simplified ? title.simple : title.plain}</p>}
            <p className="answer-body">{latest.assistant}</p>
            <p className="answer-meta">
              {source && <span>{humanizeFlag(source)}</span>}
              {latest.timestamp && <span>· {formatTime(latest.timestamp, timeZone)}</span>}
              <span>· <Copy plain="Not medical advice" simple="Not medical advice" /></span>
            </p>
          </div>
        )}

        <form className="ask-row" onSubmit={submit}>
          <label className="sr-only" htmlFor="question">
            Medication question
          </label>
          <input
            id="question"
            className="ask-input"
            type="text"
            autoComplete="off"
            value={question}
            disabled={!canAsk}
            onChange={(event) => onQuestionChange(event.target.value)}
            placeholder={
              simplified
                ? "For example: did I take my heart tablet?"
                : "For example: did I take my heart tablet this morning?"
            }
          />
          <button type="submit" className="btn btn-ink ask-send" disabled={busy || !canAsk || !question.trim()}>
            <Copy plain="Ask" simple="Ask" />
            <Icon name="arrow-right" size={20} />
          </button>
        </form>

        <div className="ask-tools">
          <VoicePanel language={language} disabled={busy || !canAsk} onTranscript={onTranscript} />

          <div className="ask-tools-row">
            <button type="button" className="btn" disabled={busy || !hasLastAnswer} onClick={onRepeat}>
              <Icon name="refresh" size={22} />
              <Copy plain="Repeat the last answer" simple="Say that again" />
            </button>
            {busy && (
              <span className="working" role="status">
                <i aria-hidden="true" />
                <Copy plain="Checking your saved plan…" simple="Looking…" />
              </span>
            )}
            <span className="ask-tools-note">
              <Copy
                plain="Everything runs on this device. Nothing is sent to a remote service."
                simple="It all stays on this device."
              />
            </span>
          </div>

          {captureNote && (
            <p className="ask-hint" role="status">
              <Icon name="info" size={20} />
              <span>{captureNote}</span>
            </p>
          )}

          {modelOffline && (
            <p className="ask-hint">
              <Icon name="info" size={20} />
              <span>
                <Copy
                  plain="The local language model is not reachable, so free-text questions return a safe routing message instead of an answer. The buttons below still read your saved plan directly."
                  simple="The helper model is off right now. The buttons below still work."
                />
              </span>
            </p>
          )}
        </div>

        <div className="chips">
          <button type="button" className="chip" disabled={busy || !canAsk} onClick={() => onQuickAction("next")}>
            <Copy plain="What do I take next?" simple="What is next?" />
          </button>
          <button type="button" className="chip" disabled={busy || !canAsk} onClick={() => onQuickAction("today")}>
            <Copy plain="What is on my plan for today?" simple="What is today?" />
          </button>
          <button type="button" className="chip" disabled={busy || !canAsk} onClick={() => onQuickAction("history")}>
            <Copy plain="What has been recorded so far?" simple="What did I take?" />
          </button>
        </div>

        {earlier.length > 0 && (
          <div className="transcript">
            <h3 className="kicker">
              <Copy plain="Earlier in this session" simple="Before this" />
            </h3>
            {earlier.map((item) => (
              <div className="transcript-entry" key={item.id}>
                <p className="transcript-q">{item.user}</p>
                <p className="transcript-a">{item.assistant}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
