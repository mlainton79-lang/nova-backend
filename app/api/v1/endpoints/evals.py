"""
Eval endpoints — lets Matthew (or Tony himself) run the regression suite.
"""
from fastapi import APIRouter, Depends
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
