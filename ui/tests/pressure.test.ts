import { describe, expect, test } from "vitest";
import { attentionCount } from "@/lib/pressure";
import type { PressureResponse } from "@/lib/schemas";

const flagged = (o: object) =>
  ({ stale_working_count: 50, low_value_count: 35, contradiction_count: 2, disputed_count: 0,
     stale_candidates_count: 0, prune_candidates_count: 80, ...o }) as PressureResponse["flagged"];

describe("attentionCount", () => {
  test("counts overlapping prune candidates once", () => expect(attentionCount(flagged({})).total).toBe(82));
  test("falls back to low + stale on older servers", () =>
    expect(attentionCount(flagged({ prune_candidates_count: undefined })).total).toBe(87));
  test("includes disputed and stale candidates", () =>
    expect(attentionCount(flagged({ disputed_count: 1, stale_candidates_count: 2 })).total).toBe(85));
});
