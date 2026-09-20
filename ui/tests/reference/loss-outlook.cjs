// Reference: the model exactly as published in the Stoa AI loss outlook page. One edit: the final
// module.exports also lists EVENTS so Node tests can reach the dataset.

// Seed loss event dataset for the demo. Compiled from public reporting; amounts approximate; unverified.
// sig: fin=financial authority, pii, write=write access, cust=customer facing, auto=autonomy, hil=human in loop
const S = (fin, pii, write, cust, auto, hil) => ({ fin, pii, write, cust, auto, hil });
const C = (type, usd, party, ins, grade, src) => ({ type, usd, party, ins, grade, src });
const EVENTS = [
  // AI Hallucinations
  { id: "E01", title: "Moffatt v. Air Canada: chatbot invented a refund policy", year: 2024, org: "Air Canada", sector: "airline", band: "large", rev: 16e9, jur: "CA", cat: "hall", sys: "chatbot", sig: S(0,0,0,1,"low","none"), comps: [C("judgment", 600, "third", "yes", "A", "BC Civil Resolution Tribunal, 2024 BCCRT 149 (about CAD 812)")], status: "final" },
  { id: "E02", title: "Mata v. Avianca: fabricated case citations in a court filing", year: 2023, org: "Levidow, Levidow & Oberman", sector: "legal", band: "micro", rev: null, jur: "US", cat: "hall", sys: "generative", sig: S(0,0,0,0,"low","partial"), comps: [C("judgment", 5000, "first", "partial", "A", "SDNY sanctions order, June 2023")], status: "final" },
  { id: "E03", title: "Lacey v. State Farm: sanctions for AI-generated bogus research", year: 2025, org: "Two law firms (special master order)", sector: "legal", band: "large", rev: 1.3e9, jur: "US", cat: "hall", sys: "generative", sig: S(0,0,0,0,"low","partial"), comps: [C("judgment", 31100, "first", "partial", "B", "C.D. Cal. special master order, May 2025")], status: "final" },
  { id: "E04", title: "MyPillow defamation defense: brief with nonexistent cases", year: 2025, org: "Defense counsel", sector: "legal", band: "micro", rev: null, jur: "US", cat: "hall", sys: "generative", sig: S(0,0,0,0,"low","partial"), comps: [C("judgment", 6000, "first", "partial", "B", "D. Colo. sanctions order, July 2025")], status: "final" },
  { id: "E05", title: "Government report with fabricated references, partial refund", year: 2025, org: "Deloitte Australia", sector: "consulting", band: "large", rev: null, jur: "AU", cat: "hall", sys: "generative", sig: S(0,0,0,1,"low","partial"), comps: [C("contract_refund", null, "first", "yes", "B", "Press reports, Oct 2025; contract about AUD 440k, refund amount not confirmed here")], status: "final" },
  { id: "E06", title: "Bard launch demo gave a wrong answer", year: 2023, org: "Alphabet", sector: "software", band: "mega", rev: 283e9, jur: "US", cat: "hall", sys: "generative", sig: S(0,0,0,1,"low","none"), comps: [C("market_cap_change", 100e9, "first", "no", "B", "Press reports, Feb 2023 (one-day market value move)")], status: "final" },
  { id: "E07", title: "Tessa eating-disorder helpline bot gave harmful advice", year: 2023, org: "NEDA", sector: "health", band: "micro", rev: null, jur: "US", cat: "hall", sys: "chatbot", sig: S(0,1,0,1,"medium","none"), comps: [], status: "final", nearMiss: true },
  { id: "E08", title: "MyCity chatbot told businesses to break the law", year: 2024, org: "City of New York", sector: "government", band: "large", rev: null, jur: "US", cat: "hall", sys: "chatbot", sig: S(0,0,0,1,"low","none"), comps: [], status: "final", nearMiss: true },
  { id: "E09", title: "Support bot invented a login policy, customers cancelled", year: 2025, org: "Cursor (Anysphere)", sector: "software", band: "mid", rev: null, jur: "US", cat: "hall", sys: "chatbot", sig: S(0,1,0,1,"medium","none"), comps: [], status: "final", nearMiss: true },
  // Prompt Injections
  { id: "E10", title: "Dealership chatbot talked into a one-dollar truck offer", year: 2023, org: "Chevrolet of Watsonville", sector: "retail", band: "small", rev: null, jur: "US", cat: "inj", sys: "chatbot", sig: S(0,0,0,1,"low","none"), comps: [], status: "final", nearMiss: true },
  { id: "E11", title: "EchoLeak: zero-click data exfiltration from an enterprise copilot", year: 2025, org: "Microsoft", sector: "software", band: "mega", rev: 245e9, jur: "US", cat: "inj", sys: "agent", sig: S(0,1,0,0,"medium","none"), comps: [], status: "final", nearMiss: true },
  { id: "E12", title: "Workspace AI assistant indirect prompt injection disclosure", year: 2024, org: "Slack (Salesforce)", sector: "software", band: "large", rev: null, jur: "US", cat: "inj", sys: "agent", sig: S(0,1,0,0,"medium","none"), comps: [], status: "final", nearMiss: true },
  { id: "E13", title: "Coding assistant extension shipped with an injected wiper prompt", year: 2025, org: "Amazon (Q Developer)", sector: "software", band: "mega", rev: 638e9, jur: "US", cat: "inj", sys: "agent", sig: S(0,0,1,0,"high","none"), comps: [], status: "final", nearMiss: true },
  { id: "E14", title: "Autonomous crypto agent's wallet drained via queued malicious prompts", year: 2025, org: "AIXBT", sector: "crypto", band: "micro", rev: null, jur: "US", cat: "inj", sys: "agent", sig: S(1,0,1,1,"high","none"), comps: [C("fraud_loss", 100000, "first", "partial", "C", "Press reports, Mar 2025 (about 55 ETH)")], status: "final" },
  // Data Leakage and privacy
  { id: "E15", title: "Italian privacy regulator fines a chatbot provider", year: 2024, org: "OpenAI", sector: "software", band: "large", rev: 3.7e9, jur: "EU", cat: "leak", sys: "generative", sig: S(0,1,0,1,"low","none"), comps: [C("regulatory_fine", 15.6e6, "third", "partial", "A", "Garante decision, Dec 2024 (EUR 15M)")], status: "appealed" , fitAnyway: true},
  { id: "E16", title: "Italian privacy regulator fines a companion chatbot", year: 2025, org: "Luka (Replika)", sector: "software", band: "small", rev: null, jur: "EU", cat: "leak", sys: "chatbot", sig: S(0,1,0,1,"medium","none"), comps: [C("regulatory_fine", 5.6e6, "third", "partial", "A", "Garante decision, 2025 (EUR 5M)")], status: "final" },
  { id: "E17", title: "Dutch regulator fines a facial recognition vendor", year: 2024, org: "Clearview AI", sector: "software", band: "small", rev: null, jur: "EU", cat: "leak", sys: "decision", sig: S(0,1,0,0,"medium","none"), comps: [C("regulatory_fine", 33e6, "third", "partial", "A", "Dutch DPA decision, Sept 2024 (EUR 30.5M)")], status: "final" },
  { id: "E18", title: "Voice assistant recordings class settlement", year: 2025, org: "Apple", sector: "consumer tech", band: "mega", rev: 391e9, jur: "US", cat: "leak", sys: "chatbot", sig: S(0,1,0,1,"low","none"), comps: [C("settlement", 95e6, "third", "yes", "A", "Lopez v. Apple settlement, N.D. Cal.")], status: "final" },
  { id: "E19", title: "State biometric privacy settlement over face tagging", year: 2024, org: "Meta", sector: "software", band: "mega", rev: 135e9, jur: "US", cat: "leak", sys: "decision", sig: S(0,1,0,1,"medium","none"), comps: [C("settlement", 1.4e9, "third", "partial", "A", "Texas Attorney General release, July 2024")], status: "final" },
  { id: "E20", title: "Biometric privacy class settlement over face tagging", year: 2021, org: "Facebook", sector: "software", band: "mega", rev: 86e9, jur: "US", cat: "leak", sys: "decision", sig: S(0,1,0,1,"medium","none"), comps: [C("settlement", 650e6, "third", "yes", "A", "In re Facebook Biometric Information Privacy Litigation, N.D. Cal.")], status: "final" },
  { id: "E21", title: "Children's voice recordings retained by a voice assistant", year: 2023, org: "Amazon (Alexa)", sector: "consumer tech", band: "mega", rev: 514e9, jur: "US", cat: "leak", sys: "chatbot", sig: S(0,1,0,1,"low","none"), comps: [C("regulatory_fine", 25e6, "third", "partial", "A", "FTC and DOJ release, 2023")], status: "final" },
  { id: "E22", title: "Children's data used to train models, algorithm deletion ordered", year: 2022, org: "WW International (Kurbo)", sector: "consumer", band: "large", rev: 1.2e9, jur: "US", cat: "leak", sys: "decision", sig: S(0,1,0,1,"low","none"), comps: [C("regulatory_fine", 1.5e6, "third", "partial", "A", "FTC release, Mar 2022")], status: "final" },
  { id: "E23", title: "Insurer's AI video claims analysis, biometric class settlement", year: 2022, org: "Lemonade", sector: "insurance", band: "mid", rev: 128e6, jur: "US", cat: "leak", sys: "decision", sig: S(1,1,0,1,"high","partial"), comps: [C("settlement", 4e6, "third", "yes", "B", "Press reports of BIPA class settlement, 2022")], status: "final" },
  { id: "E24", title: "Engineers pasted source code into a public chatbot", year: 2023, org: "Samsung", sector: "electronics", band: "mega", rev: 200e9, jur: "KR", cat: "leak", sys: "generative", sig: S(0,0,0,0,"low","none"), comps: [], status: "final", nearMiss: true },
  { id: "E25", title: "Hiring chatbot backend exposed applicant records", year: 2025, org: "Paradox.ai / McDonald's", sector: "hr tech", band: "mid", rev: null, jur: "US", cat: "leak", sys: "chatbot", sig: S(0,1,1,1,"medium","none"), comps: [C("incident_response", null, "first", "yes", "B", "Security researcher disclosure, 2025; no loss figure published")], status: "final" },
  { id: "E26", title: "Cache bug exposed other users' chat titles and payment details", year: 2023, org: "OpenAI", sector: "software", band: "mid", rev: null, jur: "US", cat: "leak", sys: "generative", sig: S(0,1,0,1,"low","none"), comps: [], status: "final", nearMiss: true },
  // IP Infringement
  { id: "E27", title: "Authors' class settlement over pirated training books", year: 2025, org: "Anthropic", sector: "software", band: "large", rev: 5e9, jur: "US", cat: "ip", sys: "generative", sig: S(0,0,0,1,"low","none"), comps: [C("settlement", 1.5e9, "third", "partial", "A", "Bartz v. Anthropic settlement, N.D. Cal., 2025")], status: "final" },
  { id: "E28", title: "Newspaper copyright suit over training and outputs", year: 2023, org: "OpenAI / Microsoft", sector: "software", band: "large", rev: null, jur: "US", cat: "ip", sys: "generative", sig: S(0,0,0,1,"low","none"), comps: [], status: "pending" },
  { id: "E29", title: "Studios sue an image generator over character outputs", year: 2025, org: "Midjourney", sector: "software", band: "mid", rev: null, jur: "US", cat: "ip", sys: "generative", sig: S(0,0,0,1,"low","none"), comps: [], status: "pending" },
  { id: "E30", title: "Legal research startup found liable for training on headnotes", year: 2025, org: "Ross Intelligence", sector: "legal tech", band: "micro", rev: null, jur: "US", cat: "ip", sys: "generative", sig: S(0,0,0,1,"low","none"), comps: [], status: "appealed" },
  // Performance Failure
  { id: "E31", title: "Home pricing model overpaid, business line shut down", year: 2021, org: "Zillow", sector: "real estate", band: "large", rev: 8.1e9, jur: "US", cat: "perf", sys: "decision", sig: S(1,0,1,0,"high","partial"), comps: [C("asset_writedown", 304e6, "first", "no", "A", "Company Q3 2021 results (inventory writedown)")], status: "final" },
  { id: "E32", title: "Ad targeting model ingested bad data, revenue shortfall", year: 2022, org: "Unity", sector: "software", band: "large", rev: 1.1e9, jur: "US", cat: "perf", sys: "decision", sig: S(0,0,1,0,"high","none"), comps: [C("business_interruption", 110e6, "first", "no", "A", "Company Q1 2022 earnings call (own revenue impact)")], status: "final" },
  { id: "E33", title: "Oncology advisor project abandoned after audit", year: 2017, org: "MD Anderson / IBM Watson", sector: "health", band: "large", rev: null, jur: "US", cat: "perf", sys: "decision", sig: S(0,1,0,0,"low","full"), comps: [C("asset_writedown", 62e6, "first", "no", "B", "University of Texas audit, press reports")], status: "final" },
  { id: "E34", title: "\"Robot lawyer\" could not do what it advertised", year: 2025, org: "DoNotPay", sector: "legal tech", band: "small", rev: null, jur: "US", cat: "perf", sys: "generative", sig: S(0,1,0,1,"medium","none"), comps: [C("regulatory_fine", 193000, "third", "partial", "A", "FTC final order, 2025")], status: "final" },
  { id: "E35", title: "Robotaxi dragged a pedestrian, incident report incomplete", year: 2023, org: "Cruise", sector: "mobility", band: "mid", rev: null, jur: "US", cat: "perf", sys: "physical", sig: S(0,0,1,1,"high","none"), comps: [C("regulatory_fine", 1.5e6, "third", "partial", "A", "NHTSA consent order, 2024")], status: "final" },
  { id: "E36", title: "Driver assistance fatal crash, jury verdict", year: 2025, org: "Tesla", sector: "automotive", band: "mega", rev: 97e9, jur: "US", cat: "perf", sys: "physical", sig: S(0,0,1,1,"high","partial"), comps: [C("judgment", 243e6, "third", "yes", "A", "Benavides v. Tesla, S.D. Fla., Aug 2025")], status: "appealed" },
  { id: "E37", title: "Automated fraud detection falsely accused benefit claimants", year: 2022, org: "State of Michigan (MiDAS)", sector: "government", band: "large", rev: null, jur: "US", cat: "perf", sys: "analog", sig: S(1,1,1,1,"high","none"), comps: [C("settlement", 20e6, "third", "partial", "B", "Class settlement, press reports")], status: "final", analog: true },
  { id: "E38", title: "Automated debt recovery raised unlawful debts", year: 2020, org: "Australian Government (Robodebt)", sector: "government", band: "mega", rev: null, jur: "AU", cat: "perf", sys: "analog", sig: S(1,1,1,1,"high","none"), comps: [C("settlement", 1.2e9, "third", "no", "B", "Class settlement about AUD 1.8B including refunds (sovereign program)")], status: "final", analog: true },
  { id: "E39", title: "Care-denial prediction model class action", year: 2023, org: "UnitedHealth (naviHealth)", sector: "health", band: "mega", rev: 372e9, jur: "US", cat: "perf", sys: "decision", sig: S(1,1,1,0,"high","partial"), comps: [], status: "pending" },
  // Algorithmic Bias
  { id: "E40", title: "Hiring software auto-rejected older applicants", year: 2023, org: "iTutorGroup", sector: "edtech", band: "small", rev: null, jur: "US", cat: "bias", sys: "decision", sig: S(0,1,1,0,"high","none"), comps: [C("settlement", 365000, "third", "yes", "A", "EEOC consent decree, Aug 2023")], status: "final" },
  { id: "E41", title: "Tenant screening score disadvantaged voucher holders", year: 2024, org: "SafeRent Solutions", sector: "proptech", band: "small", rev: null, jur: "US", cat: "bias", sys: "decision", sig: S(0,1,0,0,"high","none"), comps: [C("settlement", 2.275e6, "third", "yes", "A", "Louis v. SafeRent, D. Mass., 2024")], status: "final" },
  { id: "E42", title: "Housing ad delivery algorithm, civil penalty", year: 2022, org: "Meta", sector: "software", band: "mega", rev: 117e9, jur: "US", cat: "bias", sys: "decision", sig: S(0,1,0,1,"high","none"), comps: [C("regulatory_fine", 115054, "third", "partial", "A", "DOJ settlement, June 2022")], status: "final" },
  { id: "E43", title: "Student loan underwriting model, state fair lending settlement", year: 2025, org: "Earnest Operations", sector: "fintech", band: "mid", rev: null, jur: "US", cat: "bias", sys: "decision", sig: S(1,1,1,1,"high","partial"), comps: [C("settlement", 2.5e6, "third", "partial", "B", "Massachusetts Attorney General release, July 2025")], status: "final" },
  { id: "E44", title: "Childcare benefits risk model, data protection fine", year: 2021, org: "Dutch Tax Administration", sector: "government", band: "large", rev: null, jur: "EU", cat: "bias", sys: "decision", sig: S(1,1,1,1,"high","partial"), comps: [C("regulatory_fine", 3.3e6, "third", "partial", "A", "Dutch DPA decision, 2021 (EUR 2.75M)")], status: "final" },
  { id: "E45", title: "Applicant screening platform collective action", year: 2023, org: "Workday", sector: "hr tech", band: "large", rev: 7.3e9, jur: "US", cat: "bias", sys: "decision", sig: S(0,1,1,0,"high","none"), comps: [], status: "pending" },
  { id: "E46", title: "Store facial recognition misidentified shoppers, 5-year ban", year: 2023, org: "Rite Aid", sector: "retail", band: "large", rev: 24e9, jur: "US", cat: "bias", sys: "decision", sig: S(0,1,0,1,"medium","partial"), comps: [], status: "final", nearMiss: true },
  // Erroneous Transactions
  { id: "E47", title: "Faulty automated trading deployment, 45 minutes of bad orders", year: 2012, org: "Knight Capital", sector: "fintech", band: "large", rev: 1.4e9, jur: "US", cat: "trans", sys: "analog", sig: S(1,0,1,0,"high","none"), comps: [C("direct_financial_loss", 440e6, "first", "partial", "A", "SEC order, 2013")], status: "final", analog: true },
  { id: "E48", title: "Deepfake video call led staff to wire funds", year: 2024, org: "Arup", sector: "engineering", band: "large", rev: 2.6e9, jur: "HK", cat: "trans", sys: "analog", sig: S(1,0,1,0,"low","partial"), comps: [C("fraud_loss", 25.6e6, "first", "yes", "B", "Company confirmation, press reports, 2024 (about HKD 200M)")], status: "final", analog: true },
  // Data Loss and Corruption
  { id: "E49", title: "Coding agent deleted a production database during a freeze", year: 2025, org: "Replit (customer project)", sector: "software", band: "mid", rev: null, jur: "US", cat: "loss", sys: "agent", sig: S(0,1,1,0,"high","none"), comps: [], status: "final", nearMiss: true },
  { id: "E50", title: "Command-line agent destroyed user files after a failed move", year: 2025, org: "Google (Gemini CLI)", sector: "software", band: "mega", rev: null, jur: "US", cat: "loss", sys: "agent", sig: S(0,0,1,0,"high","none"), comps: [], status: "final", nearMiss: true },
];
if (typeof module !== "undefined") module.exports = { EVENTS };

