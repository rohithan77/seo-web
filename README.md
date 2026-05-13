# SEO Agent Web

A proper web app version of the SEO Agent. Users paste a URL, get a full audit + 30-day plan, then execute tasks one at a time. WordPress credentials are only asked when a task needs them — never stored.

## Stack

- **Frontend** — Next.js 15 (App Router) + Tailwind CSS · deployed on Vercel
- **Backend** — FastAPI (Python) + Anthropic SDK · deployed on Railway/Render

## Local setup

### 1. Backend

```bash
cd backend
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env

pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
cp .env.local.example .env.local
# NEXT_PUBLIC_API_URL=http://localhost:8000

npm install
npm run dev
```

Open http://localhost:3000

## Deploy

### Backend → Railway

1. Create a new Railway project
2. Connect this repo, set root to `seo-web/backend`
3. Set env var: `ANTHROPIC_API_KEY`, `FRONTEND_URL=https://your-vercel-url.vercel.app`
4. Railway auto-detects Python and runs `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Frontend → Vercel

1. Import repo into Vercel, set root to `seo-web/frontend`
2. Set env var: `NEXT_PUBLIC_API_URL=https://your-railway-url.railway.app`
3. Deploy

## WordPress access — security model

- No credentials required for the audit phase (URL only)
- When a task requires WordPress changes, the app shows a credential form inline
- Recommended: create a dedicated **Editor** user in WordPress → Users → Add New
  - Never use your admin account
  - Generate an Application Password specifically for SEO Agent
  - Revoke it anytime from WordPress Admin → Users → Your Profile → Application Passwords
- Credentials are sent to the backend per-request, used for that task only, and never written to disk
- Each client/company gets an isolated session (UUID-based workspace in `backend/sessions/`)

## Flow

```
1. Enter URL → backend starts audit (no credentials needed)
2. 6 agents run in parallel → live progress on screen
3. Full findings report: critical/high/medium/low issues
4. "Generate Plan" → Claude builds a 30-day task list
5. Review plan, uncheck tasks you want to skip, click Approve
6. Execute task by task:
   - Non-WP tasks run immediately
   - WP tasks show a credential form (inline, per-task)
   - Each task shows what changed
```
