/**
 * The AI loss outlook: a seeded Monte Carlo over public AI loss events.
 *
 * A faithful TypeScript port of the model published in the "Stoa AI loss
 * outlook" page. The dataset, categories and assumptions are loaded verbatim
 * from lossOutlook.data.json; `tests/lossModel.test.ts` runs the original
 * script (tests/reference/loss-outlook.cjs) against this port on the same
 * inputs and requires identical numbers.
 *
 * Output is an indication for discussion with a licensed broker and carrier:
 * not a quote, not a premium, not advice. Every figure is reproducible from
 * the seed, the dataset and the assumptions version shown on the page.
 */
import data from "./lossOutlook.data.json";

export type HumanInLoop = "none" | "partial" | "approval_above_threshold" | "full";
export type Autonomy = "low" | "medium" | "high";
export type Insurable = "yes" | "partial" | "no";

export interface Sig { fin: number; pii: number; write: number; cust: number; auto: Autonomy; hil: string }
export interface Comp { type: string; usd: number | null; party: string; ins: Insurable; grade: string; src: string }
export interface LossEvent {
  id: string; title: string; year: number; org: string; sector: string; band: string; rev: number | null; jur: string;
  cat: string; sys: string; sig: Sig; comps: Comp[]; status: string; nearMiss?: boolean; analog?: boolean; fitAnyway?: boolean;
}
export interface Cat { key: string; name: string; dims: string[]; third: boolean }
export interface Assume {
  version: string; alpha: number; scaleClamp: number[]; k: number; reportingShift: number; defenseLoad: number; capMult: number;
  insFrac: Record<string, number>; inflation: number; currentYear: number; pLow: number; pMid: number; pHigh: number;
  years: number; bootReps: number; bootYears: number; shockSigma: number; sigmaCap: number; transCapShare: number; refRevenue: number; priorJitter: number;
  base: Record<string, number>; prior: Record<string, { median: number; sigma: number }>; hil: Record<string, number>; autonomy: Record<string, number>;
  gateFloor: Record<string, number>; limitSteps: number[]; subSteps: number[]; retSteps: number[];
}
export interface FinancialAuthority { enabled: boolean; max_per_action_usd: number; monthly_action_volume: number }
export interface Capabilities {
  financial_authority: FinancialAuthority; pii_access: boolean; sensitive_data_access: string; write_access_to_systems: boolean;
  autonomy_level: Autonomy; human_in_loop: HumanInLoop; customer_facing: boolean;
}
export interface ModelAgent { name: string; capabilities: Capabilities; dimension_scores: Record<string, number> }
export interface Policy { type: "cyber" | "tech_eo" | "crime"; limit: number; ai_exclusion: boolean }
export interface Intake { revenue: number; sector: string; jurisdictions: string[]; records: number; regulated: boolean; minors: boolean; existing_coverage: Policy[] }

export const EVENTS = data.EVENTS as LossEvent[];
export const CATS = data.CATS as Cat[];
export const DIMS = data.DIMS as [string, string][];
export const DEFAULT_ASSUME = data.DEFAULT_ASSUME as Assume;
export const FIXTURES = data.FIXTURES as Record<string, { label: string; scan: { schema: string; agents: ModelAgent[] }; intake: Intake }>;
const BAND_REV: Record<string, number> = { micro: 3e6, small: 30e6, mid: 300e6, large: 7e9, mega: 150e9 };

type Rng = () => number;

function mulberry32(a: number): Rng {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function streamSeed(seed: number, year: number, cat: number): number {
  let h = Math.imul(seed | 0, 0x9E3779B1) ^ Math.imul(year + 1, 0x85EBCA6B) ^ Math.imul(cat + 7, 0xC2B2AE35);
  h ^= h >>> 16; h = Math.imul(h, 0x7FEB352D); h ^= h >>> 15; h = Math.imul(h, 0x846CA68B); h ^= h >>> 16;
  return h >>> 0;
}
function normal(r: Rng): number { let u = 0; while (u === 0) u = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r()); }
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const mean = (a: number[]) => a.reduce((s, v) => s + v, 0) / a.length;
function quantileSorted(s: ArrayLike<number>, p: number): number { if (!s.length) return 0; const i = clamp(Math.ceil(p * s.length) - 1, 0, s.length - 1); return s[i] ?? 0; }
const snapUp = (v: number, steps: number[]) => { for (const s of steps) if (v <= s) return s; return steps[steps.length - 1] ?? v; };
const snapDown = (v: number, steps: number[]) => { let o = steps[0] ?? v; for (const s of steps) if (s <= v) o = s; return o; };

