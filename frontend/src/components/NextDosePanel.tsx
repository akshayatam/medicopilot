import { Copy, useSimplified } from "./Copy";
import { Icon } from "./Icon";
import { formatTime, sentenceCase, statusPresentation } from "../format";
import type { Dashboard } from "../types";
import type { MarkTarget } from "./ConfirmDialog";

type NextDosePanelProps = {
  data: Dashboard;
  busy: boolean;
  onMark: (target: MarkTarget) => void;
};

export function NextDosePanel({ data, busy, onMark }: NextDosePanelProps) {
  const simplified = useSimplified();
  const ready = data.readiness.ready_for_medication_tracking;
  const next = data.next_dose;
  const timeZone = data.patient.timezone;
  const doses = Array.isArray(data.today) ? data.today : [];
  const nextDose = doses.find((dose) => dose.dose_id === next.dose_id);
  const detail = next.dose_id ? data.dose_details?.[next.dose_id] : undefined;

  if (!ready) {
    return (
      <section className="band" aria-labelledby="next-heading">
        <div className="shell">
          <div className="hero-empty">
            <span className="hero-badge hero-badge-quiet" aria-hidden="true">
              <Icon name="alert" size={52} strokeWidth={3} />
            </span>
            <div>
              <h1 id="next-heading">
                <Copy plain="This plan needs review" simple="This plan is not ready" />
              </h1>
              <p>{next.message}</p>
              <Progress data={data} />
            </div>
          </div>
        </div>
      </section>
    );
  }

  if (!new Set(["upcoming", "due"]).has(next.status) || !next.dose_id) {
    return (
      <section className="band" aria-labelledby="next-heading">
        <div className="shell">
          <div className="hero-empty">
            <span className="hero-badge" aria-hidden="true">
              <Icon name="check" size={52} strokeWidth={3} />
            </span>
            <div>
              <h1 id="next-heading">
                <Copy plain="Nothing more is scheduled today" simple="Nothing left today" />
              </h1>
              <p>{next.message}</p>
              <Progress data={data} />
            </div>
          </div>
        </div>
      </section>
    );
  }

  const status = statusPresentation(nextDose?.status ?? "upcoming");
  const parts = [
    detail?.period ? sentenceCase(detail.period) : null,
    detail?.meal_context ?? null,
    detail?.purpose ? `For: ${detail.purpose}` : null,
    detail?.instruction ?? null,
    next.appearance ? `Looks like: ${next.appearance}` : null,
  ].filter(Boolean);

  return (
    <section className="band" aria-labelledby="next-heading">
      <div className="shell">
        <div className="hero">
          <div className="hero-main">
            <p className="kicker kicker-accent hero-kicker">
              <Copy plain="Next medicine" simple="Take this next" />
            </p>
            <h1 className="hero-name" id="next-heading">
              {next.medication}
            </h1>
            {parts.length > 0 && <p className="hero-detail">{parts.join(" · ")}</p>}
            <p className="hero-time">{formatTime(next.scheduled_at, timeZone)}</p>
            <div className="hero-when">
              {status.tone === "urgent" ? (
                <span className="hero-when-urgent">
                  <Icon name={status.icon} size={18} strokeWidth={2.5} />
                  {simplified ? status.simpleLabel : status.label}
                </span>
              ) : (
                <span className="hero-when-calm">
                  {simplified ? status.simpleLabel : status.label}
                </span>
              )}
            </div>
            <p className="hero-message">{next.message}</p>
          </div>

          <div className="hero-side">
            <p className="hero-side-note">
              <Copy
                plain="When you have taken it, record it here."
                simple="Took it? Tell me here."
              />
            </p>
            <button
              type="button"
              className="btn btn-accent hero-mark"
              disabled={busy}
              onClick={() =>
                onMark({
                  doseId: next.dose_id!,
                  name: next.medication ?? "",
                  scheduledAt: next.scheduled_at,
                  status: nextDose?.status ?? "upcoming",
                  instruction: detail?.instruction ?? null,
                })
              }
            >
              <Icon name="check" size={30} strokeWidth={3} />
              <Copy plain="I took this" simple="I took it" />
            </button>
            <p className="hero-side-note">
              {status.tone === "urgent" ? (
                <Copy
                  plain="You will be asked to confirm this exact dose before anything is written down."
                  simple="I will check with you first. Then I write it down."
                />
              ) : (
                <Copy
                  plain="This one is not due yet. You will be asked to confirm this exact dose first."
                  simple="This is early. I will check with you first."
                />
              )}
            </p>
            <hr className="hairline" />
            <Progress data={data} />
            <a className="hero-link" href="#today">
              <Copy plain="See the whole day" simple="See the whole day" />
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}

export function Progress({ data }: { data: Dashboard }) {
  const { completed, total, remaining, percent } = data.progress;
  const simplified = useSimplified();
  return (
    <div className="progress">
      <p className="hero-count">
        {simplified
          ? `${completed} of ${total} taken`
          : `${completed} of ${total} doses recorded today`}
      </p>
      <div
        className="progress-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={completed}
        aria-label={`${completed} of ${total} scheduled doses recorded`}
      >
        <div className="progress-fill" style={{ width: `${percent}%` }} />
      </div>
      <div className="progress-head">
        <span className="muted">{percent}% complete</span>
        <span>
          {simplified ? `${remaining} to go` : `${remaining} still to record`}
        </span>
      </div>
    </div>
  );
}
