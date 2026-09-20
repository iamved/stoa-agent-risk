import type { ReactNode } from "react";

/** A flat figure tile: label, one number, one line of context. */
export function StatCard({ label, value, detail, href, tone = "neutral" }: { label: string; value: ReactNode; detail?: ReactNode; href?: string; tone?: "neutral" | "gold" | "warn" }) {
  const valueClass = tone === "gold" ? "text-gold" : tone === "warn" ? "text-sev-high" : "text-navy";
  const body = (
    <div className="panel px-4 py-3.5 h-full flex flex-col gap-1">
      <div className="text-[12px] text-ink-muted leading-snug">{label}</div>
      <div className={`num text-[24px] leading-none mt-0.5 ${valueClass}`}>{value}</div>
      {detail ? <div className="caption leading-snug mt-1">{detail}</div> : null}
    </div>
  );
  return href ? (
    <a href={href} className="block rounded-md no-underline hover:[&>div]:border-line-strong">
      {body}
    </a>
  ) : (
    body
  );
}