const CATS = [
  { key: "hall", name: "AI Hallucinations", dims: ["output_fidelity"], third: true },
  { key: "inj", name: "Prompt Injections", dims: ["injection_tamper_surface"], third: false },
  { key: "leak", name: "Data Leakage", dims: ["boundary_leakage"], third: true },
  { key: "ip", name: "IP Infringement", dims: ["output_fidelity", "control_coverage_gap"], third: true },
  { key: "perf", name: "Performance Failure", dims: ["conduct_variability", "dependency_drift"], third: true },
  { key: "bias", name: "Algorithmic Bias", dims: ["unreviewed_high_impact_action", "control_coverage_gap"], third: true },
  { key: "trans", name: "Erroneous Transactions", dims: ["mandate_overreach", "unreviewed_high_impact_action"], third: false },
  { key: "loss", name: "Data Loss and Corruption", dims: ["mandate_overreach", "dependency_drift"], third: false },
];
const DIMS = [
  ["boundary_leakage", "Boundary leakage"], ["mandate_overreach", "Mandate overreach"],
  ["injection_tamper_surface", "Injection and tamper surface"], ["control_coverage_gap", "Control coverage gap"],
  ["unreviewed_high_impact_action", "Unreviewed high-impact action"], ["output_fidelity", "Output fidelity"],
  ["conduct_variability", "Conduct variability"], ["dependency_drift", "Dependency drift"],
];
const BAND_REV = { micro: 3e6, small: 30e6, mid: 300e6, large: 7e9, mega: 150e9 };

