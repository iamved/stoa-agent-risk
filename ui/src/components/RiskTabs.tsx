import { useApp } from "../app/context";
import { buildHash, type ScreenId } from "../app/router";
import { activeFindings } from "../data/selectors";

/** Findings, drift and the register are three views of one model. */
export function RiskTabs({ current }: { current: ScreenId }) {
  const { envelope } = useApp();
  const drift = envelope.diff ? envelope.diff.summary.agents_changed + envelope.diff.summary.agents_added + envelope.diff.summary.agents_removed : null;
  const tabs: { id: ScreenId; label: string; count: number | null }[] = [
    { id: "findings", label: "Findings", count: activeFindings(envelope).length },
    { id: "drift", label: "Drift", count: drift },
    { id: "register", label: "Risk register", count: envelope.register.length },
  ];
  return (
    <div className="mb-4">
      <div role="tablist" aria-label="Findings views" className="flex flex-wrap gap-1 border-b border-line no-print">
        {tabs.map((t) => {
          const active = t.id === current;
          return (
            <a key={t.id} role="tab" aria-selected={active} href={buildHash(t.id)} className={`px-3 py-2 text-[13.5px] no-underline -mb-px border-b-2 ${active ? "border-gold text-navy font-medium" : "border-transparent text-ink-muted hover:text-navy"}`}>
              {t.label}
              {t.count !== null ? <span className="ml-1.5 text-[11px] tabular-nums text-ink-muted">{t.count}</span> : null}
            </a>
          );
        })}
      </div>
    </div>
  );
}
