"""
Tony's agentic task endpoint.
POST /api/v1/agent/task — give Tony a task, he figures out how to do it
GET /api/v1/agent/runs — see Tony's recent autonomous runs
"""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from app.core.security import verify_token
from app.core.agent import run_agent_task, get_conn
import json

router = APIRouter()

@router.post("/agent/task")
async def agent_task(task: str, _=Depends(verify_token)):
    """Give Tony a task. He plans, uses tools, and executes autonomously."""
    result = await run_agent_task(task)
    return result

@router.get("/agent/runs")
async def agent_runs(limit: int = 20, _=Depends(verify_token)):
    """See Tony's recent autonomous task runs."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT task_id, step, result, ok, created_at 
            FROM agent_runs 
            ORDER BY created_at DESC 
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {"runs": [
            {"task_id": r[0], "step": r[1], "result": r[2], "ok": r[3], "time": str(r[4])}
            for r in rows
        ]}
    except Exception as e:
        return {"error": str(e)}
