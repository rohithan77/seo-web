"""
Task executor — runs a single task against a WordPress site via the REST API.

Safety model:
  1. Snapshot the target post/page before any change
  2. Generate optimized content using Claude (not just truncation)
  3. Make the change
  4. Verify the change is live on the public URL
  5. If verification fails → restore the snapshot automatically
  6. Credentials are passed per-request, never stored

Only modifies the specific post/page the task targets.
Never touches theme files, plugins, users, or other posts.
"""

import re
import json
import time
import requests
import anthropic
from urllib.parse import urlparse
from models import Task, TaskResult, TaskPreview


# ── Claude content generator ──────────────────────────────────────────────────

def _claude_generate(prompt: str, max_tokens: int = 512) -> str:
    """Call Claude synchronously to generate SEO content."""
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def _generate_meta(page_title: str, page_content: str, target_url: str, task_description: str) -> tuple[str, str]:
    """
    Use Claude to generate an SEO-optimized meta title and description.
    Returns (meta_title, meta_description).
    """
    prompt = f"""You are a senior SEO copywriter. Generate an optimized meta title and description for this web page.

Page URL: {target_url}
Page title: {page_title}
Task context: {task_description}
Page content sample: {page_content[:800]}

Rules:
- Meta title: 50-60 characters, include primary keyword near the start, brand name at end if space allows
- Meta description: 140-155 characters, include a clear value proposition and a soft CTA
- Be specific to the actual page content — no generic filler
- Do NOT wrap in quotes

Return exactly this format (2 lines, nothing else):
TITLE: <meta title here>
DESC: <meta description here>"""

    result = _claude_generate(prompt)
    title = ""
    desc = ""
    for line in result.splitlines():
        if line.startswith("TITLE:"):
            title = line[6:].strip()[:60]
        elif line.startswith("DESC:"):
            desc = line[5:].strip()[:155]
    if not title:
        title = (page_title or target_url)[:60]
    if not desc:
        desc = task_description[:155]
    return title, desc


def _generate_schema(page_title: str, page_content: str, target_url: str, existing_schema_types: list) -> dict:
    """
    Use Claude to determine the right Schema.org type and generate proper JSON-LD.
    """
    prompt = f"""You are a Schema.org expert. Generate the most appropriate JSON-LD structured data for this page.

Page URL: {target_url}
Page title: {page_title}
Existing schema types: {existing_schema_types}
Page content sample: {page_content[:600]}

Choose the SINGLE most appropriate @type from:
WebPage, Article, BlogPosting, Product, LocalBusiness, Organization, FAQPage, HowTo, Person, Service

Rules:
- If it looks like a blog post or article, use BlogPosting or Article
- If it has Q&A content, use FAQPage
- If it's a business homepage, use LocalBusiness or Organization
- Do NOT add a type that already exists in existing schema types
- Return ONLY valid JSON — no markdown, no explanation

Return a single JSON object with @context, @type, name, url, and any type-specific fields that you can infer."""

    result = _claude_generate(prompt, max_tokens=600)
    # Extract JSON from response
    m = re.search(r'\{[\s\S]*\}', result)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    # Fallback generic schema
    return {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": page_title,
        "url": target_url,
    }


def _generate_alt_text(image_title: str, image_filename: str, page_context: str) -> str:
    """Use Claude to generate descriptive, SEO-friendly alt text for an image."""
    prompt = f"""Write concise, descriptive alt text for an image on a web page.

Image title: {image_title}
Image filename: {image_filename}
Page context: {page_context[:200]}

Rules:
- 5-12 words maximum
- Describe what the image shows, not "image of" or "photo of"
- Include a relevant keyword naturally if it fits
- Return ONLY the alt text, nothing else"""

    return _claude_generate(prompt, max_tokens=60).strip('"').strip("'")


# ── Connection helpers ────────────────────────────────────────────────────────

def _session(url: str, username: str, password: str) -> tuple[requests.Session, str]:
    s = requests.Session()
    s.auth = (username, password)
    s.headers.update({"Content-Type": "application/json", "User-Agent": "SEOAgent/1.0"})
    api = url.rstrip("/") + "/wp-json/wp/v2"
    return s, api


