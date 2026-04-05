# Weather Station 4 Project Handbook

Version: 1.0  
Audience: product owner, developers, operators, and support  
Scope: complete project context in one place

---

## 1) Product Goals

### Mission
Build a reliable personal weather station platform that turns raw station telemetry into useful, local, real-time weather intelligence.

### Primary Goals
- Continuously ingest weather observations every 15 minutes.
- Serve a live dashboard with recent conditions and trends.
- Provide short-horizon local rain prediction with transparent factors.
- Send practical rain alerts to Telegram with low noise.
- Keep operations simple enough for a small team to run on Dokploy/VPS.

### Success Criteria
- New observation persisted at least every 15 minutes.
- Dashboard reflects latest data and historical trends.
- API endpoints return data within expected latency.
- Rain alerts are sent only on meaningful state transitions.
- Recovery from deployment/restart is straightforward.

### Non-Goals (for now)
- Complex ML pipelines and model training infrastructure.
- Multi-tenant account management.
- Full alerting rules engine with arbitrary user-defined conditions.

---

## 2) System Overview

### High-level Architecture
- Data Source: Weather Underground PWS current observation API.
- Ingestion Worker: `pws_fetcher.py` (scheduled every 15 minutes).
- Database: PostgreSQL table `pws_observations`.
- API Server: FastAPI app in `app/main.py`.
- Prediction Engine: heuristic scorer in `app/rain_predictor.py`.
- Frontend: Jinja + dashboard template (`templates/dashboard.html`).
- Notifications: Telegram Bot API from ingestion process.

### Data Flow
1. Scheduler triggers `pws_fetcher.py` every 15 minutes.
2. Script fetches current station observation from WU API.
3. Script inserts normalized fields + full raw JSON into PostgreSQL.
4. Script loads last 6 hours of observations.
5. Script computes rain probability using heuristic factors.
6. Script sends Telegram only when alert conditions transition.
7. FastAPI endpoints serve latest, history, stats, and prediction to UI.

---

## 3) Repository Structure

```text
weather-station-4/
├── app/
│   ├── main.py                 # FastAPI API + dashboard routes
│   └── rain_predictor.py       # Heuristic rain scoring logic
├── templates/
│   └── dashboard.html          # Frontend dashboard UI
├── pws_fetcher.py              # Scheduled ingestion + prediction + Telegram
├── DOKPLOY_CRON_SETUP.md       # Dokploy/cron operational runbook
├── Dockerfile                  # Container image build
├── docker-compose.yml          # Local/compose service definition
├── requirements.txt            # Python dependencies
├── run.sh                      # Local quickstart script
└── README.md                   # Project overview
```

---

## 4) Development Logic and Technical Decisions

### 4.1 Ingestion Design
- Stores both extracted metrics and full raw observation JSON (`raw_json`).
- Uses observation timestamp (`obsTimeUtc`) parsed as UTC for correctness.
- Prevents duplicate insert by checking `(station_id, observed_at)` before insert.
- Ensures schema/index exists at runtime to reduce setup friction.

### 4.2 API Design
- Uses FastAPI async + `asyncpg` connection pool.
- Uses lifespan context (startup/shutdown replacement) instead of deprecated event hooks.
- Keeps station-scoped queries by `STATION_ID` for consistency.
- Provides endpoint-specific payload shapes tuned for frontend charts/cards.

### 4.3 Rain Prediction Philosophy
- Intentional heuristic model over opaque ML: easier to reason about and tune.
- Scoring is additive and bounded to 0-100.
- Factors (with max points):
  - Pressure trend (30)
  - Humidity (20)
  - Dew point spread (20)
  - Current precipitation (15)
  - Absolute pressure (10)
  - Solar radiation drop (5)
- Confidence is tied to sample size (fewer points -> lower confidence).

### 4.4 Alerting Logic
- Telegram alerts are stateful to reduce noise.
- Two alert channels:
  - Rain started now (precipitation transition false -> true)
  - Forecast threshold crossed (`RAIN_ALERT_THRESHOLD`)
- Alert state persisted in `rain_alert_state.json`.
- Reset behavior allows future alerts after conditions clear.

### 4.5 Reliability/Operations Decisions
- Cron schedule is external to app runtime for simplicity.
- In Dokploy environment, host cron calls into container with `docker exec`.
- Passwordless sudo is scoped to one exact command for safer automation.
- `.env` loaded from script directory to avoid cron working-directory pitfalls.

---

## 5) Configuration Reference

### Required Environment Variables
- `DATABASE_URL`: PostgreSQL DSN.
- `STATION_ID`: PWS station identifier.
- `WU_API_KEY`: Weather Underground API key.

### Optional Environment Variables
- `TELEGRAM_BOT_TOKEN`: Bot token for notifications.
- `TELEGRAM_CHAT_ID`: Destination chat/channel id.
- `RAIN_ALERT_THRESHOLD`: integer threshold (default `46`).

### FastAPI Runtime Notes
- API uses `DATABASE_URL` from environment.
- If DB is unavailable on startup, app starts and logs a warning.

---

## 6) Application Setup

### 6.1 Local Development Setup
1. Create and activate virtual environment.
2. Install dependencies from `requirements.txt`.
3. Create `.env` with required variables.
4. Start API using `run.sh` or `uvicorn app.main:app`.
5. Schedule `pws_fetcher.py` every 15 minutes (cron or manual runs while developing).