// ---------- Component B: scaling and matching ----------
function eventRevenue(e: LossEvent): number | null { return e.rev || BAND_REV[e.band] || null; }
function scaledInsurable(e: LossEvent, intake: Intake, A: Assume): { usd: number; factor: number; infl: number } | null {
  if (e.status === "pending" || e.status === "appealed") return null;
  let tot = 0, any = false;
  for (const c of e.comps) { if (c.usd == null) continue; const f = A.insFrac[c.ins] || 0; if (f > 0) { tot += c.usd * f; any = true; } }
  if (!any) return null;
  const infl = Math.pow(1 + A.inflation, Math.max(0, A.currentYear - e.year));
  const er = eventRevenue(e);
  const factor = er ? clamp(Math.pow(intake.revenue / er, A.alpha), A.scaleClamp[0] ?? 0.01, A.scaleClamp[1] ?? 10) : 1;
  return { usd: tot * infl * factor, factor, infl };
}
function similarity(e: LossEvent, agent: ModelAgent, intake: Intake): { score: number; why: string[] } {
  const c = agent.capabilities, why: string[] = []; let m = 0;
  const pairs: [boolean, string][] = [
    [!!e.sig.fin === !!c.financial_authority.enabled, c.financial_authority.enabled ? "moves money" : "no payment authority"],
    [!!e.sig.pii === !!c.pii_access, c.pii_access ? "handles personal data" : "no personal data"],
    [!!e.sig.write === !!c.write_access_to_systems, c.write_access_to_systems ? "writes to systems" : "read only"],
    [!!e.sig.cust === !!c.customer_facing, c.customer_facing ? "customer facing" : "internal use"],
    [e.sig.auto === c.autonomy_level, c.autonomy_level + " autonomy"],
    [(e.sig.hil === "none") === (c.human_in_loop === "none"), c.human_in_loop === "none" ? "no human review" : "human review present"],
  ];
  for (const [ok, label] of pairs) if (ok) { m++; why.push(label); }
  let score = 0.7 * (m / pairs.length);
  if (e.sector === intake.sector || (e.sector === "health" && intake.sector === "healthtech")) { score += 0.15; why.push("same sector"); }
  if (intake.jurisdictions.includes(e.jur)) { score += 0.15; why.push("same jurisdiction"); }
  return { score, why };
}
export interface Comparable { id: string; title: string; org: string; year: number; status: string; nearMiss: boolean; analog: boolean; raw: number | null; scaled: number | null; score: number; why: string[]; grade: string | null; src: string | null; ins: string | null }
function comparables(events: LossEvent[], agent: ModelAgent, intake: Intake, A: Assume): Record<string, Comparable[]> {
  const out: Record<string, Comparable[]> = {};
  for (const cat of CATS) {
    out[cat.key] = events.filter((e) => e.cat === cat.key).map((e) => {
      const s = similarity(e, agent, intake); const sc = scaledInsurable(e, intake, A);
      const raw = e.comps.reduce((t, c) => t + (c.usd || 0), 0) || null;
      return { id: e.id, title: e.title, org: e.org, year: e.year, status: e.status, nearMiss: !!e.nearMiss, analog: !!e.analog, raw, scaled: sc ? sc.usd : null, score: s.score, why: s.why,
        grade: e.comps.length ? e.comps[0]!.grade : null, src: e.comps.length ? e.comps[0]!.src : null, ins: e.comps.length ? e.comps[0]!.ins : null };
    }).sort((a, b) => (b.score + (b.raw ? 0.15 : 0)) - (a.score + (a.raw ? 0.15 : 0)) || (b.scaled || 0) - (a.scaled || 0));
  }
  return out;
}

