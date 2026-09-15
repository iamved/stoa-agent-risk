"""Design-partner feedback (0.7.3): three complaints, each pinned by a test.

1. Agentic surface: retry loops in provider wrappers are not agents; agents on
   Replicate-style hosted models are visible; a hand-rolled tool-call loop gets
   its tool binding, its taint flow and its autonomy.
2. Noise: namespace URIs (XMP, RDF, licenses) are not insecure endpoints.
3. Controls: auth / rate limit / logging one import hop away (the route that
   fronts the agent) are credited to the agent; approval in a comment is not.
"""

from __future__ import annotations

from pathlib import Path

from stoa.config import load_config
from stoa.rules import code_only
from stoa.scanner import ScanOptions, run_scan


def _scan(root: Path):
    config = load_config(root)
    return run_scan(ScanOptions(root=root, no_git=True), config), config


def _controls(agent) -> set[str]:
    return {c for d in agent.dimension_assessment["dimensions"] for c in d.get("controls_observed", [])}


RETRY_PROVIDER = '''
import time
from openai import OpenAI
client = OpenAI()

def complete(prompt: str) -> str:
    for attempt in range(5):
        try:
            r = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
            return r.choices[0].message.content
        except Exception:
            time.sleep(attempt)
    return ""
'''

AGENT_LOOP = '''
import json
import subprocess
from openai import OpenAI
client = OpenAI()
TOOLS = [{"type": "function", "function": {"name": "assemble", "parameters": {}}}]

def run(brief: str) -> None:
    messages = [{"role": "user", "content": brief}]
    step = 0
    while step < 8:
        resp = client.chat.completions.create(model="gpt-4o", messages=messages, tools=TOOLS)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            break
        for call in msg.tool_calls:
            args = json.loads(call.function.arguments)
            subprocess.run("ffmpeg " + args["ffmpeg_args"], shell=True)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": "ok"})
        step += 1
'''

ROUTES = '''
import logging
import logging_loki
from fastapi import Depends, FastAPI, Header
from firebase_admin import auth
from slowapi import Limiter
from slowapi.util import get_remote_address
from pipeline.loop import run

logger = logging.getLogger("app")
logger.addHandler(logging_loki.LokiHandler(url="https://loki.internal/push", tags={}, version="1"))
limiter = Limiter(key_func=get_remote_address)
app = FastAPI()

def require_user(authorization: str = Header(...)):
    return auth.verify_id_token(authorization)

@app.post("/generate")
@limiter.limit("10/minute")
def generate(brief: str, user=Depends(require_user)):
    logger.info("run")
    run(brief)
'''


def test_retry_loop_around_one_call_is_not_an_agent(tmp_path):
    (tmp_path / "llm.py").write_text(RETRY_PROVIDER)
    (tmp_path / "keywords.py").write_text('''
import tenacity
from openai import OpenAI
client = OpenAI()
@tenacity.retry(stop=tenacity.stop_after_attempt(3))
def keywords(text):
    while True:   # poll until the model answers
        r = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": text}])
        if r.choices:
            return r.choices[0].message.content
''')
    result, _ = _scan(tmp_path)
    assert [a.path for a in result.agents] == ["keywords.py"]      # `while True:` is still a loop; `for attempt` is not


def test_hand_rolled_tool_loop_gets_tools_taint_and_autonomy(tmp_path):
    (tmp_path / "loop.py").write_text(AGENT_LOOP)
    result, _ = _scan(tmp_path)
    agent = result.agents[0]
    rules = {f.rule_id for f in agent.findings}
    assert "AI002" in rules                                    # tool-call arguments -> shell: model output is the source
    assert agent.autonomy_level["level"] == "unrestricted_autonomous"
    assert agent.confidence == "high"


def test_replicate_hosted_models_are_visible(tmp_path):
    (tmp_path / "gw.py").write_text('''
import replicate

async def plan(prompt):
    steps = await replicate.async_run("mistralai/mixtral-8x7b-instruct-v0.1", input={"prompt": prompt})
    for step in steps:
        await replicate.async_run("mistralai/mistral-7b-instruct-v0.2", input={"prompt": step})
''')
    result, _ = _scan(tmp_path)
    assert result.agents and "replicate" in result.agents[0].providers
    assert "AGENT_LOOP" in {e.rule_id for e in result.agents[0].evidence}


def test_namespace_uris_are_not_insecure_endpoints(tmp_path):
    (tmp_path / "meta.py").write_text('''
XMP = {"xmp": "http://ns.adobe.com/xap/1.0/", "dc": "http://purl.org/dc/elements/1.1/",
       "iptc": "http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/", "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"}
LICENSE = "http://creativecommons.org/licenses/by/4.0/"
REAL = "http://api.internal-render-farm.io/v1/jobs"
''')
    result, _ = _scan(tmp_path)
    net = [f for f in result.findings if f.rule_id == "NET001"]
    assert len(net) == 1 and "internal-render-farm" in net[0].snippet


def test_controls_one_import_hop_away_are_credited(tmp_path):
    (tmp_path / "pipeline").mkdir(); (tmp_path / "api").mkdir()
    (tmp_path / "pipeline" / "loop.py").write_text(AGENT_LOOP)
    (tmp_path / "api" / "routes.py").write_text(ROUTES)
    result, _ = _scan(tmp_path)
    agent = next(a for a in result.agents if a.path == "pipeline/loop.py")
    assert {"authentication", "rate_limit", "observability"} <= _controls(agent)
    assert "approval" not in _controls(agent)                  # `authorization` header != human approval
    assert not any(f.rule_id in ("CTRL001", "CTRL003") for f in agent.findings)
    # the same agent alone: nothing to credit, and no false credit
    alone = tmp_path / "alone"; alone.mkdir(); (alone / "loop.py").write_text(AGENT_LOOP)
    result2, _ = _scan(alone)
    assert _controls(result2.agents[0]) == set()


def test_js_route_middleware_is_credited_across_the_import(tmp_path):
    (tmp_path / "middleware.ts").write_text('''
import { getAuth } from "firebase-admin/auth";
import rateLimit from "express-rate-limit";
export const limiter = rateLimit({ windowMs: 60000, max: 30 });
export async function requireUser(req, res, next) { req.user = await getAuth().verifyIdToken(req.headers.authorization); next(); }
''')
    (tmp_path / "route.ts").write_text('''
import OpenAI from "openai";
import { requireUser, limiter } from "./middleware";
const client = new OpenAI();
export async function handler(brief: string) {
  const messages: any[] = [{ role: "user", content: brief }];
  for (let i = 0; i < 5; i++) {
    const r = await client.chat.completions.create({ model: "gpt-4o", messages });
    messages.push(r.choices[0].message);
  }
}
''')
    result, _ = _scan(tmp_path)
    agent = next(a for a in result.agents if a.path == "route.ts")
    assert {"authentication", "rate_limit"} <= _controls(agent)


def test_approval_in_a_comment_is_not_credited():
    assert "approval" not in code_only("# every refund needs human approval\nx = 1")
    assert "approve" in code_only("def approve(x):\n    return x  # approved")
    assert "approval" not in code_only('"""Requires approval from a reviewer."""\nrun()')
