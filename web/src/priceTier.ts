import { useState } from "react";

// The price-tier dropdown selection ("All", "Value", ...). Persisted to
// sessionStorage so the dropdown choice — and therefore the slider's tier-scoped
// bounds — survive navigating to a detail page and back / a reload within the
// session (the slider's adjusted range itself rides along in the persisted
// filters). sessionStorage (not local) so it's a per-session scope.
const KEY = "browse-price-tier";

export function loadPriceTier(): string {
  try {
    return sessionStorage.getItem(KEY) || "All";
  } catch {
    return "All";
  }
}

export function usePriceTier(): [string, (v: string) => void] {
  const [tier, setTierState] = useState<string>(loadPriceTier);
  const setTier = (v: string) => {
    setTierState(v);
    try {
      sessionStorage.setItem(KEY, v);
    } catch {
      /* storage blocked: the dropdown still works for this view */
    }
  };
  return [tier, setTier];
}
