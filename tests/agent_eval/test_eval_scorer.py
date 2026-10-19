"""P6.8: the scorer of ``scripts/run_eval.py`` on canned replies (no n8n, no LLM)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import run_eval as ev

# ------------------------------------------------------------------ numbers


@pytest.mark.parametrize("text, expected", [
    ("The total is $16,081,484.40.", 16081484.40),
    ("Gesamt: 16.081.484,40 USD", 16081484.40),
    ("Razem: 16 081 484,40 USD", 16081484.40),
    ("Razem: 16 081 484,40", 16081484.40),
    ("about 16.1M", 16.1e6),
    ("rund 16,1 Mio.", 16.1e6),
    ("618,515.60 rounds to 618,516", 618515.6),
    ("22,6 % of the target", 22.6),
    ("There are 1,234 walls", 1234),
    ("Es gibt 1.234 Wände", 1234),
    ("12k", 12000),
])
def test_numbers_are_found_in_any_locale(text, expected):
    found = ev.extract_numbers(text)
    assert any(abs(c - expected) <= 1e-6 * max(1, expected) + 0.06 for cands in found
               for c in cands), found


def test_dates_and_level_names_are_not_numbers():
    text = "Snapshot: Week 3 (2027-01-17) on L1 and B30"
    flat = [c for cands in ev.extract_numbers(text) for c in cands]
    assert 2027 not in flat and 17 not in flat and 1 not in flat and 30 not in flat
    assert 3 in flat  # "Week 3" is a number the reply states


def test_number_matching_uses_tolerance_and_rounding():
    found = ev.extract_numbers("The estimate is 618,515 dollars")
    assert ev.number_matches(618515.60, 0.005, False, found)        # truncated, still close
    assert not ev.number_matches(618515.60, 0.0, True, found)       # exact counts must match
    assert ev.number_matches(45, 0.0, True, ev.extract_numbers("We have 45 walls"))
    assert not ev.number_matches(45, 0.0, True, ev.extract_numbers("We have 44 walls"))
    assert not ev.number_matches(1_000_000, 0.005, False, ev.extract_numbers("1,020,000"))
    assert ev.number_matches(-20, 0.005, False, ev.extract_numbers("20 percent cheaper"))


# ------------------------------------------------------------------ status


@pytest.mark.parametrize("lang, reply, subject, expected, ok", [
    ("en", "The Shell cluster would be 4,467,302, which is above its target of 3,826,446.",
     "Shell", "over_target", True),
    ("en", "The Shell cluster remains under target at 4,467,302.", "Shell", "over_target", False),
    # the bug: the grand total stays under target but the cluster is over its own
    ("en", "The grand total remains under the target, but the Shell cluster is over its target.",
     "Shell", "over_target", True),
    ("en", "The Shell cluster is over its target, the grand total is under the target.",
     None, "under_target", False),
    ("de", "Das Cluster Shell liegt mit 4.467.302 über dem Zielwert.", "Shell", "over_target",
     True),
    ("de", "Das Cluster Shell liegt unter dem Zielwert.", "Shell", "over_target", False),
    ("es", "El grupo Shell queda por encima de su objetivo.", "Shell", "over_target", True),
    ("es", "El total está por debajo del objetivo.", None, "under_target", True),
    ("pl", "Klaster Shell jest powyżej celu.", "Shell", "over_target", True),
    ("pl", "Klaster Shell jest poniżej celu.", "Shell", "over_target", False),
    ("en", "I do not know.", "Shell", "over_target", False),
    # without what_if the first status in the reply wins: "Before" is read as the answer
    ("en", "Before: Shell is 3,500,000, under target. After: Shell is 4,467,302, over target.",
     "Shell", "over_target", False),
])
def test_status_heuristic(lang, reply, subject, expected, ok):
    assert ev.check_status(reply, lang, expected, subject)[0] is ok


# what-if replies state "before" and "after"; only the status after the change counts
WHATIF_REPLIES = [
    # the reply of cost-whatif-cluster-over-target that scored a false negative
    ("en", "What-if scenario (not the current estimate): Before: Shell is 3,500,000, which is "
           "under target. After: Shell is 4,467,302, which is over target.", "Shell"),
    ("de", "Szenario (What-if, nicht der aktuelle Stand): Vorher: Shell liegt mit 3.500.000 "
           "unter dem Zielwert. Nachher: Shell liegt mit 4.467.302 über dem Zielwert.", "Shell"),
    ("es", "Escenario hipotetico (no es la estimacion actual): Antes: Shell esta en 3.500.000, "
           "por debajo del objetivo. Después: Shell esta en 4.467.302, por encima del objetivo.",
     "Shell"),
    ("pl", "Scenariusz (what-if, nie obecny kosztorys): Przed: Shell 3 500 000, poniżej celu. "
           "Po: Shell 4 467 302, powyżej celu.", "Shell"),
    # the total stays under target while the cluster goes over
    ("en", "What-if scenario: Before: the grand total is under target. After: the grand total "
           "is still under target, but Shell is over its target.", "Shell"),
]


@pytest.mark.parametrize("lang, reply, subject", WHATIF_REPLIES)
def test_what_if_status_is_the_one_after_the_change(lang, reply, subject):
    assert ev.check_status(reply, lang, "over_target", subject, what_if=True)[0]
    assert not ev.check_status(reply, lang, "under_target", subject, what_if=True)[0]


def test_what_if_reply_without_after_is_read_as_a_whole():
    reply = "The Shell cluster would be over its target."
    assert ev.check_status(reply, "en", "over_target", "Shell", what_if=True)[0]
    assert not ev.check_status(reply, "en", "under_target", "Shell", what_if=True)[0]


def test_what_if_question_uses_the_status_after_in_the_score():
    q = {"id": "cost-whatif-cluster-over-target", "lang": "en", "category": "COST",
         "expect": {"scenario_label": True, "needs_tools": True,
                    "status": {"value": "over_target", "subject": "Shell"}}}
    reply = ("What-if scenario (not the current estimate): Before: Shell is 3,500,000, under "
             "target. After: Shell is 4,467,302, over target. Snapshot: Week 3 (2027-01-17)")
    response = dict(GOOD, reply=reply, category="COST")
    result = ev.score_question(q, response, 2.0)
    assert result["checks"]["status"]["ok"], result["checks"]["status"]
    assert result["correct"]


# ------------------------------------------------------------------ tool errors and language


def test_tool_errors_are_found_without_failed_true():
    """failed=false, a polite reply and a tiny tool response: the case Max saw."""
    polite = {"reply": "Sorry, the data is currently not reachable. Please try again later.",
              "failed": False, "tools": ["get_cost_summary"], "tool_response_chars": [31]}
    assert "no data" in ev.detect_tool_error(polite, [])
    reply_only = {"reply": "I could not retrieve the data right now.", "failed": False,
                  "tools": ["get_cost_summary"], "tool_response_chars": [4000]}
    assert "not reachable" in ev.detect_tool_error(reply_only, [])
    assert ev.detect_tool_error({"reply": "Die Daten sind nicht erreichbar.", "tools": [],
                                 "tool_response_chars": []}, [])
    assert ev.detect_tool_error({"reply": "No se pudo acceder a los datos.", "tools": [],
                                 "tool_response_chars": []}, [])
    assert ev.detect_tool_error({"reply": "Brak dostępu do danych.", "tools": [],
                                 "tool_response_chars": []}, [])
    assert ev.detect_tool_error({"reply": "x", "failed": True}, [])
    assert ev.detect_tool_error({"reply": "Sorry, I could not answer that right now. Please try "
                                          "again in a minute.", "tools": []}, [])
    assert ev.detect_tool_error({"reply": "ok", "tool_errors": ["unknown_cluster"],
                                 "tools": ["get_cost_items"], "tool_response_chars": [200]}, [])


def test_expected_tool_errors_are_not_failures():
    response = {"reply": "That cluster does not exist. Valid clusters: Shell, Interiors.",
                "tool_errors": ["unknown_cluster"], "tools": ["get_cost_items"],
                "tool_response_chars": [220], "failed": False}
    assert ev.detect_tool_error(response, ["unknown_cluster"]) is None
    assert ev.detect_tool_error(response, []) is not None


@pytest.mark.parametrize("lang, text", [
    ("en", "The total cost estimate is 100 dollars and we are under the target for it."),
    ("de", "Die Gesamtkosten betragen 100 Dollar und wir liegen unter dem Zielwert."),
    ("es", "El costo total es de 100 dólares y estamos por debajo del objetivo."),
    ("pl", "Całkowity koszt wynosi 100 dolarów i jesteśmy poniżej celu dla tego projektu."),
])
def test_language_detection(lang, text):
    assert ev.detect_language(text)[0] == lang


def test_short_text_has_no_language():
    assert ev.detect_language("OK 42")[0] is None


# ------------------------------------------------------------------ one question


def question(**expect):
    return {"id": "q", "group": "cost", "lang": "en", "category": "COST", "ask": "?",
            "expect": expect}


def number(value, **kw):
    return {"value": value, "label": "n", "exact": False, "tol": 0.005, **kw}


GOOD = {"reply": "The Shell cluster would be 4,467,302 in this what-if scenario, above its "
                 "target of 3,826,446. Snapshot: Week 3 (2027-01-17)",
        "category": "COST", "language": "en", "tools": ["cost_what_if"],
        "tool_response_chars": [2200], "tool_errors": [], "failed": False}


def test_a_good_answer_is_correct():
    q = question(numbers=[number(4467302.0)], status={"value": "over_target", "subject": "Shell"},
                 scenario_label=True, needs_tools=True)
    result = ev.score_question(q, GOOD, 8.2)
    assert result["correct"], result["checks"]
    assert result["snapshot_line"] is True and result["overflow"] is False


def test_wrong_number_wrong_status_and_missing_label_fail():
    q = question(numbers=[number(4467302.0)], status={"value": "over_target", "subject": "Shell"},
                 scenario_label=True)
    bad = dict(GOOD, reply="The Shell cluster remains under target at 4,000,000.")
    result = ev.score_question(q, bad, 3)
    failed = {k for k, v in result["checks"].items() if not v["ok"]}
    assert {"number:n", "status", "scenario_label"} <= failed and not result["correct"]


def test_answer_without_a_tool_call_fails_when_data_is_needed():
    q = question(numbers=[number(1.0)], needs_tools=True)
    result = ev.score_question(q, dict(GOOD, reply="It is 1.", tools=[], tool_response_chars=[]), 1)
    assert not result["checks"]["tools_called"]["ok"]


def test_category_is_required_only_where_declared():
    q = dict(question(no_tools=True), category="OTHER")
    wrong = dict(GOOD, reply="Hello there, I can only answer questions about this project.",
                 category="COST", tools=[], tool_response_chars=[])
    assert ev.score_question(q, wrong, 1)["correct"]                  # reported, not required
    q["expect"]["category_required"] = True
    assert not ev.score_question(q, wrong, 1)["correct"]


def test_a_set_of_categories_is_accepted():
    """A greeting may be routed to GENERAL ("what can you do") or OTHER (small talk)."""
    q = dict(question(no_tools=True), category=["GENERAL", "OTHER"])
    reply = "Hello there, I can answer questions about cost, carbon and quantities."
    for category in ("GENERAL", "OTHER"):
        r = ev.score_question(q, dict(GOOD, reply=reply, category=category, tools=[],
                                      tool_response_chars=[]), 1)
        assert r["checks"]["category"]["ok"], category
    wrong = ev.score_question(q, dict(GOOD, reply=reply, category="COST", tools=[],
                                      tool_response_chars=[]), 1)
    assert not wrong["checks"]["category"]["ok"]
    assert "GENERAL or OTHER" in wrong["checks"]["category"]["detail"]
    q["expect"]["category_required"] = True
    assert not ev.score_question(q, dict(GOOD, reply=reply, category="COST", tools=[],
                                         tool_response_chars=[]), 1)["correct"]


def test_overflow_by_size_or_by_message():
    q = question()
    huge = dict(GOOD, tool_response_chars=[ev.TOOL_CHARS_CAP + 1])
    assert ev.score_question(q, huge, 1)["overflow"]
    msg = dict(GOOD, reply="Error: maximum context length exceeded")
    assert ev.score_question(q, msg, 1)["overflow"]
    assert not ev.score_question(q, GOOD, 1)["overflow"]


def test_names_and_narrowing():
    q = question(names_any=["Shell", "Interiors"], tool_errors_allowed=["unknown_cluster"])
    reply = dict(GOOD, reply="There is no such cluster. Did you mean Shell?",
                 tool_errors=["unknown_cluster"], tool_response_chars=[200])
    assert ev.score_question(q, reply, 1)["correct"]
    assert not ev.score_question(q, dict(reply, reply="It costs 5."), 1)["correct"]
    q2 = question(asks_to_narrow=True, tool_errors_allowed=["too_many_results"])
    narrow = dict(GOOD, reply="That matches too many items; please narrow it down by cluster.",
                  tool_errors=["too_many_results"])
    assert ev.score_question(q2, narrow, 1)["correct"]


def test_percentile_and_gates():
    assert ev.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95) == 10
    assert ev.percentile(list(range(1, 41)), 95) == 38
    results = [{"correct": True, "latency_s": 5.0, "overflow": False, "tool_error": None,
                "group": "cost", "snapshot_line": True} for _ in range(9)]
    results.append({"correct": False, "latency_s": 6.0, "overflow": False, "tool_error": None,
                    "group": "cost", "snapshot_line": None})
    settings = {"min_accuracy": 0.9, "latency_p95_s": 20}
    assert ev.summarize(results, settings, [])["passed"]
    results[0]["overflow"] = True
    assert not ev.summarize(results, settings, [])["passed"]
    results[0]["overflow"] = False
    results[1]["latency_s"] = 25.0
    assert not ev.summarize(results, settings, [])["gates"]["p95_latency_s"]["ok"]
    results[1]["latency_s"] = 5.0
    results[2]["correct"] = False
    assert not ev.summarize(results, settings, [])["gates"]["accuracy"]["ok"]
    assert not ev.summarize([], settings, [])["passed"]


# ------------------------------------------------------------------ runner against a stub webhook


class Stub(BaseHTTPRequestHandler):
    seen: list[dict] = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Stub.seen.append({"token": self.headers.get("X-Concho-Token"), **body})
        reply = dict(GOOD) if "cluster" in body["content"] else dict(
            GOOD, reply="Sure. Snapshot: Week 3 (2027-01-17)", tools=[], tool_response_chars=[])
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def test_runner_posts_setup_first_in_one_channel_with_the_token(tmp_path, monkeypatch, capsys):
    server = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    Stub.seen.clear()
    eval_set = {"snapshot": {"id": "S"}, "settings": {"min_accuracy": 0.5}, "questions": [
        {"id": "follow", "group": "follow-up", "lang": "en", "category": "COST",
         "setup": ["first message"], "ask": "and the cluster?",
         "expect": {"numbers": [number(4467302.0)]}},
        {"id": "later", "tier": 2, "skip": "tier2", "ask": "x", "lang": "en"}]}
    path = tmp_path / "set.json"
    path.write_text(json.dumps(eval_set), encoding="utf-8")
    monkeypatch.setenv("CONCHO_WEBHOOK_TOKEN", "t0k")
    try:
        code = ev.main(["--set", str(path), "--report", str(tmp_path / "r.json"),
                        "--url", f"http://127.0.0.1:{server.server_port}/webhook/x"])
    finally:
        server.shutdown()
    assert code == 0
    first, second = Stub.seen
    assert first["content"] == "first message" and second["content"] == "and the cluster?"
    assert first["channel_id"] == second["channel_id"] and first["author_id"] == second["author_id"]
    assert first["source"] == "eval" and first["token"] == "t0k"
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert report["summary"]["questions"] == 1 and report["skipped"] == [
        {"id": "later", "reason": "tier2"}]


class NotFound(BaseHTTPRequestHandler):
    """What n8n answers when the production webhook is not registered at this path."""
    def do_POST(self):
        data = b'{"code":404,"message":"The requested webhook is not registered."}'
        self.send_response(404)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def free_port() -> int:
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_http_404_is_a_transport_error_not_an_agent_error():
    server = HTTPServer(("127.0.0.1", 0), NotFound)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        response, _ = ev.post(f"http://127.0.0.1:{server.server_port}/webhook/x", "t",
                              {"content": "x"})
    finally:
        server.shutdown()
    assert response["transport_error"] == "HTTP 404" and response["failed"] is False
    result = ev.score_question(question(numbers=[number(1.0)]), response, 1.0)
    assert not result["correct"]
    assert result["tool_error"] == ("transport error: HTTP 404, is the workflow active / "
                                    "webhook registered?")
    assert "agent error" not in result["tool_error"]
    assert result["transport_error"] == "HTTP 404"


def test_connection_refused_is_a_transport_error():
    response, _ = ev.post(f"http://127.0.0.1:{free_port()}/webhook/x", "t", {"content": "x"})
    assert response["transport_error"] == "connection refused"
    error = ev.detect_tool_error(response, [])
    assert error.startswith("transport error: connection refused,")
    assert "agent error" not in error


def test_unauthorized_names_the_token_and_a_non_json_answer_is_a_transport_error():
    assert "CONCHO_WEBHOOK_TOKEN" in ev.transport_error_message("HTTP 403")
    assert "CONCHO_WEBHOOK_TOKEN" in ev.transport_error_message("HTTP 401")

    class Html(NotFound):
        def do_POST(self):
            data = b"<html>proxy</html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(("127.0.0.1", 0), Html)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        response, _ = ev.post(f"http://127.0.0.1:{server.server_port}/x", "t", {})
    finally:
        server.shutdown()
    assert response["transport_error"] == "the answer is not JSON"


def test_the_runner_reports_transport_errors_separately(tmp_path, monkeypatch, capsys):
    server = HTTPServer(("127.0.0.1", 0), NotFound)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    eval_set = {"snapshot": {"id": "S"}, "settings": {}, "questions": [
        {"id": "q1", "group": "cost", "lang": "en", "category": "COST", "ask": "total?",
         "expect": {"numbers": [number(4467302.0)]}}]}
    path = tmp_path / "set.json"
    path.write_text(json.dumps(eval_set), encoding="utf-8")
    monkeypatch.setenv("CONCHO_WEBHOOK_TOKEN", "t0k")
    try:
        code = ev.main(["--set", str(path), "--report", str(tmp_path / "r.json"),
                        "--url", f"http://127.0.0.1:{server.server_port}/webhook/x"])
    finally:
        server.shutdown()
    out = capsys.readouterr().out
    assert code == 1
    assert "transport error: HTTP 404, is the workflow active / webhook registered?" in out
    assert "failed=true" not in out
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert report["summary"]["transport_errors"] == 1
