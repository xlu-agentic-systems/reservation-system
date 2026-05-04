from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import combinations

from .storage import ACTIVE_STATUSES, ReservationRecord, RestaurantTableRecord


@dataclass(frozen=True)
class AssignmentPlan:
    table_ids: tuple[str, ...]
    table_names: tuple[str, ...]
    capacity: int


class TablePlanner:
    def __init__(self, tables: list[RestaurantTableRecord], reservations: list[ReservationRecord]) -> None:
        self.tables = [table for table in tables if table.is_active]
        self.reservations = [reservation for reservation in reservations if reservation.status in ACTIVE_STATUSES]

    def best_plan(self, *, party_size: int, start_time: str, end_time: str) -> AssignmentPlan | None:
        busy_table_ids = self.busy_table_ids(start_time=start_time, end_time=end_time)
        candidates: list[AssignmentPlan] = []
        for group in self.candidate_table_groups():
            if any(table.id in busy_table_ids for table in group):
                continue
            capacity = sum(table.capacity for table in group)
            if capacity < party_size:
                continue
            candidates.append(
                AssignmentPlan(
                    table_ids=tuple(table.id for table in group),
                    table_names=tuple(table.name for table in group),
                    capacity=capacity,
                )
            )

        if not candidates:
            return None
        return min(candidates, key=lambda plan: (plan.capacity - party_size, len(plan.table_ids), plan.capacity))

    def available_seats(self, *, start_time: str, end_time: str) -> int:
        busy_table_ids = self.busy_table_ids(start_time=start_time, end_time=end_time)
        return sum(table.capacity for table in self.tables if table.id not in busy_table_ids)

    def busy_table_ids(self, *, start_time: str, end_time: str) -> set[str]:
        start = parse_iso(start_time)
        end = parse_iso(end_time)
        busy: set[str] = set()
        for reservation in self.reservations:
            if not ranges_overlap(start, end, parse_iso(reservation.reservation_time), parse_iso(reservation.ends_at)):
                continue
            if not reservation.table_ids:
                busy.update(table.id for table in self.tables)
                continue
            busy.update(reservation.table_ids)
        return busy

    def candidate_table_groups(self) -> list[tuple[RestaurantTableRecord, ...]]:
        groups = [(table,) for table in self.tables]
        combinable_by_zone: dict[str, list[RestaurantTableRecord]] = {}
        for table in self.tables:
            if table.can_combine:
                combinable_by_zone.setdefault(table.zone, []).append(table)

        for zone_tables in combinable_by_zone.values():
            for size in range(2, min(4, len(zone_tables)) + 1):
                groups.extend(combinations(zone_tables, size))
        return groups


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def ranges_overlap(first_start: datetime, first_end: datetime, second_start: datetime, second_end: datetime) -> bool:
    return first_start < second_end and second_start < first_end
