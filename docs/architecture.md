# Architecture

## System Boundary

The backend is the source of truth for reservations and table inventory. Online clients and phone-agent workflows both call the same `ReservationService`, which normalizes reservation times, asks the table planner for a feasible assignment, persists records, and exposes availability from the same SQLite database.

## Backend

- `app/main.py`: FastAPI entrypoint and HTTP schemas.
- `app/reservations.py`: booking rules, slot normalization, capacity enforcement, and status transitions.
- `app/inventory.py`: table assignment planner for overlapping reservation intervals and combinable tables.
- `app/layout_import.py`: plugin boundary for loading table layout data from first-party or future external providers.
- `app/storage.py`: SQLite storage adapter.
- `app/llm_agent.py`: phone-agent orchestration, OpenAI parser, and deterministic fallback parser.

## Mobile

The Expo app exposes four operational surfaces on the first screen:

- availability slots
- online reservation form
- AI call-agent turn simulator
- reservation list for the selected day

## Synchronization Model

Synchronization is handled by centralizing writes in the backend. There is no separate mobile-side or phone-side reservation store. Overbooking prevention happens immediately before persistence by checking active table assignments for the requested time interval.

For a production deployment, the SQLite adapter can be replaced with Postgres while keeping the `ReservationService` interface stable. The create path should then use a database transaction with row-level locks or a per-slot inventory table.

## Layout Import Boundary

Layout providers implement `LayoutProvider.load_tables()` and return table specs. The current API accepts JSON table specs through `POST /inventory/import` with `dry_run`, `upsert`, and `replace` modes. Replace mode deactivates missing tables instead of deleting them, and rejects changes that would deactivate a table assigned to an active reservation.
