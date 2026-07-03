import { typeColor, tierColor } from "@/lib/theme";

/** Escape characters that are unsafe in HTML attribute and text contexts. */
export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}

type TooltipNode = {
  type?: string | null;
  tier?: string | null;
  content?: string | null;
  degree?: number | null;
};

/** Build the HTML string for a brain-canvas node tooltip with all user content escaped. */
export function buildNodeTooltip(node: TooltipNode): string {
  const type = escapeHtml(node.type ?? "memory");
  const tier = escapeHtml(node.tier ?? "working");
  const content = escapeHtml((node.content ?? "").slice(0, 90));
  const deg = node.degree ?? 0;
  const typeHex = typeColor(node.type ?? undefined);
  const tierHex = tierColor(node.tier ?? undefined);

  return [
    `<div style="background:rgba(8,12,28,0.95);border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:10px 14px;max-width:300px;font-family:Inter,system-ui,sans-serif;box-shadow:0 8px 32px rgba(0,0,0,0.6);">`,
    `<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px;">`,
    `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${typeHex};box-shadow:0 0 8px ${typeHex};"></span>`,
    `<span style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.1em;color:${typeHex};">${type}</span>`,
    `<span style="font-size:10px;color:${tierHex};opacity:0.7;">${tier}</span>`,
    `<span style="font-size:10px;color:rgba(255,255,255,0.3);margin-left:auto;">${deg} links</span>`,
    `</div>`,
    `<div style="font-size:13px;color:rgba(234,240,255,0.9);line-height:1.5;">${content}</div>`,
    `</div>`,
  ].join("");
}
