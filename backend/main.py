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
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from models import ExecuteTaskRequest, PreviewTaskRequest, Task, TaskResult
from audit import run_audit
from planner import generate_plan
from executor import execute_task, preview_task

load_dotenv()

app = FastAPI(title="SEO Agent API")

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


@app.get("/health")
async def health():
    return {"status": "ok", "api_key_set": bool(os.getenv("ANTHROPIC_API_KEY"))}
SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", "./sessions"))
SESSIONS_DIR.mkdir(exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Session helpers ──────────────────────────────────────────────────────────

def session_path(sid: str) -> Path:
    p = SESSIONS_DIR / sid
    p.mkdir(exist_ok=True)
    return p


def write_json(sid: str, name: str, data: dict):
    (session_path(sid) / name).write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8"
    )


def read_json(sid: str, name: str) -> dict | None:
    p = session_path(sid) / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def get_session_or_404(sid: str) -> Path:
    p = SESSIONS_DIR / sid
    if not p.exists():
        raise HTTPException(404, f"Session {sid} not found")
    return p


# ── Audit ────────────────────────────────────────────────────────────────────

class StartAuditRequest(BaseModel):
    url: str


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
        write_json(session_id, "report.json", report.model_dump())
        events.append({"type": "complete", "session_id": session_id})
    except Exception as e:
        events.append({"type": "error", "message": str(e)})


@app.post("/api/audit/start")
async def start_audit(req: StartAuditRequest):
    url = req.url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    session_id = str(uuid.uuid4())[:8]
    session_path(session_id)
    write_json(session_id, "meta.json", {
        "url": url,
        "session_id": session_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "auditing",
    })

    _progress[session_id] = []
    task = asyncio.create_task(_run_audit_bg(session_id, url))
    _audit_tasks[session_id] = task

    return {"session_id": session_id, "url": url}


@app.get("/api/audit/{session_id}/stream")
async def audit_stream(session_id: str):
    get_session_or_404(session_id)

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
async def get_report(session_id: str):
    get_session_or_404(session_id)
    report = read_json(session_id, "report.json")
    if not report:
        raise HTTPException(202, "Audit still in progress")
    return report


# ── Plan ─────────────────────────────────────────────────────────────────────

_plan_tasks: dict[str, asyncio.Task] = {}


async def _generate_plan_bg(session_id: str, report_data: dict):
    from models import AuditReport
    import traceback
    try:
        write_json(session_id, "plan_status.json", {"status": "generating"})
        report = AuditReport(**report_data)
        print(f"[plan] Report loaded — {len(report.all_findings)} findings")
        plan = await generate_plan(report)
        if not plan.tasks:
            write_json(session_id, "plan_status.json", {"status": "error", "message": "Claude returned no tasks"})
            return
        write_json(session_id, "plan.json", plan.model_dump())
        write_json(session_id, "plan_status.json", {"status": "done"})
        print(f"[plan] Done — {len(plan.tasks)} tasks")
    except Exception as e:
        traceback.print_exc()
        write_json(session_id, "plan_status.json", {"status": "error", "message": str(e)})


@app.post("/api/plan/{session_id}/generate")
async def generate_plan_endpoint(session_id: str):
    get_session_or_404(session_id)
    report_data = read_json(session_id, "report.json")
    if not report_data:
        raise HTTPException(400, "Audit not complete — wait for audit to finish first")

    status = read_json(session_id, "plan_status.json") or {}
    if status.get("status") == "generating":
        return {"status": "generating"}

    task = asyncio.create_task(_generate_plan_bg(session_id, report_data))
    _plan_tasks[session_id] = task
    return {"status": "generating"}


@app.get("/api/plan/{session_id}")
async def get_plan(session_id: str):
    get_session_or_404(session_id)
    status = read_json(session_id, "plan_status.json") or {}
    if status.get("status") == "generating":
        return {"status": "generating"}
    if status.get("status") == "error":
        raise HTTPException(500, status.get("message", "Plan generation failed"))
    plan = read_json(session_id, "plan.json")
    if not plan:
        raise HTTPException(404, "Plan not generated yet — call /generate first")
    return plan


