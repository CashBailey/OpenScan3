from fastapi import FastAPI
from fastapi.testclient import TestClient

from openscan_firmware.models.task import Task


def test_create_task_respects_allowlist(monkeypatch, latest_router_loader, admin_headers):
    app = FastAPI()
    router_module = latest_router_loader("tasks")
    app.include_router(router_module.router)

    async def fake_create_and_run_task(task_name, *args, **kwargs):  # noqa: ANN001
        return Task(name=task_name, task_type=task_name)

    class StubTaskManager:
        create_and_run_task = staticmethod(fake_create_and_run_task)

    monkeypatch.setattr(router_module, "get_task_manager", lambda: StubTaskManager())
    monkeypatch.setenv("OPENSCAN_ALLOWED_TASKS", "allowed_task")

    with TestClient(app) as client:
        blocked = client.post("/tasks/blocked_task", headers=admin_headers, json={})
        assert blocked.status_code == 403

        allowed = client.post("/tasks/allowed_task", headers=admin_headers, json={})
        assert allowed.status_code == 202
