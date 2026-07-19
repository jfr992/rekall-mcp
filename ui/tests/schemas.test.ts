import { describe, test, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

import {
  HealthSchema,
  GraphResponseSchema,
  KbResponseSchema,
  PressureResponseSchema,
  PrunePlanSchema,
  PruneApplyResponseSchema,
  BackfillReportSchema,
  DetailResponseSchema,
  DetailResponseV2Schema,
  ResumeResponseSchema,
  ByEntityResponseSchema,
  InsightsResponseSchema,
  StreamResponseSchema,
} from "@/lib/schemas";

const FIXTURES = path.join(__dirname, "fixtures");

function load(name: string): unknown {
  return JSON.parse(fs.readFileSync(path.join(FIXTURES, name), "utf-8"));
}

describe("schemas parse real fixtures", () => {
  test("HealthSchema", () => {
    expect(HealthSchema.parse(load("health.json"))).toMatchObject({ status: "healthy" });
  });

  test("GraphResponseSchema", () => {
    const parsed = GraphResponseSchema.parse(load("graph.json"));
    expect(parsed.graph?.nodes.length).toBe(2);
    expect(parsed.graph?.links.length).toBe(1);
  });

  test("KbResponseSchema", () => {
    const parsed = KbResponseSchema.parse(load("kb.json"));
    expect(parsed.decisions.length).toBe(1);
    expect(parsed.requirements.length).toBe(1);
    expect(parsed.preferences.length).toBe(1);
    expect(parsed.learnings.length).toBe(1);
  });

  test("PressureResponseSchema", () => {
    const parsed = PressureResponseSchema.parse(load("pressure.json"));
    expect(parsed.flagged.stale_working_count).toBe(8);
  });

  test("PressureResponseSchema parses disputed and stale_candidates flagged lists (T5)", () => {
    const parsed = PressureResponseSchema.parse(load("pressure.json"));
    expect(parsed.flagged.disputed_count).toBe(1);
    expect(parsed.flagged.disputed[0].memory_id).toBe("d1");
    expect(parsed.flagged.stale_candidates_count).toBe(1);
    expect(parsed.flagged.stale_candidates[0].memory_id).toBe("s1");
  });

  test("PrunePlanSchema", () => {
    const parsed = PrunePlanSchema.parse(load("prune-plan.json"));
    expect(parsed.candidates.length).toBe(2);
    expect(parsed.plan_id).toHaveLength(32);
  });

  test("PruneApplyResponseSchema", () => {
    expect(PruneApplyResponseSchema.parse(load("prune-apply.json")).deleted).toEqual(["w1", "w2"]);
  });

  test("BackfillReportSchema", () => {
    expect(BackfillReportSchema.parse(load("backfill.json")).total).toBe(53);
  });

  test("DetailResponseSchema", () => {
    const parsed = DetailResponseSchema.parse(load("detail.json"));
    expect(parsed.memory?.memory_id).toBe("2026-04-01_decision_abc12345");
    expect(parsed.neighbors.length).toBe(1);
  });

  test("ResumeResponseSchema", () => {
    expect(ResumeResponseSchema.parse(load("resume.json")).truncated).toBe(false);
  });

  test("ByEntityResponseSchema", () => {
    const parsed = ByEntityResponseSchema.parse(load("by-entity.json"));
    expect(parsed.entity).toBe("MetalLB");
    expect(parsed.memories[0].entities).toContain("MetalLB");
  });

  test("DetailResponseV2Schema parses v2 fixture with all new fields", () => {
    const parsed = DetailResponseV2Schema.parse(load("detail-v2.json"));
    expect(parsed.memory?.memory_id).toBe("2026-07-01_decision_abc1");
    // relationships: both directions
    expect(parsed.relationships?.length).toBe(2);
    const directions = parsed.relationships?.map((r) => r.direction);
    expect(directions).toContain("in");
    expect(directions).toContain("out");
    // neighbors compat alias: outgoing only
    expect(parsed.neighbors.length).toBe(1);
    expect(parsed.neighbors[0].relation).toBe("depends_on");
    // provenance
    expect(parsed.provenance?.agent).toBe("claude-code");
    expect(parsed.provenance?.trust_boundary).toBe("public");
    // lifecycle
    expect(parsed.lifecycle?.tier).toBe("working");
    expect(parsed.lifecycle?.retention_days).toBe(90);
    // storage
    expect(parsed.storage?.qdrant).toBe(true);
    expect(parsed.storage?.yaml).toBe(false);
    // warnings
    expect(parsed.warnings).toEqual([]);
  });

  test("DetailResponseV2Schema also parses v1 fixture (backward compat)", () => {
    const parsed = DetailResponseV2Schema.parse(load("detail.json"));
    expect(parsed.memory?.memory_id).toBe("2026-04-01_decision_abc12345");
    expect(parsed.neighbors.length).toBe(1);
    // v2-only fields absent in v1 fixture are undefined
    expect(parsed.relationships).toBeUndefined();
    expect(parsed.provenance).toBeUndefined();
    expect(parsed.lifecycle).toBeUndefined();
  });

  test("InsightsResponseSchema", () => {
    const parsed = InsightsResponseSchema.parse(load("insights.json"));
    expect(parsed.in_scope).toBe(41);
    expect(parsed.per_week.length).toBe(10);
    expect(parsed.avg_top_score_denominator).toBe(19);
    expect(parsed.tier_counts.identity).toBe(2);
    expect(parsed.event_window.events).toBe(5000);
  });

  test("StreamResponseSchema parses every row kind", () => {
    const parsed = StreamResponseSchema.parse(load("stream.json"));
    expect(parsed.rows.map((r) => r.kind)).toEqual([
      "saved",
      "recalled",
      "recalled",
      "promoted",
      "consolidated",
    ]);
    const saved = parsed.rows[0];
    if (saved.kind !== "saved") throw new Error("expected saved row");
    expect(saved.payload.fades_in_hours).toBe(311);
    const miss = parsed.rows[2];
    if (miss.kind !== "recalled") throw new Error("expected recalled row");
    expect(miss.payload.memory_ids).toEqual([]);
    expect(miss.payload.top_score).toBeNull();
    expect(parsed.event_window.events).toBe(4211);
  });

  test("StreamRecalledRowSchema keeps capture_origin on recalled rows", () => {
    const parsed = StreamResponseSchema.parse(load("stream.json"));
    const recalled = parsed.rows[1];
    if (recalled.kind !== "recalled") throw new Error("expected recalled row");
    // schema must not strip the field — the feed renders it when query is null
    expect(recalled.payload.capture_origin).toBe("recall");
  });
});
