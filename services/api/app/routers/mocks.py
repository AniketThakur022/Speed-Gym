"""Mock exams — `/api/v1/mocks/*` (architecture: `/api/mocks/configure|submit-answer|results`).

Server-scored, pool-independent. The questions an attempt was served are
snapshotted with their correct answers (never sent to the client); scoring
replays against that snapshot. CAT: +3 / −1 wrong MCQ / TITA no negative
(MOCK-EXM-01). GMAT/GRE: raw counts with approximate linear scaling, labelled
as such. Ads off, sinking skills deferred, phase transitions muted — those are
client behaviours the response declares (`rules`), not server state.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..flags import require_flag
from ..mocks import scoring
from ..mocks.blueprints import BLUEPRINTS, catalogue
from ..mocks.sources import source_for
from ..social import xp as xp_mod
from ..social.policy import is_kid

router = APIRouter(prefix="/mocks", tags=["mocks"])

LATE_GRACE_SECONDS = 60


class ConfigureRequest(BaseModel):
    exam: Literal["cat", "gmat", "gre"]
    sections: Optional[list[str]] = None
    mode: Literal["full", "sectional"] = "full"


class SubmitAnswerRequest(BaseModel):
    mock_id: str
    question_id: str = Field(max_length=200)
    answer: Optional[str] = Field(default=None, max_length=8000)
    time_ms: Optional[int] = Field(default=None, ge=0)


class BulkAnswer(BaseModel):
    question_id: str = Field(max_length=200)
    answer: Optional[str] = Field(default=None, max_length=8000)
    time_ms: Optional[int] = Field(default=None, ge=0)


class SubmitRequest(BaseModel):
    mock_id: str
    answers: list[BulkAnswer] = Field(default_factory=list, max_length=200)
    section_times: dict[str, int] = Field(default_factory=dict)
    elapsed_seconds: Optional[int] = Field(default=None, ge=0)


async def _attempt(conn, user_id: str, mock_id: str):
    return await (
        await conn.execute(
            """SELECT id, blueprint_key, sections, status, started_at, completed_at, time_limit_seconds,
                      timers_suppressed, total_score, max_score, percentile, section_scores, section_times,
                      weak_areas, deferred_sinking_skills, scaled_scores, late_answers, total_time_taken_seconds
               FROM mock_exam_attempts WHERE user_id = %s::uuid AND mock_id = %s""",
            (user_id, mock_id),
        )
    ).fetchone()


async def _served(conn, attempt_id) -> dict[str, list[dict]]:
    rows = await (
        await conn.execute(
            """SELECT section_key, position, question_id, kind, text, options, correct_answer, skill,
                      difficulty, marks_correct, marks_wrong
               FROM mock_exam_questions WHERE attempt_id = %s ORDER BY section_key, position""",
            (attempt_id,),
        )
    ).fetchall()
    served: dict[str, list[dict]] = {}
    for r in rows:
        served.setdefault(r[0], []).append({
            "section_key": r[0], "position": r[1], "question_id": r[2], "kind": r[3], "text": r[4],
            "options": r[5], "correct_answer": r[6], "skill": r[7],
            "difficulty": float(r[8]) if r[8] is not None else None,
            "marks_correct": float(r[9]), "marks_wrong": float(r[10]),
        })
    return served


def _public_question(q: dict) -> dict:
    return {k: v for k, v in q.items() if k not in ("correct_answer",)}


@router.get("/blueprints")
async def blueprints(user: dict = Depends(require_flag("mock_exams"))) -> dict:
    cat = catalogue()
    for bp in cat:
        for s in bp["sections"]:
            s["available"] = await source_for(s["pool"]).available()
    return {"blueprints": cat, "scaled_scores_note": "GMAT/GRE scaled scores are approximate linear scalings, not official concordances."}


@router.post("/configure")
async def configure(body: ConfigureRequest, user: dict = Depends(require_flag("mock_exams"))) -> dict:
    bp = BLUEPRINTS[body.exam]
    keys = body.sections or [s.key for s in bp.sections]
    unknown = [k for k in keys if bp.section(k) is None]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown sections for {body.exam}: {unknown}")
    if body.mode == "full" and set(keys) != {s.key for s in bp.sections}:
        raise HTTPException(status_code=422, detail="full mode serves every section; use mode=sectional for a subset")
    sections = [s for s in bp.sections if s.key in keys]

    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await (await conn.execute("SELECT age FROM users WHERE id = %s::uuid", (user["id"],))).fetchone()
        timers_suppressed = bool(row and is_kid(row[0]))
        mock_id = f"{body.exam}_{datetime.now(timezone.utc):%Y%m%d}_{uuid.uuid4().hex[:8]}"

        served: dict[str, list[dict]] = {}
        short: dict[str, int] = {}
        for s in sections:
            qs = await source_for(s.pool).fetch(s, s.questions, seed=f"{user['id']}:{mock_id}:{s.key}")
            if not qs:
                raise HTTPException(
                    status_code=503,
                    detail=f"no question pool bound for {body.exam}.{s.key} (pool '{s.pool}'); the serving-path decision binds it",
                )
            if len(qs) < s.questions:
                short[s.key] = s.questions - len(qs)
            served[s.key] = qs

        max_score = sum(
            len(qs) * bp.section(k).marks_correct for k, qs in served.items() if bp.section(k).auto_scored
        )
        time_limit = sum(s.minutes for s in sections) * 60
        attempt_id = (
            await (
                await conn.execute(
                    """INSERT INTO mock_exam_attempts
                           (user_id, mock_id, exam_type, blueprint_key, sections, max_score,
                            time_limit_seconds, timers_suppressed, status)
                       VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, 'started') RETURNING id""",
                    (user["id"], mock_id, body.exam, bp.key, json.dumps([s.key for s in sections]),
                     max_score, time_limit, timers_suppressed),
                )
            ).fetchone()
        )[0]
        for s in sections:
            for pos, q in enumerate(served[s.key], start=1):
                wrong = s.marks_wrong_mcq if q["kind"] == "mcq" else (0.0 if q["kind"] == "essay" else s.marks_wrong_tita)
                await conn.execute(
                    """INSERT INTO mock_exam_questions
                           (attempt_id, section_key, position, question_id, kind, text, options, correct_answer,
                            skill, difficulty, marks_correct, marks_wrong)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (attempt_id, s.key, pos, q["question_id"], q["kind"], q["text"],
                     json.dumps(q.get("options")) if q.get("options") is not None else None,
                     q.get("correct_answer"), q.get("skill"), q.get("difficulty"),
                     s.marks_correct if s.auto_scored else 0.0, wrong),
                )
        await conn.commit()

    return {
        "mock_id": mock_id,
        "exam": bp.key,
        "mode": body.mode,
        "time_limit_seconds": time_limit,
        "timers_suppressed": timers_suppressed,
        "rules": {
            "negative_marking": bp.negative_marking,
            "ads": "disabled",
            "sinking_skills": "deferred",
            "phase_transitions": "muted",
            "scaled_scores_approximate": bp.scoring == "scaled",
        },
        "short_sections": short,
        "sections": [
            {
                "key": s.key, "name": s.name, "minutes": s.minutes, "kinds": list(s.kinds),
                "marks_correct": s.marks_correct, "marks_wrong_mcq": s.marks_wrong_mcq,
                "questions": [
                    {**_public_question(q), "position": i}
                    for i, q in enumerate(served[s.key], start=1)
                ],
            }
            for s in sections
        ],
    }


