import { Icon } from "./Icons";

/** Marks a row as an agent. An icon, not initials in a circle: initials read as a person. */
export function AgentMark() {
  return <span aria-hidden="true" className="inline-flex shrink-0 w-6 h-6 rounded-md bg-navy-100 text-navy items-center justify-center"><Icon.agent /></span>;
}
