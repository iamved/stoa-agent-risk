import { useMemo, useState } from "react";
import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { type UniqueAgent } from "../data/agents";
import { FLOW_WIDTH, LANES, agentWorstLevel, buildFlow, flowAgents, flowCaption, worstLevel, type Flow, type FlowNode, type LaneId, type Tone } from "../data/flow";
import { autonomyLabel } from "../data/labels";
import { RISK_LABEL, SEVERITY_RANK, findingTitle, pluralize, type RiskLevel } from "../data/selectors";
import { SeverityBadge } from "./Badge";

const HEAD = 74, NODE_H = 46, CHIP_H = 32, GAP = 10;

const BOX: Record<Tone, string> = {
  risk: "fill-sev-high-bg stroke-sev-high",
  warn: "fill-sev-medium-bg stroke-sev-medium",
  ok: "fill-ok-bg stroke-ok",
  missing: "fill-paper stroke-ink-muted [stroke-dasharray:4_3]",
  neutral: "fill-panel stroke-line-strong",
};
const DOT: Record<RiskLevel, string> = { high: "bg-sev-high", medium: "bg-sev-medium", low: "bg-sev-low" };

type Placed = FlowNode & { x: number; y: number; w: number; h: number };

function layout(flow: Flow): { placed: Placed[]; height: number } {
  const byLane = new Map<LaneId, FlowNode[]>(LANES.map((l) => [l.id, flow.nodes.filter((n) => n.lane === l.id)]));
  const stack = (list: FlowNode[]) => list.reduce((s, n) => s + (n.small ? CHIP_H : NODE_H) + GAP, -GAP);
  const tools = byLane.get("tools")!, reach = byLane.get("reach")!;
  // The main path sits on one line; safeguards hang below their step, tools and reach centre on it.
  const above = Math.max(NODE_H / 2, stack(tools) / 2, stack(reach) / 2);
  const below = Math.max(Math.max(stack(byLane.get("entry")!), stack(byLane.get("agent")!)) - NODE_H / 2, stack(tools) / 2, stack(reach) / 2);
  const cy = HEAD + 26 + above;
  const placed: Placed[] = [];
  for (const lane of LANES) {
    const list = byLane.get(lane.id)!;
    const x = lane.cx - lane.w / 2;
    let y = lane.id === "tools" || lane.id === "reach" ? cy - stack(list) / 2 : cy - NODE_H / 2;
    for (const n of list) {
      const h = n.small ? CHIP_H : NODE_H;
      placed.push({ ...n, x, y, w: lane.w, h });
      y += h + GAP;
    }
  }
  return { placed, height: Math.round(cy + below + 28) };
}

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

function Glyph({ tone, x, y }: { tone: Tone; x: number; y: number }) {
  const mark = "fill-none stroke-panel [stroke-width:1.6] [stroke-linecap:round] [stroke-linejoin:round]";
  if (tone === "risk") return <g><path className="fill-sev-high" d={`M${x} ${y - 7} ${x + 7.5} ${y + 6}H${x - 7.5}z`} /><path className={mark} d={`M${x} ${y - 2.5}v3.6M${x} ${y + 3.6}v.2`} /></g>;
  if (tone === "warn") return <path className="fill-sev-medium" d={`M${x} ${y - 7} ${x + 7} ${y} ${x} ${y + 7} ${x - 7} ${y}z`} />;
  if (tone === "ok") return <g><circle className="fill-ok" cx={x} cy={y} r={7} /><path className={mark} d={`M${x - 3.2} ${y}l2.3 2.4 4.2-4.6`} /></g>;
  if (tone === "missing") return <circle className="fill-none stroke-ink-muted [stroke-width:1.4] [stroke-dasharray:2.5_2]" cx={x} cy={y} r={6} />;
  return null;
}

