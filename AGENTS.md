# AGENTS.md

> **README for AI Coding Agents** — This file provides the architectural context, directory structure, conventions, commands, and refactoring roadmap required to work effectively on the **Winvest (`stockspace`)** repository.

---

## 1. Project Overview & Architectural Standard

**Winvest (`stockspace`)** is a Korean stock market analytics web platform and automated quantitative data pipeline.
- **Web Application (SSR Hypermedia)**: Serves daily market health signals (KOSPI/KOSDAQ) and Relative Strength (RS) stock rankings using **FastAPI + Jinja2 + HTMX + Alpine.js + Tailwind CSS v4 + DaisyUI v5**.
- **Analytics & Storage Layer**: Uses **Tinybird (ClickHouse)** for sub-second analytical queries (`tinybird/`) and **Supabase PostgreSQL + SQLModel** (`db.py`, `models.py`) for relational persistence.
- **Automated Data Pipelines & Quant Strategies**: GitHub Actions workflows (`.github/workflows/`) and batch scripts (`scripts/`) ingest daily KRX stock/index data, compute technical indicators (RS, MA, RSI, ADX), and execute quantitative strategies.

### Primary Reference Architecture: [`fastapi/full-stack-fastapi-template`](https://github.com/fastapi/full-stack-fastapi-template) (Adapted for SSR)

