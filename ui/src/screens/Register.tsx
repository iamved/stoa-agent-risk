import { useMemo, useState } from "react";
import { useApp } from "../app/context";
import { buildHash, navigate, useRoute } from "../app/router";
import { ExposureBadge, Pill } from "../components/Badge";
import { Drawer } from "../components/Drawer";
import { Chips, KeyValue } from "../components/KeyValue";
import { Section } from "../components/Section";
import { StatCard } from "../components/StatCard";
import { STATUSES, TREATMENTS, declaredOf, isDeclaredEqual, reviewDue, riskName, summarize, toToml, type Declared } from "../data/register";
import { formatDate } from "../data/selectors";
import type { RegisterRow } from "../data/types";

export function Register() {
  const { envelope } = useApp();
  const route = useRoute();
  const rows = envelope.register;
  const asOf = envelope.registry.repository.head_commit?.date ?? null;
  const s = summarize(envelope);
  const selected = route.id ? rows.find((r) => r.risk_id === route.id) ?? null : null;

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-[24px] m-0">Risk register</h1>
        <div className="caption">One row per agent and dimension the scanner scored at moderate or above. Treatments are declared in stoa-declared.toml and reviewed like code.</div>
      </div>

      <div className="mt-4 grid gap-3 grid-cols-2 md:grid-cols-5">
        <StatCard label="Register rows" value={s.rows} detail={`${s.declared} with a declared treatment`} />
        <StatCard label="Undeclared" value={s.byTreatment.undeclared} detail="no owner or treatment yet" tone={s.byTreatment.undeclared ? "warn" : "neutral"} />
        <StatCard label="Transfer" value={s.byTreatment.transfer} detail={`${s.byTreatment.mitigate} mitigate · ${s.byTreatment.accept} accept · ${s.byTreatment.avoid} avoid`} href={s.byTreatment.transfer ? buildHash("evidence", null, { view: "underwriter" }) : undefined} />
        <StatCard label="Review due" value={s.due} detail={asOf ? `as of ${formatDate(asOf)}` : "no scan date"} tone={s.due ? "warn" : "neutral"} />
        <StatCard label="Unmatched declarations" value={s.unmatched} detail="declared risk ids with no scored exposure" tone={s.unmatched ? "warn" : "neutral"} />
      </div>

      <Section title="Register" caption="Inherent is the score before observed controls are credited; residual is the scanner's own level. Click a row to declare or edit its treatment.">
        <div className="panel overflow-x-auto">
          <table className="tbl" aria-label="Risk register">
            <thead>
              <tr>
                <th>Risk</th><th>Description</th><th>Inherent</th><th>Residual</th><th>Treatment</th><th>Owner</th><th>Controls</th><th>Status</th><th>Review by</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr><td colSpan={9} className="caption text-center">No agent scored at moderate or above in this scan, so the register is empty.</td></tr>
              ) : rows.map((row) => {
                const due = reviewDue(row, asOf);
                return (
                  <tr key={row.risk_id} data-clickable="true" tabIndex={0} onClick={() => navigate("register", row.risk_id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); navigate("register", row.risk_id); } }}>
                    <td>
                      <div className="font-medium">{row.dimension_name}</div>
                      <div className="caption">{row.agent_name ?? row.agent_id}{row.unmatched ? " · unmatched" : ""}</div>
                    </td>
                    <td className="max-w-[320px] caption">{row.statement}</td>
                    <td>{row.inherent ? <ExposureBadge exposure={row.inherent.level} /> : <span className="caption">–</span>}</td>
                    <td>{row.residual ? <ExposureBadge exposure={row.residual.level} /> : <span className="caption">–</span>}</td>
                    <td>{row.declared?.treatment ? <Pill tone={row.declared.treatment === "transfer" ? "gold" : "neutral"}>{row.declared.treatment}</Pill> : <span className="caption">undeclared</span>}</td>
                    <td className="caption">{row.declared?.owner || "–"}</td>
                    <td className="tabular-nums">{row.controls_observed.length}</td>
                    <td className="caption">{row.declared?.status ?? "–"}</td>
                    <td className={due ? "text-sev-high font-medium" : "caption"}>{row.declared?.review_by ? formatDate(row.declared.review_by) : "–"}{due ? " (due)" : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>

      <RegisterDrawer row={selected} onClose={() => navigate("register")} />
      {route.id && !selected ? <p className="caption mt-3">No register row with id <span className="mono">{route.id}</span>.</p> : null}
    </div>
  );
}

function RegisterDrawer({ row, onClose }: { row: RegisterRow | null; onClose: () => void }) {
  if (!row) return null;
  return <RegisterDrawerBody key={row.risk_id} row={row} onClose={onClose} />;
}

