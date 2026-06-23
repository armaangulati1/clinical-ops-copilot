"""FastAPI + HTMX approval UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from agent.audit import get_case_history
from schemas.decisions import ProposedAction
from ui.deps import AppServices, build_services, connect_mcp_host

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters["tojson"] = lambda value, indent=2: json.dumps(
    value, indent=indent
)


def create_app(services: AppServices | None = None) -> FastAPI:
    app = FastAPI(title="Clinical Ops Approval UI")
    app.state.services = services or build_services()

    @app.get("/", response_class=HTMLResponse)
    async def queue(request: Request) -> HTMLResponse:
        pending = app.state.services.store.list_pending()
        return TEMPLATES.TemplateResponse(
            request,
            "queue.html",
            {"pending": pending},
        )

    @app.get("/approvals/{approval_id}", response_class=HTMLResponse)
    async def approval_detail(request: Request, approval_id: str) -> HTMLResponse:
        approval = app.state.services.store.get(approval_id)
        if approval is None:
            return HTMLResponse("Approval not found", status_code=404)
        history = get_case_history(approval.case_id, app.state.services.audit)
        return TEMPLATES.TemplateResponse(
            request,
            "detail.html",
            {"approval": approval, "history": history},
        )

    @app.post("/approvals/{approval_id}/approve")
    async def approve(approval_id: str) -> RedirectResponse:
        await connect_mcp_host(app.state.services)
        await app.state.services.gate.approve(
            approval_id,
            reviewer="ui-reviewer",
        )
        return RedirectResponse(url=f"/approvals/{approval_id}", status_code=303)

    @app.post("/approvals/{approval_id}/reject")
    async def reject(approval_id: str) -> RedirectResponse:
        await app.state.services.gate.reject(
            approval_id,
            reviewer="ui-reviewer",
        )
        return RedirectResponse(url=f"/approvals/{approval_id}", status_code=303)

    @app.post("/approvals/{approval_id}/edit-approve")
    async def edit_approve(
        approval_id: str,
        tool: str = Form(...),
        arguments_json: str = Form(...),
    ) -> RedirectResponse:
        await connect_mcp_host(app.state.services)
        arguments = json.loads(arguments_json)
        if not isinstance(arguments, dict):
            msg = "arguments_json must be a JSON object"
            raise ValueError(msg)
        edited = ProposedAction(
            server="clinic-ops",
            tool=tool,
            arguments=_stringify_form_values(arguments),
        )
        await app.state.services.gate.approve_with_edit(
            approval_id,
            edited,
            reviewer="ui-reviewer",
        )
        return RedirectResponse(url=f"/approvals/{approval_id}", status_code=303)

    return app


def _stringify_form_values(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value if isinstance(value, str) else str(value)
        for key, value in arguments.items()
    }


app = create_app()
