import { Copy } from "./Copy";
import { Icon } from "./Icon";
import type { PatientSummary } from "../types";

type AppHeaderProps = {
  patients: PatientSummary[];
  patientId: string;
  busy: boolean;
  reviewerOpen: boolean;
  onSelectPatient: (patientId: string) => void;
  onToggleReviewer: () => void;
};

export function AppHeader({
  patients,
  patientId,
  busy,
  reviewerOpen,
  onSelectPatient,
  onToggleReviewer,
}: AppHeaderProps) {
  return (
    <header className="band">
      <div className="shell masthead">
        <div className="masthead-brand">
          <div className="brand-line">
            <span className="brand-name">Medication Copilot</span>
            <span className="brand-tag">Local prototype</span>
          </div>
          <span className="brand-note">
            <Copy
              plain="Synthetic data only — nothing here is a real patient record."
              simple="Practice data only. Not a real person."
            />
          </span>
        </div>

        <div className="masthead-controls">
          <div className="patient-picker">
            <label htmlFor="patient-select">
              <Copy plain="Plan for" simple="Plan for" />
            </label>
            <span className="select-shell">
              <select
                id="patient-select"
                value={patientId}
                disabled={busy || patients.length === 0}
                onChange={(event) => onSelectPatient(event.target.value)}
              >
                {patients.map((patient) => (
                  <option key={patient.patient_id} value={patient.patient_id}>
                    {patient.label}
                  </option>
                ))}
              </select>
              <Icon name="chevron-down" size={20} />
            </span>
          </div>

          <button type="button" className="toggle" aria-pressed={reviewerOpen} onClick={onToggleReviewer}>
            {reviewerOpen && <Icon name="check" size={15} strokeWidth={3.5} />}
            Reviewer view
          </button>
        </div>
      </div>
    </header>
  );
}
