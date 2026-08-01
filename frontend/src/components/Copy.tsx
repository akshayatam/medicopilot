import { createContext, useContext } from "react";

/**
 * Simplified language is a display preference. Only the selected wording is rendered so
 * assistive technology never announces both variants.
 */
export const SimplifiedContext = createContext(false);

export function useSimplified(): boolean {
  return useContext(SimplifiedContext);
}

export function Copy({ plain, simple }: { plain: string; simple: string }) {
  return <>{useSimplified() ? simple : plain}</>;
}

export function pick(simplified: boolean, plain: string, simple: string): string {
  return simplified ? simple : plain;
}
