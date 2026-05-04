from __future__ import annotations

from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import get_settings
from .layout_import import LayoutImportService, StaticLayoutProvider, TableSpec, table_to_dict
from .llm_agent import DeterministicIntentParser, OpenAIIntentParser, ReservationCallAgent
from .reservations import (
    ReservationCreate,
    ReservationError,
    ReservationNotAvailableError,
    ReservationNotFoundError,
    ReservationService,
    ReservationUpdate,
    record_to_dict,
)
from .security import audit_request, require_admin_api_key
from .storage import ReservationStore


settings = get_settings()
store = ReservationStore(settings.database_path)
layout_import_service = LayoutImportService(store)
service = ReservationService(
    store,
    timezone_name=settings.timezone,
    open_time=settings.open_time,
    close_time=settings.close_time,
    slot_minutes=settings.slot_minutes,
    slot_capacity=settings.slot_capacity,
    default_duration_minutes=settings.default_duration_minutes,
)
parser = (
    OpenAIIntentParser(api_key=settings.openai_api_key, model=settings.openai_model)
    if settings.openai_api_key
    else DeterministicIntentParser()
)
call_agent = ReservationCallAgent(service, parser)

app = FastAPI(title="Restaurant Reservation System")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_admin(request: Request) -> None:
    require_admin_api_key(settings, request)


class ReservationCreateBody(BaseModel):
    guest_name: str = Field(min_length=1)
    phone: str = Field(min_length=1)
    party_size: int = Field(gt=0)
    reservation_time: str
    duration_minutes: int | None = Field(default=None, gt=0)
    channel: str = "online"
    notes: str = ""


class ReservationStatusBody(BaseModel):
    status: str


class ReservationUpdateBody(BaseModel):
    guest_name: str | None = Field(default=None, min_length=1)
    phone: str | None = Field(default=None, min_length=1)
    party_size: int | None = Field(default=None, gt=0)
    reservation_time: str | None = None
    duration_minutes: int | None = Field(default=None, gt=0)
    notes: str | None = None


class TableSpecBody(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    capacity: int = Field(gt=0)
    zone: str = "Dining Room"
    x: float = 0
    y: float = 0
    can_combine: bool = True
    is_active: bool = True


class LayoutImportBody(BaseModel):
    mode: str = "upsert"
    dry_run: bool = True
    tables: list[TableSpecBody]


class CallTurnBody(BaseModel):
    session_id: str = Field(min_length=1)
    utterance: str = Field(min_length=1)
    caller_phone: str | None = None


@app.get("/health")
def health() -> dict[str, object]:
    try:
        table_count = len(store.list_tables())
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc
    return {
        "status": "ok",
        "restaurant": settings.restaurant_name,
        "llm_enabled": bool(settings.openai_api_key),
        "admin_auth_configured": bool(settings.admin_api_key),
        "table_count": table_count,
    }


@app.get("/availability")
def availability(
    date_value: date = Query(alias="date"),
    party_size: int = Query(default=1, gt=0),
) -> dict[str, object]:
    try:
        slots = service.availability(date_value, party_size=party_size)
    except ReservationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"date": date_value.isoformat(), "slots": [slot.__dict__ for slot in slots]}


@app.get("/tables")
def list_tables(_: None = Depends(require_admin)) -> dict[str, object]:
    return {"tables": [table_to_dict(table) for table in store.list_tables(include_inactive=True)]}


@app.post("/inventory/import")
def import_inventory(
    body: LayoutImportBody,
    request: Request,
    _: None = Depends(require_admin),
) -> dict[str, object]:
    specs = [
        TableSpec(
            id=table.id,
            name=table.name,
            capacity=table.capacity,
            zone=table.zone,
            x=table.x,
            y=table.y,
            can_combine=table.can_combine,
            is_active=table.is_active,
        )
        for table in body.tables
    ]
    result = layout_import_service.import_layout(
        provider=StaticLayoutProvider(specs),
        mode=body.mode,
        dry_run=body.dry_run,
    )
    if result.errors:
        raise HTTPException(status_code=400, detail=list(result.errors))
    audit_request(store, request, action="inventory.import", target_type="inventory")
    return {
        "mode": result.mode,
        "dry_run": result.dry_run,
        "imported_tables": result.imported_tables,
        "active_tables_after_import": result.active_tables_after_import,
        "warnings": list(result.warnings),
    }


@app.post("/reservations", status_code=201)
def create_reservation(body: ReservationCreateBody, request: Request) -> dict[str, object]:
    try:
        record = service.create_reservation(
            ReservationCreate(
                guest_name=body.guest_name,
                phone=body.phone,
                party_size=body.party_size,
                reservation_time=body.reservation_time,
                duration_minutes=body.duration_minutes,
                channel=body.channel,
                notes=body.notes,
            )
        )
    except ReservationNotAvailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReservationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_request(store, request, action="reservation.create", target_type="reservation", target_id=record.id)
    return record_to_dict(record)


@app.get("/reservations")
def list_reservations(
    date_value: date | None = Query(default=None, alias="date"),
    query: str | None = None,
    _: None = Depends(require_admin),
) -> dict[str, object]:
    records = service.list_reservations(date_value, query=query)
    return {"reservations": [record_to_dict(record) for record in records]}


@app.get("/reservations/{reservation_id}")
def get_reservation(
    reservation_id: str,
    _: None = Depends(require_admin),
) -> dict[str, object]:
    try:
        record = service.get_reservation(reservation_id)
    except ReservationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return record_to_dict(record)


@app.patch("/reservations/{reservation_id}")
def update_reservation(
    reservation_id: str,
    body: ReservationUpdateBody,
    request: Request,
    _: None = Depends(require_admin),
) -> dict[str, object]:
    try:
        record = service.update_reservation(
            reservation_id,
            ReservationUpdate(
                guest_name=body.guest_name,
                phone=body.phone,
                party_size=body.party_size,
                reservation_time=body.reservation_time,
                duration_minutes=body.duration_minutes,
                notes=body.notes,
            ),
        )
    except ReservationNotAvailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReservationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReservationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_request(store, request, action="reservation.update", target_type="reservation", target_id=record.id)
    return record_to_dict(record)


@app.patch("/reservations/{reservation_id}/status")
def update_reservation_status(
    reservation_id: str,
    body: ReservationStatusBody,
    request: Request,
    _: None = Depends(require_admin),
) -> dict[str, object]:
    try:
        record = service.update_status(reservation_id, body.status)
    except ReservationNotAvailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReservationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReservationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_request(store, request, action=f"reservation.status.{body.status}", target_type="reservation", target_id=record.id)
    return record_to_dict(record)


@app.post("/agent/call-turn")
async def call_turn(body: CallTurnBody) -> dict[str, object]:
    return await call_agent.handle_turn(
        session_id=body.session_id,
        utterance=body.utterance,
        caller_phone=body.caller_phone,
    )
