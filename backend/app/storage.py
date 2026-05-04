from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4


ACTIVE_STATUSES = {"confirmed", "seated"}


@dataclass(frozen=True)
class ReservationRecord:
    id: str
    guest_name: str
    phone: str
    party_size: int
    reservation_time: str
    channel: str
    status: str
    notes: str
    source_session_id: str | None
    created_at: str
    updated_at: str


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
                    guest_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    party_size INTEGER NOT NULL CHECK (party_size > 0),
                    reservation_time TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    source_session_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reservations_time_status
                ON reservations (reservation_time, status)
                """
            )

    def create(
        self,
        *,
        guest_name: str,
        phone: str,
        party_size: int,
        reservation_time: str,
        channel: str,
        notes: str = "",
        source_session_id: str | None = None,
    ) -> ReservationRecord:
        now = utc_now()
        record_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO reservations (
                    id, guest_name, phone, party_size, reservation_time, channel,
                    status, notes, source_session_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    guest_name,
                    phone,
                    party_size,
                    reservation_time,
                    channel,
                    "confirmed",
                    notes,
                    source_session_id,
                    now,
                    now,
                ),
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
        return to_record(row) if row else None

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
        return [to_record(row) for row in rows]

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


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_record(row: sqlite3.Row) -> ReservationRecord:
    return ReservationRecord(
        id=row["id"],
        guest_name=row["guest_name"],
        phone=row["phone"],
        party_size=int(row["party_size"]),
        reservation_time=row["reservation_time"],
        channel=row["channel"],
        status=row["status"],
        notes=row["notes"],
        source_session_id=row["source_session_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
