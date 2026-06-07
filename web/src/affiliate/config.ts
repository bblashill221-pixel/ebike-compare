// Per-brand affiliate configuration.
//
// This is a STATIC, client-side site, so any affiliate code here is inherently
// public (it appears in the outbound URL). Nothing secret lives here.
//
// TODO: fill in each brand's real program + code. Until a brand has a non-empty
// `code`, affiliateUrl() falls back to the plain product URL (no tracking, no harm).
//
// Two program shapes are supported:
//   - "param":   append a referral query param to the product URL (?<param>=<code>)
//   - "deeplink":route the product URL through an affiliate-network deep link
//                (Impact / ShareASale / AvantLink / CJ ...), wrapping the encoded URL
//   - "none":    no program; always use the plain URL

export type AffiliateProgram =
  | { type: "none" }
  | { type: "param"; param: string; code: string }
  | { type: "deeplink"; template: string; code: string };

// `template` for deeplink: use {URL} for the encoded product url and {CODE} for the code.
// e.g. "https://goto.example.com/c/{CODE}?u={URL}"
export const AFFILIATE: Record<string, AffiliateProgram> = {
  aventon: { type: "param", param: "ref", code: "" },
  blix: { type: "param", param: "ref", code: "" },
  euphree: { type: "param", param: "ref", code: "" },
  evelo: { type: "param", param: "ref", code: "" },
  heybike: { type: "param", param: "ref", code: "" },
  himiway: { type: "param", param: "ref", code: "" },
  lectric: { type: "param", param: "ref", code: "" },
  mokwheel: { type: "param", param: "ref", code: "" },
  monarc: { type: "param", param: "ref", code: "" },
  priority: { type: "param", param: "ref", code: "" },
  ride1up: { type: "param", param: "ref", code: "" },
  specialized: { type: "param", param: "ref", code: "" },
  tern: { type: "param", param: "ref", code: "" },
  velotric: { type: "param", param: "ref", code: "" },
  velowave: { type: "param", param: "ref", code: "" },
  vvolt: { type: "param", param: "ref", code: "" },
};

export const DEFAULT_PROGRAM: AffiliateProgram = { type: "none" };