@router.post("/submit-answer")
async def submit_answer(body: SubmitAnswerRequest, user: dict = Depends(require_flag("mock_exams"))) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        att = await _attempt(conn, user["id"], body.mock_id)
        if att is None:
            raise HTTPException(status_code=404, detail="no such mock")
        if att[3] not in ("started", "in_progress"):
            raise HTTPException(status_code=409, detail=f"mock is {att[3]}")
        owns = await (
            await conn.execute(
                "SELECT 1 FROM mock_exam_questions WHERE attempt_id = %s AND question_id = %s",
                (att[0], body.question_id),
            )
        ).fetchone()
        if not owns:
            raise HTTPException(status_code=404, detail="that question is not part of this mock")
        await conn.execute(
            """INSERT INTO mock_exam_answers (attempt_id, question_id, answer, time_ms, submitted_at)
               VALUES (%s, %s, %s, %s, NOW())
               ON CONFLICT (attempt_id, question_id) DO UPDATE
                 SET answer = EXCLUDED.answer, time_ms = EXCLUDED.time_ms, submitted_at = NOW()""",
            (att[0], body.question_id, body.answer, body.time_ms),
        )
        await conn.execute(
            "UPDATE mock_exam_attempts SET status = 'in_progress' WHERE id = %s AND status = 'started'", (att[0],)
        )
        await conn.commit()
    return {"mock_id": body.mock_id, "question_id": body.question_id, "recorded": True}


