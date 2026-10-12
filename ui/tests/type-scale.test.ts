import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "vitest";

const root = join(__dirname, "..");

test("no text smaller than 11px in app or components", () => {
  const files = ["app", "components"].flatMap((dir) =>
    (readdirSync(join(root, dir), { recursive: true }) as string[])
      .filter((f) => f.endsWith(".tsx"))
      .map((f) => join(dir, f)),
  );
  const offenders = files.filter((f) => /text-\[(8|9|10)(\.\d+)?px\]/.test(readFileSync(join(root, f), "utf8")));
  expect(offenders).toEqual([]);
});
