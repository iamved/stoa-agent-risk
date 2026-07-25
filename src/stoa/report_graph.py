"""Interactive architecture-graph section embedded in stoa-report.html.

The report is otherwise script-free with a CSP that blocks all script
execution (``default-src 'none'``, no ``script-src``). This section is the
one exception: it inlines a vendored copy of Cytoscape.js (MIT, see
``NOTICE``) plus a small fixed render script.

Both inlined ``<script>`` tags have content that is **identical on every
render** — no repo-derived data is ever interpolated into them. Per-repo
graph data instead lives in a separate ``<script type="application/json">``
tag, which never executes and so needs no CSP allowance at all (only
``</script`` escaping, standard practice for embedding JSON in HTML).

Because both executable scripts are byte-fixed, their SHA-256 hashes are
computed once at import time (not per render, and never from repo data) and
used to build a `script-src 'sha256-...' 'sha256-...'` CSP directive: any
content that isn't one of these two exact, reviewed scripts — including
anything an attacker might smuggle through a data value — cannot execute.
"""

from __future__ import annotations

import base64
import hashlib
from importlib import resources

from .graph_model import Graph, to_json_dict

_VENDOR_JS = (resources.files("stoa") / "templates" / "cytoscape.min.js").read_text(
    encoding="utf-8"
)
CYTOSCAPE_VERSION = "3.34.0"

_GLUE_JS = r"""
(function () {
  var SEVERITY_COLOR = {
    critical: ["#fde8e8", "#b42318"],
    high: ["#fdf0e0", "#b54708"],
    medium: ["#fef7dc", "#93700b"],
    low: ["#eef2f6", "#465063"],
    info: ["#e8f0fe", "#1d4ed8"],
    none: ["#f1f3f6", "#5a6272"]
  };
  var SEVERITY_RANK = { none: 0, info: 1, low: 2, medium: 3, high: 4, critical: 5 };
  var SHAPE = { agent: "round-rectangle", mcp_server: "hexagon", tool: "round-diamond", resource: "barrel" };

  var root = document.getElementById("stoa-graph-root");
  if (!root) return;
  var dataEl = document.getElementById("stoa-graph-data");
  var data = JSON.parse(dataEl.textContent);
  var emptyEl = document.getElementById("stoa-graph-empty");
  if (!data.nodes.length) {
    if (emptyEl) emptyEl.style.display = "block";
    return;
  }

  var elements = data.nodes.map(function (n) {
    return { data: { id: n.id, label: n.label, type: n.type, severity: n.display_severity || "none" }, ref: n };
  }).concat(data.edges.map(function (e, i) {
    return {
      data: {
        id: "e" + i, source: e.source, target: e.target,
        kind: e.kind, severity: e.max_severity || "none"
      },
      ref: e
    };
  }));

  var refById = {};
  elements.forEach(function (el) { refById[el.data.id] = el.ref; });

  var cy = cytoscape({
    container: root,
    elements: elements.map(function (el) { return { data: el.data }; }),
    style: [
      { selector: "node", style: {
          "shape": function (el) { return SHAPE[el.data("type")] || "ellipse"; },
          "background-color": function (el) { return (SEVERITY_COLOR[el.data("severity")] || SEVERITY_COLOR.none)[0]; },
          "border-color": function (el) { return (SEVERITY_COLOR[el.data("severity")] || SEVERITY_COLOR.none)[1]; },
          "border-width": 2,
          "label": "data(label)",
          "font-size": 10,
          "color": "#1a1d23",
          "text-valign": "bottom",
          "text-margin-y": 4,
          "width": 28,
          "height": 28
      }},
      { selector: "edge", style: {
          "width": 1.5,
          "line-color": function (el) { return (SEVERITY_COLOR[el.data("severity")] || SEVERITY_COLOR.none)[1]; },
          "target-arrow-color": function (el) { return (SEVERITY_COLOR[el.data("severity")] || SEVERITY_COLOR.none)[1]; },
          "target-arrow-shape": "triangle",
          "curve-style": "bezier",
          "opacity": 0.85
      }},
      { selector: ".stoa-hidden", style: { "display": "none" } }
    ],
    layout: { name: "cose", animate: false, nodeRepulsion: 8000, idealEdgeLength: 90 }
  });

  var panel = document.getElementById("stoa-graph-panel");

  function clearPanel() {
    while (panel.firstChild) panel.removeChild(panel.firstChild);
  }
  function row(label, value) {
    var p = document.createElement("p");
    p.className = "kv";
    var k = document.createElement("span");
    k.className = "k";
    k.textContent = label + ": ";
    p.appendChild(k);
    p.appendChild(document.createTextNode(value));
    return p;
  }
  function heading(text) {
    var h = document.createElement("h4");
    h.textContent = text;
    return h;
  }
  function findingsList(findings) {
    var ul = document.createElement("ul");
    ul.className = "pill-list";
    if (!findings.length) {
      var li = document.createElement("li");
      li.textContent = "none";
      ul.appendChild(li);
      return ul;
    }
    findings.forEach(function (f) {
      var li = document.createElement("li");
      li.className = "hot";
      li.textContent = f.rule_id + " (" + f.severity + ") " + f.path + ":" + f.line;
      if (f.message) li.title = f.message;
      ul.appendChild(li);
    });
    return ul;
  }

  function showNode(n) {
    clearPanel();
    panel.appendChild(heading(n.label));
    panel.appendChild(row("type", n.type));
    panel.appendChild(row("worst severity", n.display_severity || "none observed"));
    if (n.path) panel.appendChild(row("location", n.path + (n.symbol ? " :: " + n.symbol : "")));
    var dims = Object.keys(n.dimension_scores || {});
    if (dims.length) {
      panel.appendChild(heading("Dimension scores"));
      dims.forEach(function (d) { panel.appendChild(row(d, String(n.dimension_scores[d]))); });
    }
    panel.appendChild(heading("Findings (" + n.findings.length + ")"));
    panel.appendChild(findingsList(n.findings));
  }

  function showEdge(e) {
    clearPanel();
    panel.appendChild(heading(refById[e.source] ? refById[e.source].label : e.source));
    var arrow = document.createElement("p");
    arrow.className = "meta";
    arrow.textContent = "→ " + (refById[e.target] ? refById[e.target].label : e.target);
    panel.appendChild(arrow);
    panel.appendChild(row("kind", e.kind));
    panel.appendChild(row("provenance", e.provenance));
    panel.appendChild(row("weight", String(e.weight)));
    panel.appendChild(heading("Findings (" + e.findings.length + ")"));
    panel.appendChild(findingsList(e.findings));
  }

  cy.on("tap", "node", function (evt) { showNode(refById[evt.target.id()]); });
  cy.on("tap", "edge", function (evt) { showEdge(refById[evt.target.id()]); });

  function applyFilters() {
    var checked = {};
    document.querySelectorAll(".stoa-graph-type-filter").forEach(function (cb) {
      checked[cb.value] = cb.checked;
    });
    var minRank = SEVERITY_RANK[document.getElementById("stoa-graph-min-severity").value] || 0;
    var query = (document.getElementById("stoa-graph-search").value || "").toLowerCase();

    var visible = {};
    cy.nodes().forEach(function (node) {
      var d = node.data();
      var ok = checked[d.type] !== false
        && SEVERITY_RANK[d.severity || "none"] >= minRank
        && (!query || d.label.toLowerCase().indexOf(query) !== -1);
      visible[d.id] = ok;
      node.toggleClass("stoa-hidden", !ok);
    });
    cy.edges().forEach(function (edge) {
      var d = edge.data();
      var ok = visible[d.source] && visible[d.target];
      edge.toggleClass("stoa-hidden", !ok);
    });
  }

  document.querySelectorAll(".stoa-graph-type-filter, #stoa-graph-min-severity").forEach(function (el) {
    el.addEventListener("change", applyFilters);
  });
  var search = document.getElementById("stoa-graph-search");
  if (search) search.addEventListener("input", applyFilters);
})();
""".strip()


