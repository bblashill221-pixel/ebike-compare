import { useSyncExternalStore } from "react";
import type { Model } from "./types";

// Global "show sold out" preference, toggled from the Features filter. Starts
// OFF (unselected) on each app load, so only available models are shown by
// default; when OFF, Browse hides unavailable models and every view hides
// unavailable color options. Kept in an in-memory store (not persisted) so it's
// shared live between the Browse list and the separate-route detail page during
// a session, but resets to the default on a fresh load.
let value = false;
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

export function setShowSoldOut(v: boolean) {
  value = v;
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
