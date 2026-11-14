import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AppShell } from "./components/layout/AppShell";
import { EXAMPLES } from "./lib/examples";
import { useRunStore } from "./store/runStore";
import { initBranchSync } from "./store/branchStore";
import { initMentorSync } from "./store/mentorStore";
import { initViewSync } from "./store/viewStore";
import "./index.css";

initViewSync();
initMentorSync();
initBranchSync();
const first = EXAMPLES.find((e) => e.name === "fib_naive.py") ?? EXAMPLES[0];
if (first) useRunStore.getState().loadExample(first.name, first.source);

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <AppShell />
  </StrictMode>,
);
