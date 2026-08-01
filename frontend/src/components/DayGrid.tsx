import { Copy, useSimplified } from "./Copy";
import { Icon } from "./Icon";
import { TAKEN_STATUSES, formatTime, sentenceCase, statusPresentation } from "../format";
import type { Dashboard, Dose } from "../types";
import type { MarkTarget } from "./ConfirmDialog";

type DayGridProps = {
  data: Dashboard;
  busy: boolean;
  onMark: (target: MarkTarget) => void;
};

export function DayGrid({ data, busy, onMark }: DayGridProps) {
  const simplified = useSimplified();
  const doses = Array.isArray(data.today) ? data.today : [];
  const emptyMessage = Array.isArray(data.today)
    ? "No dose instances are stored for today."
    : data.today.message;
  const { completed, total } = data.progress;

  return (
    <section className="band-ground" id="today" aria-labelledby="today-heading">
      <div className="shell section">
        <div className="section-head">
          <h2 id="today-heading">
            <Copy plain="Your day, as saved on your plan" simple="Everything for today" />
          </h2>
          <span className="section-meta">
            {simplified
              ? `${completed} of ${total} taken`
              : `${completed} of ${total} doses recorded today`}
          </span>
        </div>

        {doses.length > 0 ? (
          <div className="day-grid">
            {doses.map((dose) => (
              <DoseCell
                key={dose.dose_id}
                dose={dose}
                data={data}
                isNext={dose.dose_id === data.next_dose.dose_id}
                busy={busy}
                onMark={onMark}
              />
            ))}
          </div>
        ) : (
          <p className="empty-cell">{emptyMessage}</p>
        )}

        {data.prn_medications.length > 0 && <AsNeeded data={data} />}
        {doses.some((dose) => dose.appearance) && (
          <p className="appearance-caution">
            Appearance can vary by manufacturer or refill. Check the prescription label if a medicine looks different.
          </p>
        )}
      </div>
    </section>
  );
}

function DoseCell({
  dose,
  data,
  isNext,
  busy,
  onMark,
}: {
  dose: Dose;
  data: Dashboard;
  isNext: boolean;
  busy: boolean;
  onMark: (target: MarkTarget) => void;
}) {
  const simplified = useSimplified();
  const timeZone = data.patient.timezone;
  const detail = data.dose_details?.[dose.dose_id];
  const status = statusPresentation(dose.status);
  const taken = TAKEN_STATUSES.has(dose.status);
  const label = simplified ? status.simpleLabel : status.label;

  return (
    <article className={`dose-cell${isNext ? " dose-cell-active" : ""}`}>
      <div className="dose-slot">
        <span className="kicker">
          {detail?.period ? sentenceCase(detail.period) : <Copy plain="Scheduled" simple="On your plan" />}
        </span>
        <span className="dose-time tabular">{formatTime(dose.scheduled_at, timeZone)}</span>
      </div>

      <div>
        <h3 className="dose-name">{dose.name}</h3>
        <p className="dose-strength">{dose.strength || "Strength not recorded"}</p>
        {dose.appearance && <p className="dose-note">Looks like: {dose.appearance}</p>}
        {detail?.meal_context && <p className="dose-note">{detail.meal_context}</p>}
        {detail?.purpose && <p className="dose-note">For: {detail.purpose}</p>}
      </div>

      <div className="dose-foot">
        {taken ? (
          <p className="dose-state">
            <Icon name={status.icon} size={24} strokeWidth={3} />
            {simplified
              ? `${label} ${formatTime(dose.taken_at, timeZone)}`
              : `${label} at ${formatTime(dose.taken_at, timeZone)}`}
          </p>
        ) : (
          <div className="dose-actions">
            <p className={`dose-state${isNext ? " dose-state-active" : " dose-state-quiet"}`}>
              <Icon name={status.icon} size={22} strokeWidth={isNext ? 3 : 2.5} />
              {label}
            </p>
            <button
              type="button"
              className={`btn dose-mark${isNext ? " btn-accent" : " btn-outline-strong"}`}
              disabled={busy}
              onClick={() =>
                onMark({
                  doseId: dose.dose_id,
                  name: `${dose.name}${dose.strength ? ` ${dose.strength}` : ""}`,
                  scheduledAt: dose.scheduled_at,
                  status: dose.status,
                  instruction: detail?.instruction ?? null,
                })
              }
            >
              <Icon name="check" size={22} strokeWidth={3} />
              <Copy plain="I took this" simple="I took it" />
              <span className="sr-only">
                {` — ${dose.name} at ${formatTime(dose.scheduled_at, timeZone)}`}
              </span>
            </button>
          </div>
        )}
      </div>
    </article>
  );
}

function AsNeeded({ data }: { data: Dashboard }) {
  return (
    <div className="prn">
      <div className="section-head">
        <h2>
          <Copy plain="Taken only when needed" simple="Only when you need it" />
        </h2>
        <p>
          <Copy
            plain="These are on your plan without a fixed time, so no reminder is created for them."
            simple="No set time for these. I will not remind you."
          />
        </p>
      </div>
      <div className="prn-grid">
        {data.prn_medications.map((medication) => (
          <article className="prn-cell" key={medication.name}>
            <span className="kicker">
              <Copy plain="As needed" simple="When needed" />
            </span>
            <h3 className="dose-name">{medication.name}</h3>
            <p className="dose-strength">{medication.strength || "Strength not recorded"}</p>
            {medication.purpose && <p className="dose-note">For: {medication.purpose}</p>}
            {medication.instruction && <p className="dose-note">{medication.instruction}</p>}
          </article>
        ))}
      </div>
    </div>
  );
}
