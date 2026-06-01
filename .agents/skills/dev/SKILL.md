---
name: dev
description: Master development skill for the Winvest project. ALWAYS trigger this skill when the user asks to create, modify, debug, or review any feature, component, route, template, or code in the winvest repository. Covers the full tech stack (FastAPI + HTMX + Alpine.js + Jinja2 + Tailwind CSS + Turso/SQLModel), project structure conventions inspired by Hybridhash/FastAPI-HTMX, PRD-driven workflow, and Cloudflare deployment rules. Use even when the user says things like "add a page", "make a route", "fix the template", "update the DB", or "deploy this".
---

# Winvest Development Skill

Master guideline for the Winvest project. This skill handles **project-level decisions** (architecture, structure, conventions). For **technology-specific deep knowledge**, always delegate to the sub-skills listed in Section 6.

## 1. PRD-First Workflow

- **Living PRDs** live in `tasks/` (e.g., `tasks/prd-rs-dashboard.md`).
- **Before writing any code**, read the relevant PRD. If none exists, suggest creating one with `/prd`.
- Check off PRD checkboxes (`- [x]`) as you complete steps.
- Commit using the `conventional-commit` skill.

---

## 2. Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python 3.x) |
| Templates | Jinja2 |
| Interactivity | HTMX 2.x |
| Client-side state | Alpine.js |
| Styling | Tailwind CSS v4 (CDN, no build step) |
| Database | Turso via `sqlalchemy-libsql` + SQLModel |
| Deployment | Cloudflare Tunnels |

**Non-negotiable constraints:**
- No React, Vue, or other SPA frameworks.
- No Cloudflare R2 or flat JSON files for structured/time-series data — use Turso.
- Return **HTML partials** from HTMX endpoints, not JSON.
- DB credentials exclusively from `.env`: `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`.

---

## 3. Project Structure

