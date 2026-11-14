import { useEffect, useRef } from "react";
import { jumpScene, holdMs, sceneIndexAt } from "../../lib/scenes";
import { useMentorStore } from "../../store/mentorStore";
import { SPEEDS, usePlayback } from "../../store/playbackStore";
import { getRunData, useRunStore } from "../../store/runStore";
import { useUiStore } from "../../store/uiStore";

const BASE_STEPS_PER_SECOND = 6;

/** Play loop + keyboard shortcuts for the whole app (mounted once). In presentation mode the loop pauses at the
 *  start of every scene long enough to read its narration, so playback and narration advance together. */
export function usePlayer(): void {
  const playing = usePlayback((s) => s.playing);
  const acc = useRef(0);
  const holdUntil = useRef(0);
  const heldScene = useRef(-1);

  useEffect(() => {
    if (!playing) return;
    heldScene.current = -1;
    const id = window.setInterval(() => {
      if (Date.now() < holdUntil.current) return;
      acc.current += BASE_STEPS_PER_SECOND * usePlayback.getState().speed * 0.05;
      const whole = Math.floor(acc.current);
      if (whole < 1) return;
      acc.current -= whole;
      const { step: cur, speed } = usePlayback.getState();
      const max = getRunData().totalSteps;
      if (cur >= max) {
        if (useRunStore.getState().status !== "running") usePlayback.setState({ playing: false });
        return;
      }
      let next = Math.min(cur + whole, max);
      if (useUiStore.getState().presenting) {
        const scenes = useMentorStore.getState().scenes;
        const idx = sceneIndexAt(scenes, next);
        if (idx >= 0 && idx !== heldScene.current) {
          heldScene.current = idx;
          next = scenes[idx].from_step;
          holdUntil.current = Date.now() + holdMs(scenes[idx].text, speed);
        }
      }
      usePlayback.setState({ step: next, follow: false });
    }, 50);
    return () => window.clearInterval(id);
  }, [playing]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      const target = e.target as HTMLElement;
      const tag = target.tagName;
      const presenting = useUiStore.getState().presenting;
      if (tag === "TEXTAREA" || tag === "INPUT" || tag === "SELECT") return;
      if (!presenting && target.closest(".monaco-editor")) return;
      const pb = usePlayback.getState();
      if (e.key === " ") { e.preventDefault(); pb.togglePlay(); }
      else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        if (e.shiftKey) {
          const to = jumpScene(useMentorStore.getState().scenes, pb.step, e.key === "ArrowRight" ? 1 : -1);
          if (to !== null) pb.goTo(to);
        } else if (e.key === "ArrowRight") pb.next();
        else pb.prev();
      } else if (e.key === "[" || e.key === "]") {
        const i = SPEEDS.indexOf(pb.speed as (typeof SPEEDS)[number]);
        const j = Math.max(0, Math.min(SPEEDS.length - 1, (i < 0 ? 2 : i) + (e.key === "]" ? 1 : -1)));
        pb.setSpeed(SPEEDS[j]);
      } else if ((e.key === "f" || e.key === "F") && presenting) {
        if (document.fullscreenElement) void document.exitFullscreen();
        else void document.documentElement.requestFullscreen?.();
      } else if (e.key === "Escape" && presenting) {
        useUiStore.getState().setPresenting(false);
        if (document.fullscreenElement) void document.exitFullscreen();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
