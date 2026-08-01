/**
 * Minimal typings for the on-device Web Speech surface.
 *
 * The DOM lib ships the result/event types but not the recognizer itself, and the
 * on-device members (`processLocally`, `available`) are newer still. Only the members
 * this application actually uses are declared.
 */

type SpeechAvailability = "available" | "downloadable" | "downloading" | "unavailable";

interface LocalSpeechRecognition extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  /** When true the browser must transcribe on this device or fail; it never falls back to a server. */
  processLocally: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
}

interface LocalSpeechRecognitionConstructor {
  new (): LocalSpeechRecognition;
  /** Reports whether the language can be transcribed without leaving the device. */
  available?(options: { langs: string[]; processLocally: boolean }): Promise<SpeechAvailability>;
  availableOnDevice?(lang: string): Promise<SpeechAvailability>;
  /** Downloads the browser's on-device speech model for the language. */
  install?(options: { langs: string[]; processLocally: boolean }): Promise<boolean>;
  installOnDevice?(lang: string): Promise<boolean>;
}

interface Window {
  SpeechRecognition?: LocalSpeechRecognitionConstructor;
  webkitSpeechRecognition?: LocalSpeechRecognitionConstructor;
}
