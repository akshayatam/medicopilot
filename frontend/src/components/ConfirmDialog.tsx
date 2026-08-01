import { useEffect, useRef } from "react";
import { Copy, useSimplified } from "./Copy";
import { Icon } from "./Icon";
import { formatTime } from "../format";

export type MarkTarget = {
  doseId: string;
  name: string;
  scheduledAt?: string;
  status: string;
  /** The saved instruction, restated verbatim. The dialog never adds guidance of its own. */
  instruction?: string | null;
};

type ConfirmDialogProps = {
  target: MarkTarget;
  timeZone: string;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

const FOCUSABLE = 'button:not([disabled]), a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * Confirms one exact stored dose before the interface asks the runtime service to record it.
 * The dialog never decides anything about the medicine; it restates what is already saved.
 */
export function ConfirmDialog({ target, timeZone, busy, onConfirm, onCancel }: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const notDueYet = target.status === "upcoming";

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    confirmRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCancel();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      previous?.focus();
    };
  }, [onCancel]);

  const simplified = useSimplified();

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onCancel}>
      <div
        ref={dialogRef}
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-body"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <span className="kicker kicker-accent">
          {notDueYet ? (
            <Copy plain="Earlier than planned" simple="This is early" />
          ) : (
            <Copy plain="Please check" simple="Please check" />
          )}
        </span>
        <h2 id="confirm-title">
          {simplified ? `Write down ${target.name}?` : `Record ${target.name} as taken?`}
        </h2>
        <p className="dialog-body" id="confirm-body">
          <Copy
            plain="Only confirm if you have actually taken this dose. Nothing else on your plan changes."
            simple="Only say yes if you really took it. Nothing else changes."
          />
        </p>
        <div className="dialog-fact">
          <strong>{target.name}</strong>
          <span className="tabular">
            {target.scheduledAt ? formatTime(target.scheduledAt, timeZone) : "Time not recorded"}
          </span>
          {target.instruction && <span className="dialog-fact-note">{target.instruction}</span>}
        </div>
        <div className="dialog-actions">
          <button ref={confirmRef} type="button" className="btn btn-accent" disabled={busy} onClick={onConfirm}>
            <Icon name="check" size={24} strokeWidth={3} />
            <Copy plain="Yes, I took it" simple="Yes, I took it" />
          </button>
          <button type="button" className="btn btn-outline-strong" disabled={busy} onClick={onCancel}>
            <Copy plain="No, go back" simple="No, go back" />
          </button>
        </div>
      </div>
    </div>
  );
}
