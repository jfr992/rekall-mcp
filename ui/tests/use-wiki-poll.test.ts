import { describe, it, expect } from "vitest";
import { candidatesRefetchInterval } from "@/lib/queries/use-wiki";

describe("candidatesRefetchInterval", () => {
  it("polls every 2s while the job is running", () => {
    expect(candidatesRefetchInterval("running")).toBe(2000);
  });
  it("stops for every other status", () => {
    for (const s of ["idle", "done", "error", "unconfigured", undefined] as const) {
      expect(candidatesRefetchInterval(s)).toBe(false);
    }
  });
});
