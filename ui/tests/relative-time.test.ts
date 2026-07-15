import { describe, test, expect } from "vitest";
import { relativeTime } from "@/lib/relative-time";

describe("relativeTime", () => {
  test("formats seconds, minutes, hours, days and null", () => {
    const now = new Date("2026-07-14T12:00:00Z").getTime();
    expect(relativeTime("2026-07-14T11:59:30Z", now)).toBe("30s ago");
    expect(relativeTime("2026-07-14T11:15:00Z", now)).toBe("45m ago");
    expect(relativeTime("2026-07-14T09:00:00Z", now)).toBe("3h ago");
    expect(relativeTime("2026-07-11T12:00:00Z", now)).toBe("3d ago");
    expect(relativeTime(null, now)).toBe("—");
    expect(relativeTime("not-a-date", now)).toBe("—");
  });
});
