import { useCallback, useEffect, useRef, useState } from "react";

export const MAX_DICTATION_MS = 30_000;
const TICK_MS = 250;
/** Below this the transcript is treated as uncertain and the person is told to check it. */
const LOW_CONFIDENCE = 0.7;

export type DictationStatus =
  | "checking"
  /** No recognizer, or no way to prove the audio would stay on this device. */
  | "unsupported"
  /** The browser can do it locally once its on-device model is downloaded. */
  | "needs-setup"
  | "installing"
  | "idle"
  | "listening";

/** Why the microphone is unavailable, so the panel can say something specific. */
export type DictationBlocker = "insecure-context" | "no-recognizer" | "no-local-mode" | "language" | null;

type Options = {
  /** BCP-47 tag from the patient record; falls back to the browser default. */
  language: string;
  onTranscript: (text: string, note: string) => void;
};

const ERROR_MESSAGES: Record<string, string> = {
  "not-allowed": "Microphone access was refused. You can allow it in your browser settings, or upload a written transcript instead.",
  "service-not-allowed": "This browser would not transcribe on the device, so nothing was recorded.",
  "no-speech": "I did not hear anything. Please try again, or upload a written transcript.",
  "audio-capture": "No microphone was found on this device.",
  "language-not-supported": "This device cannot transcribe that language locally.",
  network: "On-device transcription is unavailable. Nothing was sent anywhere, and nothing was recorded.",
};

/**
 * Dictation that never leaves the device.
 *
 * The microphone is offered only when the browser reports that the language can be
 * transcribed locally, and `processLocally` is set so the browser fails rather than
 * streaming audio to a server. The transcript is handed back for the person to read and
 * correct — it is never submitted automatically, because a spoken phrase can route to a
 * dose-recording action and rules.md requires explicit confirmation first.
 */
export function useLocalDictation({ language, onTranscript }: Options) {
  const [status, setStatus] = useState<DictationStatus>("checking");
  const [blocker, setBlocker] = useState<DictationBlocker>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [partial, setPartial] = useState("");
  const [error, setError] = useState("");

  const recognitionRef = useRef<LocalSpeechRecognition | null>(null);
  const tickRef = useRef<number | null>(null);
  const finalRef = useRef("");
  const confidenceRef = useRef(1);
  const startedAtRef = useRef(0);
  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;

  const probe = useCallback(async (): Promise<{ status: DictationStatus; blocker: DictationBlocker }> => {
    const Recognition = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    // Microphone access needs a secure origin; localhost counts.
    if (!window.isSecureContext) return { status: "unsupported", blocker: "insecure-context" };
    if (!Recognition) return { status: "unsupported", blocker: "no-recognizer" };
    // Without an availability probe there is no way to prove the audio stays on this
    // device, so the microphone stays off rather than risk it reaching a server.
    if (!(Recognition.available || Recognition.availableOnDevice)) {
      return { status: "unsupported", blocker: "no-local-mode" };
    }
    try {
      const availability = Recognition.available
        ? await Recognition.available({ langs: [language], processLocally: true })
        : await Recognition.availableOnDevice!(language);
      if (availability === "available") return { status: "idle", blocker: null };
      if (availability === "downloading") return { status: "installing", blocker: null };
      if (availability === "downloadable") return { status: "needs-setup", blocker: null };
      return { status: "unsupported", blocker: "language" };
    } catch {
      return { status: "unsupported", blocker: "no-local-mode" };
    }
  }, [language]);

  useEffect(() => {
    let cancelled = false;
    void probe().then((result) => {
      if (cancelled) return;
      setStatus(result.status);
      setBlocker(result.blocker);
    });
    return () => {
      cancelled = true;
    };
  }, [probe]);

  /**
   * Downloads the browser's own on-device speech model, on an explicit click. This fetches
   * a browser-managed model; no audio is captured or sent, and recognition stays local.
   */
  const install = useCallback(async () => {
    const Recognition = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    const installer = Recognition?.install ?? Recognition?.installOnDevice;
    if (!Recognition || !installer) return;
    setStatus("installing");
    setError("");
    try {
      await (Recognition.install
        ? Recognition.install({ langs: [language], processLocally: true })
        : Recognition.installOnDevice!(language));
    } catch {
      setError("The on-device voice model could not be set up. You can upload a written transcript instead.");
    }
    const result = await probe();
    setStatus(result.status);
    setBlocker(result.blocker);
  }, [language, probe]);

  const clearTick = useCallback(() => {
    if (tickRef.current !== null) {
      window.clearInterval(tickRef.current);
      tickRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
  }, []);

  const start = useCallback(() => {
    const Recognition = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!Recognition || recognitionRef.current) return;

    const recognition = new Recognition();
    recognition.lang = language;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    recognition.processLocally = true;

    finalRef.current = "";
    confidenceRef.current = 1;
    startedAtRef.current = Date.now();
    setPartial("");
    setError("");
    setElapsedMs(0);

    recognition.onstart = () => {
      setStatus("listening");
      clearTick();
      tickRef.current = window.setInterval(() => {
        const elapsed = Date.now() - startedAtRef.current;
        setElapsedMs(elapsed);
        if (elapsed >= MAX_DICTATION_MS) recognition.stop();
      }, TICK_MS);
    };

    recognition.onresult = (event) => {
      let interim = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const alternative = result[0];
        if (result.isFinal) {
          finalRef.current = `${finalRef.current} ${alternative.transcript}`.trim();
          if (typeof alternative.confidence === "number" && alternative.confidence > 0) {
            confidenceRef.current = Math.min(confidenceRef.current, alternative.confidence);
          }
        } else {
          interim += alternative.transcript;
        }
      }
      setPartial(interim.trim());
    };

    recognition.onerror = (event) => {
      setError(ERROR_MESSAGES[event.error] ?? "Recording stopped before anything could be understood.");
    };

    recognition.onend = () => {
      clearTick();
      recognitionRef.current = null;
      setStatus("idle");
      setPartial("");
      const heard = finalRef.current.trim();
      const seconds = Math.max(1, Math.round((Date.now() - startedAtRef.current) / 1000));
      setElapsedMs(0);
      if (!heard) return;
      const uncertain = confidenceRef.current < LOW_CONFIDENCE;
      const note = uncertain
        ? `Heard ${seconds} second${seconds === 1 ? "" : "s"} of speech, but parts were unclear. Please read the words above and correct them before you ask.`
        : `Heard ${seconds} second${seconds === 1 ? "" : "s"} of speech. The words above are what I understood — correct them if they are wrong, then choose Ask.`;
      onTranscriptRef.current(heard, note);
    };

    recognitionRef.current = recognition;
    try {
      recognition.start();
    } catch {
      recognitionRef.current = null;
      setStatus("idle");
      setError("Recording could not be started.");
    }
  }, [clearTick, language]);

  useEffect(
    () => () => {
      clearTick();
      recognitionRef.current?.abort();
      recognitionRef.current = null;
    },
    [clearTick],
  );

  return {
    status,
    blocker,
    listening: status === "listening",
    ready: status === "idle" || status === "listening",
    needsSetup: status === "needs-setup",
    installing: status === "installing",
    elapsedMs,
    partial,
    error,
    clearError: () => setError(""),
    install,
    start,
    stop,
  };
}
