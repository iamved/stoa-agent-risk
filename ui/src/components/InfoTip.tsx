import { EXPOSURE_METHOD, SEVERITY_METHOD } from "../data/exposure";

/**
 * A small "i" that explains a label. Opens on hover and on keyboard focus, and
 * its text is the button's accessible name, so it is never hover-only.
 */
export function InfoTip({ topic, text, align = "center" }: { topic: string; text: string; align?: "left" | "center" | "right" }) {
  const position = align === "left" ? "left-0" : align === "right" ? "right-0" : "left-1/2 -translate-x-1/2";
  return (
    <span className="relative inline-flex group align-middle no-print">
      <button type="button" aria-label={`${topic}. ${text}`} onClick={(e) => e.stopPropagation()} className="w-[15px] h-[15px] rounded-full border border-line-strong bg-panel text-[10px] leading-none font-semibold text-ink-muted normal-case cursor-help hover:text-navy hover:border-navy focus-visible:outline focus-visible:outline-2 focus-visible:outline-navy">i</button>
      <span role="tooltip" className={`pointer-events-none absolute z-40 top-full mt-1.5 ${position} w-[270px] rounded-md border border-line-strong bg-panel px-3 py-2 text-[12px] leading-snug font-normal normal-case tracking-normal text-left text-ink shadow-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible group-focus-within:opacity-100 group-focus-within:visible`}>{text}</span>
    </span>
  );
}

export function ExposureTip({ align }: { align?: "left" | "center" | "right" }) {
  return <InfoTip topic="How exposure is derived" text={EXPOSURE_METHOD} align={align} />;
}

export function SeverityTip({ align }: { align?: "left" | "center" | "right" }) {
  return <InfoTip topic="How severity is set" text={SEVERITY_METHOD} align={align} />;
}
