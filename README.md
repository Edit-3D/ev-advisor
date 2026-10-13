# EV Advisor

EV Advisor is a FastAPI and React foundation for a multi-agent electric vehicle assistant. Stage 2 adds reproducible OpenEV Data normalization and deterministic vehicle tools. LLM, RAG, and multi-agent orchestration remain intentionally out of scope.

## Project structure

```text
backend/     FastAPI application, vehicle tools, and tests
frontend/    React + TypeScript + Vite client
data/        Original OpenEV Data input, license, and normalized output
scripts/     Reproducible dataset ingestion entry point
test.py      Existing Gemini/LangGraph diagnostic (preserved)
```

## Vehicle dataset

The source is **OpenEV Data 1.24.0**, supplied as `data/raw/open-ev-data-v1.24.0.json`. The original file is preserved unchanged. It contains 1,189 records and declares source schema version 1.0.0. OpenEV Data is distributed under the **Community Data License Agreement – Permissive 2.0**; the required license text remains at `data/LICENSE-OPENEV-DATA.txt`.

The source represents each model year and variant as a vehicle record. Manufacturer, model, and trim are `{slug, name}` objects; an optional variant object further identifies body-style or equipment variants. Technical data is nested under `battery`, `charging`, `range`, and `body`. Rated ranges can include WLTP, EPA, CLTC, NEDC, JC08, or `other` cycles. Pricing, when present, is a list of market-specific MSRP entries under `pricing.msrp`.

Regenerate the normalized dataset from the project root:

```powershell
.\.venv\Scripts\python.exe scripts\ingest_vehicles.py
```

The default output is a curated 100-record dataset with these configurable limits:

| Manufacturer | Records | Distinct models covered |
| --- | ---: | ---: |
| Tesla | 18 | 5 |
| Volvo | 18 | 4 |
| BMW | 28 | 7 |
| Volkswagen | 20 | 5 |
| Hyundai | 16 | 4 |

Selection is deterministic and follows these rules in order:

1. Restrict candidates to the configured manufacturers and require each quota to be satisfiable.
2. Select the strongest representative of every distinct model before adding second configurations. If a quota is smaller than the model count, model representatives compete by completeness, newest model year, then original vehicle ID.
3. Fill remaining positions by preferring previously unseen combinations of net battery capacity, drivetrain, AC/DC charging power, trim, and variant.
4. Break remaining ties by the number of individually novel specification values, completeness of battery/range/charging data, newest year, then original vehicle ID.

The original identifiers and specifications are retained without modification. Identical repeated IDs are removed; conflicting records with the same ID fail validation. Running ingestion repeatedly against the same input and configuration produces byte-identical output.

Optional paths and source version can be supplied with `--source`, `--output`, and `--source-version`. To replace the default manufacturer configuration, repeat `--manufacturer-limit NAME=COUNT` for every desired manufacturer:

```powershell
.\.venv\Scripts\python.exe scripts\ingest_vehicles.py `
  --manufacturer-limit Tesla=10 `
  --manufacturer-limit Volvo=10
```

The generated metadata separately records the 1,189 source records, the number selected for curation, the number successfully normalized, and the configured limits.

Each normalized vehicle contains:

- `id`, `brand`, `model`, `year`, `trim`, and optional `variant`
- usable net `battery_kwh` with `battery_capacity_type: "net"`
- a preferred `range_km`/`range_type` pair plus all source `ranges`
- AC and optional DC charging power in kW
- zero or more MSRP `prices`, each retaining amount, currency, country, and year
- optional `body_type` and a source URL

No currency conversion is performed. Prices are source MSRP observations, not live prices or verified Swedish retail prices. The source has pricing for only 174 of 1,189 records, contains no consumption field, has no estimated real-world range field, and omits DC power for 45 records. These unavailable values are not invented. The curated file is intentionally limited to the configured brands and is not a statistically representative sample of the full OpenEV dataset.

### Deterministic vehicle tools

The independently testable functions in `backend/app/vehicles/tools.py` are:

- `search_vehicles`: filters by manufacturer, body type, minimum net battery capacity, minimum rated range/cycle, and maximum price. Price filtering requires an explicit ISO currency and never converts currencies. Results report how many candidates lacked a requested price or range cycle.
- `compare_vehicles`: compares two or more IDs, preserves source values, reports unknown IDs, and lists missing optional fields per vehicle.
- `calculate_charging_cost`: calculates grid energy and estimated cost from energy added, unit electricity price, and charging efficiency. Its default efficiency is 90%.

