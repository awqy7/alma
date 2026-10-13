"""Test Worker dispatch of APPLY_REAL_PLAN, READ_BENEFICIARIES and READ_FEES."""
import json
import pytest

from uuid import uuid4
from engine.worker import Worker
from engine.ipc.contracts import Command
from tests.browser.test_real_automation import mock_eproc_server

def make_cmd(name, payload):
    return Command(version=1, id=str(uuid4()), type="COMMAND", name=name, payload=payload)

@pytest.mark.asyncio
async def test_worker_dispatches_apply_real_plan(mock_eproc_server):
    events = []
    worker = Worker(fixture_mode=True, emit=lambda ev: events.append(ev))
    try:
        # 1. Connect
        conn_res = await worker.dispatch(make_cmd("CONNECT", {"url": mock_eproc_server, "headless": True}))
        assert conn_res["state"] == "AUTHENTICATED"

        # 2. Read beneficiaries
        beneficiaries = await worker.dispatch(make_cmd("READ_BENEFICIARIES", {}))
        assert len(beneficiaries) == 1
        assert "Autor Fictício" in beneficiaries[0]["text"]

        # 3. Apply Real Plan
        plan = {
            "expected_process": "0000000-00.2026.0.00.0001",
            "total": "2790.00",
            "arrears": "2400.00",
            "expert": "390.00",
            "base_date": "2026-09",
        }
        res = await worker.dispatch(make_cmd("APPLY_REAL_PLAN", plan))
        assert res["ok"] is True
        assert res["mode"] == "REAL"
        assert res["official_changes"] == 3
        assert res["execution"]["header"]["total"] == "2.790,00"
        assert res["execution"]["beneficiary"]["arrears"] == "2.400,00"
        assert res["execution"]["fee"]["expert"] == "390,00"
        assert res["execution"]["screenshot"].startswith("data:image/png;base64,")

        # Verify step events
        step_names = [e["name"] for e in events if e.get("type") == "EVENT"]
        assert "REAL_EXECUTION_STEP" in step_names
    finally:
        await worker.close()
