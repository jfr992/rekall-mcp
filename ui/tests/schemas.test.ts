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
  ResumeResponseSchema,
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
});
