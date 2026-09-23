/**
 * The Agent Risk Flow Graph draws what the other screens count. Every box on
 * an agent's path comes from the same merged tools, safeguard states and
 * findings, so these tests hold the diagram to those screens' numbers.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Envelope } from "../src/data/types";
import { toolsOf, uniqueAgents } from "../src/data/agents";
import { COVERAGE_CONTROLS, safeguardRows } from "../src/data/controls";
import { LANES, agentWorstLevel, buildFlow, flowAgents, flowCaption, laneOf } from "../src/data/flow";
import { activeFindings } from "../src/data/selectors";

const load = (name: string) => JSON.parse(readFileSync(new URL(`../fixtures/${name}.envelope.json`, import.meta.url), "utf8")) as Envelope;
const demo = load("meridian-pay");

describe.each(["meridian-pay", "two-stacks", "first-run", "hostile"])("%s", (name) => {
  const env = load(name);
  const rows = safeguardRows(env);

  it("draws every unique agent once, richest first", () => {
    const agents = flowAgents(env);
    expect(agents.length).toBe(uniqueAgents(env).length);
    expect(new Set(agents.map((a) => a.id)).size).toBe(agents.length);
  });

  it("each agent's path holds exactly its tools, safeguards and findings", () => {
    for (const agent of flowAgents(env)) {
      const flow = buildFlow(env, agent);
      const row = rows.find((r) => r.agent === agent)!;
      expect(flow.nodes.filter((n) => n.kind === "tool").map((n) => n.label)).toEqual(toolsOf(agent).map((t) => t.name));
      // The diagram draws the safeguards a risk officer asks about first; the rest are on the Controls screen.
      const drawn = COVERAGE_CONTROLS.filter((c) => !["sandbox", "deterministic_sampling"].includes(c));
      for (const control of drawn) {
        const node = flow.nodes.find((n) => n.control === control)!;
        expect(node, control).toBeTruthy();
        expect(node.state).toBe(row.states[control]);
        if (row.states[control] === "detected") expect(node.own).toBe("ok");
      }
      const mine = activeFindings(env).filter((r) => r.uniqueAgents.includes(agent));
      expect(flow.findings).toEqual(mine);
      const onBoxes = new Set(flow.nodes.flatMap((n) => n.findings));
      for (const r of onBoxes) expect(mine).toContain(r);
      // Every edge joins two boxes that exist, and every lane has at least one box.
      const ids = new Set(flow.nodes.map((n) => n.id));
      for (const e of flow.edges) { expect(ids.has(e.from), e.from).toBe(true); expect(ids.has(e.to), e.to).toBe(true); }
      for (const lane of LANES) expect(flow.nodes.some((n) => n.lane === lane.id), lane.id).toBe(true);
      // A box that carries a high-severity finding reads as needing attention.
      for (const n of flow.nodes) if (n.findings.some((r) => r.finding.severity === "critical" || r.finding.severity === "high")) expect(n.tone).toBe("risk");
      // No em dash reaches the panel from the scanner's evidence text.
      for (const t of [...flow.evidence, ...flow.permissions, flowCaption(flow)]) expect(t).not.toContain("—");
    }
  });
});

describe("the demo", () => {
  it("shows five agents, the account-actions path first", () => {
    const agents = flowAgents(demo);
    expect(agents.map((a) => a.name)).toEqual(["account-actions", "meridian-support", "meridian-front", "meridian-escalation", "meridian-knowledge"]);
    const flow = buildFlow(demo, agents[0]!);
    expect(flow.agent.records).toHaveLength(1);
    expect(flow.nodes.filter((n) => n.kind === "tool")).toHaveLength(6);
    const gate = flow.nodes.find((n) => n.kind === "gate")!;
    expect(gate.cap).toBe("no human approval detected");
    expect(gate.heavy).toBe(4);
    expect(gate.findings.map((r) => r.finding.rule_id)).toEqual(["DECL001"]);
    expect(flow.edges.some((e) => e.from === "gate" && e.tone === "risk")).toBe(true);
    expect(flow.nodes.find((n) => n.kind === "agent")!.mismatch).toBe(true);
    expect(agentWorstLevel(demo, agents[0]!)).toBe("high");
    expect(flowCaption(flow)).toMatch(/^account-actions: 6 tools, 4 of them money-moving or high impact with no guardrail detected; 3 safeguards detected; 6 findings\./);
  });

  it("draws account actions as one path from two records when it is defined in code and on AWS", () => {
    const twoStacks = load("two-stacks");
    const agent = flowAgents(twoStacks)[0]!;
    expect(agent.name).toBe("account-actions");
    const flow = buildFlow(twoStacks, agent);
    expect(flow.agent.records).toHaveLength(2);
    expect(flow.nodes.filter((n) => n.kind === "tool")).toHaveLength(6);
    // The merged tool carries the effects seen in either record, so the code tool's payment access and the Terraform tool's database and email reach both draw.
    const payout = flow.nodes.find((n) => n.label === "change_payout_account")!;
    expect(payout.tool!.capabilities).toEqual(["database_read", "database_write", "email_send", "payment_access"]);
    expect(flow.edges.filter((e) => e.from === payout.id).map((e) => e.to).sort()).toEqual(["reach:database_read", "reach:database_write", "reach:email_send", "reach:payment_access"]);
    expect(flow.permissions.some((t) => t.startsWith("dynamodb:*"))).toBe(true);
    expect(flow.nodes.find((n) => n.kind === "gate")!.findings.map((r) => r.finding.rule_id)).toEqual(["DECL001"]);
  });

  it("places the retry finding on the tool that is retried", () => {
    const flow = buildFlow(demo, flowAgents(demo)[0]!);
    const refund = flow.nodes.find((n) => n.label === "issue_refund")!;
    expect(refund.unsafeRetry).toBe(true);
    expect(refund.findings.map((r) => r.finding.rule_id)).toEqual(["AI008"]);
    // The chatbot binds the same tool, so the same finding sits on its path too.
    const chatbot = buildFlow(demo, flowAgents(demo).find((a) => a.name === "meridian-support")!);
    expect(chatbot.nodes.find((n) => n.label === "issue_refund")!.findings.map((r) => r.finding.rule_id)).toEqual(["AI008"]);
    expect(laneOf("AI008")).toBe("tools");
  });

  it("an agent with no tools and no reach still draws a full path", () => {
    const flow = buildFlow(demo, flowAgents(demo).find((a) => a.name === "meridian-escalation")!);
    expect(flow.nodes.find((n) => n.id === "no-tools")?.cap).toBe("No tool definitions detected");
    expect(flow.nodes.find((n) => n.kind === "gate")!.cap).toBe("no human approval detected");
    expect(flow.nodes.find((n) => n.control === "approval")!.state).toBe("not_applicable");
  });

  it("is empty for a scan with no agents", () => {
    expect(flowAgents(load("no-agents"))).toEqual([]);
  });
});
