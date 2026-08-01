import { Copy } from "./Copy";
import { formatDateTime } from "../format";
import type { Dashboard } from "../types";

export function SiteFooter({ dashboard }: { dashboard: Dashboard | null }) {
  return (
    <footer className="site-footer">
      <div className="shell">
        <div>
          <span className="kicker">
            <Copy plain="About this prototype" simple="About this app" />
          </span>
          <p>
            <Copy
              plain="Synthetic data only. Everything runs on this device. Medication Copilot helps you find and record what is on your saved plan. It does not diagnose, prescribe, recommend treatment, check interactions, or change doses, and it is not a medical device. For anything about your treatment, speak to your pharmacist or doctor."
              simple="Practice data only. It all stays on this device. This app shows your saved plan and writes down what you took. It cannot tell you what to take, change a dose, or say if medicines are safe together. Ask your pharmacist or doctor about those."
            />
          </p>
          <p>
            <Copy
              plain="Imported clinical orders are kept separate from the verified plan and are shown only in the reviewer view."
              simple="Old records from the clinic are kept apart from your plan."
            />
          </p>
        </div>

        <div className="footer-side">
          <span className="kicker">
            <Copy plain="This session" simple="Right now" />
          </span>
          <div className="footer-list">
            <div>
              <span>
                <Copy plain="Application clock" simple="Time now" />
              </span>
              <span className="tabular">
                {dashboard
                  ? formatDateTime(dashboard.active_clock, dashboard.patient.timezone)
                  : "—"}
              </span>
            </div>
            <div>
              <span>
                <Copy plain="Timezone" simple="Timezone" />
              </span>
              <span>{dashboard?.patient.timezone ?? "—"}</span>
            </div>
            <div>
              <span>
                <Copy plain="Language" simple="Language" />
              </span>
              <span>{dashboard?.patient.preferred_language ?? "Not recorded"}</span>
            </div>
            <div>
              <span>
                <Copy plain="Allergy status" simple="Allergies" />
              </span>
              <span>
                {dashboard ? dashboard.patient.allergy_status.replaceAll("_", " ") : "—"}
              </span>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}
