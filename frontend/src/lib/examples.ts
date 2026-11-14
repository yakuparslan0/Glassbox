// The repository's examples/ folder, bundled as raw text (one click loads one).
const raw = import.meta.glob("../../../examples/*.py", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

export const EXAMPLES: { name: string; source: string }[] = Object.entries(raw)
  .map(([path, source]) => ({ name: path.split("/").pop() as string, source }))
  .sort((a, b) => a.name.localeCompare(b.name));
