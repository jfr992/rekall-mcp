import { describe, expect, test } from "vitest";
import { parseServerTime } from "@/lib/time";

describe("parseServerTime", () => {
  test("offset-less timestamp is UTC", () => {
    expect(parseServerTime("2026-10-10T21:27:44").getTime()).toBe(Date.UTC(2026, 9, 10, 21, 27, 44));
  });
  test("microseconds are accepted", () => {
    expect(parseServerTime("2026-10-10T21:27:44.550165").getTime()).toBe(Date.UTC(2026, 9, 10, 21, 27, 44, 550));
  });
  test("Z and numeric offsets are respected", () => {
    const t = Date.UTC(2026, 9, 10, 21, 27, 44);
    expect(parseServerTime("2026-10-10T21:27:44Z").getTime()).toBe(t);
    expect(parseServerTime("2026-10-10T21:27:44+00:00").getTime()).toBe(t);
    expect(parseServerTime("2026-10-10T17:27:44-04:00").getTime()).toBe(t);
  });
  test("date-only strings are left to the caller (parsed as given)", () => {
    expect(parseServerTime("2026-10-10").getTime()).toBe(new Date("2026-10-10").getTime());
  });
});
