export type PatientSummary = {
  patient_id: string;
  display_name: string;
  age: number;
  preferred_language: string | null;
  timezone: string;
  ready: boolean;
  label: string;
};

export type Dose = {
  dose_id: string;
  name: string;
  strength: string;
  scheduled_at: string;
  status: string;
  taken_at: string;
};

export type NextDose = {
  status: string;
  dose_id?: string;
  medication?: string;
  scheduled_at?: string;
  message: string;
};

/** Verified, presentation-only labels the API resolves from the reminder schedule. */
export type DoseDetail = {
  period: string | null;
  meal_context: string | null;
  instruction: string | null;
  purpose: string;
};

export type PrnMedication = {
  name: string;
  strength: string;
  purpose: string;
  instruction: string | null;
};

export type Dashboard = {
  patient: {
    id: string;
    display_name: string;
    age: number;
    preferred_language: string | null;
    timezone: string;
    allergy_status: string;
  };
  readiness: {
    ready_for_medication_tracking: boolean;
    blocking_issues: string[];
    warnings: string[];
    source: string;
  };
  active_clock: string;
  today: Dose[] | { status: string; message: string; date?: string };
  next_dose: NextDose;
  progress: { completed: number; total: number; remaining: number; percent: number };
  prn_medications: PrnMedication[];
  purposes: Record<string, string>;
  /** Added by the current API; optional so a stale local server cannot crash the UI. */
  dose_details?: Record<string, DoseDetail>;
};

export type ActionResponse = {
  answer: string;
  result: Record<string, unknown>;
  dashboard: Dashboard;
};

export type SourceMedication = {
  id: string;
  raw_display: string;
  fhir_status: string;
  current_use_status: string;
  validation_flags: string[];
  reconciliation_flags: Array<Record<string, unknown>>;
  included_in_plan: boolean;
};

export type Health = {
  ollama_reachable?: boolean;
  configured_model?: string;
  model_available?: boolean;
  generation_ok?: boolean;
  patient_directory_readable?: boolean;
  patients_loaded?: number;
  patients_ready?: number;
  schema_validation_ok?: boolean;
  timezone_data_valid?: boolean;
  schema_errors?: string[];
  healthy_for_deterministic_use?: boolean;
  active_application_time?: string;
  error?: string;
};

export type ConversationItem = {
  id: number;
  user: string;
  assistant: string;
  timestamp?: string;
};

export type QuickAction = "today" | "next" | "history";
