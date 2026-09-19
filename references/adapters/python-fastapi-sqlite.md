# Python + FastAPI + SQLite Adapter

Use this adapter when the project reality is Python backend, FastAPI service layer, and SQLite persistence.

## Architecture Defaults

- Backend entry: `app.main:app` or equivalent FastAPI application object.
- API style: RESTful JSON endpoints.
- Persistence: SQLite file database for MVP/local deployment.
- Validation: Pydantic models for request and response contracts.
- Soft delete: prefer `is_deleted` when deletion must be reversible.
- Audit fields: use `created_at` and `updated_at`; include actor fields when user identity exists.

## Validation Commands

- `python -m pytest`
- FastAPI startup check through `uvicorn` when available.

## Design Notes

- Do not force Java/Spring/PostgreSQL assumptions.
- Avoid long-lived global DB connections unless the project already has a safe pattern.
- Prefer parameterized queries or ORM-safe filters.
- Document SQLite concurrency and migration limits when relevant.

