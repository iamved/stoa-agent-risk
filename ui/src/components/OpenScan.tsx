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
 * Says where the scan on screen came from whenever that is not obvious: the
 * hosted demo, or a file the viewer opened. A dashboard a customer generated
 * for their own repository shows nothing here.
 */
export function ScanSourceBanner() {
  const { envelope, opened, openScan, openError, clearOpenError } = useApp();
  const demo = envelope.demo === true && opened === null;
  if (!demo && opened === null && !openError) return null;
  return (
    <div className="no-print px-6 pt-4">
      {demo || opened !== null ? (
        <div className="panel px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="min-w-0 flex-1 basis-[32ch]">
            {demo ? (
              <>
                <div className="text-[13.5px] font-medium text-navy">Demo data for a fictional company</div>
                <div className="caption mt-0.5">To see your own agents here, run <span className="mono">stoa scan . --dashboard-json stoa-dashboard.json</span> and open that file. It is read in this browser and never uploaded.</div>
              </>
            ) : (
              <>
                <div className="text-[13.5px] font-medium text-navy truncate">Showing <span className="mono">{opened}</span></div>
                <div className="caption mt-0.5">Opened from your computer and read in this browser. Nothing was uploaded, and closing the tab forgets it.</div>
              </>
            )}
          </div>
          <OpenScanButton onOpen={openScan} className={demo ? "btn btn-primary" : "btn"}>{demo ? "Open your scan" : "Open another scan"}</OpenScanButton>
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
