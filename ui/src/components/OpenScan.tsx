import { useRef, type ReactNode } from "react";
import { useApp } from "../app/context";

/** A button that opens the file picker. The input is reset after each pick so the same file can be reopened. */
export function OpenScanButton({ onOpen, className = "btn", role, children }: { onOpen: (file: File) => void; className?: string; role?: "menuitem"; children: ReactNode }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <button type="button" role={role} className={className} onClick={() => input.current?.click()}>{children}</button>
      <input
        ref={input}
        type="file"
        accept=".json,.html,application/json,text/html"
        hidden
        aria-hidden="true"
        tabIndex={-1}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) onOpen(file);
        }}
      />
    </>
  );
}

/**
 * Says when the scan on screen is a file the viewer opened, and reports a file
 * that could not be opened. A dashboard's own embedded scan shows nothing here.
 */
export function ScanSourceBanner() {
  const { opened, openScan, openError, clearOpenError } = useApp();
  if (opened === null && !openError) return null;
  return (
    <div className="no-print px-6 pt-4">
      {opened !== null ? (
        <div className="panel px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="min-w-0 flex-1 basis-[32ch]">
            <div className="text-[13.5px] font-medium text-navy truncate">Showing <span className="mono">{opened}</span></div>
            <div className="caption mt-0.5">Opened from your computer and read in this browser. Nothing was uploaded, and closing the tab forgets it.</div>
          </div>
          <OpenScanButton onOpen={openScan} className="btn">Open another scan</OpenScanButton>
        </div>
      ) : null}
      {openError ? (
        <div role="alert" className="panel mt-2 px-4 py-3 flex flex-wrap items-start gap-x-4 gap-y-2">
          <div className="min-w-0 flex-1">
            <div className="text-[13.5px] font-medium text-sev-critical">That file could not be opened{openError.found ? <> (<span className="mono">{openError.found}</span>)</> : null}</div>
            <div className="caption mt-0.5">{openError.message} The scan on screen is unchanged.</div>
          </div>
          <button type="button" className="btn btn-sm" onClick={clearOpenError}>Dismiss</button>
        </div>
      ) : null}
    </div>
  );
}
