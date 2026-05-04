from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from threading import Lock
from zoneinfo import ZoneInfo

from .inventory import TablePlanner
from .storage import ACTIVE_STATUSES, ReservationRecord, ReservationStore


VALID_CHANNELS = {"online", "phone", "agent", "walk_in"}
VALID_STATUSES = {"confirmed", "cancelled", "seated", "no_show"}
ALLOWED_STATUS_TRANSITIONS = {
    "confirmed": {"seated", "cancelled", "no_show"},
    "seated": set(),
    "cancelled": set(),
    "no_show": set(),
}


class ReservationError(ValueError):
    pass


class ReservationNotAvailableError(ReservationError):
    pass


class ReservationNotFoundError(ReservationError):
    pass


@dataclass(frozen=True)
class ReservationCreate:
    guest_name: str
    phone: str
    party_size: int
    reservation_time: str
    duration_minutes: int | None = None
    channel: str = "online"
    notes: str = ""
    source_session_id: str | None = None


@dataclass(frozen=True)
class ReservationUpdate:
    guest_name: str | None = None
    phone: str | None = None
    party_size: int | None = None
    reservation_time: str | None = None
    duration_minutes: int | None = None
    notes: str | None = None


@dataclass(frozen=True)
class AvailabilitySlot:
    reservation_time: str
    ends_at: str
    seats_remaining: int
    available: bool
    table_ids: tuple[str, ...] = ()
    table_names: tuple[str, ...] = ()


