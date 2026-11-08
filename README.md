# Meal Shopper

Self-hosted meal planner and shopping app for a two-person household. It keeps a recipe and ingredient library with shop-specific pack prices, plans lunch and dinner across weeks, builds a shopping list that accounts for pantry stock, and records what was actually spent.

Product behaviour is specified in [docs/spec.md](docs/spec.md) (SRS v1.0).

## Stack

- Python 3.12
- FastAPI
- SQLAlchemy 2.x (typed declarative)
- Alembic
- SQLite
- Jinja2 templates and HTMX 2.0.4 (vendored at `app/static/htmx.min.js`, no CDN)
- pytest
- Docker on a Linux server

## Status

Ingredients and shops are usable:

- Create and edit an ingredient with a canonical unit, notes, and a duplicate-name warning that can be overridden
- Search the ingredient list and filter active or archived records
- Archive an ingredient instead of deleting it
- Record several purchase options per ingredient (shop, pack quantity, pack label, price) and compare the price per canonical unit
- Keep price history when a pack price or quantity changes
- Add, rename, and archive shops
- Create and edit two-portion meals, including an inline new ingredient that stays on the recipe
- Estimate a meal's ingredient cost, and say which ingredients have no price

The planner, shopping, stock, and spending are not built yet. The container still serves navigation and a health check, and the SQLite database lives on a host mount.

## Configuration

Copy the example environment file if you want to override the defaults:

```bash
cp .env.example .env
```

| Variable | Default | Purpose |
|---|---|---|
| `APP_PORT` | `8000` | Host port and the port uvicorn listens on inside the container |
| `DATABASE_URL` | `sqlite:////data/app.db` | Database file. `/data` is the mounted volume |
| `APP_TIMEZONE` | `Europe/London` | Application timezone. Wins over `TZ` when both are set |
| `TZ` | `Europe/London` | Accepted as the timezone, and sets the container clock |
| `APP_ENV` | `production` in Compose, `development` in code | Runtime environment name |

Do not commit `.env`. The database file and the `data/` directory stay on the host and are gitignored.

## Run with Docker

Build the image and start the app in the background:

```bash
docker compose up --build -d --wait
```

Open `http://127.0.0.1:8000/` on this machine, or `http://<server>:8000/` from another device on the LAN. Check the process with:

```bash
curl -fsS http://127.0.0.1:8000/health
```

The response is `{"status":"ok"}`.

The published port is reachable on the host's network interfaces. Do not forward it from your router to the public internet; the app has no authentication.

Stop the container, leaving the database file in place:

```bash
docker compose stop
```

Start it again:

```bash
docker compose start
```

Recreate the container after a code change, or to confirm persistence (SRS FR-20):

```bash
docker compose down
docker compose up --build -d --wait
```

`docker compose down` removes the container and keeps `./data`. The database file is `./data/app.db`.

Confirm the file is still there and still has the migration stamp:

```bash
test -f data/app.db && python -c "import sqlite3; print(sqlite3.connect('data/app.db').execute('select version_num from alembic_version').fetchone())"
```

A surviving database prints `('0003_meals',)`.

To back up, stop the container and copy `data/app.db`. Copy that file back to restore. Start the container only after the copy finishes.

## Tests

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
```
