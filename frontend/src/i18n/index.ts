import { useUiStore } from "../store/uiStore";
import { en } from "./en";
import { tr, type Key } from "./tr";

export type { Key } from "./tr";
export type Lang = "tr" | "en";
const dicts: Record<Lang, Record<Key, string>> = { tr, en };

/** Translate a key; `{name}` placeholders are replaced from `params`. Reads the current language from the store. */
export function t(key: Key, params: Record<string, string | number> = {}): string {
  const lang = useUiStore.getState().lang;
  return dicts[lang][key].replace(/\{(\w+)\}/g, (_, name: string) => String(params[name] ?? ""));
}

/** Hook form: re-renders the component when the language changes. */
export function useT(): typeof t {
  useUiStore((s) => s.lang);
  return t;
}
