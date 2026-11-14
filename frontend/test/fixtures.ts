import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { RunEvent } from "../src/types/generated";

// Shared with the backend tests: real runner traces with ground-truth `snapshot` events.
const DIR = join(__dirname, "..", "..", "backend", "tests", "fixtures", "traces");

export function fixtureNames(): string[] {
  return readdirSync(DIR)
    .filter((f) => f.endsWith(".ndjson"))
    .map((f) => f.replace(".ndjson", ""))
    .sort();
}

export function loadFixture(name: string): RunEvent[] {
  return readFileSync(join(DIR, `${name}.ndjson`), "utf-8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as RunEvent);
}
