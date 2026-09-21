import { useRef, type ReactNode } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";

export interface Column<Row> {
  id: string;
  header: string;
  /** An explanation shown beside the header, e.g. how a scale is derived. */
  hint?: ReactNode;
  /** CSS width, e.g. "120px" or "2fr". */
  width: string;
  cell: (row: Row) => ReactNode;
  sortValue?: (row: Row) => string | number;
  align?: "left" | "right";
}

export interface SortState {
  column: string;
  dir: "asc" | "desc";
}

/**
 * Virtualized, sortable table. Renders only the visible window, so 5,000
 * rows stay responsive. Rows are focusable and open on Enter or Space.
 */
export function DataTable<Row>({ rows, columns, rowKey, onRowClick, sort, onSort, height = 560, emptyText = "Nothing matches these filters.", ariaLabel }: {
  rows: Row[];
  columns: Column<Row>[];
  rowKey: (row: Row) => string;
  onRowClick?: (row: Row) => void;
  sort?: SortState | null;
  onSort?: (column: string) => void;
  height?: number;
  emptyText?: string;
  ariaLabel: string;
}) {
  const parent = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parent.current,
    estimateSize: () => 44,
    overscan: 12,
  });
  const clickableRows = Boolean(onRowClick);
  const template = columns.map((c) => c.width).join(" ") + (clickableRows ? " 28px" : "");
  const items = virtualizer.getVirtualItems();

  return (
    <div className="panel overflow-hidden">
      <div ref={parent} style={{ height, overflow: "auto" }} role="table" aria-label={ariaLabel} aria-rowcount={rows.length}>
        <div role="row" className="grid sticky top-0 z-10 bg-panel border-b border-line-strong" style={{ gridTemplateColumns: template, minWidth: "720px" }}>
          {columns.map((c) => {
            const sortable = Boolean(c.sortValue && onSort);
            const active = sort?.column === c.id;
            return (
              <div key={c.id} role="columnheader" aria-sort={active ? (sort?.dir === "asc" ? "ascending" : "descending") : undefined} className={`px-2.5 py-2 text-[11px] uppercase tracking-wide text-ink-muted font-semibold flex items-center gap-1.5 ${c.align === "right" ? "justify-end" : ""}`}>
                {sortable ? (
                  <button type="button" onClick={() => onSort?.(c.id)} className={`inline-flex items-center gap-1 uppercase ${active ? "text-navy" : ""}`}>
                    {c.header}
                    <span aria-hidden="true" className="text-[9px]">{active ? (sort?.dir === "asc" ? "▲" : "▼") : "↕"}</span>
                  </button>
                ) : (
                  <span>{c.header}</span>
                )}
                {c.hint}
              </div>
            );
          })}
          {clickableRows ? <div role="columnheader" aria-hidden="true" /> : null}
        </div>
        {rows.length === 0 ? (
          <div className="p-6 caption text-center">{emptyText}</div>
        ) : (
          <div style={{ height: virtualizer.getTotalSize(), position: "relative", minWidth: "720px" }}>
            {items.map((item) => {
              const row = rows[item.index];
              if (row === undefined) return null;
              const clickable = Boolean(onRowClick);
              return (
                <div
                  key={rowKey(row)}
                  role="row"
                  aria-rowindex={item.index + 1}
                  data-index={item.index}
                  ref={virtualizer.measureElement}
                  tabIndex={clickable ? 0 : -1}
                  onClick={clickable ? () => onRowClick?.(row) : undefined}
                  onKeyDown={clickable ? (e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onRowClick?.(row);
                    }
                  } : undefined}
                  className={`group grid items-start border-b border-line/70 text-[13px] ${clickable ? "cursor-pointer hover:bg-paper focus-visible:bg-paper" : ""}`}
                  style={{ gridTemplateColumns: template, position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${item.start}px)` }}
                >
                  {columns.map((c) => (
                    <div key={c.id} role="cell" className={`px-2.5 py-2 min-w-0 overflow-hidden break-words ${c.align === "right" ? "text-right" : ""}`}>
                      {c.cell(row)}
                    </div>
                  ))}
                  {clickableRows ? <div role="cell" aria-hidden="true" className="py-2 pr-2 text-right text-ink-muted opacity-0 group-hover:opacity-100">›</div> : null}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export function sortRows<Row>(rows: Row[], columns: Column<Row>[], sort: SortState | null): Row[] {
  if (!sort) return rows;
  const column = columns.find((c) => c.id === sort.column);
  if (!column?.sortValue) return rows;
  const value = column.sortValue;
  const dir = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = value(a);
    const vb = value(b);
    if (typeof va === "number" && typeof vb === "number") return (va - vb) * dir;
    return String(va).localeCompare(String(vb)) * dir;
  });
}