class ReservationService:
    def __init__(
        self,
        store: ReservationStore,
        *,
        timezone_name: str,
        open_time: str,
        close_time: str,
        slot_minutes: int,
        slot_capacity: int,
        default_duration_minutes: int = 90,
    ) -> None:
        self.store = store
        self.store.seed_default_tables(slot_capacity)
        self.timezone = ZoneInfo(timezone_name)
        self.open_time = parse_time(open_time)
        self.close_time = parse_time(close_time)
        self.slot_minutes = slot_minutes
        self.slot_capacity = slot_capacity
        self.default_duration_minutes = default_duration_minutes
        self._write_lock = Lock()

    def create_reservation(self, request: ReservationCreate) -> ReservationRecord:
        if not request.guest_name.strip():
            raise ReservationError("guest_name is required")
        if not request.phone.strip():
            raise ReservationError("phone is required")
        if request.party_size <= 0:
            raise ReservationError("party_size must be greater than zero")
        if request.channel not in VALID_CHANNELS:
            raise ReservationError(f"channel must be one of {sorted(VALID_CHANNELS)}")
        duration_minutes = request.duration_minutes or self.default_duration_minutes
        if duration_minutes <= 0:
            raise ReservationError("duration_minutes must be greater than zero")

        with self._write_lock:
            normalized_time = self.normalize_datetime(request.reservation_time)
            ends_at = to_utc_iso(parse_iso(normalized_time) + timedelta(minutes=duration_minutes))
            self.ensure_turn_within_hours(normalized_time, ends_at)
            planner = self.planner_for_window(start_time=normalized_time, end_time=ends_at)
            plan = planner.best_plan(
                party_size=request.party_size,
                start_time=normalized_time,
                end_time=ends_at,
            )
            if plan is None:
                raise ReservationNotAvailableError("No table assignment is available for that party and time")

            return self.store.create(
                guest_name=request.guest_name.strip(),
                phone=request.phone.strip(),
                party_size=request.party_size,
                reservation_time=normalized_time,
                duration_minutes=duration_minutes,
                ends_at=ends_at,
                channel=request.channel,
                notes=request.notes.strip(),
                source_session_id=request.source_session_id,
                table_ids=plan.table_ids,
            )

    def get_reservation(self, reservation_id: str) -> ReservationRecord:
        record = self.store.get(reservation_id)
        if record is None:
            record = self.store.get_by_confirmation_code(reservation_id)
        if record is None:
            raise ReservationNotFoundError("reservation not found")
        return record

    def list_reservations(self, target_date: date | None = None, query: str | None = None) -> list[ReservationRecord]:
        if target_date is None:
            records = self.store.list()
        else:
            start = datetime.combine(target_date, time.min, self.timezone).astimezone(timezone.utc)
            end = start + timedelta(days=1)
            records = self.store.list(start_time=to_utc_iso(start), end_time=to_utc_iso(end))
        if not query:
            return records
        normalized_query = query.strip().lower()
        return [
            record
            for record in records
            if normalized_query in record.guest_name.lower()
            or normalized_query in record.phone.lower()
            or normalized_query in record.confirmation_code.lower()
        ]

    def update_status(self, reservation_id: str, status: str) -> ReservationRecord:
        if status not in VALID_STATUSES:
            raise ReservationError(f"status must be one of {sorted(VALID_STATUSES)}")
        with self._write_lock:
            existing = self.get_reservation(reservation_id)
            if status == existing.status:
                return existing
            if status not in ALLOWED_STATUS_TRANSITIONS[existing.status]:
                raise ReservationError(f"cannot transition reservation from {existing.status} to {status}")
            if status in ACTIVE_STATUSES and existing.status not in ACTIVE_STATUSES:
                plan = self.assignment_plan_for_record(existing, exclude_reservation_id=existing.id)
                if plan is None:
                    raise ReservationNotAvailableError("No table assignment is available to reactivate this reservation")
                self.store.replace_table_assignments(existing.id, plan.table_ids)
            if status not in ACTIVE_STATUSES:
                self.store.replace_table_assignments(existing.id, ())
            record = self.store.update_status(existing.id, status)
            if record is None:
                raise ReservationNotFoundError("reservation not found")
            return record

    def update_reservation(self, reservation_id: str, update: ReservationUpdate) -> ReservationRecord:
        with self._write_lock:
            existing = self.get_reservation(reservation_id)
            if existing.status != "confirmed":
                raise ReservationError("only confirmed reservations can be edited")
            guest_name = (update.guest_name if update.guest_name is not None else existing.guest_name).strip()
            phone = (update.phone if update.phone is not None else existing.phone).strip()
            party_size = update.party_size if update.party_size is not None else existing.party_size
            duration_minutes = update.duration_minutes if update.duration_minutes is not None else existing.duration_minutes
            notes = (update.notes if update.notes is not None else existing.notes).strip()
            reservation_time = (
                self.normalize_datetime(update.reservation_time)
                if update.reservation_time is not None
                else existing.reservation_time
            )

            if not guest_name:
                raise ReservationError("guest_name is required")
            if not phone:
                raise ReservationError("phone is required")
            if party_size <= 0:
                raise ReservationError("party_size must be greater than zero")
            if duration_minutes <= 0:
                raise ReservationError("duration_minutes must be greater than zero")

            ends_at = to_utc_iso(parse_iso(reservation_time) + timedelta(minutes=duration_minutes))
            self.ensure_turn_within_hours(reservation_time, ends_at)
            planner = self.planner_for_window(
                start_time=reservation_time,
                end_time=ends_at,
                exclude_reservation_id=existing.id,
            )
            plan = planner.best_plan(party_size=party_size, start_time=reservation_time, end_time=ends_at)
            if plan is None:
                raise ReservationNotAvailableError("No table assignment is available for the updated reservation")

            record = self.store.update_details(
                reservation_id=existing.id,
                guest_name=guest_name,
                phone=phone,
                party_size=party_size,
                reservation_time=reservation_time,
                duration_minutes=duration_minutes,
                ends_at=ends_at,
                notes=notes,
                table_ids=plan.table_ids,
            )
            if record is None:
                raise ReservationNotFoundError("reservation not found")
            return record

    def availability(self, target_date: date, party_size: int = 1) -> list[AvailabilitySlot]:
        if party_size <= 0:
            raise ReservationError("party_size must be greater than zero")

        slots: list[AvailabilitySlot] = []
        cursor = datetime.combine(target_date, self.open_time, self.timezone)
        close = datetime.combine(target_date, self.close_time, self.timezone)
        while cursor + timedelta(minutes=self.default_duration_minutes) <= close:
            slot_time = to_utc_iso(cursor.astimezone(timezone.utc))
            ends_at = to_utc_iso(cursor.astimezone(timezone.utc) + timedelta(minutes=self.default_duration_minutes))
            planner = self.planner_for_window(start_time=slot_time, end_time=ends_at)
            plan = planner.best_plan(party_size=party_size, start_time=slot_time, end_time=ends_at)
            slots.append(
                AvailabilitySlot(
                    reservation_time=slot_time,
                    ends_at=ends_at,
                    seats_remaining=planner.available_seats(start_time=slot_time, end_time=ends_at),
                    available=plan is not None,
                    table_ids=plan.table_ids if plan else (),
                    table_names=plan.table_names if plan else (),
                )
            )
            cursor += timedelta(minutes=self.slot_minutes)
        return slots

    def planner_for_window(
        self,
        *,
        start_time: str,
        end_time: str,
        exclude_reservation_id: str | None = None,
    ) -> TablePlanner:
        return TablePlanner(
            self.store.list_tables(),
            self.store.overlapping_reservations(
                start_time=start_time,
                end_time=end_time,
                exclude_reservation_id=exclude_reservation_id,
            ),
        )

    def assignment_plan_for_record(
        self,
        record: ReservationRecord,
        *,
        exclude_reservation_id: str | None = None,
    ):
        planner = self.planner_for_window(
            start_time=record.reservation_time,
            end_time=record.ends_at,
            exclude_reservation_id=exclude_reservation_id,
        )
        return planner.best_plan(
            party_size=record.party_size,
            start_time=record.reservation_time,
            end_time=record.ends_at,
        )

    def normalize_datetime(self, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReservationError("reservation_time must be an ISO datetime") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=self.timezone)
        parsed = floor_to_slot(parsed.astimezone(self.timezone), self.slot_minutes)
        return to_utc_iso(parsed.astimezone(timezone.utc))

    def ensure_turn_within_hours(self, reservation_time: str, ends_at: str) -> None:
        local_start = parse_iso(reservation_time).astimezone(self.timezone)
        local_end = parse_iso(ends_at).astimezone(self.timezone)
        if local_start.date() != local_end.date():
            raise ReservationNotAvailableError("Requested turn must end on the same service date")
        if not (self.open_time <= local_start.time() and local_end.time() <= self.close_time):
            raise ReservationNotAvailableError("Requested time is outside restaurant reservation hours")


def record_to_dict(record: ReservationRecord) -> dict[str, object]:
    return asdict(record)


def parse_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def floor_to_slot(value: datetime, slot_minutes: int) -> datetime:
    minute = (value.minute // slot_minutes) * slot_minutes
    return value.replace(minute=minute, second=0, microsecond=0)


def to_utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
