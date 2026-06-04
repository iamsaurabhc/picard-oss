/** Normalize Picard version strings (strip leading v, whitespace). */
export function normalizeVersion(raw: string): string {
  return raw.trim().replace(/^v/i, "");
}

/** True only when latest is strictly newer than current (semver-ish x.y.z). */
export function isVersionNewer(latest: string, current: string): boolean {
  const l = normalizeVersion(latest);
  const c = normalizeVersion(current);
  if (!l || !c || l === c) return false;
  const lp = l.split(/[.+_-]/).map((n) => parseInt(n, 10) || 0);
  const cp = c.split(/[.+_-]/).map((n) => parseInt(n, 10) || 0);
  const len = Math.max(lp.length, cp.length);
  for (let i = 0; i < len; i++) {
    const a = lp[i] ?? 0;
    const b = cp[i] ?? 0;
    if (a > b) return true;
    if (a < b) return false;
  }
  return false;
}
