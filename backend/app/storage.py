from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Protocol
from uuid import uuid4


ACTIVE_STATUSES = {"confirmed", "seated"}


@dataclass(frozen=True)
class ReservationRecord:
    id: str
    confirmation_code: str
    guest_name: str
    phone: str
    party_size: int
    reservation_time: str
    duration_minutes: int
    ends_at: str
    channel: str
    status: str
    notes: str
    source_session_id: str | None
    table_ids: tuple[str, ...]
    table_names: tuple[str, ...]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class RestaurantTableRecord:
    id: str
    name: str
    capacity: int
    zone: str
    x: float
    y: float
    can_combine: bool
    is_active: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AgentSessionRecord:
    session_id: str
    caller_phone: str | None
    guest_name: str | None
    phone: str | None
    party_size: int | None
    reservation_time: str | None
    notes: str
    state: str
    reservation_id: str | None
    created_at: str
    updated_at: str


class TableImportSpec(Protocol):
    id: str
    name: str
    capacity: int
    zone: str
    x: float
    y: float
    can_combine: bool
    is_active: bool


class ReservationStore:
    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reservations (
                    id TEXT PRIMARY KEY,
                    confirmation_code TEXT NOT NULL DEFAULT '',
                    guest_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    party_size INTEGER NOT NULL CHECK (party_size > 0),
                    reservation_time TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL DEFAULT 90,
                    ends_at TEXT NOT NULL DEFAULT '',
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    source_session_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self.ensure_column(connection, "reservations", "confirmation_code", "TEXT NOT NULL DEFAULT ''")
            connection.execute(
                """
                UPDATE reservations
                SET confirmation_code = upper(substr(hex(randomblob(4)), 1, 8))
                WHERE confirmation_code = ''
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_reservations_confirmation_code
                ON reservations (confirmation_code)
                """
            )
            self.ensure_column(connection, "reservations", "duration_minutes", "INTEGER NOT NULL DEFAULT 90")
            self.ensure_column(connection, "reservations", "ends_at", "TEXT NOT NULL DEFAULT ''")
            connection.execute(
                """
                UPDATE reservations
                SET ends_at = strftime('%Y-%m-%dT%H:%M:%SZ', reservation_time, '+' || duration_minutes || ' minutes')
                WHERE ends_at = ''
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reservations_time_status
                ON reservations (reservation_time, status)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS restaurant_tables (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    capacity INTEGER NOT NULL CHECK (capacity > 0),
                    zone TEXT NOT NULL DEFAULT 'Dining Room',
                    x REAL NOT NULL DEFAULT 0,
                    y REAL NOT NULL DEFAULT 0,
                    can_combine INTEGER NOT NULL DEFAULT 1,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reservation_table_assignments (
                    reservation_id TEXT NOT NULL,
                    table_id TEXT NOT NULL,
                    PRIMARY KEY (reservation_id, table_id),
                    FOREIGN KEY (reservation_id) REFERENCES reservations(id),
                    FOREIGN KEY (table_id) REFERENCES restaurant_tables(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_call_sessions (
                    session_id TEXT PRIMARY KEY,
                    caller_phone TEXT,
                    guest_name TEXT,
                    phone TEXT,
                    party_size INTEGER,
                    reservation_time TEXT,
                    notes TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'collecting',
                    reservation_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self.ensure_column(connection, "agent_call_sessions", "state", "TEXT NOT NULL DEFAULT 'collecting'")
            self.ensure_column(connection, "agent_call_sessions", "reservation_id", "TEXT")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_call_turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def ensure_column(self, connection: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})")}
        if column_name not in columns:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def seed_default_tables(self, total_capacity: int) -> None:
        if self.list_tables(include_inactive=True):
            return
        table_sizes: list[int] = []
        remaining = total_capacity
        while remaining > 0:
            capacity = 2 if remaining >= 2 else remaining
            table_sizes.append(capacity)
            remaining -= capacity
        for index, capacity in enumerate(table_sizes, start=1):
            self.create_table(
                name=f"T{index}",
                capacity=capacity,
                zone="Dining Room",
                x=float((index - 1) % 5),
                y=float((index - 1) // 5),
                can_combine=capacity <= 4,
            )

    def create_table(
        self,
        *,
        name: str,
        capacity: int,
        zone: str = "Dining Room",
        x: float = 0,
        y: float = 0,
        can_combine: bool = True,
        is_active: bool = True,
        table_id: str | None = None,
    ) -> RestaurantTableRecord:
        now = utc_now()
        record_id = table_id or str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO restaurant_tables (
                    id, name, capacity, zone, x, y, can_combine, is_active, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    name,
                    capacity,
                    zone,
                    x,
                    y,
                    int(can_combine),
                    int(is_active),
                    now,
                    now,
                ),
            )
        record = self.get_table(record_id)
        if record is None:
            raise RuntimeError("Table was not persisted")
        return record

    def import_tables(self, tables: tuple[TableImportSpec, ...], *, replace: bool) -> None:
        now = utc_now()
        incoming_ids = {table.id for table in tables}
        with self.connect() as connection:
            if replace:
                connection.execute(
                    f"""
                    UPDATE restaurant_tables
                    SET is_active = 0, updated_at = ?
                    WHERE id NOT IN ({", ".join("?" for _ in incoming_ids)})
                    """,
                    [now, *sorted(incoming_ids)],
                )
            for table in tables:
                connection.execute(
                    """
                    INSERT INTO restaurant_tables (
                        id, name, capacity, zone, x, y, can_combine, is_active, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        capacity = excluded.capacity,
                        zone = excluded.zone,
                        x = excluded.x,
                        y = excluded.y,
                        can_combine = excluded.can_combine,
                        is_active = excluded.is_active,
                        updated_at = excluded.updated_at
                    """,
                    (
                        table.id,
                        table.name,
                        table.capacity,
                        table.zone,
                        table.x,
                        table.y,
                        int(table.can_combine),
                        int(table.is_active),
                        now,
                        now,
                    ),
                )

    def get_table(self, table_id: str) -> RestaurantTableRecord | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM restaurant_tables WHERE id = ?", (table_id,)).fetchone()
        return to_table_record(row) if row else None

    def list_tables(self, *, include_inactive: bool = False) -> list[RestaurantTableRecord]:
        where = "" if include_inactive else "WHERE is_active = 1"
        with self.connect() as connection:
            rows = connection.execute(f"SELECT * FROM restaurant_tables {where} ORDER BY zone, name").fetchall()
        return [to_table_record(row) for row in rows]

    def active_assignment_table_ids(self) -> set[str]:
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT reservation_table_assignments.table_id
                FROM reservation_table_assignments
                JOIN reservations ON reservations.id = reservation_table_assignments.reservation_id
                WHERE reservations.status IN ({placeholders})
                """,
                sorted(ACTIVE_STATUSES),
            ).fetchall()
        return {row["table_id"] for row in rows}

    def create(
        self,
        *,
        guest_name: str,
        phone: str,
        party_size: int,
        reservation_time: str,
        duration_minutes: int,
        ends_at: str,
        channel: str,
        notes: str = "",
        source_session_id: str | None = None,
        table_ids: tuple[str, ...] = (),
    ) -> ReservationRecord:
        now = utc_now()
        record_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO reservations (
                    id, confirmation_code, guest_name, phone, party_size, reservation_time, duration_minutes, ends_at, channel,
                    status, notes, source_session_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    confirmation_code(),
                    guest_name,
                    phone,
                    party_size,
                    reservation_time,
                    duration_minutes,
                    ends_at,
                    channel,
                    "confirmed",
                    notes,
                    source_session_id,
                    now,
                    now,
                ),
            )
            connection.executemany(
                """
                INSERT INTO reservation_table_assignments (reservation_id, table_id)
                VALUES (?, ?)
                """,
                [(record_id, table_id) for table_id in table_ids],
            )
        record = self.get(record_id)
        if record is None:
            raise RuntimeError("Reservation was not persisted")
        return record

    def get(self, reservation_id: str) -> ReservationRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM reservations WHERE id = ?",
                (reservation_id,),
            ).fetchone()
        return to_record(row, self.table_assignments_for_reservation(reservation_id)) if row else None

    def get_by_confirmation_code(self, confirmation_code_value: str) -> ReservationRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM reservations WHERE confirmation_code = ?",
                (confirmation_code_value.strip().upper(),),
            ).fetchone()
        return to_record(row, self.table_assignments_for_reservation(row["id"])) if row else None

    def list(
        self,
        *,
        start_time: str | None = None,
        end_time: str | None = None,
        status: str | None = None,
    ) -> list[ReservationRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if start_time:
            clauses.append("reservation_time >= ?")
            params.append(start_time)
        if end_time:
            clauses.append("reservation_time < ?")
            params.append(end_time)
        if status:
            clauses.append("status = ?")
            params.append(status)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM reservations {where} ORDER BY reservation_time, created_at",
                params,
            ).fetchall()
        return [to_record(row, self.table_assignments_for_reservation(row["id"])) for row in rows]

    def overlapping_reservations(
        self,
        *,
        start_time: str,
        end_time: str,
        exclude_reservation_id: str | None = None,
    ) -> list[ReservationRecord]:
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM reservations
                WHERE reservation_time < ?
                AND ends_at > ?
                AND status IN ({placeholders})
                AND (? IS NULL OR id != ?)
                ORDER BY reservation_time
                """,
                [end_time, start_time, *sorted(ACTIVE_STATUSES), exclude_reservation_id, exclude_reservation_id],
            ).fetchall()
        return [to_record(row, self.table_assignments_for_reservation(row["id"])) for row in rows]

    def table_assignments_for_reservation(self, reservation_id: str) -> tuple[tuple[str, str], ...]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT restaurant_tables.id, restaurant_tables.name
                FROM reservation_table_assignments
                JOIN restaurant_tables ON restaurant_tables.id = reservation_table_assignments.table_id
                WHERE reservation_table_assignments.reservation_id = ?
                ORDER BY restaurant_tables.name
                """,
                (reservation_id,),
            ).fetchall()
        return tuple((row["id"], row["name"]) for row in rows)

    def replace_table_assignments(self, reservation_id: str, table_ids: tuple[str, ...]) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM reservation_table_assignments WHERE reservation_id = ?",
                (reservation_id,),
            )
            connection.executemany(
                """
                INSERT INTO reservation_table_assignments (reservation_id, table_id)
                VALUES (?, ?)
                """,
                [(reservation_id, table_id) for table_id in table_ids],
            )

    def update_details(
        self,
        *,
        reservation_id: str,
        guest_name: str,
        phone: str,
        party_size: int,
        reservation_time: str,
        duration_minutes: int,
        ends_at: str,
        notes: str,
        table_ids: tuple[str, ...],
    ) -> ReservationRecord | None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE reservations
                SET guest_name = ?,
                    phone = ?,
                    party_size = ?,
                    reservation_time = ?,
                    duration_minutes = ?,
                    ends_at = ?,
                    notes = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    guest_name,
                    phone,
                    party_size,
                    reservation_time,
                    duration_minutes,
                    ends_at,
                    notes,
                    utc_now(),
                    reservation_id,
                ),
            )
            connection.execute(
                "DELETE FROM reservation_table_assignments WHERE reservation_id = ?",
                (reservation_id,),
            )
            connection.executemany(
                """
                INSERT INTO reservation_table_assignments (reservation_id, table_id)
                VALUES (?, ?)
                """,
                [(reservation_id, table_id) for table_id in table_ids],
            )
        return self.get(reservation_id)

    def seats_reserved_for_slot(self, reservation_time: str) -> int:
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT COALESCE(SUM(party_size), 0) AS seats
                FROM reservations
                WHERE reservation_time = ?
                AND status IN ({placeholders})
                """,
                [reservation_time, *sorted(ACTIVE_STATUSES)],
            ).fetchone()
        return int(row["seats"])

    def update_status(self, reservation_id: str, status: str) -> ReservationRecord | None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE reservations
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, utc_now(), reservation_id),
            )
        return self.get(reservation_id)

    def get_agent_session(self, session_id: str) -> AgentSessionRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_call_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return to_agent_session_record(row) if row else None

    def upsert_agent_session(
        self,
        *,
        session_id: str,
        caller_phone: str | None = None,
        guest_name: str | None = None,
        phone: str | None = None,
        party_size: int | None = None,
        reservation_time: str | None = None,
        notes: str | None = None,
        state: str | None = None,
        reservation_id: str | None = None,
    ) -> AgentSessionRecord:
        existing = self.get_agent_session(session_id)
        now = utc_now()
        created_at = existing.created_at if existing else now
        values = {
            "caller_phone": caller_phone if caller_phone is not None else (existing.caller_phone if existing else None),
            "guest_name": guest_name if guest_name is not None else (existing.guest_name if existing else None),
            "phone": phone if phone is not None else (existing.phone if existing else None),
            "party_size": party_size if party_size is not None else (existing.party_size if existing else None),
            "reservation_time": (
                reservation_time if reservation_time is not None else (existing.reservation_time if existing else None)
            ),
            "notes": notes if notes is not None else (existing.notes if existing else ""),
            "state": state if state is not None else (existing.state if existing else "collecting"),
            "reservation_id": reservation_id if reservation_id is not None else (existing.reservation_id if existing else None),
        }
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_call_sessions (
                    session_id, caller_phone, guest_name, phone, party_size,
                    reservation_time, notes, state, reservation_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    caller_phone = excluded.caller_phone,
                    guest_name = excluded.guest_name,
                    phone = excluded.phone,
                    party_size = excluded.party_size,
                    reservation_time = excluded.reservation_time,
                    notes = excluded.notes,
                    state = excluded.state,
                    reservation_id = excluded.reservation_id,
                    updated_at = excluded.updated_at
                """,
                (
                    session_id,
                    values["caller_phone"],
                    values["guest_name"],
                    values["phone"],
                    values["party_size"],
                    values["reservation_time"],
                    values["notes"],
                    values["state"],
                    values["reservation_id"],
                    created_at,
                    now,
                ),
            )
        record = self.get_agent_session(session_id)
        if record is None:
            raise RuntimeError("Agent session was not persisted")
        return record

    def append_agent_turn(self, *, session_id: str, role: str, text: str, action: str = "") -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_call_turns (id, session_id, role, text, action, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(uuid4()), session_id, role, text, action, utc_now()),
            )

    def append_audit_event(self, *, actor: str, action: str, target_type: str, target_id: str = "") -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (id, actor, action, target_type, target_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(uuid4()), actor, action, target_type, target_id, utc_now()),
            )

    def audit_event_count(self) -> int:
        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()
        return int(row["count"])


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def confirmation_code() -> str:
    return uuid4().hex[:8].upper()


