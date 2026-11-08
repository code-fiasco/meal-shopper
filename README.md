# Meal Shopper

Self-hosted meal planner and shopping app for a two-person household. Recipes and ingredients keep shop-specific pack prices, the planner covers lunch and dinner, the shopping list accounts for pantry stock, and spending records what was actually paid.

Product behaviour is specified in [docs/spec.md](docs/spec.md). Acceptance checks are in [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md).

## Install

Requirements: Docker, on a Linux host.

```bash
git clone git@github.com:code-fiasco/meal-shopper.git
cd meal-shopper
cp .env.example .env
docker compose up --build -d --wait
```

Open http://127.0.0.1:5373/ on this machine. The published port is bound to localhost only.

```bash
curl -fsS http://127.0.0.1:5373/health
```

The response is `{"status":"ok"}`.

## Configuration

Copy `.env.example` to `.env` to override the defaults. Do not commit `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `APP_PORT` | `5373` | Port inside the container, and the localhost port on the host |
| `DATABASE_URL` | `sqlite:////data/app.db` | Database file. `/data` is the `./data` mount |
| `APP_TIMEZONE` | `Europe/London` | Application timezone. Wins over `TZ` when both are set |
| `TZ` | `Europe/London` | Accepted as the timezone, and sets the container clock |
| `APP_ENV` | `production` in Compose | Runtime environment name |
| `APP_AUTH_USER` | unset | Optional Basic auth username. Set together with the password |
| `APP_AUTH_PASSWORD` | unset | Optional Basic auth password |

Leave both auth variables unset and the app runs open. Set both and every page asks for those credentials. `/health` stays open so the container health check can run. There is no registration and no user account store. A username without a password, or the other way around, stops the app from starting.

## Security

This app is for one household. It has no public registration.

Run it behind Cloudflare Access, reached through a Cloudflare Tunnel whose `cloudflared` connector runs on this same host. The Compose file publishes the port on `127.0.0.1` only, so the tunnel is the path in. Do not bind `0.0.0.0`, do not forward the port from the router, and do not expose it to the internet any other way.

The app does not call out to other services. Fonts, HTMX, and Chart.js are in the image.

## Upgrade

From the project directory:

```bash
git pull
docker compose up --build -d --wait
```

The container applies database migrations on startup (`alembic upgrade head`) before it serves pages. `./data` is left in place. Confirm the stamp after an upgrade:

```bash
python -c "import sqlite3; print(sqlite3.connect('data/app.db').execute('select version_num from alembic_version').fetchone())"
```

A current database prints `('0008_integrity',)`.

## Backup and restore

Backups use SQLite's online backup API, not a copy of the live file.

Download a copy from **Settings → Download backup**. The same file is written to `data/backups/`.

From the host, while the container is running:

```bash
docker compose exec web python -m app.cli backup
```

That prints a path such as `/data/backups/meal-shopper-20261108-184500.db`, which is `data/backups/` on the host.

Restore only while the app is stopped, so nothing writes the old file during the replace:

```bash
docker compose stop
docker compose run --rm --no-deps --entrypoint python web \
  -m app.cli restore /data/backups/meal-shopper-20261108-184500.db
docker compose up -d --wait
```

Use the backup filename you actually have. The restore copies that file onto `/data/app.db` with the same backup API and removes leftover `-wal` and `-shm` files.

## Demo data

This is optional and does not run on startup. It adds a few ingredients, two meals, and the current week's plan. A second run does nothing if Tomato pasta is already there.

```bash
docker compose exec web python -m app.cli seed
```

## Tests

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest
```

GitHub Actions runs those three commands on every push and pull request. The meal-plan PDF needs the DejaVu fonts (`fonts-dejavu-core`).

## Troubleshooting

- **The browser cannot connect.** The port is `127.0.0.1:5373`, not port 8000, and it is not published on the LAN. Use the machine itself, or the Cloudflare Tunnel.
- **The health check is ok but pages ask for a password.** `APP_AUTH_USER` and `APP_AUTH_PASSWORD` are set. Use those credentials, or unset both and recreate the container.
- **The container exits straight away and mentions auth.** One of the auth variables is set and the other is empty. Set both, or neither.
- **Upgrade fails during migration.** Leave `./data` as it is and restore the latest file from `data/backups/` with the commands above. Do not delete `data/app.db` first.
- **A backup file will not open.** Take a new one from Settings or `python -m app.cli backup`. Do not copy `data/app.db` while the container is running.
- **Demo data did not appear.** The command reports that it is already present when a meal named Tomato pasta exists.
