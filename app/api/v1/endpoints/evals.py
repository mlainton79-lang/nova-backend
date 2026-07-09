"""
Eval endpoints — lets Matthew (or Tony himself) run the regression suite.
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional
from app.core.security import verify_token
from app.evals.runner import run_all, run_one, log_result_to_db
from app.evals.test_cases import TESTS, get_test_by_id

router = APIRouter()


class EvalRunRequest(BaseModel):
    endpoint: str = "chat"  # or "council"
    category: Optional[str] = None  # filter to one category
    log: bool = True  # persist result to DB


@router.post("/evals/run")
async def run_evals(req: EvalRunRequest, _=Depends(verify_token)):
    """
    Run the regression suite against Tony. Returns full results + summary.
    """
    summary = await run_all(endpoint=req.endpoint, category=req.category)
    if req.log:
        log_result_to_db(summary)
    return summary


class SingleEvalRequest(BaseModel):
    test_id: str
    endpoint: str = "chat"


@router.post("/evals/run_one")
async def run_single(req: SingleEvalRequest, _=Depends(verify_token)):
    """Run a single test by ID."""
    test = get_test_by_id(req.test_id)
    if not test:
        return {"ok": False, "error": f"Test {req.test_id!r} not found"}
    result = await run_one(test, endpoint=req.endpoint)
    return {"ok": True, "result": result}


@router.get("/evals/tests")
async def list_tests(_=Depends(verify_token)):
    """List all registered tests."""
    return {
        "ok": True,
        "total": len(TESTS),
        "tests": [
            {"id": t["id"], "category": t.get("category"), "message": t["message"]}
            for t in TESTS
        ],
    }


@router.get("/evals/history")
async def eval_history(limit: int = 10, _=Depends(verify_token)):
    """Get the most recent eval runs from DB for trend tracking."""
    try:
        import os, psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()
        cur.execute("""
            SELECT id, run_at, endpoint, passed, total, pass_rate
            FROM tony_eval_runs
            ORDER BY run_at DESC LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {
            "ok": True,
            "runs": [
                {"id": r[0], "run_at": str(r[1]), "endpoint": r[2],
                 "passed": r[3], "total": r[4], "pass_rate": r[5]}
                for r in rows
            ],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/evals/daily-loop")
async def daily_loop_quality(_=Depends(verify_token)):
    """Run deterministic shape checks for Capture / Resume / Review."""
    from app.core.capture import capture_note
    from app.core.daily_loop_quality import (
        combine_daily_loop_quality,
        evaluate_capture_result,
        evaluate_daily_review_payload,
        evaluate_today_brief_payload,
    )
    from app.core.daily_review import get_daily_review
    from app.core.today_brief import get_today_brief

    today_payload = await get_today_brief()
    review_payload = await get_daily_review()
    capture_payload = await capture_note("api key should not be saved")

    return combine_daily_loop_quality([
        evaluate_today_brief_payload(today_payload),
        evaluate_daily_review_payload(review_payload),
        evaluate_capture_result(capture_payload),
    ])


@router.get("/evals/memory-retrieval")
async def memory_retrieval_quality(_=Depends(verify_token)):
    """Check that a captured note can be retrieved again."""
    from app.core.memory_quality import run_capture_retrieval_eval

    return await run_capture_retrieval_eval()


@router.get("/evals/daily-surface-model")
async def daily_surface_model_quality(_=Depends(verify_token)):
    """Run model-assisted quality checks for Today Brief / Daily Review."""
    from app.core.daily_surface_model_eval import run_daily_surface_model_eval

    return await run_daily_surface_model_eval()


@router.get("/evals/failure-candidates")
async def production_failure_eval_candidates(
    minutes: int = Query(24 * 60, ge=1, le=24 * 60),
    limit: int = Query(25, ge=1, le=100),
    _=Depends(verify_token),
):
    """Suggest eval cases from recent warning/error/critical run_events."""
    from app.core.production_failure_evals import recent_failure_events

    return recent_failure_events(minutes=minutes, limit=limit)