@router.post("/submit")
async def submit(body: SubmitRequest, user: dict = Depends(require_flag("mock_exams"))) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        att = await _attempt(conn, user["id"], body.mock_id)
        if att is None:
            raise HTTPException(status_code=404, detail="no such mock")
        attempt_id, bp_key, sections, status, started_at, *_ = att
        if status == "completed":
            raise HTTPException(status_code=409, detail="already submitted")
        bp = BLUEPRINTS[bp_key]
        time_limit = int(att[6] or bp.total_minutes * 60)
        timers_suppressed = bool(att[7])
        served = await _served(conn, attempt_id)
        valid_ids = {q["question_id"] for qs in served.values() for q in qs}

        # Offline-taken mocks arrive as one bulk submit. The server cannot
        # verify their timing, so they are accepted when the client-reported
        # elapsed time fits the limit and the result is labelled accordingly.
        timing = "server"
        if body.answers:
            elapsed = body.elapsed_seconds if body.elapsed_seconds is not None else sum(body.section_times.values())
            if not timers_suppressed and elapsed > time_limit + LATE_GRACE_SECONDS:
                raise HTTPException(status_code=422, detail="reported elapsed time exceeds the exam limit")
            timing = "client_reported"
            for a in body.answers:
                if a.question_id not in valid_ids:
                    continue
                await conn.execute(
                    """INSERT INTO mock_exam_answers (attempt_id, question_id, answer, time_ms, submitted_at)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (attempt_id, question_id) DO UPDATE
                         SET answer = EXCLUDED.answer, time_ms = EXCLUDED.time_ms""",
                    (attempt_id, a.question_id, a.answer, a.time_ms, started_at),
                )

        rows = await (
            await conn.execute(
                "SELECT question_id, answer, time_ms, submitted_at FROM mock_exam_answers WHERE attempt_id = %s",
                (attempt_id,),
            )
        ).fetchall()
        deadline = started_at + timedelta(seconds=time_limit + LATE_GRACE_SECONDS)
        answers: dict[str, Optional[str]] = {}
        late = 0
        total_time_ms = 0
        for qid, ans, tms, at in rows:
            if not timers_suppressed and at > deadline:
                late += 1
                continue
            answers[qid] = ans
            total_time_ms += int(tms or 0)

        result = scoring.score_attempt(bp, served, answers, body.section_times or None)
        others = await (
            await conn.execute(
                """SELECT total_score FROM mock_exam_attempts
                   WHERE blueprint_key = %s AND sections = %s::jsonb AND status = 'completed'
                     AND id <> %s AND total_score IS NOT NULL""",
                (bp_key, json.dumps(sections), attempt_id),
            )
        ).fetchall()
        pct = scoring.percentile(result.total_raw, [float(r[0]) for r in others])
        elapsed_seconds = int(body.elapsed_seconds if body.elapsed_seconds is not None else
                              (sum(body.section_times.values()) or total_time_ms / 1000))
        weak_skills = [w["skill"] for w in result.weak_areas if w["skill"] != "unclassified"]
        scaled = {r.key: r.scaled for r in result.sections if r.scaled is not None}
        if result.scaled_total is not None:
            scaled["total"] = result.scaled_total

        async with conn.cursor() as cur:
            await cur.execute(
                """UPDATE mock_exam_attempts
                   SET status = 'completed', completed_at = NOW(), total_score = %s, max_score = %s,
                       percentile = %s, section_scores = %s, section_times = %s, weak_areas = %s,
                       deferred_sinking_skills = %s, scaled_scores = %s, late_answers = %s,
                       total_time_taken_seconds = %s
                   WHERE id = %s""",
                (result.total_raw, result.max_raw, pct, json.dumps({r.key: r.as_dict() for r in result.sections}),
                 json.dumps(body.section_times), json.dumps(result.weak_areas), json.dumps(weak_skills),
                 json.dumps(scaled), late, elapsed_seconds, attempt_id),
            )
            xp = await xp_mod.award(cur, user["id"], "mock_completed", body.mock_id)
            day = await xp_mod.record_activity_day(cur, user["id"], xp_mod.utc_today(), len(answers))
            if day["new_day"]:
                xp += await xp_mod.award(cur, user["id"], "streak_day", xp_mod.utc_today().isoformat())
        await conn.commit()

    return {
        "mock_id": body.mock_id,
        "exam": bp.key,
        "status": "completed",
        "timing": timing,
        "late_answers_discarded": late,
        "score": result.as_dict(),
        "percentile": pct,
        "peers": len(others),
        "deferred_sinking_skills": weak_skills,
        "xp_awarded": xp,
    }