This repository standardizes on the backend architecture of **[`fastapi/full-stack-fastapi-template`](https://github.com/fastapi/full-stack-fastapi-template) (★ 46k+, Official FastAPI Template by `tiangolo`)**, adapted for a **Server-Side Rendered (SSR) Hypermedia (HTMX + Alpine.js)** stack:

1. **Why We Do NOT Split Top-Level `frontend/` and `backend/` Directories**:
   - In `full-stack-fastapi-template`, `frontend/` is separated because it is a standalone React/Vite SPA with its own Node.js build pipeline and container communicating via JSON REST APIs.
   - In **FastAPI + Jinja2 + HTMX + Alpine.js (CDN)**, there is no separate Node.js build server or JSON API boundary—FastAPI routes directly render and return HTML templates and HTMX partials (`TemplateResponse`).
   - Just as `full-stack-fastapi-template` places server-rendered templates (`email-templates/`) **inside** `backend/app/`, an SSR HTMX application keeps `templates/` and `static/` **co-located inside the Python application package (`app/`)** to preserve Locality of Behavior (LoB) and simplify serverless deployment (`@vercel/python`).
2. **Core Layered Structure (from `full-stack-fastapi-template`)**:
   - **`app/core/`**: Global configuration (`config.py`) and database engine initialization (`db.py`).
   - **`app/models.py`**: Unified SQLModel database tables and Pydantic schemas.
   - **`app/crud/`**: Data access and domain business logic (Tinybird & PostgreSQL queries, indicator formatting). Routes never contain raw queries or heavy data transformation.
   - **`app/api/`**: Centralized router registration (`api/main.py`), shared dependencies (`api/deps.py` using `Annotated`), and endpoint modules (`api/routes/`).
   - **`app/templates/` & `app/static/`**: Jinja2 layout (`base.html`), full-page views (`pages/`), and HTMX partial fragments (`partials/`).

---

## 2. Tech Stack & Non-Negotiable Constraints

| Layer | Technology | Notes |
|---|---|---|
| **Backend Framework** | FastAPI (Python 3.13) | App entrypoint (`app/main.py` / `main.py`) |
| **Server Templates** | Jinja2 | `templates/base.html`, `pages/`, `partials/` |
| **Hypermedia (Server UI)** | HTMX | Partial HTML swapping via `/api/*` endpoints |
| **Client-Side State** | Alpine.js 3.x | Strictly for browser-local UI state (drawers, dropdowns, filter chips, theme) |
| **Styling & UI Components** | Tailwind CSS v4 (Browser CDN) + DaisyUI v5 | Zero-build CDN setup in `templates/base.html` |
| **Analytical Data Engine** | Tinybird (`tinybird-sdk` / ClickHouse) | Primary read engine for web dashboards (`tinybird/datasources/`, `tinybird/pipes/`) |
| **Relational DB & ORM** | Supabase PostgreSQL + SQLModel | Configured via `DATABASE_URL` |
| **Deployment & Edge Caching** | Vercel (`@vercel/python`) / Cloudflare | Uses `Cache-Control: public, s-maxage=..., stale-while-revalidate=...` |

### Non-Negotiable Rules
- **No SPA Frameworks or Separate Frontend Build Server**: Do not introduce React, Vue, Next.js, Vite, or a separate `frontend/` SPA directory.
- **HTML Over the Wire**: Web endpoints targeted by HTMX must return rendered **HTML partials** (`TemplateResponse`), never raw JSON for client-side template rendering.
- **Alpine.js Boundary**: Never use `fetch()` or `axios` inside Alpine.js to load server data—server communication belongs to HTMX. Use Alpine.js exclusively for instant client-side interactions (drawer state, filter chip toggles, theme switching, client-side table sorting/filtering of already-loaded rows).
- **Secrets Management**: Never hardcode credentials or tokens. Load all secrets (`DATABASE_URL`, `TINYBIRD_TOKEN`, `TINYBIRD_API_URL`) via environment variables / `.env`.

---

## 3. Directory Structure (`full-stack-fastapi-template` SSR Layout)

```text
winvest/
├── app/                             # Main Web Application Package
│   ├── main.py                      # FastAPI app entrypoint, StaticFiles mount, api_router include
│   ├── models.py                    # SQLModel table & schema definitions
│   ├── core/                        # Global configuration (config.py) & DB initialization (db.py)
│   ├── crud/                        # Data access & domain business logic (Thin Routers, Fat CRUD)
│   ├── api/                         # HTTP Routing & Dependency Injection
│   │   ├── main.py                  # Aggregates all route modules into a single api_router
│   │   ├── deps.py                  # Shared Annotated dependencies (SessionDep, templates)
│   │   └── routes/                  # Modular route handlers (views & HTMX partial endpoints)
│   ├── templates/                   # Jinja2 SSR Templates
│   │   ├── base.html                # Master layout (Tailwind v4 + DaisyUI v5 + HTMX + Alpine CDNs)
│   │   ├── pages/                   # Full-page shells ({% extends "base.html" %})
│   │   └── partials/                # Pure HTMX HTML fragments (NO <html>, <head>, or <body> tags)
│   └── static/                      # Static assets
├── tinybird/                        # Tinybird Python SDK (client.py, datasources/, pipes/)
├── scripts/                         # Standalone KRX data ingestion, backfilling & quant scripts
├── tasks/                           # Living Product Requirements Documents (prd-*.md)
└── .github/workflows/               # Scheduled GitHub Actions for daily ingestion & trading bots
```

---

## 4. Setup & Development Commands

### Environment Setup
```bash
# Activate virtual environment
source .venv/bin/activate

# Install web server dependencies (lightweight, used by Vercel)
pip install -r requirements.txt

# Install full dependencies including data ingestion & quant libraries
pip install -r requirements-scripts.txt
```

### Running the Web Server
```bash
# Development server with auto-reload (FastAPI CLI)
fastapi dev app/main.py

# Or via Uvicorn directly
uvicorn app.main:app --reload --port 8000
```

### Database & Data Pipeline Operations
```bash
# Initialize / verify Supabase PostgreSQL tables
python -m app.core.db

# Run daily KRX data ingestion pipelines locally (optional --date YYYY-MM-DD)
python scripts/ingest_daily_krx_indices.py
python scripts/ingest_daily_krx_stocks.py
python scripts/ingest_daily_krx_adjusted_stocks.py
```

---

## 5. Core Architectural & Coding Guidelines

### 5.1 FastAPI Routing & Layer Separation (`api/routes/` vs `crud/`)
- **Centralized Router Registration (`app/api/main.py`)**:
  Following `full-stack-fastapi-template`, declare `prefix` and `tags` on each sub-router in `app/api/routes/` and aggregate them into `api_router` in `app/api/main.py`.
- **Annotated Dependencies (`app/api/deps.py`)**:
  Define reusable `Annotated` type aliases in `app/api/deps.py` (e.g., `SessionDep = Annotated[Session, Depends(get_session)]`) instead of repeating `Depends(...)` across route signatures.
- **Thin Routers, Fat CRUD**:
  Route handlers in `app/api/routes/` must only parse HTTP parameters, invoke domain functions from `app/crud/`, and return `templates.TemplateResponse(..., headers=...)`. Move all data queries and business transformations into `app/crud/`.
- **`def` vs `async def`**:
  - Declare endpoints that call synchronous/blocking I/O (`tinybird.pipes.*.query()`, SQLModel `Session`) using standard `def`, **not** `async def`. FastAPI runs standard `def` endpoints in a threadpool to prevent blocking the event loop.
  - Use `async def` only for non-blocking shell/redirect routes.
- **Edge Caching Pattern**:
  - Pass `headers={"Cache-Control": "public, s-maxage=..., stale-while-revalidate=..."}` directly to `templates.TemplateResponse(...)` so both shell pages and HTMX partial fragments are cached at the edge.

### 5.2 Hypermedia Template Pattern (`pages/` vs `partials/`)
- **App Shell + Lazy HTMX Partials**:
  - Full pages in `templates/pages/*.html` extend `base.html` and render the layout shell immediately.
  - Heavy data sections use `hx-get="/api/..." hx-trigger="load" hx-indicator="#loading"` to asynchronously swap in HTML fragments from `templates/partials/*.html`.
- **Partial Purity**:
  - Files in `templates/partials/` must be pure HTML fragments without `<!DOCTYPE html>`, `<html>`, `<head>`, or `<body>` tags.

### 5.3 UI/UX & Styling Standards (Tailwind v4 + DaisyUI v5 + Alpine.js)
- **DaisyUI v5 Semantic Classes**: Prefer DaisyUI components (`card`, `navbar`, `dock`, `drawer`, `badge`, `btn`, `table`, `loading-spinner`) and semantic theme tokens (`bg-base-100`, `bg-base-200`, `text-base-content`, `text-primary`, `badge-success`, `badge-error`) so Light and Dark modes work seamlessly.
- **Responsive Mobile-First Design**: Support both desktop (`navbar` top navigation, wide data tables) and mobile (`dock` bottom navigation bar, horizontal chip scrolling, responsive slide-over drawer).
- **High-Density Financial UI**: Use crisp typography (`Plus Jakarta Sans` & `JetBrains Mono`) and smooth micro-interactions (`x-transition`, `x-cloak`).

### 5.4 Data Pipeline & Pandas Conventions (`scripts/`)
- **Vectorized Operations Only**: Never use `df.iterrows()` when transforming KRX stock DataFrames. Use vectorized Pandas/NumPy operations and `df.to_dict(orient="records")` before bulk ingestion into Tinybird or PostgreSQL.

---

## 6. Workflow, Testing & Git Conventions

### PRD-First Development
- Feature specifications live in `tasks/prd-*.md` (e.g., `tasks/prd-market-dashboard.md`, `tasks/prd-rs-dashboard.md`, `tasks/prd-rs-drawer.md`).
- **Before implementing or modifying a feature**, read the corresponding PRD in `tasks/`. If building a major new feature without a PRD, use the `prd` skill to draft or update one first.
- Check off completed task items (`- [x]`) in the PRD as implementation progresses.

### Verification & Testing
- Verify web UI changes by running the local server and inspecting both desktop and mobile viewports (or using Playwright via the `webapp-testing` skill).
- Ensure both **Light** and **Dark** themes render with proper contrast (`data-theme="light"` / `data-theme="dark"`).
- Check browser console logs and network responses for HTMX swap errors (`htmx:afterSwap`, `htmx:responseError`).

### Git Branch, Commit & PR Rules
- **Branch Naming**: Follow the `conventional-branch` specification (`feature/<name>`, `bugfix/<name>`, `hotfix/<name>`, `chore/<name>`, `refactor/<name>`).
- **Commits**: Follow the `conventional-commit` specification (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`, `perf:`).
- **Pull Requests**: Follow the repository's PR standards via the `pr-creator` skill.

---

## 7. Specialized Agent Skills Reference (`.agents/skills/`)

When working on specific technical domains in this repository, read the corresponding skill's `SKILL.md` in `.agents/skills/`:

| Domain / Task | Skill Path |
|---|---|
| FastAPI conventions (`Annotated`, `Depends`, routers, `async` vs `def`) | `.agents/skills/fastapi/SKILL.md` |
| HTMX attributes, swap strategies, triggers, HTMX 2.x/4.0 updates | `.agents/skills/htmx/SKILL.md`, `.agents/skills/htmx-knowledge-patch/SKILL.md` |
| Alpine.js reactivity (`x-data`, `Alpine.data`, `$watch`, events) | `.agents/skills/alpine/SKILL.md` |
| DaisyUI v5 components, themes, semantic color system | `.agents/skills/daisyui/SKILL.md` |
| Tailwind CSS v4 browser runtime & `@theme` tokens | `.agents/skills/tailwind/SKILL.md` |
| Frontend aesthetics, UX accessibility, UI design system | `.agents/skills/frontend-design/SKILL.md`, `.agents/skills/web-design-guidelines/SKILL.md` |
| Tinybird datasources, SQL pipes, CLI (`tb`), and Python SDK | `.agents/skills/tinybird-best-practices/SKILL.md`, `.agents/skills/tinybird-python-sdk-guidelines/SKILL.md`, `.agents/skills/tinybird-cli-guidelines/SKILL.md` |
| ClickHouse SQL & schema optimization | `.agents/skills/clickhouse-best-practices/SKILL.md` |
| Supabase & PostgreSQL schema/query optimization | `.agents/skills/supabase/SKILL.md`, `.agents/skills/supabase-postgres-best-practices/SKILL.md` |
| PRD authoring & task tracking (`tasks/prd-*.md`) | `.agents/skills/prd/SKILL.md` |
| Playwright browser verification & E2E testing | `.agents/skills/webapp-testing/SKILL.md` |
| Git branches, commits, and PR creation | `.agents/skills/conventional-branch/SKILL.md`, `.agents/skills/conventional-commit/SKILL.md`, `.agents/skills/pr-creator/SKILL.md` |
