import type { ActionResponse, Dashboard, Health, PatientSummary, QuickAction, SourceMedication } from "./types";

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: options?.body ? { "Content-Type": "application/json", ...options.headers } : options?.headers,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : "The local service could not complete that request.");
  }
  return response.json() as Promise<T>;
}

const patientPath = (patientId: string) => `/api/patients/${encodeURIComponent(patientId)}`;

export const api = {
  patients: (signal?: AbortSignal) => request<PatientSummary[]>("/api/patients", { signal }),
  dashboard: (patientId: string, signal?: AbortSignal) =>
    request<Dashboard>(`${patientPath(patientId)}/dashboard`, { signal }),
  sourceRecord: (patientId: string, signal?: AbortSignal) =>
    request<SourceMedication[]>(`${patientPath(patientId)}/source-record`, { signal }),
  health: (signal?: AbortSignal) => request<Health>("/api/health", { signal }),
  ask: (patientId: string, text: string, simplified: boolean) =>
    request<ActionResponse>(`${patientPath(patientId)}/ask`, {
      method: "POST",
      body: JSON.stringify({ text, simplified }),
    }),
  action: (patientId: string, action: QuickAction) =>
    request<ActionResponse>(`${patientPath(patientId)}/actions/${action}`, { method: "POST" }),
  markTaken: (patientId: string, doseId: string) =>
    request<ActionResponse>(`${patientPath(patientId)}/doses/${encodeURIComponent(doseId)}/taken`, {
      method: "POST",
      body: JSON.stringify({ confirmed: true }),
    }),
};

/** An aborted fetch is an expected outcome when the patient changes mid-request. */
export function isAbort(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === "AbortError";
}

export function messageOf(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}
