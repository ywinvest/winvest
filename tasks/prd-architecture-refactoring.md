# PRD: Architecture Refactoring (`full-stack-fastapi-template` SSR Standard)

## Document Status
- Status: Complete
- File Mode: Single
- Current Phase: Complete
- Last Updated: 2026-11-01
- PRD File: `tasks/prd-architecture-refactoring.md`
- Purpose: Living PRD and execution source of truth for refactoring the Winvest (`stockspace`) web application into the `app/` package structure modeled after `fastapi/full-stack-fastapi-template` (adapted for SSR HTMX + Alpine.js).

## Problem
Currently, the Winvest web application files (`main.py`, `db.py`, `models.py`, `routes/`, `crud/`, `templates/`, `static/`) are scattered at the repository root alongside standalone quantitative trading scripts (`woo1.py`, `woo2.py`, `daily_market_report.py`) and batch ingestion utilities (`scripts/`). In addition:
- Business logic and Tinybird queries for the Market dashboard are embedded directly inside the route handler (`routes/api/market.py`), violating separation of concerns.
- Template and static directory paths rely on relative working-directory strings (`"templates"`, `"static"`), which are fragile when entrypoints change.
- There is no centralized `core/config.py`, `api/deps.py`, or `api/main.py` router aggregator as standardized by `fastapi/full-stack-fastapi-template`.

## Goals
- **G-1**: Restructure the FastAPI web application into a cohesive `app/` package (`app/core/`, `app/models.py`, `app/crud/`, `app/api/`, `app/templates/`, `app/static/`) following `fastapi/full-stack-fastapi-template` adapted for SSR Hypermedia.
- **G-2**: Decouple business logic and Tinybird data fetching from HTTP route handlers (Thin Routers in `app/api/routes/`, Fat CRUD in `app/crud/`).
- **G-3**: Standardize FastAPI dependency injection (`app/api/deps.py` using `Annotated`) and centralized router registration (`app/api/main.py`).
- **G-4**: Preserve 100% compatibility with existing URLs (`/`, `/market`, `/rs`, `/api/market-status`, `/api/rs-table`, `/static/*`), Vercel deployment (`vercel.json`), and `scripts/` batch pipelines.

## Non-Goals
- **NG-1**: Splitting into a separate `frontend/` SPA directory or introducing a Node.js build step (we use SSR Jinja2 + HTMX + Alpine.js CDN).
- **NG-2**: Rewriting quantitative indicator calculation formulas in root `market.py` / `rs.py` used by GitHub Actions batch jobs.
- **NG-3**: Changing UI design, DaisyUI v5 / Tailwind v4 styling, or Tinybird SQL pipes.

## Success Criteria
- **SC-1**: All web application modules reside cleanly inside `app/` (`app/main.py`, `app/models.py`, `app/core/`, `app/crud/`, `app/api/`, `app/templates/`, `app/static/`), and legacy root folders (`routes/`, `crud/`, `templates/`, `static/`, `main.py`, `db.py`, `models.py`) are removed.
- **SC-2**: `app/api/routes/market.py` and `app/api/routes/rs.py` contain only HTTP request/response handling and cache headers, delegating data retrieval and formatting to `app/crud/market.py` and `app/crud/rs.py`.
- **SC-3**: All endpoints (`GET /`, `GET /market`, `GET /rs`, `GET /api/market-status`, `GET /api/rs-table`, `GET /static/stockspace_logo_transparent.png`) return expected status codes and rendered HTML/assets when tested against `app.main:app`.
- **SC-4**: Batch scripts in `scripts/` referencing SQLModel/DB imports are updated to `app.core.db` and `app.models` without syntax or import errors.

## Discovery Summary
- **Reviewed**: `main.py`, `db.py`, `models.py`, `routes/views/dashboard.py`, `routes/api/market.py`, `routes/api/rs.py`, `crud/rs.py`, `market.py`, `rs.py`, `vercel.json`, `scripts/*.py`, `.github/workflows/daily_update.yml`, `AGENTS.md`.
- **Current system**:
  - Web server uses `main.py` mounting `routes.views.dashboard`, `routes.api.rs`, and `routes.api.market`.
  - `routes/api/market.py` directly queries `tinybird` and formats market signals and Top 5 RS stocks, whereas `routes/api/rs.py` delegates to `crud/rs.py`.
  - Root `market.py` and `rs.py` are imported by `scripts/ingest_daily_krx_indices.py`, `scripts/ingest_daily_krx_adjusted_stocks.py`, `woo2.py`, and `daily_market_report.py`.
  - 9 legacy sync/migration scripts in `scripts/` import `from db import engine` and `from models import ...`.
