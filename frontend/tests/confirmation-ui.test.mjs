import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import test from 'node:test'

const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
const api = readFileSync(new URL('../src/api.ts', import.meta.url), 'utf8')

test('missed-dose confirmation renders affirmative and cancel controls', () => {
  assert.match(app, /pending\.type === 'record_missed_dose_as_taken'/)
  assert.match(app, />Yes, record as taken</)
  assert.match(app, />Cancel</)
  assert.match(app, /disabled=\{busy\}/)
})

test('affirmative control uses the dedicated session confirmation API', () => {
  assert.match(app, /api\.confirmMissedDose\(\{patient_id: patientId, session_id: sessionId/)
  assert.match(api, /\/api\/confirmations\/missed-dose/)
})

test('success and cancel are appended to chat and clear pending UI', () => {
  assert.match(app, /role: 'assistant', text: result\.answer/)
  assert.match(app, /setPending\(null\)/)
  assert.match(app, /role: 'assistant', text: result\.message/)
})