// ---------- Component C: severity and frequency ----------
export interface SeverityParam { n: number; Z: number; muData: number | null; sdData: number | null; muPrior: number; mu: number; sigma: number; mods: string[] }
function severityParams(events: LossEvent[], intake: Intake, agent: ModelAgent, A: Assume, resampleRng?: Rng): Record<string, SeverityParam> {
  const c = agent.capabilities, P: Record<string, SeverityParam> = {};
  for (const cat of CATS) {
    let pts = events.filter((e) => e.cat === cat.key).map((e) => scaledInsurable(e, intake, A)).filter((s): s is { usd: number; factor: number; infl: number } => Boolean(s)).map((s) => Math.log(s.usd) + A.reportingShift);
    const n = pts.length;
    let jitter = 0;
    if (resampleRng) { const src = pts; pts = pts.map(() => src[Math.floor(resampleRng() * n)] ?? 0); jitter = A.priorJitter * normal(resampleRng); }
    const pr = A.prior[cat.key]!;
    const muPrior = Math.log(pr.median) + A.alpha * Math.log(intake.revenue / A.refRevenue) + jitter;
    const Z = n / (n + A.k);
    let mu = muPrior, sigma = pr.sigma, muData: number | null = null, sdData: number | null = null;
    if (n >= 1) { muData = mean(pts); mu = Z * muData + (1 - Z) * muPrior; }
    if (n >= 2) { const md = muData ?? 0; const v = pts.reduce((s, x) => s + (x - md) ** 2, 0) / (n - 1); sdData = Math.sqrt(v); sigma = Math.sqrt(Z * v + (1 - Z) * pr.sigma ** 2); }
    sigma = clamp(sigma, 0.8, A.sigmaCap);
    let mod = cat.third ? A.defenseLoad : 1; const mods: string[] = []; if (cat.third) mods.push("defense cost loading x" + A.defenseLoad);
    if (cat.key === "leak") {
      if (intake.regulated) { mod *= 1.25; mods.push("regulated sector x1.25"); }
      if (intake.jurisdictions.includes("EU")) { mod *= 1.2; mods.push("EU exposure x1.2"); }
      const r = clamp(Math.pow(Math.max(intake.records, 1e3) / 1e6, 0.2), 0.5, 3); mod *= r; mods.push("records held x" + r.toFixed(2));
      if (intake.minors) { mod *= 1.3; mods.push("serves minors x1.3"); }
    }
    if (cat.key === "bias" && intake.regulated) { mod *= 1.25; mods.push("regulated sector x1.25"); }
    if (cat.key === "hall" && intake.minors) { mod *= 1.5; mods.push("serves minors x1.5"); }
    if (cat.key === "trans") { const r = clamp(Math.pow(Math.max(c.financial_authority.max_per_action_usd, 1) / 500, 0.5), 0.2, 20); mod *= r; mods.push("per-action authority x" + r.toFixed(2)); }
    P[cat.key] = { n, Z, muData, sdData, muPrior, mu: mu + Math.log(mod), sigma, mods };
  }
  return P;
}
export interface FrequencyParam { lambda: number; mods: string[] }
function frequencyParams(agent: ModelAgent, A: Assume): Record<string, FrequencyParam> {
  const c = agent.capabilities, d = agent.dimension_scores, F: Record<string, FrequencyParam> = {};
  for (const cat of CATS) {
    const s = mean(cat.dims.map((k) => d[k] ?? 0));
    const scoreMod = Math.exp(((s - 50) / 50) * Math.log(2.5));
    let lam = A.base[cat.key]! * scoreMod * A.autonomy[c.autonomy_level]!; const mods = ["scan score " + Math.round(s) + " x" + scoreMod.toFixed(2), c.autonomy_level + " autonomy x" + A.autonomy[c.autonomy_level]];
    const h = A.hil[c.human_in_loop]!;
    if (["trans", "bias", "perf", "loss"].includes(cat.key)) { lam *= h; mods.push("human review x" + h); }
    else if (cat.key === "hall") { const hh = 1 - (1 - h) * 0.3; lam *= hh; mods.push("human review x" + hh.toFixed(2)); }
    if (cat.key === "trans") {
      if (!c.financial_authority.enabled) { lam *= A.gateFloor.trans!; mods.push("no payment authority, floor x" + A.gateFloor.trans); }
      else { const v = clamp(Math.pow(Math.max(c.financial_authority.monthly_action_volume, 1) / 50000, 0.3), 0.3, 4); lam *= v; mods.push("action volume x" + v.toFixed(2)); }
    }
    if (cat.key === "leak" && !c.pii_access && (!c.sensitive_data_access || c.sensitive_data_access === "none")) { lam *= A.gateFloor.leak!; mods.push("no personal or sensitive data, floor x" + A.gateFloor.leak); }
    if (cat.key === "loss" && !c.write_access_to_systems) { lam *= A.gateFloor.loss!; mods.push("no write access, floor x" + A.gateFloor.loss); }
    if ((cat.key === "hall" || cat.key === "inj") && !c.customer_facing) { const m = cat.key === "hall" ? 0.4 : 0.5; lam *= m; mods.push("internal use x" + m); }
    F[cat.key] = { lambda: lam, mods };
  }
  return F;
}
interface Sim { cats: Float64Array[]; agg: Float64Array; singles: number[] }
function simulate(F: Record<string, FrequencyParam>, P: Record<string, SeverityParam>, intake: Intake, A: Assume, seed: number, years: number, collectEvents: boolean, opts_fa?: FinancialAuthority): Sim {
  const nc = CATS.length, cap = A.capMult * intake.revenue, fa = opts_fa || { enabled: false, max_per_action_usd: 0, monthly_action_volume: 0 };
  const transCap = Math.max(10e3, Math.min(cap, fa.max_per_action_usd * fa.monthly_action_volume * A.transCapShare));
  const cats = CATS.map(() => new Float64Array(years)), agg = new Float64Array(years);
  const singles: number[] = [];
  for (let y = 0; y < years; y++) {
    const shock = Math.exp(A.shockSigma * normal(mulberry32(streamSeed(seed, y, 99))) - 0.5 * A.shockSigma ** 2);
    let tot = 0;
    for (let ci = 0; ci < nc; ci++) {
      const key = CATS[ci]!.key, lam = F[key]!.lambda * shock, r = mulberry32(streamSeed(seed, y, ci));
      const u = r(); let p = Math.exp(-lam), cdf = p, n = 0;
      while (u > cdf && n < 60) { n++; p *= lam / n; cdf += p; }
      let sum = 0;
      for (let j = 0; j < n; j++) { const x = Math.min(key === "trans" ? transCap : cap, Math.exp(P[key]!.mu + P[key]!.sigma * normal(r))); sum += x; if (collectEvents && singles.length < 200000) singles.push(x); }
      cats[ci]![y] = sum; tot += sum;
    }
    agg[y] = tot;
  }
  return { cats, agg, singles };
}
export interface PerCat { key: string; eal: number; p95: number; p99: number; p996: number; tailShare: number }
export interface Summary { eal: number; p50: number; p90: number; p95: number; p99: number; p996: number; pLow: number; pMid: number; pHigh: number; tvar99: number; perCat: PerCat[]; curve: { p: number; x: number }[] }
function summarize(sim: Sim, A: Assume): Summary {
  const s = Float64Array.from(sim.agg).sort(), n = s.length;
  const q = (p: number) => quantileSorted(s, p);
  const p99 = q(0.99); let tsum = 0, tn = 0; const tailCat = CATS.map(() => 0);
  for (let y = 0; y < n; y++) if ((sim.agg[y] ?? 0) >= p99 && (sim.agg[y] ?? 0) > 0) { tsum += sim.agg[y] ?? 0; tn++; for (let ci = 0; ci < CATS.length; ci++) tailCat[ci] = (tailCat[ci] ?? 0) + (sim.cats[ci]![y] ?? 0); }
  const perCat = CATS.map((c, ci) => { const cs = Float64Array.from(sim.cats[ci]!).sort(); let m = 0; for (const v of cs) m += v; return { key: c.key, eal: m / n, p95: quantileSorted(cs, 0.95), p99: quantileSorted(cs, 0.99), p996: quantileSorted(cs, 0.996), tailShare: tsum ? (tailCat[ci] ?? 0) / tsum : 0 }; });
  let m = 0; for (const v of s) m += v;
  const curve: { p: number; x: number }[] = []; for (let e = Math.log10(0.5); e >= -3.001; e -= 0.05) { const pe = Math.pow(10, e); curve.push({ p: pe, x: q(1 - pe) }); }
  return { eal: m / n, p50: q(0.5), p90: q(0.9), p95: q(0.95), p99, p996: q(0.996), pLow: q(A.pLow), pMid: q(A.pMid), pHigh: q(A.pHigh), tvar99: tn ? tsum / tn : 0, perCat, curve };
}

