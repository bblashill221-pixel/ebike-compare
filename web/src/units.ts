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

export const inToCm = (inches: number): number => Math.round(inches * 2.54);
export const cmToIn = (cm: number): number => cm / 2.54;

/** inches -> whole feet + remaining inches, e.g. 70 -> { ft: 5, in: 10 }. */
export function inToFtIn(inches: number): { ft: number; in: number } {
  const total = Math.round(inches);
  return { ft: Math.floor(total / 12), in: total % 12 };
}

export const ftInToIn = (ft: number, inch: number): number => ft * 12 + inch;
