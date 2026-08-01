import { Icon } from "./Icon";
import { humanizeFlag } from "../format";
import type { Dashboard, Health, SourceMedication } from "../types";

type ReviewerPanelProps = {
  dashboard: Dashboard | null;
  sourceRecord: SourceMedication[];
  health: Health;
  debug: Record<string, unknown>;
  busy: boolean;
  onRefreshHealth: () => void;
};

/**
 * Review surface for developers and caregivers. Source orders are shown read-only and are
 * never the daily plan; debug output carries routing metadata only, never model reasoning.
 */
export function ReviewerPanel({
  dashboard,
  sourceRecord,
  health,
  debug,
  busy,
  onRefreshHealth,
}: ReviewerPanelProps) {
  const readiness = dashboard?.readiness;

  return (
    <section className="band-ground" aria-labelledby="reviewer-heading">
      <div className="shell section">
        <div className="section-head">
          <h2 id="reviewer-heading">Reviewer view</h2>
          <p>
            Not shown to the person taking the medicines. Source records are for review only and are
            never used for reminders.
          </p>
        </div>

        <div className="reviewer-grid">
          <div className="reviewer-cell">
            <span className="kicker">Source record review</span>
            {sourceRecord.length > 0 ? (
              <table className="reviewer-table">
                <tbody>
                  {sourceRecord.map((medication) => (
                    <tr key={medication.id}>
                      <td>
                        {medication.raw_display}
                        {(medication.validation_flags.length > 0 ||
                          medication.reconciliation_flags.length > 0) && (
                          <span className="reviewer-flags">
                            {medication.validation_flags.map((flag) => (
                              <span className="reviewer-flag" key={flag}>
                                {humanizeFlag(flag)}
                              </span>
                            ))}
                            {medication.reconciliation_flags.map((flag, index) => (
                              <span className="reviewer-flag" key={`${medication.id}-r${index}`}>
                                {humanizeFlag(String(flag.type ?? "flagged for review"))}
                              </span>
                            ))}
                          </span>
                        )}
                      </td>
                      <td>
                        {humanizeFlag(medication.current_use_status)} · FHIR {medication.fhir_status}
                        <br />
                        {medication.included_in_plan ? "In the daily plan" : "Not in the daily plan"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">No imported orders were returned for this patient.</p>
            )}
            {readiness && (
              <p className="reviewer-note">
                Readiness source: {humanizeFlag(readiness.source)}.{" "}
                {readiness.blocking_issues.length > 0
                  ? `Blocking: ${readiness.blocking_issues.map(humanizeFlag).join(", ")}.`
                  : "No blocking issues."}{" "}
                {readiness.warnings.length > 0
                  ? `Warnings: ${readiness.warnings.map(humanizeFlag).join(", ")}.`
                  : "No warnings."}
              </p>
            )}
          </div>

          <div className="reviewer-cell">
            <span className="kicker">Debug</span>
            <div className="reviewer-rows">
              <div className="reviewer-row">
                <span>Data mode</span>
                <span>Synthetic</span>
              </div>
              <div className="reviewer-row">
                <span>Storage</span>
                <span>Local only</span>
              </div>
              <div className="reviewer-row">
                <span>Patient timezone</span>
                <span>{dashboard?.patient.timezone ?? "—"}</span>
              </div>
              <div className="reviewer-row">
                <span>Allergy status</span>
                <span>{dashboard ? humanizeFlag(dashboard.patient.allergy_status) : "—"}</span>
              </div>
            </div>
            <p className="reviewer-note">
              Routing metadata only. Model chain-of-thought is never requested or displayed.
            </p>
            <pre>{JSON.stringify(debug, null, 2)}</pre>
          </div>

          <div className="reviewer-cell">
            <span className="kicker">System health</span>
            <div className="reviewer-rows">
              <HealthCheck ok={health.patient_directory_readable} label="Local patient store readable" />
              <HealthCheck ok={health.schema_validation_ok} label="Runtime schema validation passed" />
              <HealthCheck ok={health.timezone_data_valid} label="Timezone data valid" />
              <HealthCheck ok={health.healthy_for_deterministic_use} label="Ready for deterministic use" />
              <HealthCheck
                ok={health.ollama_reachable}
                label={
                  health.ollama_reachable
                    ? `Local model reachable (${health.configured_model ?? "unknown"})`
                    : "Local model not reachable — deterministic features still work"
                }
              />
            </div>
            <p className="reviewer-note">
              Application clock: {health.active_application_time ?? "unknown"}
              {health.error ? ` · ${health.error}` : ""}
            </p>
            <button type="button" className="btn btn-sm" disabled={busy} onClick={onRefreshHealth}>
              <Icon name="refresh" size={18} strokeWidth={2.5} />
              Re-check health
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

function HealthCheck({ ok, label }: { ok: boolean | undefined; label: string }) {
  return (
    <p className="reviewer-check">
      <Icon name={ok ? "check" : "alert"} size={18} strokeWidth={3} />
      <span>
        {label} — {ok ? "pass" : "attention"}
      </span>
    </p>
  );
}
