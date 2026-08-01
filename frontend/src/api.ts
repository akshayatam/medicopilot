import type { ActionResponse, Dashboard, PatientSummary, SourceMedication } from "./types";

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

export const api = {
  patients: () => request<PatientSummary[]>("/api/patients"),
  dashboard: (patientId: string) => request<Dashboard>(`/api/patients/${encodeURIComponent(patientId)}/dashboard`),
  sourceRecord: (patientId: string) => request<SourceMedication[]>(`/api/patients/${encodeURIComponent(patientId)}/source-record`),
  health: () => request<Record<string, unknown>>("/api/health"),
  ask: (patientId: string, text: string, simplified: boolean) =>
    request<ActionResponse>(`/api/patients/${encodeURIComponent(patientId)}/ask`, {
      method: "POST",
      body: JSON.stringify({ text, simplified }),
    }),
  action: (patientId: string, action: "today" | "next" | "history") =>
    request<ActionResponse>(`/api/patients/${encodeURIComponent(patientId)}/actions/${action}`, { method: "POST" }),
  markTaken: (patientId: string, doseId: string) =>
    request<ActionResponse>(`/api/patients/${encodeURIComponent(patientId)}/doses/${encodeURIComponent(doseId)}/taken`, {
      method: "POST",
      body: JSON.stringify({ confirmed: true }),
    }),
};
