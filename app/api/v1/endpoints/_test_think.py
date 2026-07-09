import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[4]))


class _FakeRouter:
    def get(self, *_args, **_kwargs):
        def decorator(fn):
            return fn
        return decorator


fake_fastapi = types.ModuleType("fastapi")
fake_fastapi.APIRouter = lambda *args, **kwargs: _FakeRouter()
fake_fastapi.Depends = lambda dep=None: dep
fake_fastapi.Header = lambda default=None, **_kwargs: default
fake_fastapi.HTTPException = type("HTTPException", (Exception,), {})
sys.modules.setdefault("fastapi", fake_fastapi)


class ThinkEndpointTests(unittest.TestCase):
    def test_morning_brief_uses_intelligent_briefing(self):
        from app.api.v1.endpoints import think

        async def fake_briefing():
            return {"ok": True, "briefing": "Quiet one so far.", "state": {"emails": []}}

        fake_module = types.ModuleType("app.core.intelligent_briefing")
        fake_module.get_intelligent_briefing = fake_briefing

        with mock.patch.dict(sys.modules, {"app.core.intelligent_briefing": fake_module}):
            result = asyncio.run(think.morning_brief(None))

        self.assertTrue(result["ok"])
        self.assertEqual(result["briefing"], "Quiet one so far.")


if __name__ == "__main__":
    unittest.main()
