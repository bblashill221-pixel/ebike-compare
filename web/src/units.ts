import { useSyncExternalStore } from "react";

// Global imperial/metric preference. Unlike the (session-only) sold-out toggle,
// this is persisted to localStorage so a returning visitor keeps their choice.
// Today only the rider-height filter reads it (input in inches vs millimetres);
// it's structured so other spec displays can adopt it later.
export type UnitSystem = "imperial" | "metric";

const KEY = "units";
const listeners = new Set<() => void>();

function read(): UnitSystem {
  if (typeof localStorage === "undefined") return "imperial";
  return localStorage.getItem(KEY) === "metric" ? "metric" : "imperial";
}

let value: UnitSystem = read();

export function setUnits(v: UnitSystem) {
  value = v;
  try {
    localStorage.setItem(KEY, v);
  } catch {
    // private mode / storage disabled -> stay in-memory for the session
  }
  for (const l of listeners) l();
}

export function useUnits(): [UnitSystem, (v: UnitSystem) => void] {
  const system = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => value,
    () => "imperial" as UnitSystem,
  );
  return [system, setUnits];
}

// ----------------------------- height conversions -----------------------------
// Canonical unit is inches everywhere except the input/display boundary.

export const inToMm = (inches: number): number => Math.round(inches * 25.4);
export const mmToIn = (mm: number): number => mm / 25.4;

/** Short unit label for the active system's length input. */
export const heightUnit = (system: UnitSystem): string =>
  system === "metric" ? "mm" : "in";
