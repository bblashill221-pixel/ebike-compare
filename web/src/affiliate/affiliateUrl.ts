import { AFFILIATE, DEFAULT_PROGRAM, type AffiliateProgram } from "./config";

export function programFor(brand: string): AffiliateProgram {
  return AFFILIATE[brand?.toLowerCase()] ?? DEFAULT_PROGRAM;
}

/** True when this brand has a configured affiliate code (so the link is monetized). */
export function isAffiliate(brand: string): boolean {
  const p = programFor(brand);
  return p.type !== "none" && !!p.code;
}

/**
 * Tracked outbound URL for a product. Falls back to the plain url whenever the
 * brand has no configured code yet, so links always work.
 */
export function affiliateUrl(brand: string, url: string): string {
  const p = programFor(brand);
  if (p.type === "none" || !p.code || !url) return url;
  try {
    if (p.type === "param") {
      const u = new URL(url);
      u.searchParams.set(p.param, p.code);
      return u.toString();
    }
    // deeplink
    return p.template
      .replace("{URL}", encodeURIComponent(url))
      .replace("{CODE}", encodeURIComponent(p.code));
  } catch {
    return url;
  }
}