def to_record(row: sqlite3.Row, table_assignments: tuple[tuple[str, str], ...] = ()) -> ReservationRecord:
    return ReservationRecord(
        id=row["id"],
        confirmation_code=row["confirmation_code"],
        guest_name=row["guest_name"],
        phone=row["phone"],
        party_size=int(row["party_size"]),
        reservation_time=row["reservation_time"],
        duration_minutes=int(row["duration_minutes"]),
        ends_at=row["ends_at"],
        channel=row["channel"],
        status=row["status"],
        notes=row["notes"],
        source_session_id=row["source_session_id"],
        table_ids=tuple(table_id for table_id, _ in table_assignments),
        table_names=tuple(table_name for _, table_name in table_assignments),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def to_table_record(row: sqlite3.Row) -> RestaurantTableRecord:
    return RestaurantTableRecord(
        id=row["id"],
        name=row["name"],
        capacity=int(row["capacity"]),
        zone=row["zone"],
        x=float(row["x"]),
        y=float(row["y"]),
        can_combine=bool(row["can_combine"]),
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def to_agent_session_record(row: sqlite3.Row) -> AgentSessionRecord:
    return AgentSessionRecord(
        session_id=row["session_id"],
        caller_phone=row["caller_phone"],
        guest_name=row["guest_name"],
        phone=row["phone"],
        party_size=int(row["party_size"]) if row["party_size"] is not None else None,
        reservation_time=row["reservation_time"],
        notes=row["notes"],
        state=row["state"],
        reservation_id=row["reservation_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
