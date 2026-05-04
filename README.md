# Reservation System

Restaurant reservation system with a shared Python backend for online bookings and AI-assisted phone reservations, plus an Expo React Native front end.

## What is Included

- FastAPI backend with SQLite persistence.
- Shared reservation service for phone-agent and online reservations.
- Table-aware availability planner that assigns reservations to tables or combinable table groups for a full turn duration.
- LLM-backed call interaction endpoint with a deterministic parser fallback.
- Expo React Native app for availability, online bookings, reservation list, and call-agent simulation.
- Unit tests for the reservation consistency rules and agent parser.

## Local Setup

The local `.env` file is intentionally ignored by git. It should contain `OPENAI_API_KEY`, copied from the existing ERP system env file.

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Mobile app:

```bash
cd mobile
npm install
npm start
```

Set `EXPO_PUBLIC_API_BASE_URL` if the backend is not running on `http://localhost:8000`.

## API Summary

- `GET /health`
- `GET /availability?date=2026-05-10&party_size=2`
- `POST /reservations`
- `GET /reservations?date=2026-05-10`
- `PATCH /reservations/{reservation_id}/status`
- `POST /agent/call-turn`

The phone agent and online booking flows both create reservations through the same service, so they see the same table inventory, turn-duration, and capacity constraints.
