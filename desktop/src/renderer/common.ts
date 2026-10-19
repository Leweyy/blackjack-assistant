import type { ActionName } from "../shared/types";

export const ACTION_COLORS: Record<ActionName | "IDLE" | "RAISE", string> = {
  HIT: "#2e7d32",
  STAND: "#c62828",
  DOUBLE: "#d89b06",
  SPLIT: "#1565c0",
  SURRENDER: "#6a1b9a",
  INSURANCE: "#00838f",
  NO_INSURANCE: "#5d4037",
  RAISE: "#00897b",
  IDLE: "#2b323c",
};

export function adviceColor(action: ActionName | null, betUnits: number | null): string {
  if (action) return ACTION_COLORS[action];
  if (betUnits && betUnits > 1) return ACTION_COLORS.RAISE;
  return ACTION_COLORS.IDLE;
}

/** Electron wraps errors from the main process; show only the useful part. */
export function errorMessage(err: unknown): string {
  const text = err instanceof Error ? err.message : String(err);
  return text.replace(/^Error invoking remote method '[^']+': (Error: )?/, "");
}
