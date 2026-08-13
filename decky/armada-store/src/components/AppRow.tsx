import { ButtonItem, PanelSectionRow } from "@decky/ui";
import type { ReactNode } from "react";
import { stateIcons } from "../icons";
import type { CatalogApp, InstalledInfo, Job } from "../types";

const PHASE_LABELS: Record<string, string> = {
  queued: "Queued",
  resolving: "Finding release",
  downloading: "Downloading",
  installing: "Installing",
  extracting: "Extracting",
  removing: "Removing",
  cancelled: "Cancelled",
  done: "Done",
};

export const TERMINAL_PHASES = ["done", "error", "cancelled"];

export function jobLabel(job: Job): string {
  if (job.phase === "error") return job.error || "Failed";
  const label = PHASE_LABELS[job.phase] || job.phase;
  return job.percent != null ? `${label} ${job.percent}%` : label;
}

export function AppRow({ app, job, info, updateAvailable, onMenu }: {
  app: CatalogApp;
  job: Job | null;
  info: InstalledInfo | null;
  updateAvailable: boolean;
  onMenu: () => void;
}) {
  const active = !!job && !TERMINAL_PHASES.includes(job.phase);
  const failed = job?.phase === "error";
  const installed = !!info?.installed;
  let state: ReactNode = null;
  let stateClass = "armada-store-row-state";
  if (active && job) state = job.percent != null ? `${job.percent}%` : "...";
  else if (failed) {
    state = stateIcons.error;
    stateClass += " armada-store-error";
  } else if (installed && updateAvailable) {
    state = stateIcons.update;
    stateClass += " armada-store-update";
  } else if (installed) state = stateIcons.installed;
  return (
    <PanelSectionRow>
      <ButtonItem layout="below" onClick={onMenu}>
        <div className="armada-store-row">
          {app.icon ? (
            <img src={app.icon} alt="" loading="lazy" />
          ) : (
            <div className="armada-store-icon-fallback">{(app.name || "?").slice(0, 1).toUpperCase()}</div>
          )}
          <div className="armada-store-row-text">
            <div className="armada-store-row-name">{app.name}</div>
            {active && job?.percent != null && (
              <div className="armada-store-progress">
                <div style={{ width: `${Math.max(0, Math.min(100, job.percent))}%` }} />
              </div>
            )}
          </div>
          {state && <div className={stateClass}>{state}</div>}
        </div>
      </ButtonItem>
    </PanelSectionRow>
  );
}
