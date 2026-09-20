import { useEffect, useRef, useState } from "react";
import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { printAs } from "../app/print";

/**
 * Who is reviewing this dashboard. A static file cannot authenticate anyone,
 * so this is the applicant identity from .stoa/underwriting.toml, shown as
 * the reviewer, with the actions that used to sit in the top bar.
 */
export function UserMenu() {
  const { envelope } = useApp();
  const id = envelope.assessment.identity;
  const name = id.contact_name.trim() || "Risk officer";
  const title = id.contact_title.trim();
  const company = id.company.trim();
  const declared = Boolean(id.contact_name.trim());
  const initials = name.split(/\s+/).map((p) => p[0] ?? "").join("").slice(0, 2).toUpperCase();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (root.current && !root.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);

  return (
    <div ref={root} className="relative">
      <button type="button" onClick={() => setOpen(!open)} aria-haspopup="menu" aria-expanded={open} className="flex items-center gap-2.5 rounded-md border border-line bg-panel pl-1.5 pr-3 py-1.5 text-left hover:bg-paper" aria-label={`Reviewing as ${name}${title ? `, ${title}` : ""}${company ? ` at ${company}` : ""}`}>
        <span aria-hidden="true" className="w-7 h-7 rounded-full bg-navy text-gold text-[11px] font-semibold flex items-center justify-center">{initials}</span>
        <span className="min-w-0 hidden sm:block">
          <span className="block text-[13px] font-medium text-navy leading-tight truncate max-w-[180px]">{name}</span>
          <span className="block text-[11.5px] text-ink-muted leading-tight truncate max-w-[180px]">{[title, company].filter(Boolean).join(" · ") || "reviewer"}</span>
        </span>
        <span aria-hidden="true" className="text-ink-muted text-[10px]">▾</span>
      </button>
      {open ? (
        <div role="menu" aria-label="Reviewer" className="absolute right-0 mt-1.5 w-72 panel shadow-lg z-30 p-1.5">
          <div className="px-3 py-2 border-b border-line">
            <div className="text-[13px] font-medium text-navy">{name}</div>
            <div className="caption">{[title, company].filter(Boolean).join(" · ") || "No reviewer declared"}</div>
            {!declared ? <div className="caption mt-1">Set your name and title in .stoa/underwriting.toml so the assessment carries the right signatory.</div> : null}
          </div>
          <button role="menuitem" type="button" onClick={() => { setOpen(false); printAs("summary"); }} className="w-full text-left rounded px-3 py-2 text-[13px] hover:bg-paper">Print summary</button>
          <a role="menuitem" href={buildHash("evidence")} onClick={() => setOpen(false)} className="block rounded px-3 py-2 text-[13px] no-underline text-ink hover:bg-paper">Open the insurance assessment</a>
          <div className="px-3 pt-2 pb-1 caption text-[11px] border-t border-line mt-1">Identity comes from .stoa/underwriting.toml. This page does not sign anyone in.</div>
        </div>
      ) : null}
    </div>
  );
}
