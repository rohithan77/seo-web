"""
FastAPI backend for the SEO Agent web app.

Endpoints:
  POST /api/audit/start          { url }  → { session_id }
  GET  /api/audit/{id}/stream    SSE stream of audit progress
  GET  /api/audit/{id}/report    Full audit report JSON
  POST /api/plan/{id}/generate   Generate 30-day plan
  GET  /api/plan/{id}            Get plan
  POST /api/plan/{id}/approve    Approve plan (optionally skip tasks)
  POST /api/execute/{id}/task    Execute one task
  GET  /api/execute/{id}/status  Full execution status
"""

import uuid
import json
import asyncio
import os
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from models import ExecuteTaskRequest, PreviewTaskRequest, Task, TaskResult
from audit import run_audit
from planner import generate_plan
from executor import execute_task, preview_task
import auth as auth_module
from db import db_create_session, db_get_session, db_update_session, db_get_user_sessions

load_dotenv()

app = FastAPI(title="SEO Agent API")

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "api_key_set": bool(os.getenv("ANTHROPIC_API_KEY"))}


# ── Auth helpers ─────────────────────────────────────────────────────────────

def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = auth_module.decode_token(authorization[7:])
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user_id


def _get_session_or_404(session_id: str) -> dict:
    session = db_get_session(session_id)
    if not session:
        raise HTTPException(404, f"Session {session_id} not found")
    return session


