import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icons";
import type { Delta } from "../data/selectors";

/** A headline figure with an icon and its change since the baseline. */
export function KpiTile({ icon, label, value, delta, detail, href, tone = "neutral", upIsBad = true }: { icon: IconName; label: string; value: ReactNode; delta: Delta | null; detail?: ReactNode; href?: string; tone?: "neutral" | "warn"; upIsBad?: boolean }) {
  const Glyph = Icon[icon];
  const dir = delta ? (delta.value > 0 ? "up" : delta.value < 0 ? "down" : "flat") : "none";
  const bad = dir === "up" ? upIsBad : dir === "down" ? !upIsBad : false;
  const deltaClass = dir === "flat" || dir === "none" ? "text-ink-muted" : bad ? "text-sev-high" : "text-ok";
  const body = (
    <div className="panel p-4 h-full flex gap-3.5">
      <span className="kpi-icon" aria-hidden="true"><Glyph /></span>
      <div className="min-w-0 flex-1">
        <div className="text-[12.5px] text-ink-muted leading-snug">{label}</div>
        <div className={`num text-[26px] leading-none mt-1 ${tone === "warn" ? "text-sev-high" : "text-navy"}`}>{value}</div>
        <div className="mt-1.5 text-[12px] leading-snug">
          {delta ? (
            <span className={`inline-flex items-center gap-1 ${deltaClass}`} title={delta.label}>
              <span aria-hidden="true">{dir === "up" ? "▲" : dir === "down" ? "▼" : "•"}</span>
              <span className="tabular-nums font-medium">{dir === "flat" ? "no change" : `${delta.value > 0 ? "+" : ""}${delta.value}`}</span>
              <span className="text-ink-muted">since last scan</span>
            </span>
          ) : detail ? <span className="text-ink-muted">{detail}</span> : <span className="text-ink-muted">no baseline</span>}
        </div>
      </div>
    </div>
  );
  return href ? <a href={href} className="block rounded-xl no-underline">{body}</a> : body;
}
