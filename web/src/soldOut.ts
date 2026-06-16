import { useSyncExternalStore } from "react";
import type { Model } from "./types";

// Global "show sold out" preference, toggled from the Features filter (default
// OFF: only available models are shown, and every view hides unavailable color
// options). Persisted to localStorage: it is explicitly set and unset by the
// user, and never affected by query-param (quiz link) changes.
const KEY = "show-sold-out";

function load(): boolean {
  try {
    return localStorage.getItem(KEY) === "true";
  } catch {
    return false;
  }
}

let value = load();
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

export function setShowSoldOut(v: boolean) {
  value = v;
  try {
    localStorage.setItem(KEY, String(v));
  } catch {
    /* storage blocked: still works for this session */
  }
  emit();
}

export function useShowSoldOut(): [boolean, (v: boolean) => void] {
  const show = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => value,
    () => value,
  );
  return [show, setShowSoldOut];
}

/** A model is "available" unless every configuration is sold out. */
export function isAvailable(model: Model): boolean {
  return model.availability?.status !== "sold_out";
}
