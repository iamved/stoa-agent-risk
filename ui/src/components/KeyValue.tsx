import type { ReactNode } from "react";

export function KeyValue({ rows }: { rows: { k: string; v: ReactNode; flag?: boolean }[] }) {
  return (
    <dl className="grid grid-cols-[minmax(110px,auto)_1fr] gap-x-4 gap-y-1.5 m-0 text-[13px]">
      {rows.map((r) => (
        <div key={r.k} className="contents">
          <dt className="caption">{r.k}</dt>
          <dd className={`m-0 min-w-0 break-words ${r.flag ? "text-sev-high font-medium" : ""}`}>{r.v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Chips({ items, empty = "none", tone }: { items: { label: string; hot?: boolean; title?: string }[]; empty?: string; tone?: "mono" }) {
  if (!items.length) return <span className="caption">{empty}</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((i) => (
        <span key={i.label} title={i.title} className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11.5px] leading-none ${i.hot ? "border-sev-high/40 bg-sev-high-bg text-sev-high" : "border-line bg-paper"} ${tone === "mono" ? "mono" : ""}`}>
          {i.label}
        </span>
      ))}
    </span>
  );
}