# ── Auth endpoints ────────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/register")
async def register(req: AuthRequest):
    try:
        user_id = auth_module.register(req.email, req.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    token = auth_module.make_token(user_id)
    return {"token": token, "user_id": user_id}


@app.post("/api/auth/login")
async def login(req: AuthRequest):
    try:
        user_id = auth_module.login(req.email, req.password)
    except ValueError as e:
        raise HTTPException(401, str(e))
    token = auth_module.make_token(user_id)
    return {"token": token, "user_id": user_id}


@app.get("/api/auth/me")
async def me(user_id: str = Depends(get_current_user)):
    return {"user_id": user_id}


# ── Session helpers ──────────────────────────────────────────────────────────

# In-memory progress store (per session)
_progress: dict[str, list[dict]] = {}
_audit_tasks: dict[str, asyncio.Task] = {}


async def _run_audit_bg(session_id: str, url: str):
    events = _progress.setdefault(session_id, [])

    async def on_progress(domain: str, status: str, findings: list = None, error: str = None):
        events.append({
            "type": "progress",
            "domain": domain,
            "status": status,
            "findings_count": len(findings or []),
            "error": error,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

    try:
        report = await run_audit(url, session_id, progress_cb=on_progress)
        db_update_session(session_id, report=report.model_dump(), status="audited")
        events.append({"type": "complete", "session_id": session_id})
    except Exception as e:
        events.append({"type": "error", "message": str(e)})


@app.get("/api/sessions")
async def list_sessions(user_id: str = Depends(get_current_user)):
    """Return all sessions belonging to this user, newest first."""
    rows = db_get_user_sessions(user_id)
    return [
        {
            "session_id": r["id"],
            "url": r["url"],
            "started_at": r["started_at"],
            "status": r["status"],
        }
        for r in rows
    ]


class StartAuditRequest(BaseModel):
    url: str


@app.post("/api/audit/start")
async def start_audit(req: StartAuditRequest, user_id: str = Depends(get_current_user)):
    url = req.url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    session_id = str(uuid.uuid4())[:8]
    started_at = datetime.now(timezone.utc).isoformat()
    db_create_session(session_id, user_id, url, started_at)

    _progress[session_id] = []
    task = asyncio.create_task(_run_audit_bg(session_id, url))
    _audit_tasks[session_id] = task

    return {"session_id": session_id, "url": url}


@app.get("/api/audit/{session_id}/stream")
async def audit_stream(session_id: str, token: Optional[str] = None):
    # SSE: EventSource can't set headers, so accept token via query param
    if not token or not auth_module.decode_token(token):
        raise HTTPException(status_code=401, detail="Not authenticated")
    _get_session_or_404(session_id)

    async def generate() -> AsyncGenerator[str, None]:
        sent = 0
        while True:
            events = _progress.get(session_id, [])
            while sent < len(events):
                yield f"data: {json.dumps(events[sent])}\n\n"
                sent += 1
                if events[sent - 1].get("type") in ("complete", "error"):
                    return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/audit/{session_id}/report")
async def get_report(session_id: str, user_id: str = Depends(get_current_user)):
    session = _get_session_or_404(session_id)
    report = session.get("report")
    if not report:
        raise HTTPException(202, "Audit still in progress")
    return report


# ── Plan ─────────────────────────────────────────────────────────────────────

_plan_tasks: dict[str, asyncio.Task] = {}


async def _generate_plan_bg(session_id: str, report_data: dict):
    from models import AuditReport
    import traceback
    try:
        db_update_session(session_id, plan_status={"status": "generating"}, status="planning")
        report = AuditReport(**report_data)
        print(f"[plan] Report loaded — {len(report.all_findings)} findings")
        plan = await generate_plan(report)
        if not plan.tasks:
            db_update_session(session_id, plan_status={"status": "error", "message": "Claude returned no tasks"})
            return
        db_update_session(session_id, plan=plan.model_dump(), plan_status={"status": "done"}, status="plan_ready")
        print(f"[plan] Done — {len(plan.tasks)} tasks")
    except Exception as e:
        traceback.print_exc()
        db_update_session(session_id, plan_status={"status": "error", "message": str(e)})


@app.post("/api/plan/{session_id}/generate")
async def generate_plan_endpoint(session_id: str, user_id: str = Depends(get_current_user)):
    session = _get_session_or_404(session_id)
    report_data = session.get("report")
    if not report_data:
        raise HTTPException(400, "Audit not complete — wait for audit to finish first")

    plan_status = session.get("plan_status") or {}
    if plan_status.get("status") == "generating":
        return {"status": "generating"}

    task = asyncio.create_task(_generate_plan_bg(session_id, report_data))
    _plan_tasks[session_id] = task
    return {"status": "generating"}


@app.get("/api/plan/{session_id}")
async def get_plan(session_id: str, user_id: str = Depends(get_current_user)):
    session = _get_session_or_404(session_id)
    plan_status = session.get("plan_status") or {}
    if plan_status.get("status") == "generating":
        return {"status": "generating"}
    if plan_status.get("status") == "error":
        raise HTTPException(500, plan_status.get("message", "Plan generation failed"))
    plan = session.get("plan")
    if not plan:
        raise HTTPException(404, "Plan not generated yet — call /generate first")
    return plan


class ApprovePlanRequest(BaseModel):
    skip_task_ids: list[str] = []


@app.post("/api/plan/{session_id}/approve")
async def approve_plan(session_id: str, req: ApprovePlanRequest, user_id: str = Depends(get_current_user)):
    session = _get_session_or_404(session_id)
    plan = session.get("plan")
    if not plan:
        raise HTTPException(404, "No plan to approve")

    for task in plan["tasks"]:
        if task["id"] in req.skip_task_ids:
            task["status"] = "skipped"

    plan["approved_at"] = datetime.now(timezone.utc).isoformat()
    db_update_session(
        session_id,
        approved_plan=plan,
        task_log={"tasks": [], "session_id": session_id},
        status="executing",
    )
    return {"approved": True, "tasks": len(plan["tasks"])}


# ── Execute ──────────────────────────────────────────────────────────────────

def _norm_wp_url(url: str) -> str:
    if url and not url.startswith("http"):
        return "https://" + url
    return url


@app.post("/api/execute/{session_id}/preview")
async def preview_task_endpoint(session_id: str, req: PreviewTaskRequest, user_id: str = Depends(get_current_user)):
    """
    Generate what the task WOULD do — current values + Claude suggestions — without touching anything.
    Frontend shows this for human review/editing before calling /task to apply.
    """
    session = _get_session_or_404(session_id)
    plan_data = session.get("approved_plan")
    if not plan_data:
        raise HTTPException(400, "Plan not approved")

    task_data = next((t for t in plan_data["tasks"] if t["id"] == req.task_id), None)
    if not task_data:
        raise HTTPException(404, f"Task {req.task_id} not found")

    task = Task(**task_data)
    needs_wp = task.platform_action.startswith("wp_")
    wp_url = _norm_wp_url(req.wp_url or "")

    if needs_wp and not (wp_url and req.wp_username and req.wp_app_password):
        from models import TaskPreview
        return TaskPreview(
            task_id=req.task_id,
            action=task.platform_action,
            target_url=task.target_url or "",
            summary=task.description,
            current={},
            suggested={},
            needs_credentials=True,
        ).model_dump()

    result = await asyncio.get_event_loop().run_in_executor(
        None,
        preview_task,
        task,
        wp_url,
        req.wp_username or "",
        req.wp_app_password or "",
    )
    return result.model_dump()


@app.get("/api/execute/{session_id}/manual/{task_id}")
async def manual_instructions(session_id: str, task_id: str, user_id: str = Depends(get_current_user)):
    """
    Returns step-by-step manual instructions for a task so the user can
    do it themselves without providing credentials.
    """
    session = _get_session_or_404(session_id)
    plan_data = session.get("approved_plan")
    if not plan_data:
        raise HTTPException(400, "Plan not approved")

    task_data = next((t for t in plan_data["tasks"] if t["id"] == task_id), None)
    if not task_data:
        raise HTTPException(404, f"Task {task_id} not found")

    task = Task(**task_data)
    site_url = session.get("url", "your site")

    instructions = _build_manual_instructions(task, site_url)
    return {"task_id": task_id, "title": task.title, "instructions": instructions}


def _build_manual_instructions(task: Task, site_url: str) -> list[dict]:
    """Return a list of {step, detail} dicts describing how to do this task manually."""
    action = task.platform_action
    target = task.target_url or site_url

    if action == "wp_update_meta":
        return [
            {"step": "Install Yoast SEO or Rank Math", "detail": "Both are free. Go to Plugins → Add New in your WordPress admin and install one."},
            {"step": "Open the page in WordPress editor", "detail": f"Go to Pages (or Posts) in your WP admin and find the page for: {target}"},
            {"step": "Scroll to the SEO section at the bottom", "detail": "Yoast shows a green/red traffic light. Rank Math shows an 'SEO' tab."},
            {"step": "Set the SEO Title", "detail": f"Write a title 50–60 characters long with your primary keyword near the start. E.g. '{task.title}'"},
            {"step": "Set the Meta Description", "detail": "Write 140–155 characters that describe the page value and include a soft call-to-action. This is what Google shows in search results."},
            {"step": "Click Update / Publish", "detail": "Save the page. Google will pick up the new meta within 1–4 weeks on next crawl."},
        ]
    elif action == "wp_set_canonical":
        return [
            {"step": "Open the page in WordPress editor", "detail": f"Find the page for: {target}"},
            {"step": "Go to Yoast / Rank Math advanced settings", "detail": "Yoast: 'Advanced' tab in the SEO section. Rank Math: 'Advanced' tab."},
            {"step": "Set the canonical URL", "detail": f"Paste this exact URL: {target}"},
            {"step": "Save the page", "detail": "Click Update. This tells Google which version of the page is the 'real' one, preventing duplicate content issues."},
        ]
    elif action == "wp_add_schema":
        return [
            {"step": "Install a schema plugin", "detail": "Yoast SEO Premium, Rank Math (free), or Schema Pro all handle this. Rank Math free is recommended."},
            {"step": "Open the page in WordPress editor", "detail": f"Find the page for: {target}"},
            {"step": "Go to the Schema tab", "detail": "In Rank Math: click 'Schema' in the right sidebar. Choose the schema type that matches your page (Article, LocalBusiness, FAQ, etc.)."},
            {"step": "Fill in the required fields", "detail": "Name, URL, description at minimum. The more fields you fill, the richer the result in Google."},
            {"step": "Save and validate", "detail": "After saving, paste your URL into Google's Rich Results Test (search.google.com/test/rich-results) to confirm the schema is valid."},
        ]
    elif action == "wp_update_image_alt":
        return [
            {"step": "Go to Media Library", "detail": "In WordPress admin: Media → Library. Switch to List View for easier editing."},
            {"step": "Find images with no alt text", "detail": "Sort by 'uploaded to' to filter images for this specific page. Click each image."},
            {"step": "Fill in the Alternative Text field", "detail": "Describe what the image shows in 5–12 words. Include a keyword naturally if it fits. E.g. 'Team of nurses reviewing patient charts'"},
            {"step": "Save each image", "detail": "Click Update for each image. This improves both SEO and accessibility."},
        ]
    elif action == "wp_update_sitemap":
        return [
            {"step": "Find your sitemap URL", "detail": f"It's usually at: {site_url.rstrip('/')}/sitemap.xml — open this in a browser to confirm it loads."},
            {"step": "Submit to Google Search Console", "detail": "Go to search.google.com/search-console → Sitemaps → paste your sitemap URL → Submit."},
            {"step": "Submit to Bing Webmaster Tools", "detail": "Go to bing.com/webmasters → your site → Sitemaps → Submit sitemap URL."},
            {"step": "Ping manually (optional)", "detail": f"Visit this URL in your browser: https://www.google.com/ping?sitemap={site_url.rstrip('/')}/sitemap.xml"},
        ]
    elif action == "content_write":
        return [
            {"step": "Identify the target keyword", "detail": f"Based on the plan: {task.description}"},
            {"step": "Research the topic", "detail": "Look at the top 3–5 Google results for your target keyword. Note what headings they use and what questions they answer."},
            {"step": "Write the content", "detail": "Aim for at least 800 words. Use H2 and H3 headings. Answer the searcher's question directly in the first paragraph."},
            {"step": "Optimise before publishing", "detail": "Include your keyword in: the title, first 100 words, at least one H2, and the meta description."},
            {"step": "Add internal links", "detail": "Link to 2–3 other relevant pages on your site. This passes authority and helps Google understand your site structure."},
        ]
    elif action in ("geo_create_llms_txt", "geo_update_ai_meta"):
        return [
            {"step": "Create /llms.txt on your server", "detail": f"Via FTP or your hosting file manager, create a file at: {site_url.rstrip('/')}/llms.txt"},
            {"step": "Add your site description", "detail": "Write 2–3 sentences describing what your site is about, who it's for, and what topics it covers. This helps AI assistants like ChatGPT and Claude understand your content."},
            {"step": "List your key pages", "detail": "Add a section listing your most important pages with their URLs and a one-line description of each."},
            {"step": "Add Organization schema to your homepage", "detail": "In your SEO plugin, go to your homepage → Schema → Organization. Fill in: name, URL, logo, description, social profiles."},
        ]
    else:
        return [
            {"step": "Review the task", "detail": task.description},
            {"step": "Log into your WordPress admin", "detail": f"Go to {site_url.rstrip('/')}/wp-admin"},
            {"step": "Make the change manually", "detail": f"Action required: {action.replace('_', ' ')}"},
            {"step": "Verify the change", "detail": "After making the change, view your page and confirm it looks correct."},
        ]


@app.post("/api/execute/{session_id}/task")
async def execute_task_endpoint(session_id: str, req: ExecuteTaskRequest, user_id: str = Depends(get_current_user)):
    session = _get_session_or_404(session_id)
    plan_data = session.get("approved_plan")
    if not plan_data:
        raise HTTPException(400, "Plan not approved")

    task_data = next((t for t in plan_data["tasks"] if t["id"] == req.task_id), None)
    if not task_data:
        raise HTTPException(404, f"Task {req.task_id} not found")

    task = Task(**task_data)

    # Handle explicit skip
    if req.skip:
        for t in plan_data["tasks"]:
            if t["id"] == req.task_id:
                t["status"] = "skipped"
                break
        result = TaskResult(task_id=req.task_id, status="skipped", action_taken="Skipped by user")
        # Re-fetch log to avoid race conditions
        fresh = db_get_session(session_id) or {}
        log = fresh.get("task_log") or {"tasks": []}
        log["tasks"].append(result.model_dump())
        db_update_session(session_id, approved_plan=plan_data, task_log=log)
        return result.model_dump()

    needs_wp = task.platform_action.startswith("wp_")
    wp_url = _norm_wp_url(req.wp_url or "")

    if needs_wp and not (wp_url and req.wp_username and req.wp_app_password):
        return {
            "needs_credentials": True,
            "task_id": req.task_id,
            "platform": "wordpress",
            "message": "This task requires WordPress credentials to execute.",
        }

    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: execute_task(
            task,
            wp_url=wp_url,
            wp_username=req.wp_username or "",
            wp_app_password=req.wp_app_password or "",
            approved_content=req.approved_content,
        ),
    )

    # Update task status in plan
    for t in plan_data["tasks"]:
        if t["id"] == req.task_id:
            t["status"] = result.status
            break

    # Re-fetch log to avoid race conditions
    fresh = db_get_session(session_id) or {}
    log = fresh.get("task_log") or {"tasks": []}
    log["tasks"].append(result.model_dump())
    db_update_session(session_id, approved_plan=plan_data, task_log=log)

    return result.model_dump()


@app.get("/api/execute/{session_id}/status")
async def execution_status(session_id: str, user_id: str = Depends(get_current_user)):
    session = _get_session_or_404(session_id)
    plan = session.get("approved_plan")
    log = session.get("task_log") or {"tasks": []}
    if not plan:
        raise HTTPException(400, "Plan not approved")

    tasks = plan["tasks"]
    completed = [t for t in tasks if t["status"] == "completed"]
    skipped = [t for t in tasks if t["status"] == "skipped"]
    pending = [t for t in tasks if t["status"] == "pending"]
    failed = [t for t in tasks if t["status"] == "failed"]
    done_count = len(completed) + len(skipped)

    return {
        "session_id": session_id,
        "total": len(tasks),
        "completed": len(completed),
        "skipped": len(skipped),
        "pending": len(pending),
        "failed": len(failed),
        "progress_pct": int(done_count / len(tasks) * 100) if tasks else 0,
        "next_task": pending[0] if pending else None,
        "tasks": tasks,
        "log": log["tasks"],
    }


@app.get("/api/session/{session_id}")
async def get_session(session_id: str, user_id: str = Depends(get_current_user)):
    session = _get_session_or_404(session_id)
    return {"url": session["url"], "session_id": session["id"], "started_at": session["started_at"], "status": session["status"]}
