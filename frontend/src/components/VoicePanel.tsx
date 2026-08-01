import { useRef } from "react";
import { Copy } from "./Copy";
import { Icon } from "./Icon";
import { MAX_DICTATION_MS, useLocalDictation, type DictationBlocker } from "../useLocalDictation";
import { parseTranscript } from "../transcript";

type VoicePanelProps = {
  language: string;
  disabled: boolean;
  /** Places the words in the question box. Never submits — the person confirms by choosing Ask. */
  onTranscript: (text: string, note: string) => void;
};

export function VoicePanel({ language, disabled, onTranscript }: VoicePanelProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const dictation = useLocalDictation({ language, onTranscript });

  function readTranscriptFile(file: File) {
    const reader = new FileReader();
    reader.onerror = () => onTranscript("", "That file could not be read on this device.");
    reader.onload = () => {
      const result = parseTranscript(String(reader.result ?? ""));
      if (!result.ok) {
        onTranscript("", result.reason);
        return;
      }
      onTranscript(
        result.text,
        `Read ${result.words} word${result.words === 1 ? "" : "s"} from ${file.name}. The file was read on this device and was not uploaded anywhere. Check the words, then choose Ask.`,
      );
    };
    reader.readAsText(file);
  }

  const seconds = Math.floor(dictation.elapsedMs / 1000);
  const percent = Math.min(100, (dictation.elapsedMs / MAX_DICTATION_MS) * 100);

  return (
    <>
      <div className="ask-tools-row">
        {dictation.listening ? (
          <button type="button" className="btn btn-accent" onClick={dictation.stop}>
            <Icon name="stop" size={22} strokeWidth={2.5} />
            <Copy plain="Stop and use these words" simple="Stop" />
          </button>
        ) : dictation.needsSetup ? (
          <button type="button" className="btn btn-outline-strong" disabled={disabled} onClick={() => void dictation.install()}>
            <Icon name="microphone" size={24} strokeWidth={2.5} />
            <Copy plain="Set up voice on this device" simple="Turn on the microphone" />
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-ink"
            disabled={disabled || !dictation.ready || dictation.installing}
            onClick={dictation.start}
          >
            <Icon name="microphone" size={24} strokeWidth={2.5} />
            {dictation.installing ? (
              <Copy plain="Setting up voice…" simple="Getting ready…" />
            ) : (
              <Copy plain="Record your voice" simple="Speak instead" />
            )}
          </button>
        )}

        <label className={`btn file-button${disabled ? " is-disabled" : ""}`}>
          <Icon name="upload" size={22} strokeWidth={2.5} />
          <Copy plain="Upload a transcript" simple="Use a text file" />
          <input
            ref={fileRef}
            className="sr-only"
            type="file"
            accept=".txt,.vtt,text/plain,text/vtt"
            disabled={disabled}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) readTranscriptFile(file);
            }}
          />
        </label>

        <span className="ask-tools-note">
          <VoiceNote
            ready={dictation.ready}
            needsSetup={dictation.needsSetup}
            installing={dictation.installing}
            blocker={dictation.blocker}
          />
        </span>
      </div>

      {dictation.listening && (
        <div className="listening">
          <div className="listening-head">
            <span className="listening-dot" aria-hidden="true" />
            <span className="listening-label" role="status">
              <Copy plain="Listening" simple="Listening" />
            </span>
            <span className="tabular muted">{seconds} of 30 seconds</span>
          </div>
          <div
            className="progress-track"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={30}
            aria-valuenow={seconds}
            aria-label="Recording time used"
          >
            <div className="progress-fill" style={{ width: `${percent}%` }} />
          </div>
          {/* Visual feedback only: partial text changes too fast to announce usefully. */}
          <p className="listening-partial" aria-hidden="true">
            {dictation.partial || "…"}
          </p>
        </div>
      )}

      {dictation.error && (
        <p className="ask-hint" role="status">
          <Icon name="info" size={20} />
          <span>{dictation.error}</span>
        </p>
      )}
    </>
  );
}

function VoiceNote({
  ready,
  needsSetup,
  installing,
  blocker,
}: {
  ready: boolean;
  needsSetup: boolean;
  installing: boolean;
  blocker: DictationBlocker;
}) {
  if (ready) {
    return (
      <Copy
        plain="Up to 30 seconds. Your voice is transcribed on this device and no audio is sent anywhere."
        simple="30 seconds at most. Your voice stays on this device."
      />
    );
  }
  if (installing) {
    return (
      <Copy
        plain="Downloading this browser's on-device voice model. It is a one-time download, and no audio is being recorded."
        simple="Getting the microphone ready. This happens once."
      />
    );
  }
  if (needsSetup) {
    return (
      <Copy
        plain="Your browser can transcribe speech on this device once it downloads its voice model. That is a one-time download; your voice is never sent anywhere."
        simple="Your browser needs to get set up once. After that your voice stays here."
      />
    );
  }
  if (blocker === "insecure-context") {
    return (
      <Copy
        plain="The microphone needs a secure address. Open the app on localhost, and a written transcript is read locally in the meantime."
        simple="The microphone needs a safe address. Use a text file for now."
      />
    );
  }
  if (blocker === "language") {
    return (
      <Copy
        plain="This device cannot transcribe your recorded language locally, so the microphone is off. A written transcript is read locally instead."
        simple="No microphone for this language. You can use a text file."
      />
    );
  }
  return (
    <Copy
      plain="This browser cannot promise to transcribe speech on the device, so the microphone is off. Chrome 138 or later supports it. A written transcript is read locally instead."
      simple="No microphone in this browser. You can use a text file instead."
    />
  );
}
