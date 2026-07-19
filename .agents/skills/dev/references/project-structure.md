# Winvest Project Structure Reference

Full directory layout with per-file responsibilities.
Based on [Hybridhash/FastAPI-HTMX](https://github.com/Hybridhash/FastAPI-HTMX) conventions,
adapted for the Winvest stack (Turso instead of PostgreSQL, no auth layer).

## Top-Level Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app instance, lifespan hook, router registration |
| `db.py` | Turso engine creation, `get_session()` dependency |
| `models.py` | SQLModel table definitions (ORM + schema in one class) |
| `requirements.txt` | Python dependencies |
| `.env` | Secret credentials (never commit) |

## `main.py` Conventions

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from db import create_db_and_tables
from routes.views import dashboard_router
from routes.api import rs_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()  # Idempotent — safe to call on every start
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(dashboard_router)   # Full-page views
app.include_router(rs_router, prefix="/api")  # HTMX partial endpoints
```

## Directory Tree

```
winvest/
│
├── main.py
├── db.py
├── models.py
├── requirements.txt
├── .env
│
├── routes/
│   ├── __init__.py
│   ├── views/                    # Full-page GET routes
│   │   ├── __init__.py
│   │   └── dashboard.py          # GET /  → pages/dashboard.html
│   └── api/                      # HTMX action routes (partials)
│       ├── __init__.py
│       └── rs.py                 # GET /api/rs-table → partials/rs_table.html
│
├── templates/
│   ├── base.html                 # Master layout: <head>, nav, CDN scripts, {% block content %}
│   ├── pages/                    # Full-page templates ({% extends "base.html" %})
│   │   └── dashboard.html
│   └── partials/                 # HTMX fragment templates (no <html>/<body>)
│       └── rs_table.html
│
└── static/
    ├── css/
    │   └── custom.css            # Minimal overrides (prefer Tailwind utilities)
    └── js/
        └── custom.js             # Minimal scripts (prefer Alpine.js)
```

## Template Hierarchy

```
base.html               ← CDN scripts, nav, {% block content %}
  └── pages/dashboard.html   ← {% extends "base.html" %}, fills {% block content %}
        └── triggers HTMX → partials/rs_table.html  ← standalone fragment
```

## Route Naming Conventions

| Pattern | Route | Returns |
|---|---|---|
| Page view | `GET /dashboard` | Full TemplateResponse (pages/dashboard.html) |
| HTMX list | `GET /api/rs-table` | Partial TemplateResponse (partials/rs_table.html) |
| HTMX action | `POST /api/item` | Partial TemplateResponse or HTMLResponse |
| HTMX delete | `DELETE /api/item/{id}` | Empty `200 OK` (HTMX removes the element) |

## models.py Conventions

Use SQLModel with `table=True` — combines SQLAlchemy ORM and Pydantic schema in one class:

```python
from typing import Optional
from sqlmodel import Field, SQLModel

class StockRS(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: str = Field(index=True)       # Store as ISO string: "2025-01-15"
    code: str = Field(index=True)
    name: str
    market: str
    rs: float
    rs_1m: float
    rs_3m: float
    rs_6m: float
    rs_12m: float
```

## db.py Conventions

```python
import os
from dotenv import load_dotenv
from sqlmodel import SQLModel, create_engine, Session
import models  # Must import to register table metadata

load_dotenv()

turso_url = os.getenv("TURSO_DATABASE_URL")   # libsql://...
turso_token = os.getenv("TURSO_AUTH_TOKEN")

engine = create_engine(
    f"sqlite+{turso_url}/?secure=true",
    connect_args={"check_same_thread": False, "auth_token": turso_token},
)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
```

## Partial Template Pattern

Partials are plain HTML fragments with no surrounding document structure:

```html
{# templates/partials/rs_table.html #}
{% if not stocks %}
<p class="text-gray-400">No data available.</p>
{% else %}
<table class="w-full text-sm">
  <thead>...</thead>
  <tbody id="rs-table-body">
    {% for stock in stocks %}
    <tr>
      <td>{{ stock.name }}</td>
      <td>{{ "%.2f"|format(stock.rs) }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endif %}
```

## base.html Pattern

```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>{% block title %}Winvest{% endblock %}</title>
  <!-- Tailwind CSS -->
  <script src="https://cdn.tailwindcss.com"></script>
  <!-- HTMX -->
  <script src="https://unpkg.com/htmx.org@2.0.2"></script>
  <!-- Alpine.js -->
  <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
</head>
<body>
  <nav>...</nav>
  <main>
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```