These functions do not use an LLM and remain separate from the FastAPI layer. A later stage can wrap them as LangChain tools and route calls through LangGraph without changing their deterministic business logic.

## Local EV knowledge retrieval

The Stage 3 knowledge base gives a future Research Agent grounded background material without making an LLM or network call. Five concise Markdown documents live in `data/knowledge/`:

- `ev_charging.md`
- `battery_health.md`
- `real_world_range.md`
- `charging_costs.md`
- `ev_ownership.md`

Content was paraphrased from pages accessed on 2026-10-13 from the US Department of Energy and its Alternative Fuels Data Center, FuelEconomy.gov, NREL, and Geotab. Each document identifies direct URLs and its verification date. US-specific levels and connector examples are labeled; range cycles, tariffs, currencies, incentives, and market availability are not treated as globally interchangeable.

`KnowledgeIndex` splits text within Markdown section boundaries into windows of up to 110 words with a 20-word overlap when a section needs multiple chunks. Each chunk retains its document title, section, filename, verification date, and only the external URLs mapped to that section. A cached scikit-learn TF-IDF index ranks word and two-word features by cosine similarity. Local TF-IDF is transparent, deterministic, fast for this small corpus, and works offline without an embedding API or vector database. A minimum relevance score prevents obviously unrelated passages from being returned.

Call the reusable tool from the project root:

```python
from backend.app.rag import search_ev_knowledge

result = search_ev_knowledge(
    "How do cold weather and cabin heating affect EV range?",
    top_k=3,
)
```

The result is JSON-serializable. Each item contains `passage`, `document_title`, `section_heading`, `document_filename`, `source_urls`, `verification_date`, and `relevance_score`. For the example above, the leading result is the “Cold weather and climate control” section of `real_world_range.md`. A future LangGraph Research Agent can call this function and use the returned external URLs as citation metadata; retrieval itself never invents citations.

Run only the retrieval tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_rag_retrieval.py
```

## Docker quick start

### Prerequisites

- Docker Desktop with the WSL 2 backend (Windows), or Docker Engine with the Compose plugin
- A root `.env` file (copy `.env.example` if starting fresh)

From the project root, build and start both services:

```powershell
docker compose up --build
```

Open these URLs after both services become healthy:

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`
- API documentation: `http://localhost:8000/docs`

The browser sends containerized frontend requests to `/api/chat`. Nginx proxies them internally to `http://backend:8000/chat`; the Compose service name is never exposed to browser JavaScript. The local `data/` directory is mounted read-only at `/app/data`, so datasets are available to the backend without being copied into its image.

Stop and remove the containers and network with:

```powershell
docker compose down
```

Rebuild after dependency, Dockerfile, or frontend build-time changes:

```powershell
docker compose up --build
```

Compose reads backend environment variables at runtime from the root `.env`. This file is excluded from Git and Docker build contexts and is never copied into an image. Do not place secrets in `VITE_*` variables: Vite embeds those values in browser assets.

### Docker troubleshooting

- Run `docker compose ps` to check service and health status.
- Run `docker compose logs backend` or `docker compose logs frontend` for startup and proxy errors.
- If ports `5173` or `8000` are occupied, stop the local process using them before starting Compose.
- If the backend is unhealthy, verify that `.env` exists and run `curl.exe http://localhost:8000/health`.
- If dependencies appear stale, rebuild without cache using `docker compose build --no-cache`, then run `docker compose up`.

## Run without Docker

### Prerequisites

- Python 3.11 or newer
- Node.js 20 or newer
- An existing `.venv` in the project root

### Backend setup

From the project root in Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Keep secrets in the existing `.env` file. If starting fresh, copy `.env.example` to `.env` and replace the placeholder API key. The default model for future backend integration is:

```dotenv
GEMINI_MODEL=gemini-3.1-flash-lite
```

Start the API from the project root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

The API is available at `http://localhost:8000`; interactive documentation is at `http://localhost:8000/docs`.

Run backend tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

### Frontend setup

In a second PowerShell window:

```powershell
Set-Location .\frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The frontend sends `POST` requests to `http://localhost:8000/chat`. To use another backend URL, set `VITE_API_URL` when starting Vite.

Build the frontend:

```powershell
Set-Location .\frontend
npm run build
```

## API endpoints

- `GET /health` returns `{ "status": "ok" }`.
- `POST /chat` accepts `{ "message": "..." }` and returns a Stage 1 placeholder reply.

Vehicle tools are currently Python functions rather than public API endpoints; `/health` and `/chat` remain unchanged.