def _sha256_b64(text: str) -> str:
    return base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


VENDOR_SCRIPT_HASH = _sha256_b64(_VENDOR_JS)
GLUE_SCRIPT_HASH = _sha256_b64(_GLUE_JS)


def csp_script_src() -> str:
    return f"script-src 'sha256-{VENDOR_SCRIPT_HASH}' 'sha256-{GLUE_SCRIPT_HASH}';"


_NODE_TYPE_LABELS = (
    ("agent", "Agents"),
    ("mcp_server", "MCP servers"),
    ("tool", "Tools & providers"),
    ("resource", "Resources"),
)


def _escape_json_for_script(payload: dict) -> str:
    import json

    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return raw.replace("</script", "<\\/script").replace("<!--", "<\\!--")


def render_graph_section(graph: Graph) -> str:
    """Return the ``<section>`` HTML for the architecture graph, including
    the vendored Cytoscape.js library and its fixed render script."""
    payload = _escape_json_for_script(to_json_dict(graph))
    type_filters = "".join(
        f'<label class="fchip ok"><input type="checkbox" class="stoa-graph-type-filter" '
        f'value="{type_id}" checked> {label}</label> '
        for type_id, label in _NODE_TYPE_LABELS
    )
    return (
        '<section><h2>Architecture graph</h2>'
        '<p class="note">Agents, tools, providers, and capability-sinks this scan observed, '
        'with the findings that explain each connection. Every edge is <code>declared</code> '
        '(statically detected) — click any node or edge for evidence.</p>'
        '<div id="stoa-graph-empty" class="empty" style="display:none">'
        "No agent candidates detected — nothing to graph.</div>"
        '<div class="graph-controls">'
        f"{type_filters}"
        '<label>Min severity '
        '<select id="stoa-graph-min-severity">'
        '<option value="none">All</option><option value="info">Info+</option>'
        '<option value="low">Low+</option><option value="medium">Medium+</option>'
        '<option value="high">High+</option><option value="critical">Critical</option>'
        "</select></label> "
        '<label>Search <input type="text" id="stoa-graph-search" placeholder="label…"></label>'
        "</div>"
        '<div class="graph-layout">'
        '<div id="stoa-graph-root" class="graph-canvas"></div>'
        '<div id="stoa-graph-panel" class="graph-panel">'
        '<p class="empty">Click a node or edge to see its detail.</p></div>'
        "</div>"
        f'<script type="application/json" id="stoa-graph-data">{payload}</script>'
        f"<script>{_VENDOR_JS}</script>"
        f"<script>{_GLUE_JS}</script>"
        "</section>"
    )
