from __future__ import annotations

from fastapi import HTTPException, Request

from .config import Settings
from .storage import ReservationStore


def require_admin_api_key(settings: Settings, request: Request) -> None:
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="admin API key is not configured")
    x_api_key = request.headers.get("x-api-key")
    if x_api_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


def audit_request(store: ReservationStore, request: Request, *, action: str, target_type: str, target_id: str = "") -> None:
    actor = request.headers.get("x-actor", "api")
    store.append_audit_event(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
    )
