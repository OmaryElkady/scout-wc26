# Scout WC26

## ***Hackathon submission, June 2026. Live demo offline - free-tier API credits have expired.***

**AI-powered World Cup 2026 scouting agent — Gemini 2.5 Flash + Fivetran Connector SDK + BigQuery + Google ADK**

![Python](https://img.shields.io/badge/python-3.14-blue?logo=python&logoColor=white)
![Google Cloud](https://img.shields.io/badge/Google_Cloud-BigQuery%20%7C%20Vertex%20AI%20%7C%20Cloud%20Run-4285F4?logo=googlecloud&logoColor=white)
![Fivetran](https://img.shields.io/badge/Fivetran-Connector%20SDK-0073E6)
![License](https://img.shields.io/badge/license-MIT-green)

Live demo: **https://scout-wc26-157619000742.us-central1.run.app**

---

## Overview

Scout WC26 is an AI scouting agent for the 2026 FIFA World Cup. It ingests live football data through a **custom Fivetran Connector SDK** into a **three-layer BigQuery warehouse** (Bronze / Silver / Gold), then exposes that data through a **Gemini 2.5 Flash agent** with 9 purpose-built tools. Analysts can ask natural-language scouting questions, switch leagues mid-session, generate AI-written PDF scouting reports, and visualise the warehouse through a Chart.js dashboard — including an AI chart generator that writes BigQuery SQL on demand.

Built for the **Google Cloud Rapid Agent Hackathon — Fivetran track**.

---

## Architecture

```
RapidAPI (free-api-live-football-data)
        │
        ▼
  Fivetran Connector SDK  ◄── my_football_connector/ (custom connector)
        │
        ▼
  BigQuery Bronze    raw API snapshots + raw_json blob
        │
        ▼
  BigQuery Silver    cleaned, normalised positions, parsed dates
        │
        ▼
  BigQuery Gold      gold_player_stats · gold_team_summary · gold_match_results
        │
        ▼
  Gemini 2.5 Flash Agent (Google ADK 2.1.0) — 9 tools in src/agent/tools.py
        │
        ▼
  FastAPI on Cloud Run  ◄── REST + self-contained HTML demo at /
```

10 verified leagues supported (UEFA WC Qualification, Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Champions League, MLS, Brasileirão, Scottish Premiership) plus the World Cup 2026 placeholder for kickoff on **June 11, 2026**.

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Gemini 2.5 Flash via `google-genai` |
| Agent runtime | Google Agent Development Kit (ADK) 2.1.0 |
| Ingestion | **Fivetran Connector SDK** (custom Python connector) |
| Warehouse | BigQuery — Bronze / Silver / Gold |
| API | FastAPI 0.136 + Uvicorn |
| PDF | reportlab 4.2 |
| Frontend | Self-contained `docs/demo.html` + Chart.js |
| Deployment | Google Cloud Run (`us-central1`) |
| Language | Python 3.14 |
| Testing | pytest 9.x (205 passing unit tests) |

---

## Prerequisites

1. **Python 3.14** on PATH (`python --version`).
2. **Google Cloud project** with BigQuery + Vertex AI APIs enabled.
3. **`gcloud` CLI** installed and authenticated.
4. **RapidAPI key** for `free-api-live-football-data` (free tier: 100 req/day).
5. *(Optional)* Fivetran account if you want to deploy the connector to Fivetran's managed runtime — `fivetran debug` runs locally without it.

---

## Step-by-step setup

### 1 — Clone & create the virtual environment

```powershell
# Windows PowerShell
git clone https://github.com/<your-fork>/scout-wc26.git
cd scout-wc26
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# macOS / Linux
git clone https://github.com/<your-fork>/scout-wc26.git
cd scout-wc26
python3.14 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> All later commands assume the venv is active. On Windows always invoke `venv\Scripts\python.exe` explicitly when the system Python is not the venv — the system Python 3.14 on Windows does **not** have `fastapi`, `google-adk`, or other project deps.

### 2 — Configure environment variables

```bash
cp .env.example .env
```

Fill in the values:

| Var | Required | Notes |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | ✅ | e.g. `scout-wc26` |
| `GOOGLE_CLOUD_REGION` | ✅ | `us-central1` |
| `BQ_DATASET` | ✅ | `world_cup` |
| `RAPIDAPI_KEY` | ✅ | from RapidAPI dashboard |
| `RAPIDAPI_HOST` | ✅ | `free-api-live-football-data.p.rapidapi.com` |
| `GOOGLE_APPLICATION_CREDENTIALS` | local only | path to a service-account JSON. **Omit on Cloud Run** — ADC uses the service-account identity automatically. |
| `FIVETRAN_API_KEY` / `FIVETRAN_API_SECRET` / `FIVETRAN_CONNECTOR_ID` | optional | only needed if you deploy the connector to managed Fivetran. The direct-API fallback in `refresh_scouting_data()` works without these. |
| `LEAGUE_ID` | optional | default `10195` (UEFA WC Qual). Set to `77` after June 11 2026 for live WC data. |
| `FAST_LEAGUE_SWITCH` | optional | default `true` (parallel squad fetch). |

### 3 — Authenticate to Google Cloud (local)

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud auth application-default login
gcloud services enable bigquery.googleapis.com aiplatform.googleapis.com run.googleapis.com
```

### 4 — Build the BigQuery warehouse

```powershell
# from project root, venv active
.\venv\Scripts\python.exe scripts\setup_bq_schema.py     # creates Bronze tables (idempotent)
.\venv\Scripts\python.exe scripts\ingest_all_players.py  # ingests ~54 teams (skips cached)
.\venv\Scripts\python.exe scripts\run_pipeline.py        # Bronze → Silver → Gold
```

After this, `gold_player_stats`, `gold_team_summary`, and `gold_match_results` are populated and the agent has data to query.

### 5 — Run the API + demo UI locally

```powershell
.\venv\Scripts\python.exe -m uvicorn src.api.main:app --reload --port 8000
```

Visit **http://localhost:8000** for the full dashboard. Health check at `/health`, agent at `POST /query`.

### 6 — Run the agent in CLI mode (optional)

```powershell
.\venv\Scripts\python.exe run_agent.py        # interactive Gemini SDK agent
adk run scout_adk\                            # Google ADK CLI
adk web scout_adk                             # ADK dev UI in browser
```

### 7 — Run tests

```powershell
.\venv\Scripts\python.exe -m pytest tests\unit\ -v    # 205 passing, no GCP creds required
```

---

## Deploying to Google Cloud Run

The included `scripts/deploy_cloudrun.sh` deploys directly from source.

```bash
# Linux / macOS / Git-Bash
set -a && source .env && set +a    # expand $RAPIDAPI_KEY etc. for the script
./scripts/deploy_cloudrun.sh
```

The script runs:

```
gcloud run deploy scout-wc26 --source . --region us-central1 \
  --allow-unauthenticated \
  --memory 2Gi --cpu 2 --timeout 600 --concurrency 10 \
  --min-instances 1 --no-cpu-throttling \
  --set-env-vars GOOGLE_CLOUD_PROJECT=…,BQ_DATASET=world_cup,RAPIDAPI_KEY=…, …
```

Required IAM roles on the Cloud Run service account (`<PROJECT_NUMBER>-compute@developer.gserviceaccount.com`):

- `roles/bigquery.dataEditor`
- `roles/bigquery.jobUser`
- `roles/aiplatform.user`

Once deployed, the URL Cloud Run prints serves both the REST API and the demo UI at `/`.

> **Tips**
> - `--memory 2Gi --cpu 2` are required — the import footprint of `grpcio + google-adk + google-genai + pandas` is ≈ 1.4 GiB.
> - `--min-instances 1` keeps one warm instance so cold-start 503s never hit the demo.
> - If the container fails to start with "container failed to start and listen on port", check the container logs — almost always a missing env var (`config.py` raises `EnvironmentError` if any of `_REQUIRED_VARS` is unset).
> - **Do not** pass `--no-cache` — it is not a valid `gcloud run deploy` flag; source is re-uploaded fresh on every deploy anyway.

---

## The Fivetran custom connector

Path: `my_football_connector/connector.py` — a fully working **Fivetran Connector SDK** integration.

Highlights worth showing in a demo:

- **Two-table schema** declared at the top — `fixtures` (primary key `fixture_id`) and `players` (composite key `player_id + team_id`). Column types are inferred from upserted data, per SDK best practice.
- **Two `op.checkpoint()` calls** — one after fixtures so Fivetran can persist them even if the player sync fails mid-run, and one at the end. No `yield` anywhere; the connector uses the SDK's direct `op.upsert()` / `op.checkpoint()` API.
- **Rate-limit aware** — the free RapidAPI tier allows 100 req/day. The connector caps player syncs at `_MAX_TEAMS = 10` per run (one request per team) so it never blows the quota, and it skips coaches via the `excludeFromRanking` flag.
- **Flattening logic** — `_map_fixture()` walks confirmed live field paths (`match["home"]["score"]`, `match["status"]["reason"]["short"]`, `match["status"]["utcTime"]`) and converts scores to nullable ints. `_teams_from_matches()` discovers teams from fixtures because the standings endpoint returns `"Request Failed"` for international tournaments.
- **Defensive logging** — `log.info` for step summaries, `log.warning` for skipped teams, `log.debug` for per-request traces.

### Run the connector locally

```powershell
cd my_football_connector
$env:PYTHONUTF8 = "1"
$env:PATH = "$(Resolve-Path ..\venv\Scripts);" + $env:PATH
..\venv\Scripts\python.exe connector.py
```

First run downloads the JVM-based Fivetran tester binary (~230 MB) to `~/.ft_sdk_connector_tester/`. The output is a DuckDB file (`warehouse.db`) you can inspect to confirm the rows.

---

## Project structure

```
src/
  ingestion/        Fivetran trigger + BigQuery loaders
  agent/
    scout_agent.py  Gemini SDK agent (direct tool-call loop)
    adk_agent.py    ADK Agent — 9 FunctionTools, satisfies Agent Builder track
    tools.py        9 shared agent tools (query_players, switch_league, ...)
  pipeline/         Bronze → Silver → Gold SQL transforms
  api/main.py       FastAPI app, also serves docs/demo.html at /
  utils/            BigQuery client, football API wrapper, config, progress
scout_adk/          ADK package — exports root_agent for `adk run`/`adk web`
my_football_connector/
  connector.py      Fivetran Connector SDK implementation
  CLAUDE.md         Connector field-path notes
docs/
  demo.html         Self-contained dark-theme dashboard (Chart.js)
scripts/
  setup_bq_schema.py · ingest_all_players.py · run_pipeline.py · deploy_cloudrun.sh
tests/unit/         205 passing unit tests (no GCP creds required)
Dockerfile          Cloud Run container — python:3.14-slim, $PORT-aware CMD
```

---

## Hackathon submission checklist

- [x] Fivetran Connector SDK integration runs end-to-end (`fivetran debug` produces `warehouse.db`).
- [x] BigQuery Bronze / Silver / Gold tables populated with real football data (1,391 players across 50 teams).
- [x] Gemini 2.5 Flash agent answers natural-language scouting queries with 9 tool calls.
- [x] Google ADK 2.1.0 agent runs via `adk run` / `adk web` (Agent Builder track).
- [x] FastAPI app live on Google Cloud Run.
- [x] 205 passing unit tests.
- [x] MIT license.
- [x] 3-minute demo video.

---

## License

[MIT](LICENSE) © 2026 Omar Elkady