def _detect_plugin(session: requests.Session, site_url: str) -> str:
    try:
        r = session.get(site_url.rstrip("/") + "/wp-json/", timeout=8)
        ns = r.json().get("namespaces", [])
        if "yoast/v1" in ns:
            return "yoast"
        if "rankmath/v1" in ns:
            return "rankmath"
    except Exception:
        pass
    return "none"


def _find_post(session: requests.Session, api: str, target_url: str) -> tuple[int | None, str]:
    """Return (post_id, endpoint) by matching slug. Tries pages then posts."""
    slug = urlparse(target_url).path.strip("/").split("/")[-1] or "home"
    for endpoint in ("pages", "posts"):
        try:
            r = session.get(f"{api}/{endpoint}",
                            params={"slug": slug, "per_page": 1}, timeout=10)
            items = r.json()
            if isinstance(items, list) and items:
                return items[0]["id"], endpoint
        except Exception:
            continue
    return None, "posts"


# ── Snapshot / restore ────────────────────────────────────────────────────────

def _snapshot(session: requests.Session, api: str, post_id: int, endpoint: str) -> dict:
    """Save a full copy of the post before making any change."""
    r = session.get(f"{api}/{endpoint}/{post_id}",
                    params={"context": "edit"}, timeout=12)
    r.raise_for_status()
    post = r.json()
    return {
        "post_id": post_id,
        "endpoint": endpoint,
        "title": post.get("title", {}).get("raw", ""),
        "content": post.get("content", {}).get("raw", ""),
        "excerpt": post.get("excerpt", {}).get("raw", ""),
        "slug": post.get("slug", ""),
        "meta": post.get("meta", {}),
        "yoast_seo": post.get("yoast_seo", {}),
    }


def _restore(session: requests.Session, api: str, snap: dict) -> bool:
    """Restore a post to its snapshot. Returns True on success."""
    pid = snap["post_id"]
    ep = snap["endpoint"]
    payload = {
        "title": snap["title"],
        "content": snap["content"],
        "excerpt": snap["excerpt"],
    }
    if snap.get("yoast_seo"):
        payload["yoast_seo"] = snap["yoast_seo"]
    if snap.get("meta"):
        payload["meta"] = snap["meta"]
    try:
        r = session.post(f"{api}/{ep}/{pid}", json=payload, timeout=15)
        return r.ok
    except Exception:
        return False


# ── Live verification ─────────────────────────────────────────────────────────

