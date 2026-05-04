from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from threading import Lock
from zoneinfo import ZoneInfo

from .storage import ReservationRecord, ReservationStore


VALID_CHANNELS = {"online", "phone", "agent"}
VALID_STATUSES = {"confirmed", "cancelled", "seated", "no_show"}


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
    channel: str = "online"
    notes: str = ""
    source_session_id: str | None = None


@dataclass(frozen=True)
class AvailabilitySlot:
    reservation_time: str
    seats_remaining: int
    available: bool


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
    ) -> None:
        self.store = store
        self.timezone = ZoneInfo(timezone_name)
        self.open_time = parse_time(open_time)
        self.close_time = parse_time(close_time)
        self.slot_minutes = slot_minutes
        self.slot_capacity = slot_capacity
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

        with self._write_lock:
            normalized_time = self.normalize_datetime(request.reservation_time)
            self.ensure_open(normalized_time)
            seats_reserved = self.store.seats_reserved_for_slot(normalized_time)
            if seats_reserved + request.party_size > self.slot_capacity:
                seats_left = max(self.slot_capacity - seats_reserved, 0)
                raise ReservationNotAvailableError(f"Only {seats_left} seats remain for that slot")

            return self.store.create(
                guest_name=request.guest_name.strip(),
                phone=request.phone.strip(),
                party_size=request.party_size,
                reservation_time=normalized_time,
                channel=request.channel,
                notes=request.notes.strip(),
                source_session_id=request.source_session_id,
            )

    def list_reservations(self, target_date: date | None = None) -> list[ReservationRecord]:
        if target_date is None:
            return self.store.list()
        start = datetime.combine(target_date, time.min, self.timezone).astimezone(timezone.utc)
        end = start + timedelta(days=1)
        return self.store.list(start_time=to_utc_iso(start), end_time=to_utc_iso(end))

    def update_status(self, reservation_id: str, status: str) -> ReservationRecord:
        if status not in VALID_STATUSES:
            raise ReservationError(f"status must be one of {sorted(VALID_STATUSES)}")
        record = self.store.update_status(reservation_id, status)
        if record is None:
            raise ReservationNotFoundError("reservation not found")
        return record

    def availability(self, target_date: date, party_size: int = 1) -> list[AvailabilitySlot]:
        if party_size <= 0:
            raise ReservationError("party_size must be greater than zero")

        slots: list[AvailabilitySlot] = []
        cursor = datetime.combine(target_date, self.open_time, self.timezone)
        close = datetime.combine(target_date, self.close_time, self.timezone)
        while cursor < close:
            slot_time = to_utc_iso(cursor.astimezone(timezone.utc))
            seats_left = max(self.slot_capacity - self.store.seats_reserved_for_slot(slot_time), 0)
            slots.append(
                AvailabilitySlot(
                    reservation_time=slot_time,
                    seats_remaining=seats_left,
                    available=seats_left >= party_size,
                )
            )
            cursor += timedelta(minutes=self.slot_minutes)
        return slots

    def normalize_datetime(self, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReservationError("reservation_time must be an ISO datetime") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=self.timezone)
        parsed = floor_to_slot(parsed.astimezone(self.timezone), self.slot_minutes)
        return to_utc_iso(parsed.astimezone(timezone.utc))

    def ensure_open(self, reservation_time: str) -> None:
        local_time = datetime.fromisoformat(reservation_time.replace("Z", "+00:00")).astimezone(self.timezone)
        local_clock = local_time.time()
        if not (self.open_time <= local_clock < self.close_time):
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
