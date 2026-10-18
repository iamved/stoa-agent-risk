"""The refund support agent from the case study, instrumented in one line.

A LangGraph graph with three tools: ``lookup_order`` (read),
``issue_refund`` (payment) and ``send_email`` (external_send), and an
``interrupt()`` before any refund above 500 EUR. The only Stoa code is the
callback handler passed in ``config``: no other line of this module knows
Stoa exists.

When ``langgraph`` is not installed the same nodes run through a tiny
in-file sequencer so the demo still produces traces; the scan sees the
LangGraph import either way.
"""

from __future__ import annotations

import os
from typing import Any

try:  # the real thing when available
    from langchain_core.tools import tool
    from langgraph.graph import END, START, StateGraph
    from langgraph.prebuilt import ToolNode
    from langgraph.types import interrupt
    HAVE_LANGGRAPH = True
except Exception:  # noqa: BLE001
    HAVE_LANGGRAPH = False

    def tool(func):  # the scan reads the decorator; at runtime it is a no-op here
        return func

REFUND_APPROVAL_THRESHOLD_EUR = 500.0

ORDERS = {
    "o-1001": {"customer": "c-8841", "total_eur": 120.0, "email": "c8841@example.test"},
    "o-1002": {"customer": "c-2210", "total_eur": 980.0, "email": "c2210@example.test"},
    "o-1003": {"customer": "c-3302", "total_eur": 45.0, "email": "c3302@example.test"},
}
LEDGER: list[dict] = []
OUTBOX: list[dict] = []


# --- tools ---------------------------------------------------------------------------

@tool
def lookup_order(order_id: str) -> dict:
    """Look an order up by id."""
    return dict(ORDERS.get(order_id) or {})


@tool
def issue_refund(order_id: str, amount_eur: float) -> str:
    """Refund an order; money moves."""
    LEDGER.append({"order_id": order_id, "amount_eur": amount_eur})
    return f"refund-{len(LEDGER)}"


@tool
def send_email(to: str, subject: str) -> bool:
    """Email the customer."""
    OUTBOX.append({"to": to, "subject": subject})
    return True


def undeclared_export(order_id: str) -> str:
    """A tool that exists in the running code but not in the scanned graph."""
    return f"export-{order_id}"


TOOLS = {"lookup_order": lookup_order, "issue_refund": issue_refund, "send_email": send_email}


def _call(func, **kwargs):
    """Call a tool whether it is a plain function or a LangChain tool."""
    invoke = getattr(func, "invoke", None)
    return invoke(kwargs) if callable(invoke) and HAVE_LANGGRAPH else func(**kwargs)


# --- nodes ---------------------------------------------------------------------------

def plan(state: dict) -> dict:
    order = _call(lookup_order, order_id=state["order_id"])
    amount = min(float(state.get("requested_eur", 0.0)), order.get("total_eur", 0.0))
    return {"order": order, "amount_eur": amount}


def gate(state: dict) -> dict:
    if state["amount_eur"] > REFUND_APPROVAL_THRESHOLD_EUR:
        if HAVE_LANGGRAPH:
            decision = interrupt({"approve_refund_eur": state["amount_eur"]})
            return {"approved": bool(decision)}
        return {"approved": bool(state.get("human_decision", False))}
    return {"approved": True}


def act(state: dict) -> dict:
    if not state.get("approved"):
        return {"result": "declined"}
    ref = _call(issue_refund, order_id=state["order_id"], amount_eur=state["amount_eur"])
    _call(send_email, to=state["order"]["email"], subject=f"Refund {ref} issued")
    if state.get("export"):
        undeclared_export(state["order_id"])
    return {"result": ref}


def build_graph():
    if not HAVE_LANGGRAPH:
        return None
    graph = StateGraph(dict)
    graph.add_node("tools", ToolNode([lookup_order, issue_refund, send_email]))
    graph.add_node("plan", plan)
    graph.add_node("gate", gate)
    graph.add_node("act", act)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "gate")
    graph.add_edge("gate", "act")
    graph.add_edge("act", END)
    return graph.compile()


def run(state: dict, config: dict | None = None) -> dict:
    """Run one session: the real graph with the callback handler in
    ``config``, or the in-file sequencer calling the handler's hooks."""
    graph = build_graph()
    if graph is not None:
        return graph.invoke(state, config=config or {})
    handlers = (config or {}).get("callbacks") or []
    working: dict[str, Any] = dict(state)
    for node in (plan, gate, act):
        working.update(_sequenced(node, working, handlers))
    return working


def _sequenced(node, state: dict, handlers) -> dict:
    """Drive the callback handlers the way LangGraph would for this graph."""
    import uuid
    if node is act and not state.get("approved"):
        return node(state)
    calls = []
    if node is plan:
        calls = [("lookup_order", {"order_id": state["order_id"]})]
    elif node is act:
        calls = [("issue_refund", {"order_id": state["order_id"], "amount_eur": state["amount_eur"]}), ("send_email", {"to": state["order"]["email"], "subject": "Refund issued"})]
        if state.get("export"):
            calls.append(("undeclared_export", {"order_id": state["order_id"]}))
    if node is gate and state["amount_eur"] > REFUND_APPROVAL_THRESHOLD_EUR:
        for h in handlers:
            h.on_chain_error(_Interrupt(), run_id=uuid.uuid4(), metadata={"thread_id": state.get("thread_id")})
        if state.get("human_decision"):
            for h in handlers:
                h.on_chain_start({}, state, run_id=uuid.uuid4(), metadata={"thread_id": state.get("thread_id")})
    for name, args in calls:
        run_id = uuid.uuid4()
        for h in handlers:
            h.on_tool_start({"name": name}, "", run_id=run_id, inputs=args, metadata={"thread_id": state.get("thread_id")})
        try:
            _call(TOOLS.get(name, undeclared_export), **args)
        except Exception as exc:  # noqa: BLE001
            for h in handlers:
                h.on_tool_error(exc, run_id=run_id)
            raise
        for h in handlers:
            h.on_tool_end(None, run_id=run_id)
    return node(state)


class _Interrupt(Exception):
    """Stands in for langgraph.errors.GraphInterrupt when LangGraph is absent."""

    __name__ = "GraphInterrupt"


_Interrupt.__name__ = "GraphInterrupt"


if __name__ == "__main__":
    print("run `make demo` in this directory" if not os.environ.get("STOA_TRACE_DIR") else "configured")
