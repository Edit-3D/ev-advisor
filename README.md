# EV Advisor

Stage 1 foundation for a multi-agent electric vehicle assistant. This stage contains a FastAPI backend, a React/TypeScript frontend, and placeholder chat behavior only. Agents, tools, RAG, and EV comparison logic are intentionally not implemented yet.

## Project structure

```text
backend/     FastAPI application and endpoint tests
frontend/    React + TypeScript + Vite client
data/        Reserved for the future local EV dataset and knowledge base
test.py      Existing Gemini/LangGraph diagnostic (preserved)
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
