import { useEffect, useRef, type ReactNode } from "react";

/** Right-side detail panel. Escape closes; focus moves in on open and back on close. */
export function Drawer({ open, title, onClose, children, width = 560 }: { open: boolean; title: ReactNode; onClose: () => void; children: ReactNode; width?: number }) {
  const panel = useRef<HTMLDivElement>(null);
  const previous = useRef<Element | null>(null);

  useEffect(() => {
    if (!open) return;
    previous.current = document.activeElement;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (previous.current instanceof HTMLElement) previous.current.focus();
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 no-print" role="presentation">
      <button type="button" aria-label="Close panel" className="absolute inset-0 bg-navy/30 cursor-default" onClick={onClose} />
      <div ref={panel} tabIndex={-1} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : "Details"} className="absolute right-0 top-0 h-full bg-panel shadow-xl border-l border-line flex flex-col outline-none" style={{ width: `min(${width}px, 100vw)` }}>
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-line">
          <h2 className="text-[18px] leading-tight m-0">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="text-ink-muted hover:text-navy text-[20px] leading-none px-1">
            ×
          </button>
        </div>
        <div className="overflow-y-auto px-5 py-4 flex-1">{children}</div>
      </div>
    </div>
  );
}
