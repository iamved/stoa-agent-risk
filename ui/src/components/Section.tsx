import type { ReactNode } from "react";

export function Section({ title, caption, actions, children, id }: { title: string; caption?: ReactNode; actions?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section id={id} className="mt-6 first:mt-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
        <div>
          <h2 className="text-[17px] m-0">{title}</h2>
          {caption ? <div className="caption">{caption}</div> : null}
        </div>
        {actions ? <div className="flex gap-2 no-print">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}