const DEFAULT_ASSUME = {
  version: "demo-0.1",
  alpha: 0.5,            // revenue scaling exponent (sublinear)
  scaleClamp: [0.01, 10],
  k: 8,                  // credibility constant, Z = n / (n + k)
  reportingShift: -1.5,  // log shift on observed severities: public events skew severe
  defenseLoad: 1.25,     // loading on third-party categories: public figures omit defense costs
  capMult: 0.5,          // single event capped at this multiple of annual revenue
  insFrac: { yes: 1, partial: 0.5, no: 0 },
  inflation: 0.03, currentYear: 2026,
  pLow: 0.95, pMid: 0.99, pHigh: 0.996,
  years: 100000, bootReps: 30, bootYears: 10000,
  shockSigma: 0.3, sigmaCap: 2.1, transCapShare: 0.02, refRevenue: 50e6, priorJitter: 0.5,
  base: { hall: 0.15, inj: 0.08, leak: 0.06, ip: 0.02, perf: 0.08, bias: 0.04, trans: 0.10, loss: 0.05 },
  prior: {
    hall: { median: 40e3, sigma: 1.8 }, inj: { median: 120e3, sigma: 1.8 }, leak: { median: 200e3, sigma: 1.9 },
    ip: { median: 250e3, sigma: 2.0 }, perf: { median: 150e3, sigma: 1.8 }, bias: { median: 250e3, sigma: 1.8 },
    trans: { median: 80e3, sigma: 2.0 }, loss: { median: 100e3, sigma: 1.7 },
  },
  hil: { none: 1.0, partial: 0.7, approval_above_threshold: 0.5, full: 0.25 },
  autonomy: { low: 0.7, medium: 1.0, high: 1.3 },
  gateFloor: { trans: 0.02, leak: 0.05, loss: 0.1 },
  limitSteps: [1e6, 2e6, 3e6, 5e6, 10e6, 15e6, 20e6, 25e6, 50e6, 100e6],
  subSteps: [250e3, 500e3, 1e6, 2e6, 3e6, 5e6, 10e6, 15e6, 20e6, 25e6, 50e6, 100e6],
  retSteps: [10e3, 25e3, 50e3, 100e3, 250e3, 500e3, 1e6],
};

