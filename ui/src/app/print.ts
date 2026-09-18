/**
 * Two print renderings share one document: "summary" (one page, from any
 * screen) and "pack" (the underwriter view, from Evidence). A data attribute
 * on <html> selects which @media print rules apply; it is cleared after
 * printing so the screen is untouched.
 */
export type PrintMode = "summary" | "pack";

export function printAs(mode: PrintMode): void {
  const root = document.documentElement;
  root.dataset.print = mode;
  const clear = () => {
    delete root.dataset.print;
    window.removeEventListener("afterprint", clear);
  };
  window.addEventListener("afterprint", clear);
  window.print();
  // Browsers without afterprint (or a cancelled dialog) still recover.
  window.setTimeout(clear, 2000);
}
