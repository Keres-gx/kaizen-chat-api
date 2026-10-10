# Kaizen Chat API (demo)

A small FastAPI intermediary for the public website. It does **not** expose the n8n editor. It forwards only `POST /chat` to the local webhook-only gateway through HTTPS.

## Render service settings

Create a new **Web Service** from this repository (not a Static Site).

- Runtime: Python
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`

## Environment variables

Set these on the **Python Web Service**, not on the existing Static Site:

- `N8N_GATEWAY_URL`: current Cloudflare Quick Tunnel origin only, e.g. `https://random-words.trycloudflare.com` (no trailing path, no `/webhook/chatMNB`).
- `GATEWAY_TOKEN`: the exact same strong token entered when starting `n8n_gateway.py`.
- `ALLOWED_ORIGINS`: the exact public origin of the Render Static Site, e.g. `https://your-site.onrender.com`, no trailing slash. Replace the example with the real site URL.

Do not commit actual secrets or put them in the HTML. The `X-Chat-Token` used by the n8n Header Auth credential stays in the local gateway process; it is not an API environment variable here.

## Endpoints

- `GET /health` — health check only.
- `POST /chat` — JSON: `{"message":"hello","sessionId":"stable-session-id"}`. `sessionId` is optional on the first request; the API returns one. The browser should reuse the returned session ID for subsequent messages in the same conversation.

## Important limitations

- Cloudflare Quick Tunnels are temporary and meant for testing. If the tunnel restarts and its URL changes, update `N8N_GATEWAY_URL` in Render and redeploy/restart the service.
- The local gateway and `cloudflared` must both remain running on your notebook.
- A simple in-memory global limit of 30 chat requests/minute is included for this demo. It is not a production-grade, distributed rate limiter.
- Configure the static site's actual origin in `ALLOWED_ORIGINS`. CORS is a browser control, not authentication.
- This version only integrates chat. The contact form still uses its existing email fallback until a separate leads workflow and endpoint are configured.
