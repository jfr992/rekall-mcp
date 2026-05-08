import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// Polyfill ResizeObserver used by react-force-graph-2d
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).ResizeObserver = ResizeObserverStub;

// Mock next/font — real loader requires a real Next.js build context
vi.mock("next/font/local", () => ({
  default: () => ({
    variable: "--font-mocked",
    className: "font-mocked",
    style: { fontFamily: "mock" },
  }),
}));
