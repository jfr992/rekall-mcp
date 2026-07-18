// Empty project is the all-memories sentinel — no suffix, no dangling separator.
export function scopedTitle(title: string, project: string): string {
  return project ? `${title} · ${project}` : title;
}
