/**
 * Warning noise filter.
 *
 * The pipeline emits a lot of low-signal warnings about population priors and
 * default fills ("using population prior", "applied default", "uncertainty
 * elevated", ...). Clinicians don't care about those — only real issues should
 * surface (safety, numeric mismatches, evidence conflicts, impossible
 * physiology, failures). This drops the prior/default noise and keeps the rest.
 */

const NOISE =
  /\b(priors?|population|uncertainty elevated|not provided|applied\b[^.]*\bdefault|left unset|no evidence|kept as reported|conservative)\b/i;

export function isNoiseWarning(w: string): boolean {
  return NOISE.test(w);
}

export function realWarnings(list: readonly string[] | null | undefined): string[] {
  return (list ?? []).filter((w) => typeof w === "string" && !isNoiseWarning(w));
}
