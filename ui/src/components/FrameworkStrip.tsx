import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { frameworkClasses, type ClassState } from "../data/selectors";
import { frameworkLabel } from "../data/frameworks";

const STATE_LABEL: Record<ClassState, string> = {
  observed: "observed in this scan",
  assessable: "detector present, nothing observed",
  gap: "no detector (gap)",
  aligned: "aligned",
  outside: "outside a static scan",
};

const STATE_CLASS: Record<ClassState, string> = {
  observed: "border-sev-high/40 bg-sev-high-bg",
  assessable: "border-ok/40 bg-ok-bg",
  gap: "border-dashed border-line bg-paper text-ink-muted",
  aligned: "border-ok/40 bg-ok-bg",
  outside: "border-dashed border-line bg-paper text-ink-muted",
};

/** Which classes of the selected framework this scan touched. Gaps are shown as gaps, never hidden. */
export function FrameworkStrip() {
  const { envelope, framework } = useApp();
  const classes = frameworkClasses(envelope, framework);
  return (
    <div>
      <div className="grid gap-2 grid-cols-2 md:grid-cols-5">
        {classes.map((c) => {
          const inner = (
            <>
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-[12.5px]">{c.id}</span>
                {c.count ? <span className="text-[11px] tabular-nums">{c.count}</span> : null}
              </div>
              <div className="text-[12px] leading-snug mt-0.5">{c.name}</div>
              <div className="caption text-[11px] mt-1">{STATE_LABEL[c.state]}</div>
            </>
          );
          const cls = `rounded border p-2 block no-underline text-ink ${STATE_CLASS[c.state]}`;
          return c.count ? (
            <a key={c.id} href={buildHash("findings", null, { class: c.id })} className={cls}>
              {inner}
            </a>
          ) : (
            <div key={c.id} className={cls}>
              {inner}
            </div>
          );
        })}
      </div>
      <p className="caption mt-2 mb-0">
        {frameworkLabel(framework)}: a labeling layer. {framework === "nist" ? "Rolled up once at report level, not per rule. This is an alignment aid, not a certification claim." : "One primary class per rule. A class with no detector is listed as a gap rather than dropped."}
      </p>
    </div>
  );
}
