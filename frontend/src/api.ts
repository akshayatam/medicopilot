export type Patient = {patient_id:string;display_name:string;age:number;ready:boolean;label:string}
export type Dose = {medication_id:string;name:string;strength:string;appearance?:string|null;scheduled_at:string;status:string;taken_at:string}
export type Dashboard = {patient:{patient_id:string;display_name:string;readiness:string;ready:boolean;blocking_issues:string[];warnings:string[];allergy_status:string};active_clock:string;today:Dose[]|{status:string;message:string};next_dose:Record<string,unknown>;progress:{completed:number;total:number;missed:number;remaining:number};as_needed:Array<{medication_id:string;name:string;strength:string;purpose:string}>}
export type ApiResponse = {session_id:string;answer:string;action:string;outcome:string;pending_confirmation?:{type:string;prompt:string}|null;debug?:unknown}

async function request<T>(path:string, init?:RequestInit):Promise<T>{
  const response=await fetch(path,init)
  const value=await response.json().catch(()=>({detail:'The server returned an invalid response.'}))
  if(!response.ok) throw new Error(value.detail||'Request failed')
  return value
}
export const api={
  patients:()=>request<Patient[]>('/api/patients'),
  dashboard:(id:string)=>request<Dashboard>(`/api/patients/${encodeURIComponent(id)}/dashboard`),
  history:(id:string)=>request<{items:unknown}>(`/api/patients/${encodeURIComponent(id)}/history`),
  review:(id:string)=>request<unknown>(`/api/patients/${encodeURIComponent(id)}/source-review`),
  health:()=>request<unknown>('/api/health'),
  chat:(body:object)=>request<ApiResponse>('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),
  action:(body:object)=>request<ApiResponse>('/api/actions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),
  transcribe:(patient_id:string,audio:File)=>{const body=new FormData();body.append('patient_id',patient_id);body.append('language','English');body.append('audio',audio);return request<{success:boolean;text:string;warning?:string}>('/api/voice/transcribe',{method:'POST',body})},
  voiceSubmit:(body:object)=>request<ApiResponse>('/api/voice/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),
  voiceConfirm:(body:object)=>request<ApiResponse>('/api/voice/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),
  confirmMissedDose:(body:object)=>request<ApiResponse>('/api/confirmations/missed-dose',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),
  cancel:(body:object)=>request<{message:string}>('/api/session/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),
}