// ---------- Component D: coverage indication ----------
export const POLICY_RESPONDS: Record<string, string[]> = { cyber: ["inj", "leak", "loss"], tech_eo: ["hall", "perf", "ip", "bias"], crime: ["trans"] };
export const POLICY_NAME: Record<string, string> = { cyber: "Cyber", tech_eo: "Tech E&O", crime: "Crime" };
export type GapStatus = "unprotected" | "excluded" | "shortfall" | "ok" | "minor";
export interface Gap { key: string; need: number; sublimit: number; available: number; status: GapStatus; note: string }
function gapAnalysis(perCat: PerCat[], coverage: Policy[], stdLimit: number, A: Assume): Gap[] {
  return CATS.map((c, i) => {
    const need = perCat[i]!.p99; const sub = need > 0 ? Math.min(snapUp(need, A.subSteps), stdLimit) : 0;
    const resp = coverage.filter((p) => (POLICY_RESPONDS[p.type] || []).includes(c.key));
    const clean = resp.filter((p) => !p.ai_exclusion); const avail = clean.reduce((m, p) => Math.max(m, p.limit), 0);
    let status: GapStatus, note: string;
    if (need < 25e3) { status = "minor"; note = "Exposure is small for this deployment."; }
    else if (!resp.length) { status = "unprotected"; note = "No current policy responds to this loss type."; }
    else if (!clean.length) { status = "excluded"; note = POLICY_NAME[resp[0]!.type] + " policy would respond, but its AI exclusion likely removes cover."; }
    else if (avail < need) { status = "shortfall"; note = POLICY_NAME[clean[0]!.type] + " limit is below the 1-in-100 year loss for this category."; }
    else { status = "ok"; note = POLICY_NAME[clean[0]!.type] + " limit looks adequate, subject to wording."; }
    return { key: c.key, need, sublimit: sub, available: avail, status, note };
  });
}
export interface Indication {
  schema: string; seed: number; assumptions_version: string; dataset: { events: number; fit_points: number };
  summary: Summary; boot: Record<string, [number, number]> | null; limits: { lean: number; standard: number; conservative: number }; retention: number;
  gaps: Gap[]; confidence: "high" | "medium" | "low"; tailZ: number; severity: Record<string, SeverityParam>; frequency: Record<string, FrequencyParam>;
  comparables: Record<string, Comparable[]>; singleMedian: number; singleP90: number; disclaimer: string;
}
export function indicate(events: LossEvent[], agent: ModelAgent, intake: Intake, seed: number, Ain?: Partial<Assume>, opts?: { years?: number; noBoot?: boolean }): Indication {
  const A: Assume = { ...DEFAULT_ASSUME, ...(Ain || {}) }; opts = opts || {};
  const P = severityParams(events, intake, agent, A), F = frequencyParams(agent, A);
  const sim = simulate(F, P, intake, A, seed, opts.years || A.years, true, agent.capabilities.financial_authority);
  const S = summarize(sim, A);
  let boot: Record<string, [number, number]> | null = null;
  if (!opts.noBoot) {
    const reps: Record<string, number[]> = { eal: [], pLow: [], pMid: [], pHigh: [] };
    for (let b = 0; b < A.bootReps; b++) {
      const Pb = severityParams(events, intake, agent, A, mulberry32(streamSeed(seed, b, 1234)));
      const sb = summarize(simulate(F, Pb, intake, A, seed, A.bootYears, false, agent.capabilities.financial_authority), A);
      for (const k of Object.keys(reps)) reps[k]!.push(sb[k as keyof Summary] as number);
    }
    boot = {}; for (const k of Object.keys(reps)) { const s = reps[k]!.sort((a, b) => a - b); boot[k] = [s[1] ?? 0, s[s.length - 2] ?? 0]; }
  }
  const lean = Math.max(snapUp(S.pLow, A.limitSteps), A.limitSteps[0] ?? 0);
  const standard = Math.max(lean, snapUp(S.pMid, A.limitSteps)), conservative = Math.max(standard, snapUp(S.pHigh, A.limitSteps));
  const ss = Float64Array.from(sim.singles).sort();
  const retention = snapDown(Math.max(quantileSorted(ss, 0.5), A.retSteps[0] ?? 0), A.retSteps);
  const gaps = gapAnalysis(S.perCat, intake.existing_coverage || [], standard, A);
  const tailZ = S.perCat.reduce((t, c) => t + c.tailShare * P[c.key]!.Z, 0);
  const confidence = tailZ >= 0.6 ? "high" : tailZ >= 0.35 ? "medium" : "low";
  const fitN = CATS.reduce((t, c) => t + P[c.key]!.n, 0);
  return { schema: "stoa-coverage-indication/0.1", seed, assumptions_version: A.version, dataset: { events: events.length, fit_points: fitN },
    summary: S, boot, limits: { lean, standard, conservative }, retention, gaps, confidence, tailZ, severity: P, frequency: F,
    comparables: comparables(events, agent, intake, A), singleMedian: quantileSorted(ss, 0.5), singleP90: quantileSorted(ss, 0.9),
    disclaimer: "Indication for discussion with a licensed broker and carrier. Not a quote, not a premium, not advice." };
}