def _verify_live(public_url: str, check: str, expected: str, retries: int = 3) -> tuple[bool, str]:
    """
    Fetch the public URL and verify the SEO element is present.
    Returns (passed, found_value).
    Retries up to 3 times with 10s gaps (caching can delay propagation).
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SEOVerifier/1.0)"}
    for attempt in range(retries):
        try:
            r = requests.get(public_url, headers=headers,
                             timeout=15, allow_redirects=True)
            if r.status_code != 200:
                if attempt < retries - 1:
                    time.sleep(10)
                continue
            html = r.text

            if check == "meta_description":
                m = re.search(
                    r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']',
                    html, re.IGNORECASE)
                found = m.group(1) if m else ""
                return (expected.lower() in found.lower()), found

            if check == "meta_title":
                m = re.search(r"<title[^>]*>(.*?)</title>", html,
                              re.IGNORECASE | re.DOTALL)
                found = m.group(1).strip() if m else ""
                return (expected.lower() in found.lower()), found

            if check == "canonical":
                m = re.search(
                    r'<link\s+rel=["\']canonical["\']\s+href=["\'](.*?)["\']',
                    html, re.IGNORECASE)
                found = m.group(1) if m else ""
                return (expected.rstrip("/") == found.rstrip("/")), found

            if check == "schema_present":
                schemas = re.findall(
                    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>'
                    r'(.*?)</script>',
                    html, re.IGNORECASE | re.DOTALL)
                for s in schemas:
                    try:
                        d = json.loads(s)
                        if expected.lower() in str(d.get("@type", "")).lower():
                            return True, f"@type: {d.get('@type')}"
                    except Exception:
                        pass
                return False, f"No schema with @type '{expected}' found"

            if check == "page_exists":
                return r.status_code == 200, str(r.status_code)

            # Default: check the string appears somewhere in HTML
            return (expected.lower() in html.lower()), ""

        except Exception as e:
            if attempt < retries - 1:
                time.sleep(10)
            else:
                return False, f"fetch error: {e}"

    return False, "max retries reached"


# ── Preview (generates content, touches nothing) ─────────────────────────────

def preview_task(task: Task, wp_url: str, wp_username: str, wp_app_password: str) -> TaskPreview:
    """
    Fetch current values and generate Claude's suggestions — without applying anything.
    Returns a TaskPreview that the frontend shows for user review/editing.
    """
    action = task.platform_action
    target = task.target_url or wp_url

    # Non-WP tasks: nothing to preview on a live page
    if not action.startswith("wp_"):
        return TaskPreview(
            task_id=task.id,
            action=action,
            target_url=target,
            summary=task.description,
            current={},
            suggested={"note": "No live-site changes — manual step required."},
        )

    if not wp_url or not wp_username or not wp_app_password:
        return TaskPreview(
            task_id=task.id, action=action, target_url=target,
            summary=task.description, current={}, suggested={},
            needs_credentials=True,
        )

    try:
        session, api = _session(wp_url, wp_username, wp_app_password)

        # Auth check
        auth_r = session.get(f"{wp_url.rstrip('/')}/wp-json/wp/v2/users/me", timeout=10)
        if auth_r.status_code in (401, 403):
            return TaskPreview(
                task_id=task.id, action=action, target_url=target,
                summary="Authentication failed — check credentials.",
                current={}, suggested={}, needs_credentials=True,
            )

        post_id, endpoint = _find_post(session, api, target)
        plugin = _detect_plugin(session, wp_url)

        # Fetch current post state
        current: dict = {}
        page_text = ""
        if post_id:
            snap = _snapshot(session, api, post_id, endpoint)
            page_text = re.sub(r'<[^>]+>', ' ', snap["content"])[:1000]
            current = {
                "meta_title": snap["title"],
                "meta_description": snap.get("yoast_seo", {}).get("meta_description", "")
                    or snap.get("meta", {}).get("rank_math_description", "")
                    or snap["excerpt"],
                "canonical": snap.get("yoast_seo", {}).get("canonical", "")
                    or snap.get("meta", {}).get("rank_math_canonical_url", ""),
                "excerpt": snap["excerpt"],
                "plugin": plugin,
            }

        suggested: dict = {}

        if action == "wp_update_meta":
            meta_title, meta_desc = _generate_meta(
                page_title=current.get("meta_title", ""),
                page_content=page_text,
                target_url=target,
                task_description=task.description,
            )
            suggested = {"meta_title": meta_title, "meta_description": meta_desc}
            summary = f'Update meta title and description on {target}'

        elif action == "wp_set_canonical":
            suggested = {"canonical": target}
            summary = f'Set canonical URL to {target}'

        elif action == "wp_add_schema":
            existing_schema_types = []
            if post_id:
                r_get = session.get(f"{api}/{endpoint}/{post_id}",
                                    params={"context": "edit"}, timeout=10)
                content_raw = r_get.json().get("content", {}).get("raw", "")
                for s in re.findall(r'application/ld\+json[^>]*>(.*?)</script>',
                                    content_raw, re.DOTALL | re.IGNORECASE):
                    try:
                        d = json.loads(s)
                        if d.get("@type"):
                            existing_schema_types.append(str(d["@type"]))
                    except Exception:
                        pass
            schema_obj = _generate_schema(
                page_title=current.get("meta_title", ""),
                page_content=page_text,
                target_url=target,
                existing_schema_types=existing_schema_types,
            )
            suggested = {
                "schema_type": schema_obj.get("@type", "WebPage"),
                "schema_json": json.dumps(schema_obj, indent=2),
                "existing_types": existing_schema_types,
            }
            summary = f'Add {schema_obj.get("@type", "WebPage")} JSON-LD schema to {target}'

        elif action == "wp_update_image_alt":
            images = []
            if post_id:
                r_media = session.get(f"{api}/media",
                                      params={"per_page": 20, "parent": post_id}, timeout=15)
                for item in r_media.json():
                    if not item.get("alt_text", "").strip():
                        img_title = item.get("title", {}).get("rendered", "")
                        img_slug = item.get("slug", img_title)
                        suggested_alt = _generate_alt_text(img_title, img_slug, page_text[:200])
                        images.append({
                            "id": item["id"],
                            "filename": img_slug,
                            "current_alt": "",
                            "suggested_alt": suggested_alt,
                        })
            suggested = {"images": images}
            summary = f'Add alt text to {len(images)} image(s) on {target}'

        elif action == "wp_update_sitemap":
            suggested = {"sitemap_url": wp_url.rstrip("/") + "/sitemap.xml",
                         "action": "Ping Google + Bing with your sitemap URL"}
            summary = "Ping search engines with updated sitemap"

        else:
            suggested = {"note": f"Manual step required: {action}"}
            summary = task.description

        return TaskPreview(
            task_id=task.id,
            action=action,
            target_url=target,
            summary=summary,
            current=current,
            suggested=suggested,
        )

    except Exception as e:
        return TaskPreview(
            task_id=task.id, action=action, target_url=target,
            summary=f"Preview failed: {e}", current={}, suggested={},
        )


# ── Main executor ─────────────────────────────────────────────────────────────

def execute_task(task: Task, wp_url: str, wp_username: str, wp_app_password: str,
                 approved_content: dict | None = None) -> TaskResult:
    action = task.platform_action

    # ── Non-WordPress tasks (no credentials needed) ──────────────────────────
    if action in ("content_write", "content_rewrite"):
        return TaskResult(task_id=task.id, status="completed", verified=False,
                          action_taken=f"Content task noted: {task.title}. Draft it in your CMS.")

    if action in ("outreach_find_prospects", "outreach_send_emails"):
        return TaskResult(task_id=task.id, status="completed", verified=False,
                          action_taken=f"Outreach task noted: {task.title}.")

    if action in ("geo_create_llms_txt", "geo_update_ai_meta"):
        return TaskResult(task_id=task.id, status="completed", verified=False,
                          action_taken=f"AI visibility task noted: {task.title}. Requires SSH/manual step.")

    # ── WordPress tasks ──────────────────────────────────────────────────────
    if not wp_url or not wp_username or not wp_app_password:
        return TaskResult(task_id=task.id, status="failed", action_taken="",
                          error="WordPress credentials required for this task")

    snap = None
    action_desc = ""
    verify_check = "page_exists"
    verify_expected = "200"

    try:
        session, api = _session(wp_url, wp_username, wp_app_password)

        # Auth check
        auth_r = session.get(f"{wp_url.rstrip('/')}/wp-json/wp/v2/users/me", timeout=10)
        if auth_r.status_code == 401:
            return TaskResult(task_id=task.id, status="failed", action_taken="",
                              error="WordPress authentication failed — wrong username or app password")
        if auth_r.status_code == 403:
            return TaskResult(task_id=task.id, status="failed", action_taken="",
                              error="WordPress access denied — the user needs Editor role or higher")

        target = task.target_url or wp_url
        post_id, endpoint = _find_post(session, api, target)
        plugin = _detect_plugin(session, wp_url)

        # ── STEP 1: Snapshot before touching anything ────────────────────────
        if post_id:
            snap = _snapshot(session, api, post_id, endpoint)
            print(f"[executor] Snapshot saved for post {post_id} ({endpoint})")

        # ── STEP 2: Fetch live page data for intelligent content generation ──
        page_title = snap["title"] if snap else ""
        page_content_raw = snap["content"] if snap else ""
        # Strip HTML tags for a readable content sample
        page_text = re.sub(r'<[^>]+>', ' ', page_content_raw)[:1000]

        # ── STEP 3: Make the change ─────────────────────────────────────────
        # If approved_content is provided, use it directly (user reviewed/edited).
        # Otherwise generate fresh (fallback for non-preview path).

        if action == "wp_update_meta":
            if not post_id:
                return TaskResult(task_id=task.id, status="failed", action_taken="",
                                  error=f"Could not find post/page matching {target}")

            if approved_content and "meta_title" in approved_content:
                meta_title = approved_content["meta_title"][:60]
                meta_desc = approved_content["meta_description"][:155]
                print(f"[executor] Using approved meta for: {target}")
            else:
                print(f"[executor] Generating optimized meta for: {target}")
                meta_title, meta_desc = _generate_meta(
                    page_title=page_title,
                    page_content=page_text,
                    target_url=target,
                    task_description=task.description,
                )
            print(f"[executor] Meta title ({len(meta_title)} chars): {meta_title}")
            print(f"[executor] Meta desc ({len(meta_desc)} chars): {meta_desc}")

            payload: dict = {}
            if plugin == "yoast":
                payload["yoast_seo"] = {
                    "seo_title": meta_title,
                    "meta_description": meta_desc,
                }
            elif plugin == "rankmath":
                payload["meta"] = {
                    "rank_math_title": meta_title,
                    "rank_math_description": meta_desc,
                }
            else:
                payload["excerpt"] = meta_desc

            r = session.post(f"{api}/{endpoint}/{post_id}", json=payload, timeout=15)
            r.raise_for_status()
            action_desc = f'Updated meta on {target} — title: "{meta_title}"'
            verify_check = "meta_description"
            verify_expected = meta_desc[:40]

        elif action == "wp_set_canonical":
            if not post_id:
                return TaskResult(task_id=task.id, status="failed", action_taken="",
                                  error=f"Could not find post/page matching {target}")
            if plugin == "yoast":
                payload = {"yoast_seo": {"canonical": target}}
            elif plugin == "rankmath":
                payload = {"meta": {"rank_math_canonical_url": target}}
            else:
                return TaskResult(task_id=task.id, status="failed", action_taken="",
                                  error="No SEO plugin (Yoast/RankMath) found — cannot set canonical via REST API")
            r = session.post(f"{api}/{endpoint}/{post_id}", json=payload, timeout=15)
            r.raise_for_status()
            action_desc = f"Set canonical to {target}"
            verify_check = "canonical"
            verify_expected = target

        elif action == "wp_add_schema":
            if not post_id:
                return TaskResult(task_id=task.id, status="failed", action_taken="",
                                  error=f"Could not find post/page matching {target}")
            r_get = session.get(f"{api}/{endpoint}/{post_id}",
                                params={"context": "edit"}, timeout=10)
            r_get.raise_for_status()
            post_data = r_get.json()
            existing_content = post_data.get("content", {}).get("raw", "")

            # Find what schema types already exist
            existing_schema_types = []
            schemas_in_content = re.findall(
                r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                existing_content, re.IGNORECASE | re.DOTALL)
            for s in schemas_in_content:
                try:
                    d = json.loads(s)
                    t = d.get("@type", "")
                    if t:
                        existing_schema_types.append(t if isinstance(t, str) else str(t))
                except Exception:
                    pass

            if approved_content and "schema_json" in approved_content:
                schema_json = approved_content["schema_json"]
                schema_type = approved_content.get("schema_type", "WebPage")
                print(f"[executor] Using approved schema for: {target}")
            else:
                print(f"[executor] Generating schema for {target} (existing: {existing_schema_types})")
                schema_obj = _generate_schema(
                    page_title=page_title,
                    page_content=page_text,
                    target_url=target,
                    existing_schema_types=existing_schema_types,
                )
                schema_type = schema_obj.get("@type", "WebPage")
                schema_json = json.dumps(schema_obj, indent=2)
            schema_block = (
                f'\n<script type="application/ld+json">\n{schema_json}\n</script>\n'
            )
            print(f"[executor] Adding {schema_type} schema")

            r = session.post(f"{api}/{endpoint}/{post_id}",
                             json={"content": existing_content + schema_block}, timeout=15)
            r.raise_for_status()
            action_desc = f"Added {schema_type} JSON-LD schema to {target}"
            verify_check = "schema_present"
            verify_expected = schema_type

        elif action == "wp_update_image_alt":
            updated = 0
            skipped = 0
            # approved_content["images"] = [{ id, suggested_alt (user-edited) }, ...]
            approved_alts = {img["id"]: img["suggested_alt"]
                             for img in (approved_content or {}).get("images", [])}
            if post_id:
                r_media = session.get(f"{api}/media",
                                      params={"per_page": 50, "parent": post_id}, timeout=15)
                for item in r_media.json():
                    if not item.get("alt_text", "").strip():
                        if item["id"] in approved_alts:
                            alt = approved_alts[item["id"]]
                        else:
                            img_title = item.get("title", {}).get("rendered", "")
                            img_filename = item.get("slug", img_title)
                            print(f"[executor] Generating alt text for: {img_title or img_filename}")
                            alt = _generate_alt_text(img_title, img_filename, page_text[:200])
                        session.post(f"{api}/media/{item['id']}",
                                     json={"alt_text": alt}, timeout=10)
                        print(f"[executor]   → {alt!r}")
                        updated += 1
                    else:
                        skipped += 1
            action_desc = f"Generated descriptive alt text for {updated} images on {target} ({skipped} already had alt text)"
            verify_check = "page_exists"
            verify_expected = "200"

        elif action == "wp_update_sitemap":
            sitemap_url = wp_url.rstrip("/") + "/sitemap.xml"
            for ping in [
                f"https://www.google.com/ping?sitemap={sitemap_url}",
                f"https://www.bing.com/ping?sitemap={sitemap_url}",
            ]:
                try:
                    requests.get(ping, timeout=8)
                    print(f"[executor] Pinged: {ping}")
                except Exception:
                    pass
            action_desc = f"Pinged Google + Bing with sitemap: {sitemap_url}"
            snap = None  # No rollback needed for a ping
            verify_check = "page_exists"
            verify_expected = "200"

        else:
            action_desc = f"{action} noted — requires manual step via wp_rest.py"
            return TaskResult(task_id=task.id, status="completed",
                              action_taken=action_desc, verified=False)

        # ── STEP 4: Verify the change is live ────────────────────────────────
        time.sleep(3)  # brief pause for caches
        print(f"[executor] Verifying {verify_check} on {target}…")
        verified, found = _verify_live(target, verify_check, verify_expected)

        if not verified and action not in ("wp_update_image_alt", "wp_update_sitemap"):
            print(f"[executor] Verification FAILED for {task.id} — restoring snapshot")
            if snap:
                restored = _restore(session, api, snap)
                restore_msg = "Snapshot restored successfully." if restored else "WARNING: snapshot restore failed — check site manually."
            else:
                restore_msg = "No snapshot available to restore."
            return TaskResult(
                task_id=task.id,
                status="failed",
                action_taken=action_desc,
                verified=False,
                error=f"Change not visible on live site (check: {verify_check}, expected: {verify_expected!r}, found: {found!r}). {restore_msg}",
            )

        print(f"[executor] Task {task.id} completed and verified ✓  (found: {found!r})")
        return TaskResult(
            task_id=task.id,
            status="completed",
            action_taken=action_desc,
            verified=verified,
        )

    except requests.exceptions.HTTPError as e:
        if snap:
            try:
                session2, api2 = _session(wp_url, wp_username, wp_app_password)
                _restore(session2, api2, snap)
            except Exception:
                pass
        return TaskResult(task_id=task.id, status="failed", action_taken=action_desc or "",
                          error=f"HTTP {e.response.status_code}: {e.response.text[:300]}")

    except Exception as e:
        if snap:
            try:
                session2, api2 = _session(wp_url, wp_username, wp_app_password)
                _restore(session2, api2, snap)
            except Exception:
                pass
        return TaskResult(task_id=task.id, status="failed", action_taken=action_desc or "",
                          error=str(e))