/** The section on the Overview: a picker, the diagram, and a detail panel. */
export function AgentFlow() {
  const { envelope } = useApp();
  const agents = useMemo(() => flowAgents(envelope), [envelope]);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const agent = agents.find((a) => a.id === agentId) ?? agents[0];
  const flow = useMemo(() => (agent ? buildFlow(envelope, agent) : null), [envelope, agent]);
  if (!agent || !flow) return null;
  const node = selected ? flow.nodes.find((n) => n.id === selected) ?? null : null;
  const pick = (a: UniqueAgent) => { setAgentId(a.id); setSelected(null); };

  return (
    <section className="mt-4" aria-labelledby="flow-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2 pb-2 mb-3 border-b border-line">
        <h2 id="flow-title" className="m-0">Agent Risk Flow Graph</h2>
        <div className="caption">Select a box for its details.</div>
      </div>
      <div role="group" aria-label="Agents" className="flex flex-wrap items-center gap-1.5 mb-3">
        {agents.map((a) => {
          const level = agentWorstLevel(envelope, a);
          const on = a === agent;
          return (
            <button key={a.id} type="button" aria-pressed={on} onClick={() => pick(a)} title={level ? `Worst finding: ${RISK_LABEL[level]}` : "No findings"} className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[13px] cursor-pointer ${on ? "bg-navy border-navy text-white" : "bg-panel border-line-strong text-ink hover:border-ink-muted"}`}>
              <span aria-hidden="true" className={`w-2 h-2 rounded-full ${level ? DOT[level] : "bg-line-strong"}`} />
              {a.name}
            </button>
          );
        })}
      </div>
      <figure className="m-0 panel overflow-hidden">
        <div className="overflow-x-auto"><Diagram flow={flow} selected={selected} onSelect={setSelected} /></div>
        <figcaption className="border-t border-line px-4 py-3 caption flex flex-col gap-2">
          <Legend />
          {node ? <NodeNote flow={flow} node={node} onBack={() => setSelected(null)} /> : <div>{flowCaption(flow)}</div>}
        </figcaption>
      </figure>
    </section>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-ink-soft" aria-hidden="true">
      <span className="inline-flex items-center gap-1.5"><svg width="14" height="14" viewBox="0 0 14 14"><path className="fill-sev-high" d="M7 1.2 13.2 12.4H.8z" /></svg>Needs attention</span>
      <span className="inline-flex items-center gap-1.5"><svg width="14" height="14" viewBox="0 0 14 14"><path className="fill-sev-medium" d="M7 .8 13.2 7 7 13.2.8 7z" /></svg>Lower-severity finding</span>
      <span className="inline-flex items-center gap-1.5"><svg width="14" height="14" viewBox="0 0 14 14"><circle className="fill-ok" cx="7" cy="7" r="6.2" /></svg>Safeguard or guardrail detected</span>
      <span className="inline-flex items-center gap-1.5"><svg width="14" height="14" viewBox="0 0 14 14"><circle className="fill-none stroke-ink-muted [stroke-width:1.4] [stroke-dasharray:2.5_2]" cx="7" cy="7" r="5.6" /></svg>Not detected</span>
      <span className="inline-flex items-center gap-1.5"><svg width="28" height="14" viewBox="0 0 28 14"><path className="fill-none stroke-line-strong [stroke-width:1.6] [stroke-dasharray:5_4]" d="M1 7h26" /></svg>Reached by the agent, no tool named</span>
    </div>
  );
}

function Diagram({ flow, selected, onSelect }: { flow: Flow; selected: string | null; onSelect: (id: string | null) => void }) {
  const { placed, height } = useMemo(() => layout(flow), [flow]);
  const pos = new Map(placed.map((n) => [n.id, n]));
  const focused = Boolean(selected);
  const onEdge = (e: { from: string; to: string }) => selected !== null && (e.from === selected || e.to === selected);
  const toggle = (id: string) => onSelect(selected === id ? null : id);
  return (
    <svg viewBox={`0 0 ${FLOW_WIDTH} ${height}`} role="group" aria-label={`Risk path for ${flow.agent.name}`} className="block w-full h-auto min-w-[1040px]">
      {LANES.map((lane, i) => {
        const list = placed.filter((n) => n.lane === lane.id);
        const refs = list.flatMap((n) => n.findings);
        const level = worstLevel(refs);
        const x = lane.cx - lane.w / 2;
        return (
          <g key={lane.id}>
            {i % 2 === 1 ? <rect className="fill-paper" x={x - 16} y={0} width={lane.w + 32} height={height} /> : null}
            <text className="fill-navy text-[13.5px] font-semibold" x={x} y={26}>{lane.title}</text>
            <text className="fill-ink-muted text-[11.5px]" x={x} y={43}>{lane.sub}</text>
            <text className="fill-ink-soft text-[11.5px] font-medium" x={x} y={61}>{refs.length ? `${pluralize(refs.length, "finding")} · ${RISK_LABEL[level!]}` : "no findings"}</text>
          </g>
        );
      })}
      <line className="stroke-line" x1={0} y1={HEAD} x2={FLOW_WIDTH} y2={HEAD} />
      <g>
        {flow.edges.map((e) => {
          const a = pos.get(e.from)!, b = pos.get(e.to)!;
          const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x - 7, y2 = b.y + b.h / 2, dx = (x2 - x1) * 0.5;
          const on = onEdge(e);
          const color = e.tone === "risk" ? "stroke-sev-high" : "stroke-line-strong";
          const arrow = e.tone === "risk" ? "fill-sev-high" : "fill-line-strong";
          const dim = focused && !on ? "opacity-20" : "";
          return (
            <g key={`${e.from}>${e.to}`} className={`${dim} transition-opacity`}>
              <path className={`fill-none ${color} ${on ? "[stroke-width:2.4]" : "[stroke-width:1.6]"} ${e.loose ? "[stroke-dasharray:5_4]" : ""}`} d={`M${x1} ${y1} C${x1 + dx} ${y1} ${x2 - dx} ${y2} ${x2} ${y2}`} />
              <path className={arrow} d={`M${x2 + 7} ${y2}l-8-4.2v8.4z`} />
              {e.label ? <text className="fill-ink-muted text-[11px] font-medium" x={x1 + (x2 - x1) / 2} y={Math.min(a.y, b.y) - 7} textAnchor="middle">{e.label}</text> : null}
            </g>
          );
        })}
        {(["entry", "agent"] as LaneId[]).map((id) => {
          const list = placed.filter((n) => n.lane === id);
          if (list.length < 2) return null;
          const top = list[0]!, last = list[list.length - 1]!;
          return <line key={id} className="stroke-line-strong [stroke-width:1.2]" x1={top.x + 12} y1={top.y + top.h} x2={top.x + 12} y2={last.y} />;
        })}
      </g>
      {placed.map((n) => {
        const interactive = n.kind !== "empty";
        const pad = n.small ? 24 : 12, room = Math.floor((n.w - pad - 30) / (n.small ? 6.6 : 7.3));
        const on = selected === n.id;
        const cap = n.small ? n.cap : `${n.cap}${n.findings.length ? ` · ${pluralize(n.findings.length, "finding")}` : ""}`;
        return (
          <g key={n.id} className={`${interactive ? "cursor-pointer" : ""} outline-none group`} tabIndex={interactive ? 0 : undefined} role={interactive ? "button" : undefined} aria-pressed={interactive ? on : undefined}
            aria-label={interactive ? `${n.label}, ${n.cap}${n.findings.length ? `, ${pluralize(n.findings.length, "finding")}` : ""}` : undefined}
            onClick={interactive ? () => toggle(n.id) : undefined}
            onKeyDown={interactive ? (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggle(n.id); } } : undefined}>
            <title>{n.label ? `${n.label} · ${n.cap}` : n.cap}</title>
            <rect className={`${n.kind === "empty" ? "fill-none stroke-line-strong [stroke-dasharray:4_3]" : BOX[n.tone]} ${on ? "stroke-navy [stroke-width:2.4] [stroke-dasharray:none]" : "[stroke-width:1.2] group-hover:[stroke-width:2]"} group-focus-visible:stroke-gold group-focus-visible:[stroke-width:2.6]`}
              x={n.small ? n.x + 12 : n.x} y={n.y} width={n.small ? n.w - 12 : n.w} height={n.h} rx={n.small ? 6 : 9} />
            {n.kind === "empty" ? <text className="fill-ink-muted text-[11.5px]" x={n.x + n.w / 2} y={n.y + n.h / 2 + 4} textAnchor="middle">{n.cap}</text> : n.small ? (
              <>
                <text className="fill-navy text-[12px] font-semibold" x={n.x + pad} y={n.y + 14}>{clip(n.label, room)}</text>
                <text className="fill-ink-soft text-[10.5px]" x={n.x + pad} y={n.y + 26}>{clip(cap, room + 4)}</text>
              </>
            ) : (
              <>
                <text className="fill-navy text-[13px] font-semibold" x={n.x + pad} y={n.y + 19}>{clip(n.label, room)}</text>
                <text className="fill-ink-soft text-[11.5px]" x={n.x + pad} y={n.y + 35}>{clip(cap, room + 5)}</text>
              </>
            )}
            <Glyph tone={n.tone} x={n.x + n.w - 16} y={n.y + n.h / 2} />
          </g>
        );
      })}
    </svg>
  );
}

// --- the selected box, in the caption -----------------------------------------------------

/** One or two lines about the selected box, where the caption sits. The full record is on the Findings and Inventory screens. */
function NodeNote({ flow, node, onBack }: { flow: Flow; node: FlowNode; onBack: () => void }) {
  const { envelope } = useApp();
  const notes: string[] = [];
  if (node.kind === "request") notes.push("Everything the agent does starts here. The three safeguards below decide who can reach it, what input it accepts, and how often.");
  if (node.kind === "agent") {
    notes.push(`${flow.providers.join(", ") || "Provider not detected"} · ${node.harness ?? ""} · ${autonomyLabel(flow.inferred).toLowerCase()}.`);
    if (node.mismatch) notes.push(`Declared as ${autonomyLabel(flow.declared).toLowerCase()}, but the scan reads it as ${autonomyLabel(flow.inferred).toLowerCase()}.`);
  }
  if (node.kind === "gate") notes.push(node.own === "ok" ? "A human approval step was detected before high-impact actions." : node.heavy ? `No human approval detected. ${pluralize(node.heavy, "money-moving or high-impact tool")} can run without a person confirming.` : "No human approval detected. This agent binds no money-moving or high-impact tools.");
  if (node.kind === "safeguard") notes.push(node.state === "detected" ? "Detected in the scanned files." : node.state === "not_applicable" ? "Not expected of this agent: it does not act on its own with high-impact tools." : "Not detected in the scanned files. It may exist outside the repository.");
  if (node.kind === "tool" && node.tool) {
    if (node.exposed) notes.push(`${node.tool.money_action ? "Moves money" : "High impact"}, and no guardrail was detected around it.`);
    if (node.unsafeRetry) notes.push("Retried without an idempotency key, so one request can act twice.");
    notes.push(`Defined at ${node.tool.path}:${node.tool.line}.`);
  }
  if (node.kind === "resource" && node.reach) {
    const via = flow.edges.filter((e) => e.to === node.id && e.from.startsWith("tool:")).map((e) => flow.nodes.find((n) => n.id === e.from)!.label);
    notes.push(via.length ? `Reached through ${via.join(", ")}.` : "Reached through the agent's own code, no tool named.");
    if (node.reach.runtime) notes.push("Seen in runtime traces but not found in code or declarations.");
  }
  if (node.kind === "service" && node.sensitive) notes.push("On Stoa's list of sensitive integrations.");
  const worst = [...node.findings].sort((a, b) => SEVERITY_RANK[b.finding.severity] - SEVERITY_RANK[a.finding.severity])[0];
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-ink-soft">
      <span className="font-medium text-navy">{node.label || node.cap}</span>
      {node.label && node.kind !== "gate" && node.kind !== "safeguard" ? <span>{node.cap}.</span> : null}
      {notes.map((t) => <span key={t}>{t}</span>)}
      {worst ? <span className="inline-flex items-center gap-1.5"><SeverityBadge severity={worst.finding.severity} /><a href={buildHash("findings", worst.finding.fingerprint)} className="link">{findingTitle(envelope, worst.finding)}</a>{node.findings.length > 1 ? <span>and {pluralize(node.findings.length - 1, "more finding")}</span> : null}</span> : null}
      <button type="button" onClick={onBack} className="link bg-transparent border-0 p-0 cursor-pointer text-[12.5px]">Clear</button>
    </div>
  );
}
