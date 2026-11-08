# Meal Shopper

Self-hosted meal planner and shopping app for a two-person household. It keeps a recipe and ingredient library with shop-specific pack prices, plans lunch and dinner across weeks, builds a shopping list that accounts for pantry stock, and records what was actually spent.

Product behaviour is specified in [docs/spec.md](docs/spec.md) (SRS v1.0).

## Stack

- Python 3.12
- FastAPI
- SQLAlchemy 2.x (typed declarative)
- Alembic
- SQLite
- Jinja2 templates and HTMX
- pytest
- Docker on a Linux server

## Status

Repository skeleton only. Application code has not been written yet.

## Data

The SQLite database and anything under `data/` live on the host, mounted into the container. Do not commit `.env`, database files, or the `data/` directory.