- **Validation surface**: FastAPI `TestClient` / `uvicorn` HTTP endpoint verification, Python module import verification across `app/` and `scripts/`.
- **Design implications**: Keep root `market.py` and `rs.py` intact for batch/quant script compatibility while extracting web-specific market CRUD logic into `app/crud/market.py`. Use `pathlib.Path(__file__).resolve().parent` in `app/core/config.py` for resilient `templates/` and `static/` path resolution.

## Requirements
### Functional Requirements
- **FR-1**: Create `app/core/config.py` (centralized settings & directory paths) and `app/core/db.py` (PostgreSQL engine, `create_db_and_tables()`, `get_session()`).
- **FR-2**: Move `models.py` to `app/models.py` and update internal imports in `app/core/db.py` and `scripts/*.py`.
- **FR-3**: Create `app/crud/market.py` (moving `get_market_status`, `format_market_cap`, and `get_market_dashboard_data` out of the route layer) and move `crud/rs.py` to `app/crud/rs.py`.
- **FR-4**: Create `app/api/deps.py` with `SessionDep` (`Annotated[Session, Depends(get_session)]`) and shared `templates` (`Jinja2Templates`), `app/api/routes/{views,market,rs}.py`, and `app/api/main.py` (`api_router`).
- **FR-5**: Move `templates/` → `app/templates/` and `static/` → `app/static/`, and create `app/main.py` as the FastAPI entrypoint.
- **FR-6**: Update `vercel.json` to point to `app/main.py` and remove obsolete root web files (`main.py`, `db.py`, `models.py`, `routes/`, `crud/`, `templates/`, `static/`).

### Non-Functional Requirements
- **NFR-1**: Synchronous Tinybird/DB endpoints (`market.py`, `rs.py`) must use standard `def` (not `async def`) to run in FastAPI's threadpool without blocking the event loop.
- **NFR-2**: `Cache-Control` headers for Vercel Edge caching must be preserved on all page and partial routes.

## Assumptions
- **A-1**: Root `market.py` and `rs.py` remain at the repository root because they are pandas/pandas_ta utility modules imported by standalone scripts (`scripts/ingest_*.py`, `woo2.py`, `daily_market_report.py`).

---

## Phase Plan

### Phase 1: Core Infrastructure, Models & CRUD Layer (`app/core/`, `app/models.py`, `app/crud/`)
- **Objective**: Establish the `app/` package foundation, configuration, database engine, SQLModel definitions, and data access (`crud`) layer.

#### Phase Discovery Gate
- [x] Inspect `db.py`, `models.py`, `crud/rs.py`, `routes/api/market.py`, and `market.py`
- [x] Verify environment variables used across the app (`DATABASE_URL`, `TINYBIRD_TOKEN`, `TINYBIRD_API_URL`)

#### Implementation Checklist
- [x] Create `app/__init__.py` and `app/core/__init__.py`
- [x] Create `app/core/config.py` defining `APP_DIR`, `TEMPLATES_DIR`, `STATIC_DIR`, and environment variable settings
- [x] Create `app/models.py` (migrated from root `models.py`)
- [x] Create `app/core/db.py` (migrated from root `db.py`, importing `app.models` and `app.core.config`)
- [x] Create `app/crud/__init__.py` and migrate `crud/rs.py` to `app/crud/rs.py`
- [x] Create `app/crud/market.py` extracting `SIGNAL_MAP`, `get_market_status()`, `format_market_cap()`, and `get_market_dashboard_data()` from `routes/api/market.py`

#### Validation Checklist
- [x] Verify Python imports for `app.core.config`, `app.models`, `app.core.db`, `app.crud.rs`, and `app.crud.market`

---

