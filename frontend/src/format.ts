import type { IconName } from "./components/Icon";

/** Every date and time is rendered in the selected patient's stored timezone. */
export function formatTime(value: string | undefined, timeZone: string): string {
  if (!value) return "Not recorded";
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", timeZone }).format(new Date(value));
}

export function formatDay(value: string, timeZone: string): string {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone,
  }).format(new Date(value));
}

export function formatDateTime(value: string | undefined, timeZone: string): string {
  if (!value) return "Not recorded";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone,
  }).format(new Date(value));
}

export function sentenceCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function humanizeFlag(value: string): string {
  return sentenceCase(value.replaceAll("_", " "));
}

export const TAKEN_STATUSES = new Set(["taken", "taken_late"]);

export type StatusTone = "taken" | "urgent" | "quiet";

export type StatusPresentation = {
  label: string;
  simpleLabel: string;
  icon: IconName;
  tone: StatusTone;
};

/**
 * Presentation only. The status word itself is decided by the runtime service; this
 * table just pairs each stored status with a phrase and a glyph so the state is never
 * carried by colour alone.
 */
const STATUS_PRESENTATION: Record<string, StatusPresentation> = {
  taken: { label: "Taken", simpleLabel: "Taken", icon: "check", tone: "taken" },
  taken_late: { label: "Taken late", simpleLabel: "Taken, late", icon: "check", tone: "taken" },
  due: { label: "Due now", simpleLabel: "Time to take it", icon: "clock", tone: "urgent" },
  upcoming: { label: "Later today", simpleLabel: "Later today", icon: "circle", tone: "quiet" },
  missed: { label: "Missed", simpleLabel: "Not written down", icon: "alert", tone: "urgent" },
  skipped_by_user: { label: "Recorded as not taken", simpleLabel: "You said no", icon: "minus", tone: "quiet" },
  unknown: { label: "Not recorded", simpleLabel: "Not written down", icon: "help", tone: "quiet" },
};

export function statusPresentation(status: string): StatusPresentation {
  return (
    STATUS_PRESENTATION[status] ?? {
      label: humanizeFlag(status),
      simpleLabel: humanizeFlag(status),
      icon: "help",
      tone: "quiet",
    }
  );
}
