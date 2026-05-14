"""
Plan generator — takes audit findings and produces a 30-day task plan via Claude.
"""

import re
import json
from datetime import datetime, timezone

import anthropic

from models import AuditReport, Task, Plan


PLAN_SYSTEM = """You are a senior SEO strategist building a 30-day execution plan. You are passionate and thorough — every task must be specific, actionable, and genuinely move the needle.

Given an audit report, generate a prioritized list of SEO tasks.

PRIORITY RULES (strictly follow):
- Week 1 MUST include:
  1. Competitor gap analysis task (action: outreach_find_prospects, titled "Competitor Analysis & Gap Identification")
  2. Google Business Profile review/setup task (action: geo_update_ai_meta, titled "Google Business Profile Optimisation")
  3. Critical technical fixes (wp_update_meta for pages with missing/poor meta, wp_add_schema where schema is missing, wp_update_sitemap)
- Week 2: On-page optimisation (meta, canonical, schema, headings) for all key pages
- Week 3: Content improvements (rewrites, new content, internal links)
- Week 4: Off-page and AI visibility (backlinks, llms.txt, outreach)
- Max 25 tasks total — quality over quantity, pick the highest-value ones
- priority_score = impact × (10 - effort)
- platform_action must be one of:
  wp_update_meta, wp_update_content, wp_add_schema, wp_update_sitemap,
  wp_update_robots, wp_set_canonical, wp_publish_post, wp_update_image_alt,
  wp_update_internal_links, content_write, content_rewrite,
  outreach_find_prospects, outreach_send_emails, geo_create_llms_txt, geo_update_ai_meta

QUALITY RULES:
- description must explain EXACTLY what will change and WHY it matters for this specific site
- For competitor tasks: name 2-3 specific competitor types to research based on the site's niche
- For Google Business tasks: list the specific GBP fields to complete (category, description, posts, Q&A, photos)
- For meta tasks: specify which page and what the current problem is (missing, too short, not keyword-focused)
- No generic filler — every task should read as if written by someone who studied this site

Return ONLY a JSON array of tasks. Each task:
{
  "id": "T001",
  "week": 1,
  "title": "short action title",
  "description": "specific description of what changes and why",
  "platform_action": "wp_update_meta",
  "impact": 8,
  "effort": 2,
  "priority_score": 64,
  "estimated_minutes": 5,
  "target_url": "https://example.com/about"
}"""


def _valid_task_json(s: str) -> bool:
    try:
        d = json.loads(s)
        return isinstance(d, dict) and "title" in d
    except Exception:
        return False


async def generate_plan(report: AuditReport) -> Plan:
    client = anthropic.AsyncAnthropic()

    # Build compact findings summary for the prompt
    findings_summary = []
    for domain, audit in report.domains.items():
        if audit.status == "done":
            for f in audit.findings:
                findings_summary.append({
                    "category": str(f.category),
                    "title": str(f.title),
                    "severity": str(f.severity.value if hasattr(f.severity, "value") else f.severity),
                    "impact": int(f.impact),
                    "effort": int(f.effort),
                    "recommendation": str(f.recommendation),
                    "affected_url": f.affected_urls[0] if f.affected_urls else report.url,
                })

    # Sort by impact desc
    findings_summary.sort(key=lambda x: -x["impact"])

    print(f"[planner] Generating plan for {report.url} with {len(findings_summary)} findings")

    msg = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=6000,
        system=PLAN_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"""Build a 30-day SEO plan for: {report.url}
Platform: {report.platform}
Overall score: {report.overall_score}/100

CRITICAL REQUIREMENT: Week 1 MUST start with:
1. Competitor Analysis task (action: outreach_find_prospects)
2. Google Business Profile task (action: geo_update_ai_meta)
Then technical fixes based on the findings below.

All findings from the audit ({len(findings_summary)} total, showing top {min(len(findings_summary), 20)} by impact):
{json.dumps(findings_summary[:20], indent=2, default=str)}

Study the findings carefully. Make every task description specific to what was found on {report.url}.
Return the task plan as a JSON array only — no explanation, no markdown."""
        }]
    )
    print(f"[planner] Claude responded, parsing tasks...")

    text = msg.content[0].text.strip()
    m = re.search(r'\[[\s\S]*', text)
    if not m:
        return Plan(
            session_id=report.session_id,
            url=report.url,
            platform=report.platform,
            generated_at=datetime.now(timezone.utc).isoformat(),
            tasks=[],
        )

    json_text = m.group(0)
    # Try clean parse first; if truncated, salvage complete objects before the cut
    try:
        raw_tasks = json.loads(json_text if json_text.rstrip().endswith("]") else json_text + "]")
    except json.JSONDecodeError:
        # Extract every complete {...} block
        raw_tasks = re.findall(r'\{[^{}]*\}', json_text)
        raw_tasks = [json.loads(t) for t in raw_tasks if _valid_task_json(t)]
    print(f"[planner] Parsed {len(raw_tasks)} raw tasks from Claude")
    tasks = []
    for i, t in enumerate(raw_tasks):
        if not isinstance(t, dict):
            continue
        t.setdefault("id", f"T{i+1:03d}")
        t.setdefault("status", "pending")
        t.setdefault("target_url", report.url)
        t.setdefault("estimated_minutes", 5)
        t.setdefault("description", t.get("title", ""))
        t.setdefault("platform_action", "wp_update_meta")
        # Coerce numeric fields — Claude sometimes returns strings
        for int_field in ("week", "impact", "effort", "estimated_minutes"):
            try:
                t[int_field] = int(t.get(int_field, 1))
            except (TypeError, ValueError):
                t[int_field] = 1
        try:
            t["priority_score"] = float(t.get("priority_score", t["impact"] * (10 - t["effort"])))
        except (TypeError, ValueError):
            t["priority_score"] = 5.0
        try:
            tasks.append(Task(**t))
        except Exception as e:
            print(f"[planner] Skipping task {i}: {e} — {t}")
            continue

    return Plan(
        session_id=report.session_id,
        url=report.url,
        platform=report.platform,
        generated_at=datetime.now(timezone.utc).isoformat(),
        tasks=tasks,
    )