function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function streamSeed(seed, year, cat) {
  let h = Math.imul(seed | 0, 0x9E3779B1) ^ Math.imul(year + 1, 0x85EBCA6B) ^ Math.imul(cat + 7, 0xC2B2AE35);
  h ^= h >>> 16; h = Math.imul(h, 0x7FEB352D); h ^= h >>> 15; h = Math.imul(h, 0x846CA68B); h ^= h >>> 16;
  return h >>> 0;
}
function normal(r) { let u = 0; while (u === 0) u = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r()); }
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const mean = (a) => a.reduce((s, v) => s + v, 0) / a.length;
function quantileSorted(s, p) { if (!s.length) return 0; const i = clamp(Math.ceil(p * s.length) - 1, 0, s.length - 1); return s[i]; }
const snapUp = (v, steps) => { for (const s of steps) if (v <= s) return s; return steps[steps.length - 1]; };
const snapDown = (v, steps) => { let o = steps[0]; for (const s of steps) if (s <= v) o = s; return o; };

// ---------- Component B: scaling and matching ----------
function eventRevenue(e) { return e.rev || BAND_REV[e.band] || null; }
function scaledInsurable(e, intake, A) {
  // returns scaled, inflated, insurable USD for one event, or null if no usable amount
  if (e.status === "pending" || e.status === "appealed") return null;
  let tot = 0, any = false;
  for (const c of e.comps) { if (c.usd == null) continue; const f = A.insFrac[c.ins] || 0; if (f > 0) { tot += c.usd * f; any = true; } }
  if (!any) return null;
  const infl = Math.pow(1 + A.inflation, Math.max(0, A.currentYear - e.year));
  const er = eventRevenue(e);
  const factor = er ? clamp(Math.pow(intake.revenue / er, A.alpha), A.scaleClamp[0], A.scaleClamp[1]) : 1;
  return { usd: tot * infl * factor, factor, infl };
}
function similarity(e, agent, intake) {
  const c = agent.capabilities, why = []; let m = 0;
  const pairs = [
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
function comparables(events, agent, intake, A) {
  const out = {};
  for (const cat of CATS) {
    out[cat.key] = events.filter((e) => e.cat === cat.key).map((e) => {
      const s = similarity(e, agent, intake); const sc = scaledInsurable(e, intake, A);
      const raw = e.comps.reduce((t, c) => t + (c.usd || 0), 0) || null;
      return { id: e.id, title: e.title, org: e.org, year: e.year, status: e.status, nearMiss: !!e.nearMiss, analog: !!e.analog, raw, scaled: sc ? sc.usd : null, score: s.score, why: s.why,
        grade: e.comps.length ? e.comps[0].grade : null, src: e.comps.length ? e.comps[0].src : null, ins: e.comps.length ? e.comps[0].ins : null };
    }).sort((a, b) => (b.score + (b.raw ? 0.15 : 0)) - (a.score + (a.raw ? 0.15 : 0)) || (b.scaled || 0) - (a.scaled || 0));
  }
  return out;
}

// ---------- Component C: severity and frequency ----------
function severityParams(events, intake, agent, A, resampleRng) {
  const c = agent.capabilities, P = {};
  for (const cat of CATS) {
    let pts = events.filter((e) => e.cat === cat.key).map((e) => scaledInsurable(e, intake, A)).filter(Boolean).map((s) => Math.log(s.usd) + A.reportingShift);
    const n = pts.length;
    let jitter = 0;
    if (resampleRng) { pts = pts.map(() => pts[Math.floor(resampleRng() * n)]); jitter = A.priorJitter * normal(resampleRng); }
    const pr = A.prior[cat.key];
    const muPrior = Math.log(pr.median) + A.alpha * Math.log(intake.revenue / A.refRevenue) + jitter;
    const Z = n / (n + A.k);
    let mu = muPrior, sigma = pr.sigma, muData = null, sdData = null;
    if (n >= 1) { muData = mean(pts); mu = Z * muData + (1 - Z) * muPrior; }
    if (n >= 2) { const v = pts.reduce((s, x) => s + (x - muData) ** 2, 0) / (n - 1); sdData = Math.sqrt(v); sigma = Math.sqrt(Z * v + (1 - Z) * pr.sigma ** 2); }
    sigma = clamp(sigma, 0.8, A.sigmaCap);
    // severity modifiers from business context and authority caps
    let mod = cat.third ? A.defenseLoad : 1; const mods = []; if (cat.third) mods.push("defense cost loading x" + A.defenseLoad);
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
function frequencyParams(agent, A) {
  const c = agent.capabilities, d = agent.dimension_scores, F = {};
  for (const cat of CATS) {
    const s = mean(cat.dims.map((k) => d[k]));
    const scoreMod = Math.exp(((s - 50) / 50) * Math.log(2.5));
    let lam = A.base[cat.key] * scoreMod * A.autonomy[c.autonomy_level]; const mods = ["scan score " + Math.round(s) + " x" + scoreMod.toFixed(2), c.autonomy_level + " autonomy x" + A.autonomy[c.autonomy_level]];
    const h = A.hil[c.human_in_loop];
    if (["trans", "bias", "perf", "loss"].includes(cat.key)) { lam *= h; mods.push("human review x" + h); }
    else if (cat.key === "hall") { const hh = 1 - (1 - h) * 0.3; lam *= hh; mods.push("human review x" + hh.toFixed(2)); }
    if (cat.key === "trans") {
      if (!c.financial_authority.enabled) { lam *= A.gateFloor.trans; mods.push("no payment authority, floor x" + A.gateFloor.trans); }
      else { const v = clamp(Math.pow(Math.max(c.financial_authority.monthly_action_volume, 1) / 50000, 0.3), 0.3, 4); lam *= v; mods.push("action volume x" + v.toFixed(2)); }
    }
    if (cat.key === "leak" && !c.pii_access && (!c.sensitive_data_access || c.sensitive_data_access === "none")) { lam *= A.gateFloor.leak; mods.push("no personal or sensitive data, floor x" + A.gateFloor.leak); }
    if (cat.key === "loss" && !c.write_access_to_systems) { lam *= A.gateFloor.loss; mods.push("no write access, floor x" + A.gateFloor.loss); }
    if ((cat.key === "hall" || cat.key === "inj") && !c.customer_facing) { const m = cat.key === "hall" ? 0.4 : 0.5; lam *= m; mods.push("internal use x" + m); }
    F[cat.key] = { lambda: lam, mods };
  }
  return F;
}
function simulate(F, P, intake, A, seed, years, collectEvents, opts_fa) {
  const nc = CATS.length, cap = A.capMult * intake.revenue, fa = opts_fa || { max_per_action_usd: 0, monthly_action_volume: 0 };
  const transCap = Math.max(10e3, Math.min(cap, fa.max_per_action_usd * fa.monthly_action_volume * A.transCapShare));
  const cats = CATS.map(() => new Float64Array(years)), agg = new Float64Array(years);
  const singles = [];
  for (let y = 0; y < years; y++) {
    const shock = Math.exp(A.shockSigma * normal(mulberry32(streamSeed(seed, y, 99))) - 0.5 * A.shockSigma ** 2);
    let tot = 0;
    for (let ci = 0; ci < nc; ci++) {
      const key = CATS[ci].key, lam = F[key].lambda * shock, r = mulberry32(streamSeed(seed, y, ci));
      const u = r(); let p = Math.exp(-lam), cdf = p, n = 0;
      while (u > cdf && n < 60) { n++; p *= lam / n; cdf += p; }
      let sum = 0;
      for (let j = 0; j < n; j++) { const x = Math.min(key === "trans" ? transCap : cap, Math.exp(P[key].mu + P[key].sigma * normal(r))); sum += x; if (collectEvents && singles.length < 200000) singles.push(x); }
      cats[ci][y] = sum; tot += sum;
    }
    agg[y] = tot;
  }
  return { cats, agg, singles };
}
function summarize(sim, A) {
  const s = Float64Array.from(sim.agg).sort(), n = s.length;
  const q = (p) => quantileSorted(s, p);
  const p99 = q(0.99); let tsum = 0, tn = 0; const tailCat = CATS.map(() => 0);
  for (let y = 0; y < n; y++) if (sim.agg[y] >= p99 && sim.agg[y] > 0) { tsum += sim.agg[y]; tn++; for (let ci = 0; ci < CATS.length; ci++) tailCat[ci] += sim.cats[ci][y]; }
  const perCat = CATS.map((c, ci) => { const cs = Float64Array.from(sim.cats[ci]).sort(); let m = 0; for (const v of cs) m += v; return { key: c.key, eal: m / n, p95: quantileSorted(cs, 0.95), p99: quantileSorted(cs, 0.99), p996: quantileSorted(cs, 0.996), tailShare: tsum ? tailCat[ci] / tsum : 0 }; });
  let m = 0; for (const v of s) m += v;
  const curve = []; for (let e = Math.log10(0.5); e >= -3.001; e -= 0.05) { const pe = Math.pow(10, e); curve.push({ p: pe, x: q(1 - pe) }); }
  return { eal: m / n, p50: q(0.5), p90: q(0.9), p95: q(0.95), p99, p996: q(0.996), pLow: q(A.pLow), pMid: q(A.pMid), pHigh: q(A.pHigh), tvar99: tn ? tsum / tn : 0, perCat, curve };
}

// ---------- Component D: coverage indication ----------
const POLICY_RESPONDS = { cyber: ["inj", "leak", "loss"], tech_eo: ["hall", "perf", "ip", "bias"], crime: ["trans"] };
const POLICY_NAME = { cyber: "Cyber", tech_eo: "Tech E&O", crime: "Crime" };
function gapAnalysis(perCat, coverage, stdLimit, A) {
  return CATS.map((c, i) => {
    const need = perCat[i].p99; const sub = need > 0 ? Math.min(snapUp(need, A.subSteps), stdLimit) : 0;
    const resp = coverage.filter((p) => (POLICY_RESPONDS[p.type] || []).includes(c.key));
    const clean = resp.filter((p) => !p.ai_exclusion); const avail = clean.reduce((m, p) => Math.max(m, p.limit), 0);
    let status, note;
    if (need < 25e3) { status = "minor"; note = "Exposure is small for this deployment."; }
    else if (!resp.length) { status = "unprotected"; note = "No current policy responds to this loss type."; }
    else if (!clean.length) { status = "excluded"; note = POLICY_NAME[resp[0].type] + " policy would respond, but its AI exclusion likely removes cover."; }
    else if (avail < need) { status = "shortfall"; note = POLICY_NAME[clean[0].type] + " limit is below the 1-in-100 year loss for this category."; }
    else { status = "ok"; note = POLICY_NAME[clean[0].type] + " limit looks adequate, subject to wording."; }
    return { key: c.key, need, sublimit: sub, available: avail, status, note };
  });
}
function indicate(events, scan, intake, seed, Ain, opts) {
  const A = Object.assign({}, DEFAULT_ASSUME, Ain || {}); opts = opts || {};
  const agent = scan.agents[0];
  const P = severityParams(events, intake, agent, A), F = frequencyParams(agent, A);
  const sim = simulate(F, P, intake, A, seed, opts.years || A.years, true, agent.capabilities.financial_authority);
  const S = summarize(sim, A);
  let boot = null;
  if (!opts.noBoot) {
    const reps = { eal: [], pLow: [], pMid: [], pHigh: [] };
    for (let b = 0; b < A.bootReps; b++) {
      const Pb = severityParams(events, intake, agent, A, mulberry32(streamSeed(seed, b, 1234)));
      const sb = summarize(simulate(F, Pb, intake, A, seed, A.bootYears, false, agent.capabilities.financial_authority), A);
      for (const k in reps) reps[k].push(sb[k]);
    }
    boot = {}; for (const k in reps) { const s = reps[k].sort((a, b) => a - b); boot[k] = [s[1], s[s.length - 2]]; }
  }
  const lean = Math.max(snapUp(S.pLow, A.limitSteps), A.limitSteps[0]);
  const standard = Math.max(lean, snapUp(S.pMid, A.limitSteps)), conservative = Math.max(standard, snapUp(S.pHigh, A.limitSteps));
  const ss = Float64Array.from(sim.singles).sort();
  const retention = snapDown(Math.max(quantileSorted(ss, 0.5), A.retSteps[0]), A.retSteps);
  const gaps = gapAnalysis(S.perCat, intake.existing_coverage || [], standard, A);
  const tailZ = S.perCat.reduce((t, c) => t + c.tailShare * P[c.key].Z, 0);
  const confidence = tailZ >= 0.6 ? "high" : tailZ >= 0.35 ? "medium" : "low";
  const fitN = CATS.reduce((t, c) => t + P[c.key].n, 0);
  return { schema: "stoa-coverage-indication/0.1", seed, assumptions_version: A.version, dataset: { events: events.length, fit_points: fitN },
    summary: S, boot, limits: { lean, standard, conservative }, retention, gaps, confidence, tailZ, severity: P, frequency: F,
    comparables: comparables(events, agent, intake, A), singleMedian: quantileSorted(ss, 0.5), singleP90: quantileSorted(ss, 0.9),
    disclaimer: "Indication for discussion with a licensed broker and carrier. Not a quote, not a premium, not advice." };
}

// ---------- Fixtures ----------
const mkAgent = (name, fa, max, vol, pii, sens, write, auto, hil, cust, d) => ({ name, capabilities: { financial_authority: { enabled: fa, max_per_action_usd: max, monthly_action_volume: vol }, pii_access: pii, sensitive_data_access: sens, write_access_to_systems: write, autonomy_level: auto, human_in_loop: hil, customer_facing: cust },
  dimension_scores: { boundary_leakage: d[0], mandate_overreach: d[1], injection_tamper_surface: d[2], control_coverage_gap: d[3], unreviewed_high_impact_action: d[4], output_fidelity: d[5], conduct_variability: d[6], dependency_drift: d[7] } });
const FIXTURES = {
  F1: { label: "EdTech, seed stage: tutoring chatbot", scan: { schema: "stoa-risk-report/1.2", agents: [mkAgent("tutor-chat", false, 0, 0, true, "none", false, "medium", "none", true, [58, 30, 60, 65, 35, 66, 55, 45])] },
    intake: { revenue: 2e6, sector: "edtech", jurisdictions: ["US"], records: 120e3, regulated: true, minors: true, existing_coverage: [] } },
  F2: { label: "Fintech, Series B: refund agent", scan: { schema: "stoa-risk-report/1.2", agents: [mkAgent("refund-agent", true, 500, 200000, true, "payment", true, "high", "none", true, [62, 71, 55, 68, 80, 40, 35, 30])] },
    intake: { revenue: 40e6, sector: "fintech", jurisdictions: ["US", "EU"], records: 1.5e6, regulated: true, minors: false, existing_coverage: [{ type: "cyber", limit: 5e6, ai_exclusion: true }] } },
  F3: { label: "HealthTech, growth stage: prior-auth triage agent", scan: { schema: "stoa-risk-report/1.2", agents: [mkAgent("prior-auth-triage", false, 0, 0, true, "phi", true, "medium", "partial", false, [55, 48, 38, 52, 74, 58, 50, 42])] },
    intake: { revenue: 150e6, sector: "healthtech", jurisdictions: ["US"], records: 3e6, regulated: true, minors: false, existing_coverage: [{ type: "tech_eo", limit: 10e6, ai_exclusion: false }] } },
};
const clone = (o) => JSON.parse(JSON.stringify(o));

if (typeof module !== "undefined") module.exports = { EVENTS, CATS, DIMS, DEFAULT_ASSUME, indicate, FIXTURES, clone };

