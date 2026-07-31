from __future__ import annotations

from gemma.client import OllamaClient
from medication.patient_records import PatientRecordStore

PATIENT_QA_PROMPT = """You answer questions about one synthetic patient record.
Use only facts explicitly present in the supplied record. Never use outside medical
knowledge to fill gaps, make a diagnosis, recommend treatment, or change a dose.
If the record does not contain the answer, say so plainly. Distinguish medication
orders from documented dose administrations. An empty allergy list with
allergy_status "not_recorded" does not mean the patient has no allergies.
Keep the answer concise and identify which record section supports it. Do not output
JSON or Markdown code fences. Ground factual statements with phrases such as
"According to your saved medication plan" or "Your local record shows". This is
synthetic demo data, not medical advice."""


class PatientQuestionAnswerer:
    def __init__(self, client: OllamaClient, store: PatientRecordStore) -> None:
        self.client = client
        self.store = store

    def answer(self, patient_key: str, question: str) -> str:
        normalized = " ".join(question.strip().split())
        if not normalized:
            raise ValueError("Enter a question about the selected patient.")
        from medication.safety import check_safety
        safety = check_safety(normalized)
        if safety.unsafe:
            return safety.response or "I cannot provide medication or treatment advice."
        context = self.store.llm_context(patient_key)
        user_prompt = f"PATIENT RECORD:\n{context}\n\nQUESTION:\n{normalized}"
        return self.client.chat(PATIENT_QA_PROMPT, user_prompt, json_output=False)
