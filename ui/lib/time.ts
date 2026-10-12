const HAS_OFFSET = /(Z|[+-]\d\d:?\d\d)$/;

export function parseServerTime(s: string): Date {
  return new Date(s.includes("T") && !HAS_OFFSET.test(s) ? `${s}Z` : s);
}
