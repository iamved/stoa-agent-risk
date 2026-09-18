import type { ReactNode } from "react";

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="panel p-8 text-center">
      <h3 className="text-[16px] m-0">{title}</h3>
      {children ? <div className="caption mt-2 max-w-prose mx-auto">{children}</div> : null}
    </div>
  );
}