Modeled after [Hybridhash/FastAPI-HTMX](https://github.com/Hybridhash/FastAPI-HTMX).
For full layout with per-file responsibilities → read `references/project-structure.md`.

```
winvest/
├── main.py              # App entry, lifespan, router registration
├── db.py                # Turso engine + get_session()
├── models.py            # SQLModel table definitions
├── routes/
│   ├── views/           # GET → full TemplateResponse (pages)
│   └── api/             # GET/POST/DELETE → HTML partials (HTMX targets)
├── templates/
│   ├── base.html        # Master layout (CDN scripts, nav, {% block content %})
│   ├── pages/           # Full pages ({% extends "base.html" %})
│   └── partials/        # HTMX fragments (no <html>/<body>)
└── tasks/               # PRD files (prd-*.md)
```

---

## 4. Core Architectural Patterns

### Route Split (Hybridhash convention)
Separate full-page views from HTMX action endpoints:

```python
# routes/views/dashboard.py — renders a full page
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "pages/dashboard.html")

# routes/api/rs.py — returns an HTMX-targetable partial
@router.get("/api/rs-table", response_class=HTMLResponse)
async def rs_table(request: Request, session: Session = Depends(get_session)):
    stocks = session.exec(select(StockRS).order_by(StockRS.rs.desc())).all()
    return templates.TemplateResponse(request, "partials/rs_table.html", {"stocks": stocks})
```

For FastAPI best practices (dependency injection, lifespan, error handling) → invoke `fastapi` skill.

### HTMX Partial Loading
```html
<!-- Trigger a partial load on page load, swap into target div -->
<div hx-get="/api/rs-table" hx-trigger="load" hx-target="#rs-container"
     hx-indicator="#loading">
  <div id="loading" class="htmx-indicator">Loading...</div>
</div>
<div id="rs-container"></div>
```

For HTMX swap modes, hx-boost, OOB swaps, HTMX 2.x changes → invoke `htmx` + `htmx-knowledge-patch` skills.

### Alpine.js Scope
Use Alpine **only** for browser-local UI state (dropdowns, modals, toggles). Never use it to fetch server data — that's HTMX's job.

```html
<!-- ✅ Alpine: local toggle -->
<div x-data="{ open: false }">
  <button @click="open = !open">Menu</button>
  <nav x-show="open" x-transition>...</nav>
</div>

<!-- ❌ Wrong: using Alpine to fetch from server — use HTMX instead -->
```

For Alpine directives, `x-data`, `x-model`, stores → invoke `alpine` skill.

### Tailwind Styling
Load via CDN, no build step:
```html
<script src="https://cdn.tailwindcss.com"></script>
```
For v4 CSS-first tokens, v3 vs v4 syntax differences, theme customization → invoke `tailwind` skill.

### DataFrame → SQLModel (Bulk Insert Pattern)
Avoid `iterrows()` — use vectorized conversion:
```python
df_db = df.rename(columns={"OldCol": "model_field"}).copy()
df_db["date"] = today_str
df_db = df_db.fillna(0.0)
records = df_db.to_dict(orient="records")
objects = [MyModel(**r) for r in records]
with Session(engine) as session:
    session.add_all(objects)
    session.commit()
```

### Turso DB Connection (Critical — Known Gotcha)
`sqlalchemy-libsql` requires `auth_token` in `connect_args`, **not** in the URL:
```python
engine = create_engine(
    f"sqlite+{turso_url}/?secure=true",   # turso_url starts with libsql://
    connect_args={"check_same_thread": False, "auth_token": turso_token},
)
```
Embedding `authToken=...` in the URL causes 401 Unauthorized. For advanced Turso queries, CDC, vector search → invoke `turso-db` skill.

---

## 5. Template Hierarchy

```
base.html
  └── pages/*.html          ({% extends "base.html" %}, fills {% block content %})
        └── HTMX triggers → partials/*.html   (standalone fragments)
```

Partials must be **self-contained HTML fragments** with no `<html>` or `<body>` tags.

---

## 6. UI/UX & Design Philosophy

When building frontends, you must produce **premium, modern, and distinctive** interfaces:
- **Avoid Generic "AI Slop"**: Do not use default/generic layouts. Pick a bold aesthetic direction (e.g., Glassmorphism, Brutalism, Minimalist Luxury, Neumorphism) and commit to it.
- **Premium Dashboards**: For data-heavy product UI (like the RS Dashboard), focus on high information density, clear visual hierarchy, perfect spacing, and subtle micro-animations (using Tailwind + Alpine).
- **Accessibility & Performance**: Ensure WCAG compliance (contrast ratios, ARIA labels), logical heading structures, and fast HTML partial rendering via HTMX.
- **Design Intelligence**: For exact color palettes, typography pairings, and layout structures, you must query the local database via `python3 .agents/skills/ui-ux-pro-max-skill/src/ui-ux-pro-max/scripts/search.py` (provided by the `ui-ux-pro-max-skill`).

---

## 7. Sub-Skill Delegation

When you need deep, technology-specific knowledge, invoke these skills explicitly:

| Need | Skill to invoke |
|---|---|
| FastAPI routing, lifespan, Depends, error handling | `fastapi` |
| HTMX attributes, swap modes, triggers | `htmx` |
| HTMX 2.x / 4.0 breaking changes & new features | `htmx-knowledge-patch` |
| Tailwind v4 utilities, theme tokens, v3→v4 migration | `tailwind` |
| Alpine.js directives, stores, magic helpers | `alpine` |
| Turso queries, migrations, vector/full-text search | `turso-db` |
| Cloudflare Tunnels, D1, R2, Workers | `cloudflare` |
| Browser testing the local web app (Playwright) | `webapp-testing` |
| Bold aesthetic direction, premium UI styling, typography | `frontend-design` |
| Web UI component architecture, accessibility (A11y), performance | `web-design-guidelines` |
| Design database CLI for color palettes, font pairings, styles | `ui-ux-pro-max-skill` |

---

## References

- `references/project-structure.md` — Full directory tree, per-file conventions, code templates
