/**
 * Local transcript-file parsing. Text handling only — this module never interprets
 * medication meaning; the cleaned text is handed to the existing /ask endpoint, which
 * performs the safety check and deterministic routing.
 */

export const MAX_TRANSCRIPT_WORDS = 80;

const WEBVTT_HEADER = /^WEBVTT.*$/im;
const CUE_TIMING = /^\s*(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}\s*-->.*$/gm;
const CUE_NUMBER = /^\s*\d+\s*$/gm;
const CUE_TAG = /<\/?[^>]+>/g;
const SPEAKER_PREFIX = /^\s*[A-Za-z][\w .'-]{0,30}:\s*/gm;

export type TranscriptResult =
  | { ok: true; text: string; words: number }
  | { ok: false; reason: string };

/** Strips WebVTT scaffolding and collapses whitespace, then enforces the length cap. */
export function parseTranscript(raw: string): TranscriptResult {
  const text = raw
    .replace(WEBVTT_HEADER, " ")
    .replace(CUE_TIMING, " ")
    .replace(CUE_NUMBER, " ")
    .replace(CUE_TAG, " ")
    .replace(SPEAKER_PREFIX, " ")
    .replace(/\s+/g, " ")
    .trim();

  if (!text) {
    return { ok: false, reason: "That file had no readable text. Please upload a short written transcript." };
  }

  const words = text.split(" ").length;
  if (words > MAX_TRANSCRIPT_WORDS) {
    return {
      ok: false,
      reason: `That transcript is longer than about 30 seconds of speech (${words} words). Please shorten it to roughly ${MAX_TRANSCRIPT_WORDS} words.`,
    };
  }

  return { ok: true, text, words };
}
