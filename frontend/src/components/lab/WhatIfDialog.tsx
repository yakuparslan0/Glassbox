import { useEffect, useState } from "react";
import { useT } from "../../i18n";
import { useBranchStore } from "../../store/branchStore";
import { useUiStore } from "../../store/uiStore";

export function WhatIfDialog(): React.ReactElement | null {
  const t = useT();
  const target = useUiStore((s) => s.whatIf);
  const open = useUiStore((s) => s.openWhatIf);
  const create = useBranchStore((s) => s.create);
  const [value, setValue] = useState("");

  useEffect(() => {
    setValue(target?.current ?? "");
  }, [target]);
  if (!target) return null;

  const submit = (e: React.FormEvent): void => {
    e.preventDefault();
    open(null);
    void create({ name: target.name, depth: target.depth, step: target.step, literal: value });
  };
  return (
    <div className="gb-modal" role="dialog" aria-modal="true" aria-label={t("whatif.title")}>
      <form className="gb-modal-box" onSubmit={submit}>
        <h2 className="font-semibold mb-1">{t("whatif.title")}</h2>
        <p className="text-xs opacity-70 mb-2">{t("whatif.at", { name: target.name, step: target.step, depth: target.depth })}</p>
        <label className="grid gap-1 text-sm">
          {t("whatif.value")}
          <input autoFocus className="gb-input font-mono" value={value} onChange={(e) => setValue(e.target.value)} />
        </label>
        <p className="text-xs opacity-60 mt-1">{t("whatif.hint")}</p>
        <div className="flex gap-2 justify-end mt-3">
          <button type="button" className="gb-btn" onClick={() => open(null)}>{t("whatif.cancel")}</button>
          <button type="submit" className="gb-btn gb-btn-primary" disabled={!value.trim()}>{t("whatif.run")}</button>
        </div>
      </form>
    </div>
  );
}
