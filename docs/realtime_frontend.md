# Realtime Local Frontend (index.html)

The Bark repository ships with a local-first web UI under `frontend/index.html` that can be used
as a realtime dashboard when running the FastAPI server locally. The interface is designed for
live prompt submission, previewing audio, and monitoring synthesis status.

## Local usage
1. Start the backend in one terminal:
   ```bash
   python -m bark.server
   ```
2. Open the local dashboard in a browser:
   - Navigate to `frontend/index.html` for the full dashboard experience.
   - When using the Vite dev server, run:
     ```bash
     cd frontend
     npm install
     npm run dev
     ```
3. Submit prompts and toggle realtime options such as UHD video rendering and layered audio.

## Realtime workflow checklist
- Confirm `/api/health` reports `ok` before submitting jobs.
- Use `dry_run=false` for full generation and `render_video=true` for UHD outputs.
- Monitor the activity stream for job status updates and artifact paths.
