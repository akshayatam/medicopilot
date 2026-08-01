import {FormEvent, useEffect, useRef, useState} from 'react'
import {api, ApiResponse, Dashboard, Dose, Patient} from './api'

type ChatRole = 'user' | 'assistant' | 'system'
type MessageStatus = 'pending' | 'complete' | 'error'
type MessageSource = 'text' | 'voice' | 'quick_action'

interface ChatMessage {
  id: string
  role: ChatRole
  text: string
  createdAt: string
  status?: MessageStatus
  source?: MessageSource
}

const id = () => globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`
const time = (value: unknown) => typeof value === 'string'
  ? new Date(value).toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'})
  : 'Not recorded'
const statusLabel = (value: string) => ({
  taken: '✓ Taken', taken_late: '✓ Taken late', due: '! Due now', upcoming: '○ Upcoming',
  missed: '! Missed', unknown: '? Status unknown',
}[value] || value.replaceAll('_', ' '))

export default function App() {
  const [patients, setPatients] = useState<Patient[]>([])
  const [patientId, setPatientId] = useState('')
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [question, setQuestion] = useState('')
  const [sessionId, setSessionId] = useState<string | undefined>()
  const [pending, setPending] = useState<ApiResponse['pending_confirmation']>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [simple, setSimple] = useState(false)
  const [large, setLarge] = useState(true)
  const [contrast, setContrast] = useState(true)
  const [developer, setDeveloper] = useState(false)
  const [debug, setDebug] = useState<unknown>()
  const [review, setReview] = useState<unknown>()
  const [health, setHealth] = useState<unknown>()
  const [transcript, setTranscript] = useState('')
  const [voiceStatus, setVoiceStatus] = useState('Record with your microphone or upload audio. Nothing is submitted automatically.')
  const [recording, setRecording] = useState(false)
  const [recordingSeconds, setRecordingSeconds] = useState(0)
  const chatWindowRef = useRef<HTMLDivElement>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const recordingTimerRef = useRef<number | null>(null)
  const recordingLimitRef = useRef<number | null>(null)

  useEffect(() => {
    api.patients().then(list => {
      setPatients(list)
      if (list[0]) setPatientId(list[0].patient_id)
    }).catch(cause => setError(cause.message))
  }, [])

  const refresh = () => patientId && api.dashboard(patientId).then(setDashboard).catch(cause => setError(cause.message))

  useEffect(() => {
    setMessages([])
    setSessionId(undefined)
    setPending(null)
    setReview(undefined)
    refresh()
  }, [patientId])

  useEffect(() => {
    chatWindowRef.current?.scrollTo({top: chatWindowRef.current.scrollHeight, behavior: 'smooth'})
  }, [messages])

  useEffect(() => () => {
    streamRef.current?.getTracks().forEach(track => track.stop())
    if (recordingTimerRef.current) window.clearInterval(recordingTimerRef.current)
    if (recordingLimitRef.current) window.clearTimeout(recordingLimitRef.current)
  }, [])

  const run = async (userText: string, source: MessageSource, call: () => Promise<ApiResponse>): Promise<boolean> => {
    const normalized = userText.trim()
    if (!normalized || busy) return false
    const userId = id()
    setMessages(old => [...old, {id: userId, role: 'user', text: normalized, createdAt: new Date().toISOString(), status: 'pending', source}])
    setBusy(true)
    setError('')
    try {
      const result = await call()
      setSessionId(result.session_id)
      setPending(result.pending_confirmation)
      setDebug(result.debug)
      setMessages(old => [
        ...old.map(message => message.id === userId ? {...message, status: 'complete' as const} : message),
        {id: id(), role: 'assistant', text: result.answer, createdAt: new Date().toISOString(), status: 'complete', source},
      ])
      refresh()
      return true
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'The request could not be completed.'
      setMessages(old => [
        ...old.map(item => item.id === userId ? {...item, status: 'error' as const} : item),
        {id: id(), role: 'assistant', text: `I could not complete that request. ${message}`, createdAt: new Date().toISOString(), status: 'error', source},
      ])
      return false
    } finally {
      setBusy(false)
    }
  }

  const ask = async (event: FormEvent) => {
    event.preventDefault()
    const text = question
    const succeeded = await run(text, 'text', () => api.chat({patient_id: patientId, text, session_id: sessionId, simplified: simple, include_debug: developer}))
    if (succeeded) setQuestion('')
  }

  const action = (kind: string, label: string) => run(label, 'quick_action', () => api.action({patient_id: patientId, action: kind, session_id: sessionId, simplified: simple, include_debug: developer}))

  const repeat = () => {
    const answer = [...messages].reverse().find(message => message.role === 'assistant' && message.status === 'complete')?.text || 'There is no previous answer to repeat yet.'
    setMessages(old => [...old,
      {id: id(), role: 'user', text: 'Repeat last answer', createdAt: new Date().toISOString(), status: 'complete', source: 'quick_action'},
      {id: id(), role: 'assistant', text: answer, createdAt: new Date().toISOString(), status: 'complete', source: 'quick_action'},
    ])
  }

  const transcribe = async (file?: File) => {
    if (!file) return
    setBusy(true)
    setTranscript('')
    setVoiceStatus('Processing audio locally…')
    try {
      const result = await api.transcribe(patientId, file)
      setTranscript(result.text)
      setVoiceStatus(result.success ? 'I heard the text below. Review or edit it before submitting.' : result.warning || 'Transcription failed.')
    } catch (cause) {
      setVoiceStatus(cause instanceof Error ? cause.message : 'The recording could not be transcribed locally.')
    } finally {
      setBusy(false)
    }
  }

  const stopRecording = () => {
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
  }

  const startRecording = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setVoiceStatus('Browser microphone recording is unavailable. You can still upload an audio file.')
      return
    }
    setVoiceStatus('Requesting microphone permission…')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio: true})
      const preferred = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'].find(type => MediaRecorder.isTypeSupported(type))
      const recorder = new MediaRecorder(stream, preferred ? {mimeType: preferred} : undefined)
      streamRef.current = stream
      recorderRef.current = recorder
      chunksRef.current = []
      recorder.ondataavailable = event => { if (event.data.size) chunksRef.current.push(event.data) }
      recorder.onerror = () => setVoiceStatus('The browser could not record audio. You can still upload a file.')
      recorder.onstop = () => {
        if (recordingTimerRef.current) window.clearInterval(recordingTimerRef.current)
        if (recordingLimitRef.current) window.clearTimeout(recordingLimitRef.current)
        stream.getTracks().forEach(track => track.stop())
        streamRef.current = null
        setRecording(false)
        const mimeType = recorder.mimeType || 'audio/webm'
        const extension = mimeType.includes('ogg') ? 'ogg' : mimeType.includes('wav') ? 'wav' : 'webm'
        const recording = new File(chunksRef.current, `microphone-recording.${extension}`, {type: mimeType})
        if (recording.size === 0) {
          setVoiceStatus('The microphone recording was empty. Please try again.')
          return
        }
        void transcribe(recording)
      }
      recorder.start(250)
      setRecordingSeconds(0)
      setRecording(true)
      setVoiceStatus('Recording locally… Select Stop recording when finished. Maximum 30 seconds.')
      recordingTimerRef.current = window.setInterval(() => setRecordingSeconds(value => value + 1), 1000)
      recordingLimitRef.current = window.setTimeout(stopRecording, 30_000)
    } catch (cause) {
      streamRef.current?.getTracks().forEach(track => track.stop())
      setRecording(false)
      const denied = cause instanceof DOMException && cause.name === 'NotAllowedError'
      setVoiceStatus(denied ? 'Microphone permission was denied. Allow access or upload an audio file.' : 'The microphone could not be started. You can still upload an audio file.')
    }
  }

  const submitVoice = async () => {
    const text = transcript
    const succeeded = await run(text, 'voice', () => api.voiceSubmit({patient_id: patientId, text, session_id: sessionId, simplified: simple, include_debug: developer, language: 'English'}))
    if (succeeded) setTranscript('')
  }

  const confirm = () => run('Confirm exact voice action', 'voice', () => api.voiceConfirm({patient_id: patientId, session_id: sessionId, include_debug: developer}))
  const confirmMissedDose = () => run('Yes, record as taken', 'quick_action', () => api.confirmMissedDose({patient_id: patientId, session_id: sessionId, include_debug: developer}))
  const cancel = async () => {
    if (busy) return
    setBusy(true)
    try {
      const result = sessionId ? await api.cancel({patient_id: patientId, session_id: sessionId}) : {message: 'Okay. I did not change the dose record.'}
      setPending(null)
      setTranscript('')
      setVoiceStatus(result.message)
      setMessages(old => [...old, {id: id(), role: 'assistant', text: result.message, createdAt: new Date().toISOString(), status: 'complete', source: 'quick_action'}])
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'The pending confirmation could not be cancelled.'
      setMessages(old => [...old, {id: id(), role: 'assistant', text: message, createdAt: new Date().toISOString(), status: 'error', source: 'quick_action'}])
    } finally {
      setBusy(false)
    }
  }
  const doses = Array.isArray(dashboard?.today) ? dashboard.today : []

  return <div className={`${large ? 'large' : ''} ${contrast ? 'contrast' : ''}`}><div className="app">
    <header className="app-header">
      <div><h1>Medication Copilot</h1><p>Private, on-device medication navigation and adherence support.</p></div>
      <ul className="trust-list" aria-label="Application trust and safety information"><li>Runs locally</li><li>Synthetic data only</li><li>Not diagnosis, prescribing, interaction checking, or treatment advice</li></ul>
    </header>
    <div className="toolbar"><label>Choose a patient <select value={patientId} onChange={event => setPatientId(event.target.value)}>{patients.map(patient => <option key={patient.patient_id} value={patient.patient_id}>{patient.label}</option>)}</select></label><button onClick={refresh}>↻ Refresh dashboard</button></div>
    {error && <div className="error" role="alert">{error}</div>}
    <main className="layout"><section className="dashboard" aria-label="Medication dashboard">
      <article className="card patient"><div><small>PATIENT DASHBOARD</small><h2>{dashboard?.patient.display_name || 'Loading…'}</h2><p>{dashboard && new Date(dashboard.active_clock).toLocaleDateString([], {weekday: 'long', month: 'long', day: 'numeric'})}</p></div><div className={`readiness ${dashboard?.patient.ready ? 'ready' : 'review'}`}><strong>{dashboard?.patient.ready ? '✓ Medication plan verified' : '! Medication plan needs review'}</strong><span>{dashboard?.patient.ready ? 'Ready for dose tracking' : 'Dose tracking is unavailable'}</span></div></article>
      <article className="card next"><small>NEXT MEDICINE</small>{dashboard?.patient.ready && ['upcoming', 'due'].includes(String(dashboard.next_dose.status)) ? <><h2>{String(dashboard.next_dose.medication)}</h2><p className="appearance">{String(dashboard.next_dose.appearance || '')}</p><div className="bigtime">{time(dashboard.next_dose.scheduled_at)}</div><span className="pill">{statusLabel(String(dashboard.next_dose.status))}</span></> : <><h2>{dashboard?.patient.ready ? 'No upcoming dose' : 'Review required'}</h2><p>{String(dashboard?.next_dose.message || 'Source orders cannot be used for reminders until reviewed.')}</p></>}</article>
      <article className="card progress"><small>TODAY’S PROGRESS</small><h2>{dashboard?.progress.completed || 0} of {dashboard?.progress.total || 0} scheduled doses recorded as taken</h2><progress max={dashboard?.progress.total || 1} value={dashboard?.progress.completed || 0}/><div><strong>{dashboard?.progress.missed || 0} missed or overdue</strong><span>{dashboard?.progress.remaining || 0} remaining</span></div></article>
      <article className="card schedule"><small>TODAY’S MEDICINES</small><h2>Your saved schedule</h2>{doses.length ? doses.map((dose: Dose) => <div className={`dose ${dose.status}`} key={`${dose.medication_id}-${dose.scheduled_at}`}><b>{time(dose.scheduled_at)}</b><div><h3>{dose.name}</h3><p>{dose.strength || 'Strength not recorded'}</p>{dose.appearance && <p className="appearance">{dose.appearance}</p>}</div><span className="pill">{statusLabel(dose.status)}</span></div>) : <p>{!Array.isArray(dashboard?.today) && dashboard?.today.message || 'No scheduled doses are stored for today.'}</p>}{dashboard?.as_needed.map(medicine => <div className="dose" key={medicine.medication_id}><b>As needed</b><div><h3>{medicine.name}</h3><p>{medicine.strength}</p></div><span>No recurring due time</span></div>)}<p className="notice">Appearance can vary by manufacturer or refill. Check the prescription label and ask a pharmacist or caregiver if a medicine looks different.</p></article>
    </section><aside>
      <section className="card"><h2>Quick actions</h2><div className="actions"><button className="primary" disabled={busy} onClick={() => action('mark_next', 'Mark next dose taken')}>✓ Mark next dose taken</button><button disabled={busy} onClick={() => action('next', 'What comes next?')}>What comes next?</button><button disabled={busy} onClick={() => action('today', "Show today's medicines")}>Show today’s medicines</button><button disabled={busy} onClick={repeat}>Repeat last answer</button><button disabled={busy} onClick={() => action('history', 'Show medication history')}>History</button></div></section>
      <section className="card chat-card"><h2>Ask Medication Copilot</h2><div ref={chatWindowRef} className="chat-window" role="log" aria-live="polite" aria-label="Medication Copilot conversation">{messages.length === 0 && <div className="chat-empty">Your conversation will appear here.</div>}{messages.map(message => <article key={message.id} className={`chat-message ${message.role} ${message.status || ''}`}><div className="message-meta"><strong>{message.role === 'user' ? 'You' : message.role === 'assistant' ? 'Medication Copilot' : 'System'}</strong><time dateTime={message.createdAt}>{time(message.createdAt)}</time></div><p>{message.text}</p>{message.status === 'pending' && <span className="pending-label">Sending…</span>}{message.status === 'error' && <span className="error-label">Request failed</span>}</article>)}</div>
      <form onSubmit={ask}><label className="sr-only" htmlFor="medication-question">Medication question</label><input id="medication-question" value={question} onChange={event => setQuestion(event.target.value)} disabled={busy} placeholder="Did I take my heart tablet this morning?"/><button className="primary" disabled={busy || !question.trim()}>{busy ? 'Working…' : 'Ask'}</button></form>{pending && <div className="confirm"><strong>Confirmation required</strong><p>{pending.prompt}</p><div className="confirmation-actions">{pending.type === 'voice_mark_taken' && <button className="primary" disabled={busy} onClick={confirm}>Confirm and record</button>}{pending.type === 'record_missed_dose_as_taken' && <button className="primary" disabled={busy} onClick={confirmMissedDose}>Yes, record as taken</button>}<button disabled={busy} onClick={cancel}>Cancel</button></div></div>}
      <div className="voice-panel"><h3>Voice input</h3><p>Voice is processed locally and is not saved. Recording limit: 30 seconds.</p><div className="voice-controls"><button className={recording ? 'recording' : 'primary'} disabled={busy} onClick={recording ? stopRecording : startRecording}>{recording ? `■ Stop recording (${recordingSeconds}s)` : '● Record with microphone'}</button><label className="upload-button">Upload audio<input type="file" accept="audio/*" disabled={busy || recording} onChange={event => {void transcribe(event.target.files?.[0]); event.currentTarget.value = ''}}/></label></div><p className="voice-status" role="status">{voiceStatus}</p>{transcript && <><label htmlFor="voice-transcript">I heard — review and edit before submitting</label><textarea id="voice-transcript" value={transcript} onChange={event => setTranscript(event.target.value)} disabled={busy}/><div className="actions"><button className="primary" disabled={busy || !transcript.trim()} onClick={submitVoice}>Submit transcript</button><button disabled={busy} onClick={cancel}>Cancel</button></div></>}</div></section>
      <details className="card"><summary>Accessibility settings</summary><label><input type="checkbox" checked={simple} onChange={event => setSimple(event.target.checked)}/> Simplified language</label><label><input type="checkbox" checked={large} onChange={event => setLarge(event.target.checked)}/> Large text</label><label><input type="checkbox" checked={contrast} onChange={event => setContrast(event.target.checked)}/> High contrast</label><p>Spoken output is not implemented. Repeat last answer remains text-only.</p></details>
      <details className="card" onToggle={event => {if (event.currentTarget.open && !review) api.review(patientId).then(setReview)}}><summary>Source record review (not used for reminders)</summary><pre>{JSON.stringify(review, null, 2)}</pre></details>
      <details className="card"><summary><label><input type="checkbox" checked={developer} onChange={event => setDeveloper(event.target.checked)}/> Developer debug information</label></summary><pre>{JSON.stringify(debug || {}, null, 2)}</pre></details>
      <details className="card" onToggle={event => {if (event.currentTarget.open) api.health().then(setHealth)}}><summary>System health</summary><pre>{JSON.stringify(health || {}, null, 2)}</pre></details>
    </aside></main></div></div>
}
