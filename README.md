# Scout WC26

**AI-powered World Cup 2026 player scouting agent built with Gemini, Fivetran, and BigQuery**

![Python](https://img.shields.io/badge/python-3.11-blue?logo=python&logoColor=white)
![Google Cloud](https://img.shields.io/badge/Google_Cloud-BigQuery%20%7C%20Vertex%20AI-4285F4?logo=googlecloud&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Overview

Scout WC26 is an AI scouting agent that ingests live World Cup 2026 match data, transforms it through a Bronze/Silver/Gold data pipeline in BigQuery, and exposes a natural-language interface powered by Gemini 2.0 Flash. Ask it anything — player form, tactical matchups, top performers by position — and receive structured, data-backed scouting reports.

Built for the Google Cloud + Fivetran hackathon track.

---

## Architecture

```
API-Football (RapidAPI)
        │
        ▼
  Fivetran MCP Server  ◄── trigger via fivetran_trigger.py
        │
        ▼
  BigQuery — Bronze    (raw API snapshots)
        │
        ▼
  BigQuery — Silver    (cleaned, normalized)
        │
        ▼
  BigQuery — Gold      (aggregated player & match stats)
        │
        ▼
  Gemini 2.0 Flash Agent  ◄── tool calls defined in src/agent/tools.py
        │
        ▼
  FastAPI REST API     ◄── query agent, fetch reports
```

Data flows from the API-Football source through Fivetran's MCP server into BigQuery, where it is progressively refined across three layers. The Gemini agent queries the Gold layer via structured tool calls and returns scouting insights through a FastAPI interface.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent | Gemini 2.0 Flash via `google-cloud-aiplatform` |
| Data Ingestion | Fivetran MCP Server |
| Data Warehouse | BigQuery (GCP) |
| API | FastAPI 0.111 |
| Language | Python 3.11 |
| Testing | pytest 8.x |
| Formatting | Black |

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Fill in: GOOGLE_CLOUD_PROJECT, BIGQUERY_DATASET, FIVETRAN_API_KEY, FIVETRAN_API_SECRET, GOOGLE_APPLICATION_CREDENTIALS

# Run ingestion pipeline (pulls from football API → BigQuery via Fivetran)
python src/ingestion/fivetran_trigger.py

# Run the scouting agent (interactive CLI)
python src/agent/scout_agent.py

# Run the FastAPI server (REST interface)
uvicorn src.api.main:app --reload --port 8000

# Run tests
pytest tests/ -v
```

> **GCP Auth:** Use Application Default Credentials locally — run `gcloud auth application-default login` before starting. Never commit a service account JSON to the repo.

---

## Project Structure

```
src/
  ingestion/        # Fivetran MCP trigger, schema definitions, BigQuery loaders
  agent/            # Gemini agent: planning, tool calls, multi-step reasoning
  pipeline/         # Data transformation: raw API data → Bronze → Silver → Gold
  api/              # FastAPI REST endpoints (query agent, get reports)
  utils/            # BigQuery client wrapper, logging, config loader
tests/              # Mirror of src/ — unit + integration tests
.claude/
  hooks/            # dangerous-cmd-guard.sh, auto-format.sh
  commands/         # code-review.md slash command
docs/
  architecture.png  # Architecture diagram
```

---

## Demo

[DEMO_VIDEO_URL]

---

## Contributing

1. Fork the repo and create a feature branch.
2. Run `pytest tests/ -v` and confirm all tests pass before opening a PR.
3. Format code with Black — the auto-format hook runs on every file write.
4. Open a pull request against `main` with a clear description of the change.

---

## License

[MIT](LICENSE) © 2026 Omar Elkady
