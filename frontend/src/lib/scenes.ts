// Scene navigation helpers for the presentation mode (pure, unit-tested).
export interface SceneRange {
  from_step: number;
  to_step: number;
  text: string;
}

export function sceneIndexAt(scenes: readonly SceneRange[], step: number): number {
  return scenes.findIndex((s) => step >= s.from_step && step <= s.to_step);
}

/** Step to jump to for Shift+←/→: the start of the previous / next scene (previous: the current one if mid-scene). */
export function jumpScene(scenes: readonly SceneRange[], step: number, dir: -1 | 1): number | null {
  if (!scenes.length) return null;
  const at = sceneIndexAt(scenes, step);
  if (dir === 1) return scenes[at < 0 ? 0 : Math.min(at + 1, scenes.length - 1)].from_step;
  if (at < 0) return scenes[0].from_step;
  return scenes[at].from_step < step ? scenes[at].from_step : scenes[Math.max(at - 1, 0)].from_step;
}

/** How long the auto-play pauses at the start of a scene so its narration can be read (shorter at higher speed). */
export function holdMs(text: string, speed: number): number {
  return Math.round(Math.min(8000, Math.max(1500, text.length * 45)) / Math.max(speed, 0.25));
}
