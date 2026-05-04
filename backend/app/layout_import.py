from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .storage import ReservationStore, RestaurantTableRecord


VALID_IMPORT_MODES = {"upsert", "replace"}


@dataclass(frozen=True)
class TableSpec:
    id: str
    name: str
    capacity: int
    zone: str = "Dining Room"
    x: float = 0
    y: float = 0
    can_combine: bool = True
    is_active: bool = True


@dataclass(frozen=True)
class LayoutImportPlan:
    mode: str
    dry_run: bool
    tables: tuple[TableSpec, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class LayoutImportResult:
    mode: str
    dry_run: bool
    imported_tables: int
    active_tables_after_import: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


class LayoutProvider(Protocol):
    def load_tables(self) -> list[TableSpec]:
        ...


class StaticLayoutProvider:
    def __init__(self, tables: list[TableSpec]) -> None:
        self.tables = tables

    def load_tables(self) -> list[TableSpec]:
        return self.tables


class LayoutImportService:
    def __init__(self, store: ReservationStore) -> None:
        self.store = store

    def plan_import(self, *, provider: LayoutProvider, mode: str, dry_run: bool) -> LayoutImportPlan:
        specs = tuple(provider.load_tables())
        errors, warnings = validate_table_specs(specs, mode=mode)
        return LayoutImportPlan(
            mode=mode,
            dry_run=dry_run,
            tables=specs,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def import_layout(self, *, provider: LayoutProvider, mode: str = "upsert", dry_run: bool = False) -> LayoutImportResult:
        plan = self.plan_import(provider=provider, mode=mode, dry_run=dry_run)
        protection_errors = self.active_assignment_conflicts(plan.tables, mode=mode)
        errors = (*plan.errors, *protection_errors)
        if errors or dry_run:
            return LayoutImportResult(
                mode=plan.mode,
                dry_run=plan.dry_run,
                imported_tables=0,
                active_tables_after_import=len(self.store.list_tables()),
                errors=errors,
                warnings=plan.warnings,
            )

        self.store.import_tables(plan.tables, replace=(mode == "replace"))
        return LayoutImportResult(
            mode=plan.mode,
            dry_run=plan.dry_run,
            imported_tables=len(plan.tables),
            active_tables_after_import=len(self.store.list_tables()),
            errors=(),
            warnings=plan.warnings,
        )

    def active_assignment_conflicts(self, tables: tuple[TableSpec, ...], *, mode: str) -> tuple[str, ...]:
        existing_assignments = self.store.active_assignment_table_ids()
        incoming_by_id = {table.id: table for table in tables}
        active_incoming_ids = {table.id for table in tables if table.is_active}
        errors: list[str] = []

        incoming_inactive_assigned_ids = {
            table_id
            for table_id in existing_assignments
            if table_id in incoming_by_id and not incoming_by_id[table_id].is_active
        }
        if incoming_inactive_assigned_ids:
            errors.append(
                "import would deactivate tables with active reservations: "
                + ", ".join(sorted(incoming_inactive_assigned_ids))
            )

        if mode == "replace":
            missing_assigned_ids = existing_assignments - active_incoming_ids
            if missing_assigned_ids:
                errors.append(
                    "replace would deactivate tables with active reservations: "
                    + ", ".join(sorted(missing_assigned_ids))
                )
        return tuple(errors)


def validate_table_specs(tables: tuple[TableSpec, ...], *, mode: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if mode not in VALID_IMPORT_MODES:
        errors.append(f"mode must be one of {sorted(VALID_IMPORT_MODES)}")
    if not tables:
        errors.append("at least one table is required")

    seen_ids: set[str] = set()
    seen_names: set[tuple[str, str]] = set()
    for index, table in enumerate(tables, start=1):
        prefix = f"tables[{index}]"
        if not table.id.strip():
            errors.append(f"{prefix}.id is required")
        elif table.id in seen_ids:
            errors.append(f"{prefix}.id duplicates {table.id}")
        seen_ids.add(table.id)

        if not table.name.strip():
            errors.append(f"{prefix}.name is required")
        if table.capacity <= 0:
            errors.append(f"{prefix}.capacity must be greater than zero")
        if not table.zone.strip():
            errors.append(f"{prefix}.zone is required")

        name_key = (table.zone.strip().lower(), table.name.strip().lower())
        if name_key in seen_names:
            warnings.append(f"{prefix}.name duplicates another table name in zone {table.zone}")
        seen_names.add(name_key)

    if tables and not any(table.can_combine for table in tables):
        warnings.append("no tables are marked combinable; large parties may be rejected")
    return errors, warnings


def table_to_dict(table: RestaurantTableRecord) -> dict[str, object]:
    return {
        "id": table.id,
        "name": table.name,
        "capacity": table.capacity,
        "zone": table.zone,
        "x": table.x,
        "y": table.y,
        "can_combine": table.can_combine,
        "is_active": table.is_active,
    }