function RegisterDrawerBody({ row, onClose }: { row: RegisterRow; onClose: () => void }) {
  const { envelope } = useApp();
  const original = useMemo(() => declaredOf(row), [row]);
  const [draft, setDraft] = useState<Declared>(original);
  const [copied, setCopied] = useState<"idle" | "done" | "manual">("idle");
  const toml = toToml(row.risk_id, draft);
  const changed = !isDeclaredEqual(draft, original);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(toml);
      setCopied("done");
    } catch {
      setCopied("manual");
    }
  };

  return (
    <Drawer open title={riskName(row)} onClose={onClose} width={620}>
      <KeyValue
        rows={[
          { k: "Risk id", v: <span className="mono">{row.risk_id}</span> },
          { k: "Agent", v: row.agent_name && envelope.registry.agents.some((a) => a.id === row.agent_id) ? <a href={buildHash("inventory", row.agent_id)} className="link">{row.agent_name}</a> : <span className="caption">not in this scan{row.unmatched ? " (declared only)" : ""}</span> },
          { k: "Inherent", v: row.inherent ? <span className="flex items-center gap-2"><ExposureBadge exposure={row.inherent.level} /><span className="caption tabular-nums">score {row.inherent.score} before controls</span></span> : "not scored" },
          { k: "Residual", v: row.residual ? <span className="flex items-center gap-2"><ExposureBadge exposure={row.residual.level} /><span className="caption tabular-nums">score {row.residual.score}</span></span> : "not scored" },
          { k: "Controls observed", v: <Chips items={row.controls_observed.map((c) => ({ label: c }))} empty="none observed" /> },
          { k: "Contributing", v: <span className="caption">{row.contributing_findings.length} findings · {row.contributing_capabilities.length} capability signals</span> },
        ]}
      />
      <p className="caption mt-3">{row.statement}</p>
      {row.contributing_findings.length ? <a href={buildHash("findings", null, { dimension: row.dimension_id, agent: row.agent_id })} className="link text-[13px]">Open the findings behind this row</a> : null}

      <section className="mt-5">
        <h3 className="text-[14px] m-0 mb-2">Declared treatment</h3>
        <div className="grid gap-3 md:grid-cols-2 text-[13px]">
          <label className="flex flex-col gap-1">
            <span className="caption">Owner</span>
            <input value={draft.owner} onChange={(e) => setDraft({ ...draft, owner: e.target.value })} className="rounded border border-line bg-panel px-2 py-1" placeholder="team or person" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="caption">Treatment</span>
            <select value={draft.treatment} onChange={(e) => setDraft({ ...draft, treatment: e.target.value as Declared["treatment"] })} className="rounded border border-line bg-panel px-2 py-1" aria-label="Treatment">
              <option value="">undeclared</option>
              {TREATMENTS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 md:col-span-2">
            <span className="caption">Rationale</span>
            <textarea value={draft.rationale} onChange={(e) => setDraft({ ...draft, rationale: e.target.value })} rows={2} className="rounded border border-line bg-panel px-2 py-1" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="caption">Review by</span>
            <input type="date" value={draft.review_by} onChange={(e) => setDraft({ ...draft, review_by: e.target.value })} className="rounded border border-line bg-panel px-2 py-1" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="caption">Status</span>
            <select value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value as Declared["status"] })} className="rounded border border-line bg-panel px-2 py-1" aria-label="Status">
              <option value="">unset</option>
              {STATUSES.map((st) => <option key={st} value={st}>{st}</option>)}
            </select>
          </label>
        </div>
        {draft.treatment === "transfer" ? (
          <a href={buildHash("evidence", null, { view: "underwriter" })} className="mt-3 inline-block rounded border border-navy bg-navy text-white px-3 py-1.5 text-[13px] no-underline hover:bg-navy-700">Prepare underwriting evidence</a>
        ) : null}
      </section>

      <section className="mt-5">
        <div className="flex items-center justify-between gap-2 mb-1.5">
          <h3 className="text-[14px] m-0">stoa-declared.toml snippet{changed ? <span className="caption font-sans font-normal"> · edited</span> : null}</h3>
          <button type="button" onClick={copy} className="rounded border border-line px-2.5 py-1 text-[12.5px] hover:bg-paper">{copied === "done" ? "Copied" : "Copy"}</button>
        </div>
        <textarea readOnly value={toml} rows={toml.split("\n").length} className="w-full rounded border border-line bg-paper p-2 mono text-[12px]" aria-label="TOML snippet" onFocus={(e) => e.currentTarget.select()} />
        <p className="caption mt-1.5 mb-0">This file cannot write to your repository. Paste the block into <span className="mono">stoa-declared.toml</span> (replacing any existing entry with this risk id) and commit it, so the treatment is reviewed in a pull request.{copied === "manual" ? " Clipboard access was blocked; select the text above to copy it." : ""}</p>
      </section>
    </Drawer>
  );
}