class ApprovePlanRequest(BaseModel):
    skip_task_ids: list[str] = []


@app.post("/api/plan/{session_id}/approve")
async def approve_plan(session_id: str, req: ApprovePlanRequest):
    get_session_or_404(session_id)
    plan = read_json(session_id, "plan.json")
    if not plan:
        raise HTTPException(404, "No plan to approve")

    for task in plan["tasks"]:
        if task["id"] in req.skip_task_ids:
            task["status"] = "skipped"

    plan["approved_at"] = datetime.now(timezone.utc).isoformat()
    write_json(session_id, "approved_plan.json", plan)
    write_json(session_id, "task_log.json", {"tasks": [], "session_id": session_id})
    return {"approved": True, "tasks": len(plan["tasks"])}


# ── Execute ──────────────────────────────────────────────────────────────────

@app.post("/api/execute/{session_id}/preview")
async def preview_task_endpoint(session_id: str, req: PreviewTaskRequest):
    """
    Generate what the task WOULD do — current values + Claude suggestions — without touching anything.
    Frontend shows this for human review/editing before calling /task to apply.
    """
    get_session_or_404(session_id)
    plan_data = read_json(session_id, "approved_plan.json")
    if not plan_data:
        raise HTTPException(400, "Plan not approved")

    task_data = next((t for t in plan_data["tasks"] if t["id"] == req.task_id), None)
    if not task_data:
        raise HTTPException(404, f"Task {req.task_id} not found")

    task = Task(**task_data)
    needs_wp = task.platform_action.startswith("wp_")

    if needs_wp and not (req.wp_url and req.wp_username and req.wp_app_password):
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
        req.wp_url or "",
        req.wp_username or "",
        req.wp_app_password or "",
    )
    return result.model_dump()


@app.get("/api/execute/{session_id}/manual/{task_id}")
async def manual_instructions(session_id: str, task_id: str):
    """
    Returns step-by-step manual instructions for a task so the user can
    do it themselves without providing credentials.
    """
    get_session_or_404(session_id)
    plan_data = read_json(session_id, "approved_plan.json")
    if not plan_data:
        raise HTTPException(400, "Plan not approved")

    task_data = next((t for t in plan_data["tasks"] if t["id"] == task_id), None)
    if not task_data:
        raise HTTPException(404, f"Task {task_id} not found")

    task = Task(**task_data)
    meta = read_json(session_id, "meta.json") or {}
    site_url = meta.get("url", "your site")

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
async def execute_task_endpoint(session_id: str, req: ExecuteTaskRequest):
    get_session_or_404(session_id)
    plan_data = read_json(session_id, "approved_plan.json")
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
        write_json(session_id, "approved_plan.json", plan_data)
        result = TaskResult(task_id=req.task_id, status="skipped", action_taken="Skipped by user")
        log = read_json(session_id, "task_log.json") or {"tasks": []}
        log["tasks"].append(result.model_dump())
        write_json(session_id, "task_log.json", log)
        return result.model_dump()

    needs_wp = task.platform_action.startswith("wp_")

    if needs_wp and not (req.wp_url and req.wp_username and req.wp_app_password):
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
            wp_url=req.wp_url or "",
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
    write_json(session_id, "approved_plan.json", plan_data)

    # Append to task log
    log = read_json(session_id, "task_log.json") or {"tasks": []}
    log["tasks"].append(result.model_dump())
    write_json(session_id, "task_log.json", log)

    return result.model_dump()


@app.get("/api/execute/{session_id}/status")
async def execution_status(session_id: str):
    get_session_or_404(session_id)
    plan = read_json(session_id, "approved_plan.json")
    log = read_json(session_id, "task_log.json") or {"tasks": []}
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
async def get_session(session_id: str):
    get_session_or_404(session_id)
    return read_json(session_id, "meta.json")
