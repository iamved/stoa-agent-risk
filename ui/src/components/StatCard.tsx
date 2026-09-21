import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icons";

/** A headline figure: optional icon, label, one number, one line of context. Same family as KpiTile. */
export function StatCard({ label, value, detail, href, tone = "neutral", icon }: { label: string; value: ReactNode; detail?: ReactNode; href?: string; tone?: "neutral" | "gold" | "warn"; icon?: IconName }) {
  const valueClass = tone === "gold" ? "text-gold-ink" : tone === "warn" ? "text-sev-high" : "text-navy";
  const Glyph = icon ? Icon[icon] : null;
  const body = (
    <div className="panel p-4 h-full flex gap-3.5">
      {Glyph ? <span className="kpi-icon" aria-hidden="true"><Glyph /></span> : null}
      <div className="min-w-0 flex-1">
        <div className="text-[12.5px] text-ink-muted leading-snug">{label}</div>
        <div className={`num text-[26px] leading-none mt-1 ${valueClass}`}>{value}</div>
        {detail ? <div className="caption leading-snug mt-1.5">{detail}</div> : null}
      </div>
    </div>
  );
  return href ? <a href={href} className="block rounded-xl no-underline">{body}</a> : body;
}
