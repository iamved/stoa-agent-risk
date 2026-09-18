import type { ReactNode } from "react";

export function StatCard({ label, value, detail, href, tone = "neutral" }: { label: string; value: ReactNode; detail?: ReactNode; href?: string; tone?: "neutral" | "gold" | "warn" }) {
  const valueClass = tone === "gold" ? "text-gold" : tone === "warn" ? "text-sev-high" : "text-navy";
  const body = (
    <div className="panel p-4 h-full">
      <div className="caption uppercase tracking-wide text-[11px]">{label}</div>
      <div className={`mt-1 font-serif text-[28px] leading-none ${valueClass}`}>{value}</div>
      {detail ? <div className="caption mt-2">{detail}</div> : null}
    </div>
  );
  return href ? (
    <a href={href} className="block rounded-lg hover:shadow-sm focus-visible:outline-2">
      {body}
    </a>
  ) : (
    body
  );
}
