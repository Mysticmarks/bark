# Bark Frontend

A fully wired multimodal dashboard for Bark that speaks to the FastAPI backend in `bark/server.py`. It
supports health checks, synthesis job lifecycles with streamed progress, audio preview, and responsive
controls that default to a11y-friendly dark mode.

## Getting started

```bash
cd frontend
npm install
npm run dev # served on http://localhost:4173 with API requests proxied to http://localhost:8000
```

The dev server proxies `/api` to port 8000 (FastAPI default). Launch the backend in another shell with:

```bash
python -m bark.server
```

## Building for production

```bash
npm run build
```

This produces a minified, code-split bundle in `frontend/dist/` with manual `three` chunking, CSS code
splitting, sourcemaps, and a 4 KiB inline limit for small assets. Serve the folder with any static host
or run a quick preview:

```bash
npm run preview -- --host --port 4173
```

## Deployment notes

- Set `BARK_API_URL` or rely on the `/api` proxy when fronting the app with a reverse proxy.
- Use a CDN for the `dist/` assets or bake them into the same container image as the FastAPI service.
- For containerized deploys, copy `dist/` to your web root and mount it behind your API gateway.

## End-to-end tests

Playwright tests live in `tests/` and mock Bark API responses so they run without the backend:

```bash
npm run test:e2e
```

The Playwright config spins up the Vite dev server automatically. Tests cover prompt submission,
validation, toast notifications, and job status rendering.