export interface WhatIf { label: string; from: number; to: number }
/** Levers that would lower the bad-year figure, each re-run on a shorter simulation and scaled to the headline. */
export function whatIfs(agent: ModelAgent, intake: Intake, seed: number, last: Indication, Ain?: Partial<Assume>): WhatIf[] {
  const out: WhatIf[] = [], caps = agent.capabilities, o = { years: 30000, noBoot: true };
  const base = indicate(EVENTS, agent, intake, seed, Ain, o).summary.p99;
  const tryIt = (label: string, mut: (a: ModelAgent) => void) => { const a = JSON.parse(JSON.stringify(agent)) as ModelAgent; mut(a); const p = indicate(EVENTS, a, intake, seed, Ain, o).summary.p99; const full = last.summary.pMid; out.push({ label, from: full, to: full * (p / (base || 1)) }); };
  const order: HumanInLoop[] = ["none", "partial", "approval_above_threshold", "full"], i = order.indexOf(caps.human_in_loop);
  if (i < 2) tryIt("Require human approval above a threshold", (a) => (a.capabilities.human_in_loop = "approval_above_threshold"));
  else if (i === 2) tryIt("Approve every action", (a) => (a.capabilities.human_in_loop = "full"));
  if (caps.financial_authority.enabled) tryIt("Halve the per-action payment limit to " + money(caps.financial_authority.max_per_action_usd / 2), (a) => (a.capabilities.financial_authority.max_per_action_usd /= 2));
  const top = last.summary.perCat.slice().sort((a, b) => b.tailShare - a.tailShare)[0]!, dims = CATS.find((c) => c.key === top.key)!.dims, ds = agent.dimension_scores;
  const worst = dims.slice().sort((a, b) => (ds[b] ?? 0) - (ds[a] ?? 0))[0]!;
  if ((ds[worst] ?? 0) > 40) tryIt("Bring the " + (DIMS.find((d) => d[0] === worst)?.[1] ?? worst).toLowerCase() + " score from " + ds[worst] + " down to 40", (a) => (a.dimension_scores[worst] = 40));
  if (caps.autonomy_level === "high") tryIt("Reduce autonomy from high to medium", (a) => (a.capabilities.autonomy_level = "medium"));
  return out;
}

export function money(v: number | null | undefined): string {
  if (v == null) return "not disclosed";
  if (v >= 1e9) return "$" + +(v / 1e9).toFixed(2) + "B";
  if (v >= 1e6) return "$" + +(v / 1e6).toFixed(v >= 1e7 ? 0 : 1) + "M";
  if (v >= 1e3) return "$" + Math.round(v / 1e3) + "k";
  return "$" + Math.round(v);
}
export const pct = (v: number) => Math.round(v * 100) + "%";
export const catName = (k: string) => CATS.find((c) => c.key === k)?.name ?? k;
export const STATUS_LABEL: Record<GapStatus, string> = { unprotected: "Not insured today", excluded: "AI exclusion applies", shortfall: "Under-insured", ok: "Likely covered", minor: "Minor" };
