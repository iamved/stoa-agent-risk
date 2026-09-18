import { useState } from "react";

const LIMIT = 480;

/** Code rendered as a text node only. Long snippets truncate with a control that reveals what is already embedded. */
export function Snippet({ text, label }: { text: string; label?: string }) {
  const [expanded, setExpanded] = useState(false);
  const long = text.length > LIMIT;
  const shown = long && !expanded ? text.slice(0, LIMIT) : text;
  return (
    <div>
      {label ? <div className="caption mb-1">{label}</div> : null}
      <pre className="m-0 whitespace-pre-wrap break-words rounded border border-line bg-paper p-2.5 text-[12.5px] leading-relaxed">{shown}{long && !expanded ? "…" : ""}</pre>
      {long ? (
        <button type="button" onClick={() => setExpanded(!expanded)} className="link text-[12.5px] mt-1">
          {expanded ? "Show less" : `Show all ${text.length} characters`}
        </button>
      ) : null}
    </div>
  );
}