### Phase 2: API Routing Layer, Templates & Entrypoint (`app/api/`, `app/templates/`, `app/static/`, `app/main.py`)
- **Objective**: Build the `full-stack-fastapi-template` routing structure (`api/deps.py`, `api/routes/`, `api/main.py`), co-locate `templates/` and `static/` inside `app/`, and wire up `app/main.py`.

#### Phase Discovery Gate
- [x] Inspect `routes/views/dashboard.py`, `routes/api/market.py`, `routes/api/rs.py`, `main.py`, and `vercel.json`

#### Implementation Checklist
- [x] Move `templates/` to `app/templates/` and `static/` to `app/static/`
- [x] Create `app/api/__init__.py` and `app/api/deps.py` providing `SessionDep` (`Annotated[Session, Depends(get_session)]`) and `templates` (`Jinja2Templates(directory=str(TEMPLATES_DIR))`)
- [x] Create `app/api/routes/__init__.py`
- [x] Create `app/api/routes/views.py` (`GET /`, `GET /market`, `GET /rs`)
- [x] Create `app/api/routes/market.py` (`GET /api/market-status` calling `app.crud.market.get_market_dashboard_data()`)
- [x] Create `app/api/routes/rs.py` (`GET /api/rs-table` calling `app.crud.rs.get_rs_table_data()`)
- [x] Create `app/api/main.py` aggregating `views.router`, `market.router`, and `rs.router` into `api_router`
- [x] Create `app/main.py` initializing `FastAPI`, mounting `/static`, and including `api_router`

#### Validation Checklist
- [x] Verify `app.main:app` imports cleanly and registers all expected routes

---

### Phase 3: Script Import Updates, Legacy Cleanup & End-to-End Verification
- **Objective**: Update `scripts/*.py` imports (`db` → `app.core.db`, `models` → `app.models`), update `vercel.json`, remove legacy root web files/directories, and verify all HTTP endpoints.

#### Phase Discovery Gate
- [x] Re-check all files matching `from db import` and `from models import` in `scripts/`

#### Implementation Checklist
- [x] Update `from db import engine` → `from app.core.db import engine` and `from models import ...` → `from app.models import ...` across `scripts/*.py`
- [x] Update `vercel.json` `builds[0].src` and `routes[0].dest` from `"main.py"` to `"app/main.py"`
- [x] Remove legacy root files and directories: `main.py`, `db.py`, `models.py`, `routes/`, `crud/`
- [x] Test all routes (`GET /`, `GET /market`, `GET /rs`, `GET /api/market-status`, `GET /api/rs-table`, `GET /static/stockspace_logo_transparent.png`) using FastAPI `TestClient` / local server

#### Validation Checklist
- [x] All HTTP endpoints return 200/307 with valid HTML partials/pages and `Cache-Control` headers
- [x] `python -m py_compile` succeeds on all `app/**/*.py` and `scripts/*.py` files

---

## Final Multi-Pass Review After All Phases
- [x] 1. Requirements coverage review: every FR, NFR, and success criterion is satisfied.
- [x] 2. Cross-phase integration review: `app/`, `tinybird/`, `scripts/`, and `vercel.json` work together without broken imports.
- [x] 3. Correctness review: full pages, HTMX partials, static files, and fallback states work as expected (also fixed `TemplateResponse` `headers=` propagation for `Cache-Control`).
- [x] 4. Simplicity/refactor review: thin routers, fat CRUD, zero unnecessary abstractions.
- [x] 5. Duplication/cleanup review: old `routes/`, `crud/`, `main.py`, `db.py`, `models.py` are cleanly removed.
- [x] 6. Security/privacy review: secrets loaded via environment variables only.
- [x] 7. Performance/load review: sync Tinybird/DB endpoints use `def` (threadpool) and Edge Cache headers.
- [x] 8. Validation review: HTTP endpoints and module compilation verified.
- [x] 9. Documentation/operability review: `AGENTS.md` matches the final structure.
- [x] 10. PRD closeout review: status is Complete and change log is updated.

## Change Log
- 2026-11-01: Initial PRD created for `full-stack-fastapi-template` SSR architecture refactoring.
- 2026-11-01: Completed Phases 1–3, verified all HTTP routes and static assets via `TestClient`, fixed `Cache-Control` header attachment on `TemplateResponse`, and closed out PRD.
