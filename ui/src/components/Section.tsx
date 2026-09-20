import type { ReactNode } from "react";

export function Section({ title, caption, actions, children, id }: { title: string; caption?: ReactNode; actions?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section id={id} className="mt-8 first:mt-0">
      <div className="flex flex-wrap items-end justify-between gap-2 pb-2 mb-3 border-b border-line">
        <div>
          <h2 className="m-0">{title}</h2>
          {caption ? <div className="caption mt-0.5">{caption}</div> : null}
        </div>
        {actions ? <div className="flex gap-2 no-print">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}