### 6.2 Docker Setup
- Build image from `Dockerfile`.
- Run web service via compose (`docker-compose.yml`) or platform deployment.
- Ensure `.env` is provided to container.

### 6.3 Dokploy + Host Cron Setup
- Use documented process in `DOKPLOY_CRON_SETUP.md`.
- Core pattern: host cron executes `python /app/pws_fetcher.py` inside running container via `docker exec`.
- Keep container name in sync after redeploys.

---

## 7) User Guide

### 7.1 Dashboard Usage
- Open web app root route (`/`).
- View latest conditions cards (temp, humidity, pressure, wind, precip, UV, etc.).
- Use charts for trend analysis over selected time windows.
- Rain prediction panel explains probability and factors.

### 7.2 API Endpoints
- `GET /health`: service health string.
- `GET /api/latest`: latest normalized weather snapshot.
- `GET /api/history?hours=24`: ordered historical observations (1-168 hours).
- `GET /api/stats?hours=24`: min/max/avg aggregates for interval.
- `GET /api/rain-prediction`: heuristic forecast from recent data.
- `GET /api/observations/latest-10`: raw recent records for troubleshooting.

### 7.3 Telegram Test
- Test bot path without waiting for weather conditions:

```bash
python pws_fetcher.py --test-telegram
```

---

## 8) Operations Playbook

### Daily Checks
- Latest observation age <= 20 minutes.
- No repeated ingestion errors in log.
- API `/health` returns `ok`.
- Cron log shows expected minute marks (`00/15/30/45`).

### Common Commands

```bash
# check cron entry
crontab -l | grep pws_fetcher.py

# test non-interactive cron command path
sudo -n /usr/bin/docker exec <container_name> python /app/pws_fetcher.py

# inspect recent cron output
tail -n 30 /home/newguy/fetch-pws/weather_cron.log

# find active container name after redeploy
sudo docker ps --format '{{.Names}}' | grep myweatherstation
```

### Logs to Watch
- Ingestion script output in cron log.
- FastAPI application logs from container/runtime.
- Database connection errors and API 503 from query failures.

---

## 9) FAQ

### Why are there no Telegram alerts even though data is being saved?
Most common causes:
- Telegram env vars missing in the execution context.
- Alert conditions not met (no threshold crossing / no rain transition).
- Wrong script being scheduled (host fetcher without Telegram logic).
- Cron command failing before script runs (sudo/password issue).

### Why did cron suddenly stop after a redeploy?
Container name changed. Update:
- Crontab entry command target.
- Sudoers rule command target.

### Why does manual terminal run work but cron fails?
Cron is non-interactive and has minimal environment.
- It cannot answer sudo password prompts.
- Working directory assumptions can fail.

### Why heuristic prediction instead of ML?
Heuristics are transparent, explainable, and easy to tune with local weather behavior.

### How do I safely test Telegram end-to-end?
Use `--test-telegram` first, then validate one scheduled run in cron logs.

---

## 10) Troubleshooting Guide

### Symptom: `can't open file '/Users/.../pws_fetcher.py'`
Cause: macOS/local path accidentally used on Linux server cron.
Fix: execute inside container (`python /app/pws_fetcher.py`) or use a valid server path.

### Symptom: `sudo: a terminal is required` in cron log
Cause: cron cannot provide password prompt.
Fix: scoped NOPASSWD sudoers rule for exact docker exec command.

### Symptom: API endpoint returns `503 Database query failed`
Cause: DB connection issue or invalid `DATABASE_URL`.
Fix:
- Validate DSN and reachability.
- Validate DB is accepting connections.

### Symptom: no new rows in DB
Cause options:
- Scheduler not running.
- WU API errors/timeouts.
- DB write failure.
Fix:
- inspect cron logs
- run ingestion command manually
- validate WU key and database credentials

---

## 11) Security Notes

- Keep `.env` out of version control.
- Restrict sudoers rules to exact command paths and arguments.
- Rotate API keys/tokens if exposed.
- Avoid broad docker group access unless required by policy.

---

## 12) Team Workflow Suggestions

### Recommended Git Workflow
- Feature branch per change.
- PR with:
  - what changed
  - why changed
  - how validated
- Keep runbook updates in same PR as operational changes.

### Testing Expectations
- Manual smoke tests:
  - `/health`
  - `/api/latest`
  - one ingestion run
  - optional `--test-telegram`
- For future: add unit tests for predictor scoring and API contract tests.

---

## 13) Future Improvements Backlog

- Add unique index on `(station_id, observed_at)` at DB level and use `ON CONFLICT DO NOTHING`.
- Add structured JSON logging for easier parsing/alerts.
- Add automated tests for predictor boundaries and API schemas.
- Add containerized worker service to remove host cron dependency.
- Add dashboard/admin page for ingestion freshness and alert status.

---

## 14) Quick Start Summary

1. Configure `.env` (`DATABASE_URL`, `STATION_ID`, `WU_API_KEY`).
2. Start API service.
3. Schedule `pws_fetcher.py` every 15 minutes.
4. Verify logs and latest DB rows.
5. Test Telegram with `--test-telegram`.
6. Keep cron/container names synced after redeploy.

---

This handbook is intended to be the single source of truth for understanding, operating, and evolving this project.
