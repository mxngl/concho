"""P6.8: ``scripts/run_eval.py`` end to end against a FAKE webhook (no n8n, no LLM).

The fake "agent" answers each question from its expected numbers, in the question's language,
in the shape of the workflow's response (``{reply, category, language, tools,
tool_response_chars, failed}``). It shows that the harness posts what the workflow expects,
keeps one channel per question, sends the follow-up's first question, and passes a good agent
and fails a bad one (no memory, wrong numbers, slow, oversized tool response)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import eval_cases as ec
import eval_helpers  # noqa: F401
import pytest
import run_eval as ev

TOKEN = "fake-eval-token"
PHRASE = {
    "en": "According to the project data the result is {n}. Snapshot: Run (the latest one).",
    "de": "Laut den Projektdaten ist das Ergebnis {n}. Stand: der letzte Lauf des Projekts.",
    "es": "Según los datos del proyecto el resultado es {n}. Instantánea: la última del proyecto.",
    "pl": "Według danych projektu wynik wynosi {n}. Migawka: ostatnia z projektu.",
}
OFFTOPIC = {
    "en": "I can only help with questions about this project and its data, sorry.",
    "de": "Ich kann nur bei Fragen zu diesem Projekt und seinen Daten helfen, leider.",
    "es": "Solo puedo ayudar con preguntas sobre este proyecto y sus datos, lo siento.",
}


def fmt(value, lang):
    s = f"{value:,.2f}"
    if lang in ("de", "es"):
        return s.replace(",", "X").replace(".", ",").replace("X", ".")
    if lang == "pl":
        return s.replace(",", " ").replace(".", ",")
    return s


class FakeAgent:
    """Answers from the cases; behaviour switches model the failure modes."""

    def __init__(self, cases, *, memory=True, wrong=False, delay=0.0, tool_chars=1500):
        self.cases = {c["id"]: c for c in cases}
        self.memory, self.wrong, self.delay, self.tool_chars = memory, wrong, delay, tool_chars
        self.seen: dict[str, list[dict]] = {}
        self.lock = threading.Lock()

    def answer(self, body):
        channel = body["channel_id"]
        case = self.cases[channel.split("-", 2)[2]]
        with self.lock:
            history = self.seen.setdefault(channel, [])
            history.append(body)
            asked_before = len(history) - 1
        exp = case["expect"]
        is_primer = body["content"] == case.get("after") and asked_before == 0 and case["after"]
        cat = (exp["category"][0] if isinstance(exp["category"], list) else exp["category"])
        if cat in ("OTHER", "GENERAL") and exp.get("max_tools") == 0:
            return {"reply": OFFTOPIC[case["lang"]], "category": cat, "language": case["lang"],
                    "tools": [], "tool_response_chars": [], "failed": False}
        nums = exp["numbers"] or exp["any_of"][:1]
        forgot = case["type"] == "followup" and not self.memory
        if is_primer or forgot or self.wrong or not nums:
            text = "Sorry, I am not sure what you mean." if forgot else PHRASE[case["lang"]].format(
                n=fmt(nums[0]["value"] * (1.5 if self.wrong else 1), case["lang"]) if nums
                else "n/a")
        else:
            text = PHRASE[case["lang"]].format(n=fmt(nums[0]["value"], case["lang"]))
            text = text.replace("result is", "result for the data you asked about is")
            for extra in nums[1:]:
                text += " " + fmt(extra["value"], case["lang"])
        return {"reply": text, "category": cat, "language": case["lang"],
                "tools": ["get_cost_summary"], "tool_response_chars": [self.tool_chars],
                "failed": False}


@pytest.fixture()
def serve():
    servers = []

    def start(agent):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.headers.get("X-Concho-Token") != TOKEN:
                    self.send_response(403)
                    self.end_headers()
                    return
                agent.requests.append(body)
                if agent.delay:
                    import time
                    time.sleep(agent.delay)
                out = json.dumps(agent.answer(body)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        agent.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}/webhook/test"

    yield start
    for s in servers:
        s.shutdown()
        s.server_close()


@pytest.fixture(scope="module")
def cases(eval_conn):
    return ec.build_cases(eval_conn, ec.load_questions())[0]


def run_all(cases, url, token=TOKEN, **kw):
    run_id = "t1"
    todo = [c for c in cases if not c.get("skip")]
    results = [ev.run_case(c, url, token, run_id, 5.0) for c in todo]
    skipped = [{"id": c["id"], "reason": c["skip"]} for c in cases if c.get("skip")]
    return results, ev.summarize(results, skipped), skipped


def test_a_correct_agent_passes_every_acceptance_criterion(cases, serve):
    agent = FakeAgent(cases)
    results, summary, skipped = run_all(cases, serve(agent))
    failures = [(r["id"], r["detail"]) for r in results if not r["ok"]]
    assert failures == []
    assert summary["pass"] and summary["correct_pct"] == 100.0 and summary["overflows"] == 0
    assert len(skipped) == 6  # the tier 2 schedule questions
    assert len(results) >= 40


def test_requests_follow_the_workflow_input_contract(cases, serve):
    agent = FakeAgent(cases)
    run_all(cases, serve(agent))
    for body in agent.requests:
        assert set(body) == {"content", "author_id", "author_name", "channel_id", "message_id",
                             "source"}
        assert body["source"] == "eval"  # n8n posts nothing to Discord
        assert body["channel_id"].startswith("eval-t1-") and body["author_id"] == "eval-t1"
    # one channel per question; a follow-up posts its first question and then itself, in order
    by_channel = {}
    for body in agent.requests:
        by_channel.setdefault(body["channel_id"], []).append(body["content"])
    follow = {c["id"]: c for c in cases if c["type"] == "followup"}
    assert follow
    for cid, case in follow.items():
        assert by_channel[f"eval-t1-{cid}"] == [case["after"], case["text"]]
    for c in cases:
        if not c.get("skip") and c["type"] != "followup":
            assert by_channel[f"eval-t1-{c['id']}"] == [c["text"]]
    assert not any(c["id"].startswith("sched") for c in cases if not c.get("skip"))
    assert not any(b["channel_id"].startswith("eval-t1-sched") for b in agent.requests)


def test_an_agent_without_memory_fails_exactly_the_follow_ups(cases, serve):
    results, summary, _ = run_all(cases, serve(FakeAgent(cases, memory=False)))
    failed = {r["id"] for r in results if not r["ok"]}
    assert failed == {c["id"] for c in cases if c["type"] == "followup"}
    assert summary["pass"]  # 4 of 43 wrong is still >= 90 %: the follow-ups are reported by type
    assert summary["by_type"]["followup"] == "0/4"


def test_wrong_numbers_oversized_tool_responses_and_slowness_fail(cases, serve):
    results, summary, _ = run_all(cases, serve(FakeAgent(cases, wrong=True)))
    assert not summary["pass"] and summary["correct_pct"] < 50
    results, summary, _ = run_all(
        cases, serve(FakeAgent(cases, tool_chars=ev.TOOL_RESPONSE_CAP_CHARS + 1)))
    assert summary["overflows"] > 0 and not summary["pass"]
    slow = [c for c in cases if c["id"] in {"cost-total", "cost-target", "cost-per-sf"}]
    results, summary, _ = run_all(slow, serve(FakeAgent(slow, delay=0.3)))
    assert summary["latency_p95_s"] >= 0.3
    summary = ev.summarize([dict(r, latency_s=21.0) for r in results], [])
    assert not summary["pass"]


def test_a_wrong_token_or_dead_url_is_a_failed_answer_not_a_crash(cases, serve):
    one = [c for c in cases if c["id"] == "cost-total"]
    results, summary, _ = run_all(one, serve(FakeAgent(one)), token="wrong")
    assert not results[0]["ok"] and "no usable answer" in results[0]["detail"][0]
    results, _, _ = run_all(one, "http://127.0.0.1:9/webhook/none")
    assert not results[0]["ok"]


def test_main_dry_run_and_exit_codes(tmp_path, cases, serve, capsys, monkeypatch):
    import api_synthetic as syn
    repo = syn.make_repo(tmp_path / "team")
    monkeypatch.delenv("CONCHO_EVAL_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("CONCHO_WEBHOOK_TOKEN", raising=False)
    assert ev.main(["--repo", str(repo), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "cost.grand_total=79200" in out and "43 questions, 6 skipped" in out
    assert ev.main(["--repo", str(repo)]) == 2  # no URL / token
    assert ev.main(["--repo", str(tmp_path / "nowhere"), "--dry-run"]) == 2
    capsys.readouterr()
    # full run against the fake agent via a cases file
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps({"cases": cases, "dropped": []}), encoding="utf-8")
    url = serve(FakeAgent(cases))
    report = tmp_path / "report.json"
    assert ev.main(["--cases", str(cases_file), "--url", url, "--token", TOKEN,
                    "--report", str(report)]) == 0
    assert "RESULT: PASS" in capsys.readouterr().out
    doc = json.loads(report.read_text(encoding="utf-8"))
    assert doc["summary"]["pass"] and len(doc["skipped"]) == 6
    url = serve(FakeAgent(cases, wrong=True))
    assert ev.main(["--cases", str(cases_file), "--url", url, "--token", TOKEN]) == 1
    capsys.readouterr()
