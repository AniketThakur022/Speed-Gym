#!/usr/bin/env python3
"""Speed Gym — BACKEND demo. Drives the live FastAPI service end to end and
captures every real response into demo/output/backend.json.

Nothing here is stubbed: each number in the output file came back from the
running service, the live Postgres/Neo4j/Redis, or the real test suites.

Run:
    python3 demo/demo_backend.py                 # auto-detect the API
    BASE_URL=http://127.0.0.1:8010 python3 demo/demo_backend.py

Safety: it registers its own throwaway users (unique per run), writes only its
own rows, and never drops, deletes or restarts anything.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo" / "output" / "backend.json"
VENV_PY = ROOT / ".venv" / "bin" / "python"
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable
DOCKER = os.environ.get("DOCKER", "/Applications/Docker.app/Contents/Resources/bin/docker")
PG_CONTAINER = os.environ.get("PG_CONTAINER", "speedgym-postgres-1")
RUN_ID = uuid.uuid4().hex[:8]

# Routes that only exist on a build carrying every Phase-1 router. Used to
# detect an API process running stale code.
FULL_SURFACE = ("/api/v1/dashboard/stats", "/api/v1/mocks/configure", "/api/v1/chat/query")

steps: list[dict] = []
failures: list[str] = []          # step names that did not pass
failures_env: list[str] = []      # environment problems found while probing
numbers: dict = {}

C = {"g": "\033[0;32m", "r": "\033[0;31m", "y": "\033[0;33m", "b": "\033[1;38;5;191m", "0": "\033[0m"}
if not sys.stdout.isatty():
    C = {k: "" for k in C}


def say(msg: str) -> None:
    print(f"\n{C['b']}▌ {msg}{C['0']}")


def rec(name: str, ok: bool, **detail) -> dict:
    steps.append({"step": name, "ok": bool(ok), **detail})
    mark = f"{C['g']}✓{C['0']}" if ok else f"{C['r']}✗{C['0']}"
    print(f"  {mark} {name}")
    if not ok:
        failures.append(name)
    return steps[-1]


class CIDict(dict):
    """Header map that answers regardless of case (uvicorn lower-cases them)."""

    def __init__(self, items=()):
        super().__init__()
        for k, v in items:
            self[k] = v

    def __setitem__(self, k, v):
        super().__setitem__(str(k).lower(), v)

    def get(self, k, default=None):
        return super().get(str(k).lower(), default)

    def __contains__(self, k):
        return super().__contains__(str(k).lower())


def http(method: str, url: str, *, token=None, body=None, headers=None, raw: bytes | None = None, timeout=30):
    """Returns (status, parsed_or_text, response_headers)."""
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    data = raw
    if body is not None and raw is None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload, status, rh = r.read(), r.status, CIDict(r.headers.items())
    except urllib.error.HTTPError as e:
        payload, status, rh = e.read(), e.code, CIDict(e.headers.items())
    except Exception as e:  # noqa: BLE001 — connection refused etc.
        return 0, {"error": f"{type(e).__name__}: {e}"}, {}
    text = payload.decode("utf-8", "replace")
    try:
        return status, json.loads(text, strict=False), rh
    except ValueError:
        return status, text, rh


def run(cmd: list[str], cwd=None, timeout=600, env=None) -> tuple[int, str]:
    e = {**os.environ, **(env or {})}
    try:
        p = subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True, timeout=timeout, env=e)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return 127, f"{type(exc).__name__}: {exc}"


def psql(sql: str) -> tuple[int, str]:
    if not (os.path.exists(DOCKER) or shutil.which(DOCKER)):
        return 127, "docker cli not found"
    return run([DOCKER, "exec", PG_CONTAINER, "psql", "-U", "vmsg", "-d", "vmsg", "-t", "-A", "-F", "|", "-c", sql])


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def email(tag: str) -> str:
    return f"vmsg.demo.{tag}.{RUN_ID}@example.com"


# ── 0. Pick the API ─────────────────────────────────────────────────────────

def pick_base() -> str:
    candidates = [os.environ["BASE_URL"]] if os.environ.get("BASE_URL") else [
        "http://127.0.0.1:8000", "http://127.0.0.1:8010", "http://127.0.0.1:8080",
    ]
    surveyed = []
    for base in candidates:
        st, doc, _ = http("GET", f"{base}/openapi.json", timeout=5)
        if st != 200 or not isinstance(doc, dict):
            surveyed.append({"base": base, "reachable": False})
            continue
        paths = set(doc.get("paths") or {})
        missing = [p for p in FULL_SURFACE if p not in paths]
        surveyed.append({"base": base, "reachable": True, "route_count": len(paths),
                         "full_surface": not missing, "missing_routes": missing})
        if not missing:
            numbers["api_route_count"] = len(paths)
            rec("API selected", True, base_url=base, routes=len(paths), survey=surveyed)
            for other in surveyed:
                if other["base"] != base and other.get("reachable") and other.get("missing_routes"):
                    failures_env.append(
                        f"{other['base']} answers but runs STALE code: {len(other['missing_routes'])} Phase-1 routes "
                        f"absent ({', '.join(other['missing_routes'])}) — that uvicorn predates the current tree."
                    )
            return base
    rec("API selected", False, survey=surveyed)
    for s in surveyed:
        if s.get("reachable") and s.get("missing_routes"):
            failures_env.append(
                f"{s['base']} answers but is running STALE code: {len(s['missing_routes'])} Phase-1 routes absent "
                f"({', '.join(s['missing_routes'])}). Restart that uvicorn to pick up the current tree."
            )
    print(f"{C['r']}No API on the current build was reachable. Set BASE_URL.{C['0']}")
    sys.exit(2)


BASE = pick_base()
API = f"{BASE}/api/v1"


# ── 1. Health / readiness across all three DBs ──────────────────────────────

def step_health():
    say("1. Health and readiness — Postgres, Neo4j, Redis")
    st_h, health, _ = http("GET", f"{BASE}/health")
    st_r, ready, _ = http("GET", f"{BASE}/ready")
    ok = st_h == 200 and st_r == 200 and isinstance(ready, dict) and ready.get("status") == "ready"
    numbers["dbs_healthy"] = sum(1 for v in (ready.get("checks") or {}).values() if v == "healthy") if isinstance(ready, dict) else 0
    rec("health + readiness (3/3 DBs)", ok, health_status=st_h, health=health, ready_status=st_r, ready=ready)


# ── 2. Register → login → refresh rotation → replay refused ─────────────────

def step_auth():
    say("2. Auth — register, login, rotating refresh, replay detection")
    addr, pwd = email("learner"), "DemoPass!2026"
    st, reg, _ = http("POST", f"{API}/auth/register", body={"email": addr, "password": pwd, "display_name": "Demo Learner"},
                      headers={"X-Device-Fingerprint": "demo-device-A"})
    rec("register (201)", st == 201, status=st, user=(reg or {}).get("user") if isinstance(reg, dict) else reg)
    if st != 201:
        return None
    user = reg["user"]

    st, dup, _ = http("POST", f"{API}/auth/register", body={"email": addr, "password": pwd})
    rec("duplicate register refused (409)", st == 409, status=st, detail=dup)

    st, login, _ = http("POST", f"{API}/auth/login", body={"email": addr, "password": pwd},
                        headers={"X-Device-Fingerprint": "demo-device-A"})
    rec("login (200)", st == 200, status=st, token_prefix=str(login.get("token", ""))[:24] + "…" if isinstance(login, dict) else login)
    token = login["token"]

    st, bad, _ = http("POST", f"{API}/auth/login", body={"email": addr, "password": "wrong-password"})
    rec("wrong password refused (401)", st == 401, status=st, detail=bad)

    st, me, _ = http("GET", f"{API}/auth/me", token=token)
    rec("GET /auth/me (200)", st == 200 and me.get("user", {}).get("email") == addr, status=st, me=me)

    st, anon, _ = http("GET", f"{API}/auth/me")
    rec("unauthenticated /auth/me refused (401)", st == 401, status=st, detail=anon)

    # Rotation + replay on a SEPARATE device so the learner session survives.
    st, sess2, _ = http("POST", f"{API}/auth/login", body={"email": addr, "password": pwd},
                        headers={"X-Device-Fingerprint": "demo-device-B"})
    rt0 = sess2["refreshToken"]
    st1, rot1, _ = http("POST", f"{API}/auth/refresh", body={"refreshToken": rt0},
                        headers={"X-Device-Fingerprint": "demo-device-B"})
    rt1 = rot1.get("refreshToken") if isinstance(rot1, dict) else None
    rec("refresh rotates the token", st1 == 200 and rt1 and rt1 != rt0, status=st1,
        old_token_tail=rt0[-8:], new_token_tail=(rt1 or "")[-8:], rotated=bool(rt1 and rt1 != rt0))

    st2, replay, _ = http("POST", f"{API}/auth/refresh", body={"refreshToken": rt0},
                          headers={"X-Device-Fingerprint": "demo-device-B"})
    rec("REPLAYED refresh token refused (401)", st2 == 401, status=st2, detail=replay)

    st3, after, _ = http("POST", f"{API}/auth/refresh", body={"refreshToken": rt1})
    rec("replay revoked the whole device session (401)", st3 == 401, status=st3, detail=after,
        note="rotation_replay revokes every live refresh token on that device fingerprint")

    st4, logout, _ = http("POST", f"{API}/auth/logout", body={"refreshToken": rt1})
    rec("logout (200)", st4 == 200, status=st4, body=logout)

    for route in ("google", "phone"):
        st5, body, _ = http("POST", f"{API}/auth/{route}", body={"idToken": "demo"})
        rec(f"Firebase /auth/{route} declared-not-configured (501)", st5 == 501, status=st5, detail=body)

    return {"email": addr, "password": pwd, "token": token, "user": user}


# ── 3. QR scanner-login pairing ─────────────────────────────────────────────

def step_qr(sess):
    say("3. QR scanner-login pairing (300 s one-time HMAC nonce in Redis)")
    st, gen, _ = http("POST", f"{API}/auth/scanner-login/generate")
    ok = st == 200 and "code" in gen
    rec("generate pairing code", ok, status=st, expires_in=gen.get("expiresIn") if ok else None,
        code_prefix=(gen.get("code") or "")[:8] + "…" if ok else None,
        sig_prefix=(gen.get("sig") or "")[:16] + "…" if ok else None)
    if not ok:
        return
    code, sig, poll = gen["code"], gen["sig"], gen["pollToken"]

    st, pend, _ = http("GET", f"{API}/auth/scanner-login/poll?code={code}&pollToken={poll}")
    rec("poll before approval → pending", st == 200 and pend.get("status") == "pending", status=st, body=pend)

    st, badsig, _ = http("POST", f"{API}/auth/scanner-login/verify", token=sess["token"], body={"code": code, "sig": "deadbeef"})
    rec("tampered QR signature refused (400)", st == 400, status=st, detail=badsig)

    st, badpoll, _ = http("GET", f"{API}/auth/scanner-login/poll?code={code}&pollToken=not-the-poll-token")
    rec("wrong poll token refused (403)", st == 403, status=st, detail=badpoll)

    st, appr, _ = http("POST", f"{API}/auth/scanner-login/verify", token=sess["token"], body={"code": code, "sig": sig})
    rec("phone approves the pairing", st == 200 and appr.get("status") == "approved", status=st, body=appr)

    st, got, _ = http("GET", f"{API}/auth/scanner-login/poll?code={code}&pollToken={poll}")
    rec("scanner collects a real session", st == 200 and "token" in got, status=st,
        status_field=got.get("status"), user=got.get("user"))

    st, again, _ = http("GET", f"{API}/auth/scanner-login/poll?code={code}&pollToken={poll}")
    rec("nonce burns after collection (410)", st == 410, status=st, detail=again)


# ── 4. Practice session + trust ladder ──────────────────────────────────────

def step_practice():
    say("4. Practice session — what is served, what is withheld, and why")
    st, s, _ = http("GET", f"{API}/practice/session?size=10")
    ok = st == 200 and isinstance(s, dict) and s.get("items")
    summary = s.get("summary", {}) if isinstance(s, dict) else {}
    withheld = summary.get("withheld", {})
    numbers["practice_items_served"] = summary.get("served")
    numbers["practice_items_withheld_quarantined"] = sum(withheld.values()) if withheld else 0
    sample = []
    for it in (s.get("items") or [])[:3]:
        sample.append({k: it.get(k) for k in ("template_id", "source", "skill", "trust", "feeds_mastery",
                                              "answer_verification", "solution_verification", "answer_check",
                                              "expected_answer", "difficulty")})
    rec("GET /practice/session", bool(ok), status=st, summary=summary, sample_items=sample,
        trust_contract={
            "trust=static_verified": "book content: the QUESTION and its ANSWER are verified; the worked solution is NOT",
            "solution_verification=unverified": "no stage-7 jester has passed on the walkthrough",
            "feeds_mastery": "false for SANDBOX content and for anything with no :Skill edge — playable, but never moves BKT",
            "withheld": "factory-QUARANTINED templates are never served; the count is reported so an empty page is explainable",
        })
    first = (s.get("items") or [{}])[0]
    return first.get("template_id"), first


# ── 5. BKT — the real client-side engine, then the server ledger ────────────

def step_bkt(sess):
    say("5. BKT mastery — real engine, then /sync → dashboard")
    tsx = shutil.which("npx")
    bkt = None
    if tsx and (ROOT / "demo" / "bkt_demo.ts").exists():
        code, out = run(["npx", "--no-install", "tsx", "demo/bkt_demo.ts"], timeout=180)
        try:
            bkt = json.loads(out[out.index("{"):out.rindex("}") + 1])
        except Exception:  # noqa: BLE001
            bkt = None
        if bkt:
            numbers["bkt_p_before"] = bkt["before"]["pL"]
            numbers["bkt_p_after"] = bkt["after"]["pL"]
            numbers["bkt_band_before"] = bkt["before"]["band"]
            numbers["bkt_band_after"] = bkt["after"]["band"]
            rec("client-side BKT engine: 0.35 FRACTURED → 0.8247 FRAGILE", round(bkt["after"]["pL"], 4) == 0.8247,
                before=bkt["before"], after=bkt["after"], arithmetic=bkt["arithmetic"],
                counterfactual_wrong=bkt["counterfactual_wrong_answer"], params=bkt["params"])
        else:
            rec("client-side BKT engine", False, stdout_tail=out[-400:])
    else:
        rec("client-side BKT engine", False, reason="npx/tsx unavailable")
    return bkt


def step_sync(sess, bkt, template_id):
    say("6. /api/v1/sync — offline queue contract and event idempotency")
    token = sess["token"]
    skill = "Basic Operations (+, -, ×, ÷)"
    p_after = (bkt or {}).get("after", {}).get("pL", 0.8247261)
    now = int(time.time() * 1000)
    session_id = str(uuid.uuid4())
    attempt_id, end_id = str(uuid.uuid4()), str(uuid.uuid4())
    batch = {
        "device_id": f"demo-device-{RUN_ID}",
        "events": [
            {"event_id": attempt_id, "event_type": "problem_attempt", "client_timestamp": now,
             "session_id": session_id, "session_elapsed_ms": 4200,
             "metadata": {"is_correct": True, "time_ms": 4200, "difficulty": 1, "skill": skill,
                          "domain": "vedic", "template_id": template_id}},
            {"event_id": end_id, "event_type": "session_end", "client_timestamp": now + 1000,
             "session_id": session_id, "session_elapsed_ms": 9000,
             "metadata": {"domain": "vedic", "technique_states": {skill: {"pLearned": p_after, "attempts": 1}}}},
        ],
    }
    st1, r1, _ = http("POST", f"{API}/sync", token=token, body=batch)
    st2, r2, _ = http("POST", f"{API}/sync", token=token, body=batch)  # byte-identical resend
    ok = st1 == 200 and st2 == 200 and r1.get("accepted") == 2 and r2.get("accepted") == 0 and r2.get("duplicates") == 2
    numbers["sync_first_accepted"] = r1.get("accepted")
    numbers["sync_replay_duplicates"] = r2.get("duplicates")
    numbers["sync_xp_first"] = r1.get("xp_awarded")
    numbers["sync_xp_replay"] = r2.get("xp_awarded")

    stored = None
    rc, out = psql(f"select count(*) from raw_events where event_id in ('{attempt_id}','{end_id}');")
    if rc == 0:
        m = re.search(r"\d+", out)
        stored = int(m.group()) if m else None
    rec("same event_id sent twice → stored once", bool(ok), first_send=r1, replay_send=r2,
        rows_in_raw_events=stored,
        contract={"key": "event_id (uuid)", "mechanism": "INSERT … ON CONFLICT DO NOTHING",
                  "paths": "A raw_events · B session aggregates · C sync_outbox → Neo4j · D bkt_state_snapshots",
                  "xp": "awarded only on a freshly-inserted event, so a resend cannot pay twice"})

    st, fb, _ = http("POST", f"{API}/sync/content/feedback", token=token,
                     body={"templateId": template_id or "demo", "trustStatus": "suspect", "reason": "answer_mismatch",
                           "comment": f"demo run {RUN_ID}", "domain": "vedic", "reportedAt": now})
    rec("queued offline mutation replays (content/feedback)", st == 200, status=st, body=fb)
    st, unk, _ = http("POST", f"{API}/sync/does/not/exist", token=token, body={})
    rec("unknown sync key refused, not silently swallowed (404)", st == 404, status=st, detail=unk)

    ent = r1.get("entitlement") if isinstance(r1, dict) else None
    rec("offline entitlement re-signed on every flush", bool(ent and ent.get("signature")), entitlement=ent)
    return r1


# ── 7. The eight dashboard reads ────────────────────────────────────────────

def step_dashboard(sess):
    say("7. GET /api/v1/dashboard/* — eight reads, all real")
    token = sess["token"]
    out = {}
    ok_all = True
    for name in ("topics", "radar", "metrics", "stats", "streak", "events", "leaderboard", "recent-activity"):
        st, body, _ = http("GET", f"{API}/dashboard/{name}", token=token)
        out[name] = {"status": st, "body": body}
        ok_all = ok_all and st == 200
        print(f"      {name:<16} {st}")
    topics = out["topics"]["body"]
    mastery = topics[0]["value"] if isinstance(topics, list) and topics else None
    numbers["dashboard_mastery_pct"] = mastery
    numbers["dashboard_reads_200"] = sum(1 for v in out.values() if v["status"] == 200)
    rec("8/8 dashboard reads 200 and reflect the synced session", ok_all and mastery == 82,
        reads=out, mastery_from_bkt_snapshot=mastery,
        note="dashboard/topics reads the BKT snapshot the client shipped — 0.8247 → 82 %")
    return out


# ── 8. Mock exam ────────────────────────────────────────────────────────────

def step_mocks(sess):
    say("8. Mock exam — configure → serve → server-scored submit")
    token = sess["token"]
    st, bps, _ = http("GET", f"{API}/mocks/blueprints", token=token)
    pools = {}
    if st == 200:
        for bp in bps["blueprints"]:
            pools[bp["key"]] = [{"section": s["key"], "pool": s["pool"], "available": s["available"],
                                 "questions": s["questions"]} for s in bp["sections"]]
    rec("GET /mocks/blueprints (CAT / GMAT / GRE)", st == 200, status=st, pools=pools,
        note=bps.get("scaled_scores_note") if isinstance(bps, dict) else None)

    st, cfg, _ = http("POST", f"{API}/mocks/configure", token=token,
                      body={"exam": "cat", "sections": ["qa"], "mode": "sectional"})
    if st != 200:
        rec("configure CAT sectional (QA)", False, status=st, detail=cfg)
        return None
    mock_id = cfg["mock_id"]
    section = cfg["sections"][0]
    served = section["questions"]
    leaks = [q for q in served if "correct_answer" in q]
    rec("configure CAT sectional (QA) — answers withheld from the client", not leaks,
        mock_id=mock_id, time_limit_seconds=cfg["time_limit_seconds"], rules=cfg["rules"],
        questions_served=len(served), answer_keys_in_payload=len(leaks), sample_question=served[0])

    st, early, _ = http("GET", f"{API}/mocks/results/{mock_id}", token=token)
    rec("results withheld before submit (409)", st == 409, status=st, detail=early)

    rc, out = psql("select q.position,q.question_id,q.kind,q.correct_answer from mock_exam_questions q "
                   f"join mock_exam_attempts a on a.id=q.attempt_id where a.mock_id='{mock_id}' order by q.position;")
    key = [ln.split("|") for ln in out.strip().splitlines() if ln.strip()] if rc == 0 else []
    if not key:
        rec("read the grader's snapshot", False, reason="psql unavailable; cannot script deliberate right/wrong answers")
        return None
    answers = []
    n_correct, n_wrong = 12, 6
    for i, (_pos, qid, _kind, corr) in enumerate(key):
        if i < n_correct:
            answers.append({"question_id": qid, "answer": corr, "time_ms": 30000})
        elif i < n_correct + n_wrong:
            answers.append({"question_id": qid, "answer": "-999999", "time_ms": 25000})
    st, res, _ = http("POST", f"{API}/mocks/submit", token=token,
                      body={"mock_id": mock_id, "answers": answers, "section_times": {"qa": 1800},
                            "elapsed_seconds": 1800})
    ok = st == 200 and res.get("status") == "completed"
    sec = res["score"]["sections"][0] if ok else {}
    numbers["mock_total_raw"] = res.get("score", {}).get("total_raw") if ok else None
    numbers["mock_max_raw"] = res.get("score", {}).get("max_raw") if ok else None
    numbers["mock_percentile"] = res.get("percentile") if ok else None
    numbers["mock_peers"] = res.get("peers") if ok else None
    rec("server-scored submit (client never scored itself)", ok, status=st,
        mock_id=mock_id, section=sec, total=res.get("score", {}).get("total_raw") if ok else None,
        max_raw=res.get("score", {}).get("max_raw") if ok else None,
        percentile=res.get("percentile") if ok else None, peers=res.get("peers") if ok else None,
        weak_areas=res.get("score", {}).get("weak_areas") if ok else None,
        deferred_sinking_skills=res.get("deferred_sinking_skills") if ok else None,
        xp_awarded=res.get("xp_awarded") if ok else None,
        arithmetic=(f"{sec.get('correct')} correct × +3 = {sec.get('correct', 0) * 3}; "
                    f"{sec.get('wrong')} wrong × 0 (TITA/numeric carries NO negative under CAT rules) = 0; "
                    f"{sec.get('unattempted')} blank = 0  →  {sec.get('raw')} / {sec.get('max_raw')}") if ok else None)

    st, dup, _ = http("POST", f"{API}/mocks/submit", token=token, body={"mock_id": mock_id, "answers": []})
    rec("double submit refused (409)", st == 409, status=st, detail=dup)

    st, rev, _ = http("GET", f"{API}/mocks/results/{mock_id}", token=token)
    revealed = [r for r in (rev.get("review") or []) if r.get("correct_answer")] if st == 200 else []
    rec("results reveal the key only after submit", st == 200 and revealed, status=st,
        review_rows=len(rev.get("review") or []) if st == 200 else 0,
        sample_review=(rev.get("review") or [{}])[0] if st == 200 else None)

    st, hist, _ = http("GET", f"{API}/mocks/history", token=token)
    rec("GET /mocks/history", st == 200, status=st, attempts=len(hist.get("attempts") or []) if st == 200 else 0)
    return mock_id


def step_cat_penalty():
    say("9. CAT −1 penalty arithmetic — the real scoring engine")
    script = ROOT / "demo" / "output" / f".cat_penalty_{RUN_ID}.py"
    script.write_text(
        "import sys, json\n"
        "sys.path.insert(0, '.')\n"
        "from app.mocks.blueprints import BLUEPRINTS\n"
        "from app.mocks import scoring\n"
        "bp = BLUEPRINTS['cat']\n"
        "sec = bp.section('varc')\n"
        "qs = [{'question_id': f'q{i}', 'kind': 'mcq', 'options': ['a','b','c','d'], 'correct_answer': 'b',\n"
        "       'marks_correct': sec.marks_correct, 'marks_wrong': sec.marks_wrong_mcq, 'skill': 'RC'}\n"
        "      for i in range(1, 25)]\n"
        "ans = {}\n"
        "for i, q in enumerate(qs, 1):\n"
        "    if i <= 10: ans[q['question_id']] = 'b'\n"
        "    elif i <= 16: ans[q['question_id']] = 'c'\n"
        "r = scoring.score_section(sec, qs, ans)\n"
        "tita = bp.section('qa')\n"
        "print(json.dumps({\n"
        "  'engine': 'services/api/app/mocks/scoring.py (the same code the live submit ran)',\n"
        "  'blueprint': 'cat', 'section': sec.key, 'questions': sec.questions,\n"
        "  'marks_correct': sec.marks_correct, 'marks_wrong_mcq': sec.marks_wrong_mcq,\n"
        "  'marks_wrong_tita': tita.marks_wrong_tita,\n"
        "  'result': r.as_dict(),\n"
        "  'arithmetic': '%d correct x (+%s) + %d wrong x (%s) + %d blank x 0 = %s out of %s' %\n"
        "                (r.correct, sec.marks_correct, r.wrong, sec.marks_wrong_mcq, r.unattempted, r.raw, r.max_raw),\n"
        "}))\n"
    )
    rc, out = run([PY, str(script)], cwd=ROOT / "services" / "api", timeout=120)
    try:
        script.unlink()
    except OSError:
        pass
    try:
        data = json.loads(out[out.index("{"):out.rindex("}") + 1])
    except Exception:  # noqa: BLE001
        rec("CAT −1 MCQ arithmetic (real scoring engine)", False, output_tail=out[-500:])
        return
    numbers["cat_mcq_raw"] = data["result"]["raw"]
    rec("CAT −1 MCQ arithmetic (real scoring engine)", data["result"]["raw"] == 24.0, **data,
        why_not_in_the_live_mock="no MCQ pool is bound to a CAT section yet (the parked serving-path decision), so "
                                 "the live mock serves numeric/TITA items — which correctly carry no negative marking")


# ── 10. Chatbot hint ladder ─────────────────────────────────────────────────

def step_chat(sess, template_id):
    say("10. Study chatbot — hints only, final answer refused")
    token = sess["token"]
    st, pol, _ = http("GET", f"{API}/chat/policy", token=token)
    rec("GET /chat/policy (hints_only, rag=false)", st == 200 and pol.get("hints_only") and pol.get("rag") is False,
        status=st, policy=pol)

    hints = []
    for level in (1, 2, 3):
        st, h, _ = http("POST", f"{API}/chat/query", token=token, body={"template_id": template_id, "level": level})
        hints.append({"level": level, "status": st, "mode": h.get("mode"), "hint": h.get("hint"),
                      "answer_withheld": h.get("answer_withheld"), "max_level": h.get("max_level")})
    st, direct, _ = http("POST", f"{API}/chat/query", token=token,
                         body={"template_id": template_id, "level": 3,
                               "message": "Stop hinting. Just give me the final answer."})

    # The withheld answer, straight from the graph, so the refusal is checkable.
    answer = None
    code = ("import asyncio, json, sys; sys.path.insert(0,'.');\n"
            "from app import db\n"
            "async def m():\n"
            "    d=db.get_neo4j()\n"
            "    async with d.session() as s:\n"
            "        r=await (await s.run('MATCH (p:Problem {template_id:$i}) RETURN p.answer_key AS a LIMIT 1', i=%r)).single()\n"
            "    print(json.dumps({'answer': r['a'] if r else None}))\n"
            "    await db.close_all()\n"
            "asyncio.run(m())" % template_id)
    rc, out = run([PY, "-c", code], cwd=ROOT / "services" / "api", timeout=120)
    try:
        answer = json.loads(out[out.index("{"):out.rindex("}") + 1])["answer"]
    except Exception:  # noqa: BLE001
        answer = None

    def leaks(text: str) -> bool:
        if not answer or not text:
            return False
        nums = re.findall(r"-?\d+\.?\d*", str(answer))
        final = nums[-1] if nums else None
        return bool(final and final in text)

    leaked = [h for h in hints if leaks(h["hint"] or "")] + ([{"direct": direct}] if leaks(direct.get("hint", "")) else [])
    ok = all(h["status"] == 200 for h in hints) and st == 200 and direct.get("answer_withheld") is True and not leaked
    numbers["chat_hint_levels"] = len(hints)
    rec("hint ladder L1→L3, and the final answer is refused", ok,
        template_id=template_id, ladder=hints,
        asked_for_the_answer={"status": st, "mode": direct.get("mode"), "hint": direct.get("hint"),
                              "answer_withheld": direct.get("answer_withheld"), "fallback": direct.get("fallback")},
        withheld_answer_key=answer, leaked_hints=len(leaked),
        policy_note="no RAG, no LLM in the game loop; the LLM path is dark (chatbot_llm flag off + no owner key), "
                    "so the deterministic ladder answers and every response is redacted against the answer key")


# ── 11. Billing ─────────────────────────────────────────────────────────────

def step_billing(sess):
    say("11. Billing — INR conversion, and the refusal paths (no real payment)")
    token = sess["token"]
    st, plans, _ = http("GET", f"{API}/billing/plans")
    pro = next((p for p in plans.get("plans", []) if p["tier"] == "pro"), {}) if st == 200 else {}
    rate = plans.get("usd_inr_rate") if st == 200 else None
    numbers["usd_inr_rate"] = rate
    numbers["pro_inr_paise"] = pro.get("inr_paise")
    check = (pro.get("usd_cents", 0) * rate == pro.get("inr_paise")) if rate else False
    rec("GET /billing/plans — USD→INR derived, never hardcoded", st == 200 and check, status=st,
        default_provider=plans.get("default_provider"), default_currency=plans.get("default_currency"),
        providers_available=plans.get("providers_available"), usd_inr_rate=rate, trial_days=plans.get("trial_days"),
        plans=plans.get("plans"), family=plans.get("family"),
        arithmetic=f"pro: {pro.get('usd_cents')} US cents × {rate} = {pro.get('inr_paise')} paise (₹{(pro.get('inr_paise') or 0)/100:.2f})")

    st, sub, _ = http("GET", f"{API}/billing/subscription", token=token)
    rec("GET /billing/subscription (free tier, signed entitlement)", st == 200, status=st, body=sub)

    st, co, _ = http("POST", f"{API}/billing/checkout", token=token,
                     body={"tier": "pro", "provider": "razorpay", "currency": "INR"})
    rec("POST /billing/checkout — honest 503, owner keys absent", st == 503, status=st, detail=co,
        note="no RAZORPAY_KEY_ID/SECRET in .env on this host, so no provider call is attempted and no intent is charged")

    st, ver, _ = http("POST", f"{API}/billing/checkout/verify", token=token,
                      body={"intent_id": str(uuid.uuid4()), "razorpay_payment_id": "pay_DEMO",
                            "razorpay_subscription_id": "sub_DEMO", "razorpay_signature": "0" * 64})
    rec("POST /billing/checkout/verify — forged signature never grants a tier", st in (400, 503), status=st, detail=ver)

    st, wh, _ = http("POST", f"{BASE}/api/webhooks/razorpay", raw=b'{"event":"subscription.charged"}',
                     headers={"Content-Type": "application/json", "X-Razorpay-Signature": "0" * 64})
    rec("webhook on this host: unsigned is never accepted", st in (400, 503), status=st, detail=wh)
    return plans


def step_webhook_signature():
    """Signature verification proven end to end on a throwaway API process with a
    demo webhook secret. Nothing on the shared server is changed."""
    say("12. Razorpay webhook — signature verification and idempotency (isolated process)")
    port = free_port()
    secret = "vmsg-demo-webhook-secret"
    log = ROOT / "demo" / "output" / f".webhook-api-{RUN_ID}.log"
    proc = None
    try:
        proc = subprocess.Popen(
            [PY, "-m", "uvicorn", "app.main:app", "--port", str(port), "--host", "127.0.0.1"],
            cwd=ROOT / "services" / "api", stdout=open(log, "w"), stderr=subprocess.STDOUT,
            env={**os.environ, "RAZORPAY_WEBHOOK_SECRET": secret},
        )
        base = f"http://127.0.0.1:{port}"
        for _ in range(40):
            st, _b, _h = http("GET", f"{base}/health", timeout=2)
            if st == 200:
                break
            time.sleep(0.5)
        else:
            rec("throwaway API for the webhook demo", False, reason="did not become healthy")
            return

        sub_ref = f"sub_DEMO_{RUN_ID}"
        body = json.dumps({"event": "subscription.charged",
                           "payload": {"subscription": {"entity": {
                               "id": sub_ref, "status": "active",
                               "current_start": 1788600000, "current_end": 1791192000}}}},
                          separators=(",", ":")).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        st_bad, bad, _ = http("POST", f"{base}/api/webhooks/razorpay", raw=body,
                              headers={"Content-Type": "application/json", "X-Razorpay-Signature": "0" * 64})
        tampered = body.replace(b'"status":"active"', b'"status":"active" ')
        st_tam, tam, _ = http("POST", f"{base}/api/webhooks/razorpay", raw=tampered,
                              headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig})
        st_ok, good, _ = http("POST", f"{base}/api/webhooks/razorpay", raw=body,
                              headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig})
        st_re, redel, _ = http("POST", f"{base}/api/webhooks/razorpay", raw=body,
                               headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig})
        ok = (st_bad == 400 and st_tam == 400 and st_ok == 200 and st_re == 200
              and good.get("status") == "ok" and redel.get("status") == "duplicate")
        rec("bad sig 400 · tampered body 400 · valid 200 · redelivery deduped", ok,
            forged_signature={"status": st_bad, "body": bad},
            tampered_body_valid_sig={"status": st_tam, "body": tam},
            valid_signature={"status": st_ok, "body": good},
            redelivery={"status": st_re, "body": redel},
            note="the ledger key is sha256 of the SIGNED BYTES, not the unsigned X-Razorpay-Event-Id header; "
                 "handled=false because sub_DEMO_* matches no subscription — the event is recorded, never guessed at")
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.kill()
        try:
            log.unlink()
        except OSError:
            pass


# ── 13. Admin, flags, content trust ─────────────────────────────────────────

def step_admin():
    say("13. Admin — kill-switch config, feature flags, content trust")
    st, cfg, _ = http("GET", f"{BASE}/api/config")
    flags = cfg.get("flags", {}) if st == 200 else {}
    on = sorted(k for k, v in flags.items() if v["enabled"])
    off = sorted(k for k, v in flags.items() if not v["enabled"])
    numbers["flags_total"] = len(flags)
    numbers["flags_on"] = len(on)
    numbers["flags_dark"] = len(off)
    rec("GET /api/config — unauthenticated kill-switch read", st == 200 and flags, status=st,
        total=len(flags), enabled=on, dark=off, degraded=cfg.get("degraded") if st == 200 else None,
        note="unauthenticated by design: it must answer during an incident, and it exposes flag STATES only "
             "(no thresholds, no secrets); if the DB is unreachable it fails to all-off, never all-on")

    addr, pwd = email("admin"), "DemoAdmin!2026"
    st, reg, _ = http("POST", f"{API}/auth/register", body={"email": addr, "password": pwd, "display_name": "Demo Admin"})
    if st != 201:
        rec("admin demo account", False, status=st, detail=reg)
        return
    atok = reg["token"]
    st, denied, _ = http("GET", f"{BASE}/api/admin/flags", token=atok)
    rec("non-admin refused (403)", st == 403, status=st, detail=denied)

    rc, out = psql(f"update users set is_admin=true where email='{addr}';")
    if rc != 0:
        rec("grant admin to the demo account", False, output=out[-300:],
            note="needs docker/psql; without it only the 403 guard above is demonstrated")
        return
    rec("grant admin to the demo account (own row only)", True, sql="UPDATE users SET is_admin=true WHERE email=<demo>")

    st, fl, _ = http("GET", f"{BASE}/api/admin/flags", token=atok)
    rec("GET /api/admin/flags — full operator view", st == 200, status=st,
        count=len(fl.get("flags") or []) if st == 200 else 0,
        sample=(fl.get("flags") or [])[:4] if st == 200 else None)

    st, tr, _ = http("GET", f"{BASE}/api/admin/content/trust?limit=5", token=atok)
    numbers["content_trust_totals"] = tr.get("totals") if st == 200 else None
    rec("GET /api/admin/content/trust — the ladder that gates serving", st == 200, status=st,
        totals=tr.get("totals") if st == 200 else None, sample=(tr.get("items") or [])[:3] if st == 200 else None)

    if st == 200 and tr.get("items"):
        cid = tr["items"][0]["content_id"]
        st2, one, _ = http("GET", f"{BASE}/api/admin/content/trust/{cid}", token=atok)
        rec("GET one content-trust record", st2 == 200, status=st2, content_id=cid, record=one)

    st, reg2, _ = http("GET", f"{BASE}/api/admin/telemetry/registry", token=atok)
    rec("GET /api/admin/telemetry/registry — psychometric events are never sampled", st == 200, status=st,
        policy=reg2.get("policy") if st == 200 else None,
        events=len(reg2.get("events") or []) if st == 200 else 0)

    st, kpi, _ = http("GET", f"{BASE}/api/admin/kpi", token=atok)
    rec("GET /api/admin/kpi", st == 200, status=st, metrics=kpi.get("metrics") if st == 200 else None)

    # Audited flag write, replayed at its CURRENT value: proves the write path
    # and the audit trail without changing what anyone sees.
    cur = next((f for f in (fl.get("flags") or []) if f["flag_name"] == "ad_engine"), None)
    if cur:
        st, res, _ = http("POST", f"{BASE}/api/admin/flags/ad_engine", token=atok,
                          body={"enabled": cur["enabled"], "rollout_pct": cur["rollout_pct"]})
        st2, fl2, _ = http("GET", f"{BASE}/api/admin/flags", token=atok)
        now = next((f for f in (fl2.get("flags") or []) if f["flag_name"] == "ad_engine"), {})
        rec("kill-switch write path is audited (value restated, not changed)",
            st == 200 and now.get("enabled") == cur["enabled"], status=st, response=res,
            before=cur, after=now,
            note="ad_engine stays OFF; the demo writes back its own value so updated_by/updated_at record the "
                 "operator without changing behaviour for anyone")

    st, unknown, _ = http("POST", f"{BASE}/api/admin/flags/not_a_real_flag", token=atok, body={"enabled": True})
    rec("inventing a flag refused (404)", st == 404, status=st, detail=unknown)
    return atok


def step_dark_launch(sess):
    say("14. Dark launch — a flag-gated route is invisible, not merely forbidden")
    token = sess["token"]
    st_on, friends, _ = http("GET", f"{API}/social/friends", token=token)
    st_dark, clips, _ = http("POST", f"{API}/social/clips", token=token, body={"match_id": "demo"})
    st_pol, pol, _ = http("GET", f"{API}/social/policy", token=token)
    rec("social_friends ON → 200 · social_clips dark → 404", st_on == 200 and st_dark == 404,
        friends={"status": st_on, "body": friends}, clips={"status": st_dark, "body": clips},
        policy={"status": st_pol, "body": pol},
        note="404 not 403: a dark-launched feature must look like it does not exist, so the response never "
             "confirms what is being rolled out")


# ── 15. Rate limiting and security headers ──────────────────────────────────

def step_ratelimit():
    say("15. Rate limiting — X-RateLimit-* headers and a real 429")
    addr, pwd = email("burst"), "DemoBurst!2026"
    st, reg, _ = http("POST", f"{API}/auth/register", body={"email": addr, "password": pwd, "display_name": "Burst"})
    if st != 201:
        rec("burst account", False, status=st, detail=reg)
        return
    token = reg["token"]
    st, _b, h = http("GET", f"{API}/auth/me", token=token)
    limit = h.get("X-RateLimit-Limit")
    sec_headers = {k: v for k, v in h.items() if k.lower() in
                   ("x-content-type-options", "x-frame-options", "referrer-policy", "content-security-policy",
                    "strict-transport-security", "permissions-policy", "x-request-id")}
    trace = []
    hit, at = None, None
    for i in range(1, int(limit or 300) + 40):
        st, _b, h = http("GET", f"{API}/auth/me", token=token, timeout=10)
        if st != 429 and (i <= 3 or i % 100 == 0):
            trace.append({"request": i, "status": st, "remaining": h.get("X-RateLimit-Remaining")})
        if st == 429:
            hit, at = h, i
            trace.append({"request": i, "status": 429, "remaining": h.get("X-RateLimit-Remaining"),
                          "retry_after": h.get("Retry-After")})
            break
    numbers["rate_limit_per_minute"] = int(limit) if limit else None
    numbers["rate_limit_429_at_request"] = at
    rec("burst → 429 with Retry-After; headers on every response", at is not None,
        limit=limit, hit_429_at_request=at, retry_after=(hit or {}).get("Retry-After"),
        trace=trace, security_headers=sec_headers,
        note="fixed one-minute Redis window keyed on the JWT subject (IP when anonymous); this burst only "
             "consumed the throwaway demo user's own bucket. Redis down = fail OPEN.")

    st, cfg, _ = http("GET", f"{BASE}/api/config")
    rec("kill-switch config exempt from the limit", st == 200, status=st,
        note="/health, /ready, /api/config, webhooks and the loopback internal API are never rate limited")


# ── 16. Test suites ─────────────────────────────────────────────────────────

def step_tests():
    say("16. Test suites — run, not quoted")
    rc, out = run([PY, "-m", "pytest", "-q"], cwd=ROOT / "services" / "api", timeout=900)
    m = re.search(r"(\d+) passed", out)
    fail = re.search(r"(\d+) failed", out)
    numbers["pytest_passed"] = int(m.group(1)) if m else None
    numbers["pytest_failed"] = int(fail.group(1)) if fail else 0
    failed_ids = re.findall(r"^FAILED (\S+)", out, re.M)
    numbers["pytest_failed_ids"] = failed_ids
    rec("pytest — services/api", rc == 0 and m is not None,
        passed=numbers["pytest_passed"], failed=numbers["pytest_failed"], failed_tests=failed_ids, exit_code=rc,
        tail=out.strip().splitlines()[-1] if out.strip() else "",
        note="the dev Postgres/Redis are shared, so a few tests carry state between runs: the rate-limit test "
             "burns its 5-request bucket if the suite is run twice inside one minute, and the daily-challenge "
             "leaderboard test assumes the caller lands in the visible top slice. Re-run once per minute for a "
             "clean read.")

    rc, out = run(["npx", "--no-install", "vitest", "run"], timeout=900)
    files = re.search(r"Test Files\s+(\d+) passed", out)
    tests = re.search(r"Tests\s+(\d+) passed", out)
    numbers["vitest_files"] = int(files.group(1)) if files else None
    numbers["vitest_tests"] = int(tests.group(1)) if tests else None
    rec("vitest — game server, psychometrics, vedic-math, web", rc == 0 and tests is not None,
        test_files=numbers["vitest_files"], tests=numbers["vitest_tests"], exit_code=rc,
        suites=[ln.strip() for ln in out.splitlines() if ln.strip().startswith("✓")])


# ── main ────────────────────────────────────────────────────────────────────

def main() -> int:
    started = datetime.now(timezone.utc)
    step_health()
    sess = step_auth()
    if not sess:
        print("auth failed; nothing further can run")
        return 1
    step_qr(sess)
    template_id, _first = step_practice()
    bkt = step_bkt(sess)
    step_sync(sess, bkt, template_id)
    step_dashboard(sess)
    step_mocks(sess)
    step_cat_penalty()
    step_chat(sess, template_id)
    step_billing(sess)
    step_webhook_signature()
    step_admin()
    step_dark_launch(sess)
    step_ratelimit()
    step_tests()

    passed = sum(1 for s in steps if s["ok"])
    payload = {
        "workstream": "backend",
        "generated_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "run_id": RUN_ID,
        "base_url": BASE,
        "everything_here_was_executed": True,
        "checks_passed": passed,
        "checks_total": len(steps),
        "headline_numbers": numbers,
        "steps": steps,
        "failures": [s["step"] for s in steps if not s["ok"]],
        "environment_findings": failures_env,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    say("Summary")
    print(f"  {passed}/{len(steps)} checks passed")
    print(f"  captured → {OUT}")
    return 0 if passed == len(steps) else 1


if __name__ == "__main__":
    sys.exit(main())
