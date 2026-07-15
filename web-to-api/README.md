# Web-to-API

Web-to-API is a local bootstrap for investigating a public website, discussing the data you want
through a chat UI, and saving a validated OpenAPI 3.1 design plus source mappings. It uses Pydantic
AI with OpenAI, Logfire instrumentation, Crawl4AI, and FastAPI.

This first slice creates design artifacts only. It does not yet serve the scraped domain data.

## What it does

1. You paste a public HTTP(S) URL into the chat.
2. Lightweight HTTP inspection looks for feeds, embedded data, and static HTML structure.
3. Async Crawl4AI capture observes rendered HTML and JSON calls made by the website.
4. The agent ranks runtime sources as feed, backend JSON, embedded JSON, static HTML, then browser.
5. You co-design resources and fields in chat and approve saving the result.
6. The project is stored under `.data/projects/<project-id>/` as `investigation.json`,
   `design.json`, and `openapi.yaml`.

Only anonymous public sites are accepted. Local/private network targets and credentials in URLs are
rejected, and `robots.txt` is respected. This tool does not bypass authentication or anti-bot
controls.

## Setup

Prerequisites are Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and an OpenAI API key.

```shell
uv sync --extra dev
uv run crawl4ai-setup
cp .env.example .env
```

Put your key in `.env`:

```dotenv
OPENAI_API_KEY=your-key-here
```

Logfire is optional. If a local Logfire token/project is configured, traces are sent; otherwise the
application still runs and emits local instrumentation. Prompt and scraped content are excluded
from hosted traces by default.

## Run

```shell
uv run web-to-api
```

Open <http://127.0.0.1:8000> and begin with:

> Investigate https://example.com and help me design an API.

Service endpoints:

- `GET /healthz`
- `GET /api/projects/{project_id}`
- `GET /api/projects/{project_id}/openapi.yaml`
- FastAPI documentation at `/docs`

The packaged Pydantic AI UI also owns `/api/chat`, `/api/configure`, and `/api/health`.

## Development

```shell
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Tests use fake browser and HTTP transports; they do not require an OpenAI key, installed browser,
or external network access.

Useful configuration is documented in `.env.example`. Investigation cache entries expire after one
hour by default. Set `WEB_TO_API_CACHE_TTL_SECONDS=0` to disable durable cache entries or ask the
agent to force a refresh.

## Current boundaries

- Local, single-user use only; bind to localhost.
- Public, anonymous websites only.
- No generated scraping endpoints, scheduler, authentication, or deployment manifests yet.
- Source mappings are evidence-backed design suggestions and are not executed in this version.
- The built-in chat UI is a replaceable bootstrap; Pydantic AI's AG-UI adapter is the intended seam
  for a future custom frontend.
