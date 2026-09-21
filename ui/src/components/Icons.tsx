/* 16px stroke icons for navigation. Hand-kept to a handful; no icon library. */
import type { SVGProps } from "react";

const base: SVGProps<SVGSVGElement> = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.75, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true };

export const Icon = {
  overview: () => (
    <svg {...base}><rect x="3" y="3" width="8" height="8" rx="1.5" /><rect x="13" y="3" width="8" height="8" rx="1.5" /><rect x="3" y="13" width="8" height="8" rx="1.5" /><rect x="13" y="13" width="8" height="8" rx="1.5" /></svg>
  ),
  inventory: () => (
    <svg {...base}><circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="6" r="2.5" /><circle cx="12" cy="18" r="2.5" /><path d="M8 7.5l2.5 8M16 7.5l-2.5 8M8.5 6h7" /></svg>
  ),
  scope: () => (
    <svg {...base}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></svg>
  ),
  risk: () => (
    <svg {...base}><path d="M3 20h18" /><path d="M4 16l5-6 4 3 7-8" /></svg>
  ),
  controls: () => (
    <svg {...base}><path d="M12 3l8 3v6c0 4.5-3.5 8-8 9-4.5-1-8-4.5-8-9V6z" /><path d="M9 12l2 2 4-4" /></svg>
  ),
  loss: () => (
    <svg {...base}><rect x="2.5" y="6" width="19" height="12" rx="2" /><circle cx="12" cy="12" r="2.75" /><path d="M6 9.5v5M18 9.5v5" /></svg>
  ),
  agent: () => (
    <svg {...base}><rect x="5" y="8" width="14" height="11" rx="2.5" /><path d="M12 8V4.5" /><circle cx="12" cy="3.5" r="1" /><path d="M9.5 13v1.5M14.5 13v1.5" /></svg>
  ),
  insurance: () => (
    <svg {...base}><path d="M4 12a8 8 0 0 1 16 0z" /><path d="M12 12v6a2 2 0 0 0 4 0" /><path d="M12 3v1" /></svg>
  ),
  flag: () => (
    <svg {...base}><path d="M5 21V4" /><path d="M5 4h11l-2 4 2 4H5" /></svg>
  ),
  clock: () => (
    <svg {...base}><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></svg>
  ),
  check: () => (
    <svg {...base}><circle cx="12" cy="12" r="8.5" /><path d="M8.5 12.5l2.5 2.5 4.5-5" /></svg>
  ),
  users: () => (
    <svg {...base}><circle cx="9" cy="8" r="3" /><path d="M3.5 19a5.5 5.5 0 0 1 11 0" /><path d="M16 4.5a3 3 0 0 1 0 6" /><path d="M17.5 13.5a5 5 0 0 1 3 4.5" /></svg>
  ),
};

export type IconName = keyof typeof Icon;
