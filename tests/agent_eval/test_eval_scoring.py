"""P6.8: the scorer and the runner of the eval, offline (no n8n, no LLM, no network)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "data_api"))

import eval_questions as eq  # noqa: E402
import eval_scoring as es  # noqa: E402
import run_eval  # noqa: E402

# ------------------------------------------------------------------ numbers


@pytest.mark.parametrize("text,expected", [
    ("The total is $16,081,484.40.", 16_081_484.40),
    ("Die Gesamtkosten betragen 16.081.484,40 USD.", 16_081_484.40),
    ("El total es 16.081.484 USD.", 16_081_484),
    ("Całkowity koszt to 16 081 484 USD.", 16_081_484),
    ("Całkowity koszt to 16 081 484,40 USD.", 16_081_484.40),
    ("About 16.1 million dollars", 16_081_484),
    ("Etwa 16,1 Mio. USD", 16_081_484),
    ("około 16,1 mln USD", 16_081_484),
    ("$16.08M", 16_081_484),
    ("1,5 Millionen", 1_500_000),
    ("There are 1,234 walls", 1234),
    ("Es gibt 1.234 Wände", 1234),
    ("Es gibt 1.234 Wände", 1.234),  # an ambiguous token keeps both readings
    ("an estimate of 2.5k", 2500),
    ("saldo −800", 800),  # sign ignored
    ("Over by 51,880.00 dollars", 51_880),
])
def test_numbers_are_found_in_every_notation(text, expected):
    assert es.number_matches(expected, es.extract_numbers(text), "amount", rel_tol=0.01)


@pytest.mark.parametrize("text,expected", [
    ("The total is $16,081,484", 16_500_000),   # 2.6 % off
    ("The total is $16,081,484", 1_608_148),
    ("Total: 51,880", 51_088),
    ("It costs 12,3 dollars", 123),
])
def test_wrong_numbers_do_not_match(text, expected):
    assert not es.number_matches(expected, es.extract_numbers(text), "amount")


def test_counts_must_be_exact():
    assert es.number_matches(42, es.extract_numbers("There are 42 walls."), "count")
    assert not es.number_matches(42, es.extract_numbers("There are 43 walls."), "count")
    assert not es.number_matches(42, es.extract_numbers("About 41.9 walls"), "count")
    assert es.number_matches(42, es.extract_numbers("There are 42.0 walls"), "count")
    assert not es.number_matches(1000, es.extract_numbers("1,010 walls"), "count")


def test_dates_and_entity_names_cannot_satisfy_a_count():
    text = "On Level 2 there are 7 walls. Snapshot: Week 3 (2027-01-17)."
    found = es.extract_numbers(text, ignore=["Level 2"])
    assert not es.number_matches(2, found, "count")
    assert not es.number_matches(17, found, "count")
    assert not es.number_matches(2027, found, "count")
    assert es.number_matches(7, found, "count")
    # and without the ignore list the stand-in would have been accepted
    assert es.number_matches(2, es.extract_numbers(text), "count")


def test_german_and_polish_dates_are_ignored_too():
    found = es.extract_numbers("Stand: 17.01.2027, es sind 9 Wände", ignore=[])
    assert 9 in found and 17.01 not in found and 2027 not in found


def test_a_unit_does_not_hide_the_number():
    # "12 m" must stay 12 (metres) as well as 12 million
    found = es.extract_numbers("The wall is 12 m long")
    assert 12 in found


# ------------------------------------------------------------------ language


@pytest.mark.parametrize("lang,text", [
    ("en", "The total project cost is currently $79,200, which is under the target of $80,000."),
    ("de", "Die Gesamtkosten des Projekts betragen derzeit 79.200 USD und liegen unter dem Ziel."),
    ("es", "El costo total del proyecto es de 79.200 USD y está por debajo del objetivo."),
    ("pl", "Całkowity koszt projektu wynosi obecnie 79 200 USD i jest poniżej celu."),
    ("de", "Es gibt 2 Wände auf L1."),
    ("pl", "Na poziomie L1 jest 2 ścian."),
    ("es", "Hay 3 muros en total en el modelo."),
])
def test_language_detection(lang, text):
    assert es.detect_language(text) == lang


def test_language_is_none_when_unclear():
    assert es.detect_language("42") is None
    assert es.detect_language("") is None
    assert es.detect_language("Walls L1 B30 79200") is None


# ------------------------------------------------------------------ one answer


def question(**kw):
    q = {"id": "q", "lang": "en", "category": "COST", "tools": "some",
         "expect_numbers": [{"fact": "cost_total", "value": 79_200.0, "kind": "amount"}],
         "expect_text": [], "ignore": []}
    q.update(kw)
    return q


def response(reply, **kw):
    r = {"reply": reply, "category": "COST", "language": "en", "tools": ["get_cost_summary"],
         "tool_response_chars": [2500], "failed": False}
    r.update(kw)
    return r


GOOD = "The total project cost is $79,200, which is below the target. Snapshot: Run (2027-01-17)"


def test_a_good_answer_is_correct():
    s = es.score_reply(question(), response(GOOD), 3.2)
    assert s.correct and s.numeric_ok and s.language_ok and s.tools_ok and not s.overflow
    assert s.category_ok is None or s.category_ok
    assert s.tool_chars_max == 2500 and s.latency_s == 3.2


def test_wrong_number_wrong_language_no_tool_and_failures_are_caught():
    bad_number = es.score_reply(question(), response(GOOD.replace("79,200", "97,200")), 1)
    assert not bad_number.correct and bad_number.missing == ["cost_total=79200"]
    wrong_language = es.score_reply(
        question(), response("Die Gesamtkosten des Projekts betragen derzeit 79.200 USD."), 1)
    assert wrong_language.numeric_ok and not wrong_language.language_ok
    assert not wrong_language.correct
    no_tool = es.score_reply(question(), response(GOOD, tools=[]), 1)
    assert no_tool.numeric_ok and not no_tool.tools_ok and not no_tool.correct
    assert not es.score_reply(question(), response(GOOD, failed=True), 1).correct
    assert not es.score_reply(question(), response(""), 1).correct
    nothing = es.score_reply(question(), None, 30)
    assert nothing.failed and not nothing.correct


def test_every_expected_number_and_text_is_required():
    q = question(expect_numbers=[{"fact": "a", "value": 79_200.0, "kind": "amount"},
                                 {"fact": "b", "value": 800.0, "kind": "amount"}],
                 expect_text=["Shell"])
    partial = es.score_reply(q, response(GOOD), 1)
    assert partial.missing == ["b=800", "text:Shell"]
    full = es.score_reply(
        q, response("The Shell cluster is part of the total of $79,200, which is $800 under the "
                    "target of the project."), 1)
    assert full.correct


def test_out_of_scope_must_not_call_tools():
    q = question(expect_numbers=[], tools="none", category="OTHER")
    ok = es.score_reply(q, response("I can only help with questions about this project.",
                                    tools=[], category="OTHER", tool_response_chars=[]), 2)
    assert ok.correct and ok.category_ok
    called = es.score_reply(q, response("I can only help with this project.", category="OTHER"), 2)
    assert not called.correct and "tools:get_cost_summary" in called.missing


def test_context_overflow_is_a_tool_response_over_the_api_cap():
    ok = es.score_reply(question(), response(GOOD, tool_response_chars=[es.TOOL_CHAR_CAP]), 1)
    over = es.score_reply(
        question(), response(GOOD, tool_response_chars=[10, es.TOOL_CHAR_CAP + 1]), 1)
    assert not ok.overflow and over.overflow and over.tool_chars_max == es.TOOL_CHAR_CAP + 1


def test_routing_is_scored_separately_from_correctness():
    s = es.score_reply(question(), response(GOOD, category="GENERAL"), 1)
    assert s.category_ok is False and s.correct


# ------------------------------------------------------------------ summary


def scores(n_ok, n_bad, latency=1.0, overflow=False):
    out = [es.Score(f"ok{i}", True, True, True, True, False, latency, 100, overflow, "en")
           for i in range(n_ok)]
    out += [es.Score(f"bad{i}", False, True, True, True, False, latency, 100, False, "en")
            for i in range(n_bad)]
    return out


def test_p95_is_nearest_rank():
    assert es.p95([]) == 0.0
    assert es.p95([5.0]) == 5.0
    assert es.p95(list(map(float, range(1, 101)))) == 95.0
    assert es.p95([1.0] * 19 + [60.0]) == 1.0  # one slow call in 20 is the 100th percentile
    assert es.p95([1.0] * 18 + [60.0, 60.0]) == 60.0


def test_acceptance_criteria():
    assert es.summarize(scores(9, 1)).passed                       # 90 %
    s = es.summarize(scores(8, 2))
    assert not s.passed and "accuracy 80%" in s.reasons[0]
    assert not es.summarize(scores(10, 0, overflow=True)).passed   # an overflow
    slow = es.summarize(scores(10, 0, latency=20.0))
    assert not slow.passed and "p95" in slow.reasons[0]
    assert es.summarize(scores(10, 0, latency=19.9)).passed
    assert not es.summarize([]).passed


# ------------------------------------------------------------------ the runner


def resolved(**kw):
    base = dict(id="q1", group="cost", lang="en", category="COST", status="ready",
                text="What is the total project cost right now?", conv="q1", tools="some",
                expect_numbers=[{"fact": "cost_total", "value": 79_200.0, "kind": "amount"}])
    base.update(kw)
    return eq.ResolvedQuestion(**base)


def test_runner_posts_the_contract_the_workflow_reads_and_keeps_chats_together():
    questions = [resolved(), resolved(id="q2", conv="q1", after="q1", text="And the target?"),
                 resolved(id="q3", conv="q3", text="Another chat")]
    seen = []

    def post(url, token, payload, timeout):
        seen.append((url, token, payload))
        return 200, response(GOOD)

    results = run_eval.run_questions(questions, "http://n8n/webhook/x", "tok", post, run_id="r1")
    assert [r["id"] for r in results] == ["q1", "q2", "q3"]
    assert all(r["score"].correct for r in results)
    (u1, t1, p1), (_, _, p2), (_, _, p3) = seen
    assert (u1, t1) == ("http://n8n/webhook/x", "tok")
    assert p1["content"] == "What is the total project cost right now?"
    assert p1["source"] == "eval" and "thread_id" not in p1
    assert set(p1) == {"content", "author_id", "author_name", "channel_id", "message_id", "source"}
    # the workflow's session key is channel + user: same chat = same pair
    assert (p1["channel_id"], p1["author_id"]) == (p2["channel_id"], p2["author_id"])
    assert p3["channel_id"] != p1["channel_id"]
    assert len({p["message_id"] for p in (p1, p2, p3)}) == 3


def test_runner_measures_latency_and_survives_failures():
    ticks = iter([0.0, 2.5, 10.0, 40.0, 50.0, 50.2])

    def post(url, token, payload, timeout):
        return {"q1": (200, response(GOOD)), "q2": (500, None), "q3": (0, None)}[
            payload["message_id"].split("-")[-1]]

    qs = [resolved(), resolved(id="q2", conv="q2"), resolved(id="q3", conv="q3")]
    results = run_eval.run_questions(qs, "u", "t", post, run_id="r", clock=lambda: next(ticks))
    s = [r["score"] for r in results]
    assert [round(x.latency_s, 1) for x in s] == [2.5, 30.0, 0.2]
    assert [x.correct for x in s] == [True, False, False]
    assert [r["http_status"] for r in results] == [200, 500, 0]
    summary = es.summarize(s)
    assert not summary.passed and summary.p95_latency_s == 30.0


def test_select_adds_the_start_of_a_chat_and_drops_unready_questions():
    qs = [resolved(), resolved(id="f1", conv="f1", group="follow-up"),
          resolved(id="f2", conv="f1", group="follow-up", after="f1"),
          resolved(id="u", status="unavailable"), resolved(id="s", status="skipped")]
    assert [q.id for q in run_eval.select(qs)] == ["q1", "f1", "f2"]
    assert [q.id for q in run_eval.select(qs, only=["f2"])] == ["f1", "f2"]
    assert [q.id for q in run_eval.select(qs, groups=["cost"])] == ["q1"]


def test_report_and_table_do_not_crash_and_name_the_failures():
    q = resolved()
    results = run_eval.run_questions([q], "u", "t", lambda *a: (200, response("No idea.")),
                                     run_id="r")
    summary = es.summarize([r["score"] for r in results])
    skipped = [resolved(id="sched", status="skipped", reason="tier 2: not implemented")]
    out = io.StringIO()
    run_eval.print_table(results, skipped, summary, out)
    text = out.getvalue()
    assert text.startswith("FAIL q1")
    assert "cost_total=79200" in text and "skip sched" in text and "RESULT: FAIL" in text
    rep = run_eval.report(results, skipped, summary)
    assert rep["summary"]["passed"] is False
    assert rep["not_run"] == [
        {"id": "sched", "status": "skipped", "reason": "tier 2: not implemented"}]
    json.dumps(rep)


def test_webhook_url_from_env():
    assert run_eval.webhook_url({}, "http://x/y") == "http://x/y"
    assert run_eval.webhook_url({"CONCHO_EVAL_URL": "http://e/w"}, None) == "http://e/w"
    assert run_eval.webhook_url({"CONCHO_WEBHOOK_PATH": "p" * 30, "N8N_PORT": "5999"}, None) == (
        "http://127.0.0.1:5999/webhook/" + "p" * 30)
    with pytest.raises(SystemExit):
        run_eval.webhook_url({}, None)


def test_main_generate_only_and_missing_token(tmp_path, capsys):
    import api_synthetic as syn

    from engines.api.ingest import ingest_repo
    db = ingest_repo(syn.make_repo(tmp_path / "team"))["db"]
    assert run_eval.main(["--db", db, "--generate-only"]) == 0
    out = capsys.readouterr()
    questions = json.loads(out.out.split("\n\n")[0])
    assert any(q["id"] == "cost-total" and q["expect_numbers"][0]["value"] == syn.GRAND_TOTAL
               for q in questions)
    assert "ready" in out.err
    # running needs a token; nothing is sent without one
    rc = run_eval.main(["--db", db, "--url", "http://127.0.0.1:9/none",
                        "--env-file", str(tmp_path / "none.env")])
    assert rc == 2 and "CONCHO_WEBHOOK_TOKEN" in capsys.readouterr().err
    assert run_eval.main(["--db", str(tmp_path / "nope.db")]) == 2


def test_post_json_reports_unreachable_servers_without_raising():
    assert run_eval.post_json("http://127.0.0.1:9/nothing", "t", {"a": 1}, timeout=1) == (0, None)


# ------------------------------------------------------------------ end to end (stand-in agent)

_SENTENCE = {
    "en": "The result is {n} and this is the value from the data of the project.",
    "de": "Das Ergebnis ist {n} und das ist der Wert aus den Daten des Projekts.",
    "es": "El resultado es {n} y este es el valor de los datos del proyecto.",
    "pl": "Wynik to {n} i jest to wartość z danych projektu.",
}
_REFUSAL = {
    "en": "I can only help with questions about this project and its data.",
    "es": "Solo puedo ayudar con preguntas sobre este proyecto y sus datos.",
}


def serve_stand_in(questions, *, broken=False):
    """A local HTTP server that answers like a perfect (or a broken) Concho. Returns
    ``(server, url, requests)``."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    by_text = {q.text: q for q in questions}
    requests: list[tuple[dict, dict]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((dict(self.headers), body))
            if self.headers.get("X-Concho-Token") != "secret":
                self.send_response(403)
                self.end_headers()
                return
            q = by_text[body["content"]]
            if q.tools == "none":
                reply = _REFUSAL.get(q.lang, _REFUSAL["en"])
                answer = {"reply": reply, "category": "OTHER", "tools": [],
                          "tool_response_chars": [], "failed": False}
            else:
                numbers = " and ".join(f"{e['value']:,.2f}" if e["kind"] == "amount"
                                       else f"{int(e['value'])}" for e in q.expect_numbers)
                numbers = (numbers + " " + " ".join(q.expect_text)).strip()
                if broken:
                    numbers = "12,345,678"
                answer = {"reply": _SENTENCE[q.lang].format(n=numbers), "category": q.category,
                          "tools": ["get_cost_summary"], "tool_response_chars": [3000],
                          "failed": False}
            data = json.dumps(answer).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/webhook/x", requests


@pytest.mark.parametrize("broken,rc", [(False, 0), (True, 1)])
def test_main_end_to_end_against_a_stand_in_agent(tmp_path, capsys, monkeypatch, broken, rc):
    import api_synthetic as syn

    from engines.api.ingest import ingest_repo
    db = ingest_repo(syn.make_repo(tmp_path / "team"))["db"]
    conn = eq.open_database(Path(db))
    questions = eq.resolve_questions(eq.load_questions(), conn)
    server, url, requests = serve_stand_in(questions, broken=broken)
    monkeypatch.setenv("CONCHO_WEBHOOK_TOKEN", "secret")
    try:
        code = run_eval.main(["--db", db, "--url", url, "--report", str(tmp_path / "r.json")])
    finally:
        server.shutdown()
    out = capsys.readouterr().out
    assert code == rc, out
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    ran = [q for q in questions if q.status == "ready"]
    assert report["summary"]["total"] == len(ran) >= 40
    assert {n["status"] for n in report["not_run"]} == {"skipped", "unavailable"}
    assert ("RESULT: PASS" in out) == (rc == 0)
    if not broken:
        assert report["summary"]["correct"] == len(ran)
        assert report["summary"]["overflows"] == 0 and report["summary"]["max_tool_chars"] == 3000
    # the follow-up arrived in the same chat as its first question, with the token header
    sent = {body["message_id"].split("-", 2)[-1]: body for _, body in requests}
    assert sent["fu-qty-1"]["channel_id"] == sent["fu-qty-2"]["channel_id"]
    assert sent["fu-qty-1"]["author_id"] == sent["fu-qty-2"]["author_id"]
    assert sent["cost-total"]["channel_id"] != sent["fu-qty-1"]["channel_id"]
    assert all(h["X-Concho-Token"] == "secret" for h, _ in requests)
    assert "secret" not in (tmp_path / "r.json").read_text(encoding="utf-8")


def test_a_wrong_token_is_reported_as_failed_answers(tmp_path, monkeypatch, capsys):
    import api_synthetic as syn

    from engines.api.ingest import ingest_repo
    db = ingest_repo(syn.make_repo(tmp_path / "team"))["db"]
    questions = eq.resolve_questions(eq.load_questions(), eq.open_database(Path(db)))
    server, url, _ = serve_stand_in(questions)
    monkeypatch.setenv("CONCHO_WEBHOOK_TOKEN", "wrong")
    try:
        code = run_eval.main(["--db", db, "--url", url, "--only", "cost-total",
                              "--report", str(tmp_path / "r.json")])
    finally:
        server.shutdown()
    assert code == 1 and "HTTP 403" in capsys.readouterr().out
