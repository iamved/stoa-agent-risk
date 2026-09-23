import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { ExposureBadge } from "../components/Badge";
import { definedIn } from "../data/agents";
import { auditRows } from "../data/audit";

/** One table: agent, who answers for it, and where to take it. */
export function Audit() {
  const { envelope } = useApp();
  const rows = auditRows(envelope);
  const anyLink = rows.some((r) => r.slack || r.jira);
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-4">
        <h1 className="m-0">Launch Safety Audit</h1>
        <div className="caption">Owners and links are from stoa-declared.toml.</div>
      </div>
      {rows.length ? (
        <div className="panel overflow-x-auto">
          <table className="tbl w-full">
            <thead><tr><th>Agent</th><th>Owner</th><th>Engineer</th><th>Findings</th><th>Next step</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.agent.id}>
                  <td><a href={buildHash("inventory", r.agent.id)} className="link font-medium">{r.agent.name}</a><div className="caption">{definedIn(r.agent)}</div></td>
                  <td>{r.owner || <span className="caption">not declared</span>}</td>
                  <td>{r.engineer || <span className="caption">not declared</span>}</td>
                  <td><span className="flex items-center gap-2"><ExposureBadge exposure={r.exposure} />{r.high ? <a href={buildHash("findings", null, { agent: r.agent.records[0]!.id, severity: "critical,high" })} className="link tabular-nums">{r.high} high</a> : null}</span></td>
                  <td>
                    <span className="flex flex-wrap gap-1.5">
                      {r.slack ? <a href={r.slack} target="_blank" rel="noreferrer" className="btn btn-sm no-underline">Slack thread</a> : null}
                      {r.jira ? <a href={r.jira} target="_blank" rel="noreferrer" className="btn btn-sm no-underline">Create Jira ticket</a> : null}
                      {r.email ? <a href={r.email} className="btn btn-sm no-underline">Email owner</a> : null}
                      {!r.slack && !r.jira && !r.email ? <span className="caption">nothing declared</span> : null}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="caption">No agents were found in the scanned files.</p>}
      {!anyLink ? <p className="caption mt-3 mb-0">Add <span className="mono">slack_thread</span> to an agent and <span className="mono">jira_create_url</span> under <span className="mono">[integrations]</span> in stoa-declared.toml to link from here.</p> : null}
    </div>
  );
}
