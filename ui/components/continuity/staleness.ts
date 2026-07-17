const STALE_DAYS = 90;

/** Age label ("5mo", "1y") for memories older than the staleness threshold; null when fresh. */
export function ageBadge(date: string | undefined | null): string | null {
  if (!date) return null;
  const then = new Date(date).getTime();
  if (Number.isNaN(then)) return null;
  const days = (Date.now() - then) / 86_400_000;
  if (days < STALE_DAYS) return null;
  const months = Math.floor(days / 30);
  return months >= 12 ? `${Math.floor(months / 12)}y` : `${months}mo`;
}