@router.get("/results/{mock_id}")
async def results(mock_id: str, user: dict = Depends(require_flag("mock_exams"))) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        att = await _attempt(conn, user["id"], mock_id)
        if att is None:
            raise HTTPException(status_code=404, detail="no such mock")
        if att[3] != "completed":
            raise HTTPException(status_code=409, detail="mock not submitted yet; answers are withheld")
        served = await _served(conn, att[0])
        rows = await (
            await conn.execute(
                "SELECT question_id, answer, time_ms, submitted_at FROM mock_exam_answers WHERE attempt_id = %s",
                (att[0],),
            )
        ).fetchall()
    mine = {r[0]: (r[1], r[2], r[3]) for r in rows}
    # Review has to apply the SAME cutoff /submit scored with. Grading the
    # stored row blind reported a late answer as attempted and correct while
    # the section counts above it said unattempted — the same screen
    # contradicting itself.
    started_at, time_limit, timers_suppressed = att[4], att[6], att[7]
    deadline = (started_at + timedelta(seconds=(time_limit or 0) + LATE_GRACE_SECONDS)) if started_at else None
    review = []
    for key, qs in served.items():
        for q in qs:
            ans, tms, at = mine.get(q["question_id"], (None, None, None))
            late = bool(
                ans is not None and not timers_suppressed and deadline is not None
                and at is not None and at > deadline
            )
            review.append({
                "section": key, "position": q["position"], "question_id": q["question_id"], "kind": q["kind"],
                "text": q["text"], "options": q["options"], "skill": q["skill"],
                "your_answer": ans, "correct_answer": q["correct_answer"],
                # A discarded answer is never a correct one; `counted` says why.
                "verdict": False if late else scoring.grade(q, ans),
                "counted": not late, "late": late, "time_ms": tms,
            })
    return {
        "mock_id": mock_id, "exam": att[1], "sections": att[2],
        "total_score": float(att[8]) if att[8] is not None else None,
        "max_score": float(att[9]) if att[9] is not None else None,
        "percentile": float(att[10]) if att[10] is not None else None,
        "section_scores": att[11], "section_times": att[12], "weak_areas": att[13],
        "deferred_sinking_skills": att[14], "scaled_scores": att[15], "late_answers": att[16],
        "total_time_taken_seconds": att[17],
        "started_at": att[4].isoformat() if att[4] else None,
        "completed_at": att[5].isoformat() if att[5] else None,
        "review": review,
    }


@router.get("/history")
async def history(user: dict = Depends(require_flag("mock_exams"))) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT mock_id, exam_type, sections, total_score, max_score, percentile, scaled_scores,
                          completed_at, total_time_taken_seconds
                   FROM mock_exam_attempts WHERE user_id = %s::uuid AND status = 'completed'
                   ORDER BY completed_at DESC LIMIT 50""",
                (user["id"],),
            )
        ).fetchall()
    return {
        "attempts": [
            {
                "mock_id": r[0], "exam": r[1], "sections": r[2],
                "total_score": float(r[3]) if r[3] is not None else None,
                "max_score": float(r[4]) if r[4] is not None else None,
                "percentile": float(r[5]) if r[5] is not None else None,
                "scaled_scores": r[6], "completed_at": r[7].isoformat() if r[7] else None,
                "total_time_taken_seconds": r[8],
            }
            for r in rows
        ]
    }
