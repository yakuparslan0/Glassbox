import { useT } from "../../i18n";
import { useMentorStore } from "../../store/mentorStore";
import { usePlayback } from "../../store/playbackStore";

/** One-line narration of the scene the playhead is in (bottom of the screen, above the transport bar). */
export function NarrationStrip(): React.ReactElement | null {
  const t = useT();
  const scenes = useMentorStore((s) => s.scenes);
  const step = usePlayback((s) => s.step);
  const scene = scenes.find((s) => step >= s.from_step && step <= s.to_step);
  if (!scene || !scene.text) return null;
  return (
    <div className="px-3 py-1.5 text-sm border-t border-[var(--border)] bg-[#141a24] flex gap-3 items-baseline" aria-live="polite" data-testid="narration">
      <span className="gb-chip shrink-0">{t(scene.source === "llm" ? "mentor.source.llm" : "mentor.source.narrator")}</span>
      <span className="font-semibold shrink-0">{scene.title}</span>
      <span className="truncate" title={scene.text}>{scene.text}</span>
    </div>
  );
}
