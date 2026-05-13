"""
Audit engine — fetches page data and calls Claude to generate findings.
Each domain runs concurrently via asyncio.gather().
"""

import re
import json
import time
import asyncio
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
import anthropic

from models import Finding, AuditDomain, AuditReport, Severity


HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SEOAuditBot/1.0)"}

FINDING_SCHEMA = """Return ONLY a JSON array. Each element must have exactly these keys:
{
  "id": "F001",
  "category": "technical",
  "title": "short issue title",
  "detail": "what is wrong and where",
  "severity": "critical|high|medium|low",
  "impact": 8,
  "effort": 2,
  "affected_urls": [],
  "recommendation": "exact fix the user should apply"
}"""


# ── Page fetcher ─────────────────────────────────────────────────────────────

async def fetch_page(url: str) -> dict:
    t0 = time.monotonic()
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        try:
            r = await client.get(url, headers=HEADERS)
            load_ms = int((time.monotonic() - t0) * 1000)
            html = r.text
            soup = BeautifulSoup(html, "lxml")

            title_tag = soup.find("title")
            desc_tag = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
            canonical_tag = soup.find("link", rel="canonical")
            robots_tag = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
            h1s = [h.get_text(strip=True) for h in soup.find_all("h1")]
            h2s = [h.get_text(strip=True) for h in soup.find_all("h2")]
            imgs = soup.find_all("img")
            imgs_no_alt = [i for i in imgs if not i.get("alt", "").strip()]
            internal = [a["href"] for a in soup.find_all("a", href=True)
                        if urlparse(a["href"]).netloc in ("", urlparse(url).netloc)]
            external = [a["href"] for a in soup.find_all("a", href=True)
                        if urlparse(a["href"]).netloc not in ("", urlparse(url).netloc)]
            schemas = re.findall(
                r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                html, re.IGNORECASE | re.DOTALL
            )
            schema_types = []
            for s in schemas:
                try:
                    d = json.loads(s)
                    t = d.get("@type", "")
                    if isinstance(t, list):
                        schema_types.extend(t)
                    elif t:
                        schema_types.append(t)
                except Exception:
                    pass

            # Check sitemap
            sitemap_exists = False
            try:
                sr = await client.get(url.rstrip("/") + "/sitemap.xml", headers=HEADERS)
                sitemap_exists = sr.status_code == 200
            except Exception:
                pass

            # Check robots.txt
            robots_txt = ""
            try:
                rr = await client.get(url.rstrip("/") + "/robots.txt", headers=HEADERS)
                robots_txt = rr.text[:500] if rr.status_code == 200 else "Not found"
            except Exception:
                pass

            return {
                "url": url,
                "status_code": r.status_code,
                "is_https": url.startswith("https://"),
                "final_url": str(r.url),
                "load_time_ms": load_ms,
                "page_size_kb": round(len(html) / 1024, 1),
                "title": title_tag.get_text(strip=True) if title_tag else "",
                "title_length": len(title_tag.get_text(strip=True)) if title_tag else 0,
                "meta_description": desc_tag.get("content", "") if desc_tag else "",
                "meta_description_length": len(desc_tag.get("content", "")) if desc_tag else 0,
                "canonical": canonical_tag.get("href", "") if canonical_tag else "",
                "robots_meta": robots_tag.get("content", "") if robots_tag else "",
                "h1s": h1s,
                "h2s": h2s[:10],
                "images_total": len(imgs),
                "images_no_alt": len(imgs_no_alt),
                "internal_links": len(internal),
                "external_links": len(external),
                "schema_types": schema_types,
                "sitemap_exists": sitemap_exists,
                "robots_txt": robots_txt,
                "html_snippet": html[:3000],
            }
        except Exception as e:
            return {"url": url, "error": str(e), "status_code": 0}


# ── Claude helper ─────────────────────────────────────────────────────────────

async def claude_findings(system: str, user_msg: str, client: anthropic.AsyncAnthropic, prefix: str) -> list[dict]:
    msg = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = msg.content[0].text.strip()
    # Extract JSON array even if Claude adds surrounding text
    m = re.search(r'\[[\s\S]*\]', text)
    if not m:
        return []
    try:
        items = json.loads(m.group(0))
        for i, item in enumerate(items):
            item["id"] = f"{prefix}{i+1:03d}"
        return items
    except Exception:
        return []


def score_from_findings(findings: list[dict]) -> int:
    s = 100
    for f in findings:
        sev = f.get("severity", "low")
        s -= {"critical": 15, "high": 8, "medium": 4, "low": 1}.get(sev, 1)
    return max(0, s)


# ── Domain auditors ───────────────────────────────────────────────────────────

async def technical_audit(page: dict, client: anthropic.AsyncAnthropic) -> list[dict]:
    system = f"""You are a senior technical SEO specialist.
Analyse the website data below and return SEO issues as a JSON array.
Only report real issues. Be specific. Category must be "technical".
{FINDING_SCHEMA}"""

    user = f"""Website technical data:
URL: {page['url']}
HTTPS: {page['is_https']}
HTTP Status: {page['status_code']}
Load time: {page['load_time_ms']}ms
Page size: {page['page_size_kb']}kb
Title: "{page.get('title','')}" ({page.get('title_length',0)} chars)
Meta description: "{page.get('meta_description','')}" ({page.get('meta_description_length',0)} chars)
Canonical: {page.get('canonical','missing')}
Robots meta: {page.get('robots_meta','not set')}
H1 tags ({len(page.get('h1s',[]))}): {page.get('h1s',[])}
H2 tags (first 10): {page.get('h2s',[])}
Images: {page.get('images_total',0)} total, {page.get('images_no_alt',0)} missing alt text
Internal links: {page.get('internal_links',0)}
Schema types found: {page.get('schema_types',[])}
Sitemap.xml: {"found" if page.get('sitemap_exists') else "MISSING"}
Robots.txt: {page.get('robots_txt','not checked')}

Return findings as JSON array only."""
    return await claude_findings(system, user, client, "T")


async def content_audit(page: dict, client: anthropic.AsyncAnthropic) -> list[dict]:
    system = f"""You are a senior content SEO specialist.
Analyse the page content data and return content quality issues as a JSON array.
Category must be "content".
{FINDING_SCHEMA}"""

    soup_text = BeautifulSoup(page.get("html_snippet", ""), "lxml").get_text(separator=" ", strip=True)[:2000]
    user = f"""Page content analysis:
URL: {page['url']}
Title: "{page.get('title','')}"
Meta description: "{page.get('meta_description','')}"
H1: {page.get('h1s',[])}
H2s: {page.get('h2s',[])}
Page visible text sample: {soup_text}
Word count estimate: {len(soup_text.split())} words (from snippet)
Images without alt: {page.get('images_no_alt',0)} of {page.get('images_total',0)}

Return findings as JSON array only."""
    return await claude_findings(system, user, client, "C")


async def keyword_audit(url: str, page: dict, client: anthropic.AsyncAnthropic) -> list[dict]:
    system = f"""You are a keyword strategy specialist.
Analyse the page for keyword optimisation issues. Category must be "keywords".
{FINDING_SCHEMA}"""

    domain = urlparse(url).netloc
    soup_text = BeautifulSoup(page.get("html_snippet", ""), "lxml").get_text(separator=" ", strip=True)[:1500]
    user = f"""Keyword analysis for: {url}
Domain: {domain}
Title: "{page.get('title','')}"
Meta description: "{page.get('meta_description','')}"
H1: {page.get('h1s',[])}
H2s: {page.get('h2s',[])}
Visible content sample: {soup_text}

Identify: missing target keywords in title/meta, keyword cannibalization risk,
thin content, missing semantic keywords, topic focus issues.
Return findings as JSON array only."""
    return await claude_findings(system, user, client, "K")


async def competitor_audit(url: str, page: dict, client: anthropic.AsyncAnthropic) -> list[dict]:
    system = f"""You are a competitive SEO analyst with deep expertise in gap analysis.
Based on the page data, identify what competitors are likely doing better and concrete opportunities to close those gaps.
Think like a strategist who has studied the top 5 sites in this niche.
Category must be "competitors".
{FINDING_SCHEMA}"""

    domain = urlparse(url).netloc
    content_text = BeautifulSoup(page.get('html_snippet',''),'lxml').get_text(separator=' ',strip=True)[:1200]
    user = f"""Competitive gap analysis for: {url}
Domain: {domain}
Site title: "{page.get('title','')}"
Meta description: "{page.get('meta_description','')}"
H1: {page.get('h1s',[])}
H2s: {page.get('h2s',[])}
Schema types present: {page.get('schema_types',[])}
Has sitemap: {page.get('sitemap_exists', False)}
Images total: {page.get('images_total', 0)}, missing alt: {page.get('images_no_alt', 0)}
Content sample: {content_text}

Based on the niche/industry this site is in, identify:
1. What schema types competitors in this space use that this site is missing (FAQ, Review, BreadcrumbList, LocalBusiness, HowTo, etc.)
2. Content gaps — topic clusters, comparison pages, or resource pages competitors likely have
3. Trust signals competitors display that are missing here (testimonials schema, author markup, certifications)
4. Google Business Profile signals — is the business likely using GBP well?
5. Featured snippet opportunities this site is missing
6. Internal linking structure weaknesses

Be specific about the niche and what top-ranking sites in this space would have.
Return 5-7 high-quality findings as JSON array only."""
    return await claude_findings(system, user, client, "CO")


async def backlink_audit(url: str, client: anthropic.AsyncAnthropic) -> list[dict]:
    system = f"""You are a link-building specialist.
Based solely on the domain name and site structure, identify likely backlink issues.
Category must be "backlinks".
{FINDING_SCHEMA}"""

    domain = urlparse(url).netloc
    user = f"""Backlink audit for: {domain}
(Live backlink data not available — provide actionable recommendations based on domain analysis)

Identify: likely no-follow issues, missing link-building strategy,
anchor text diversity needs, internal link equity,
outreach opportunities for this type of site.
Return 3-5 findings as JSON array only."""
    return await claude_findings(system, user, client, "B")


async def geo_audit(url: str, page: dict, client: anthropic.AsyncAnthropic) -> list[dict]:
    system = f"""You are an AI search visibility (GEO/AEO) specialist and Google Business Profile expert.
Analyse the page for AI search engine optimisation issues AND Google Business Profile visibility.
Category must be "ai_visibility".
{FINDING_SCHEMA}"""

    # Check for llms.txt
    llms_txt = False
    try:
        async with httpx.AsyncClient(timeout=8) as client_http:
            r = await client_http.get(url.rstrip("/") + "/llms.txt", headers=HEADERS)
            llms_txt = r.status_code == 200
    except Exception:
        pass

    html_snippet = page.get('html_snippet', '')
    has_faq = "faq" in html_snippet.lower() or "frequently asked" in html_snippet.lower()
    has_list_formatting = any(tag in html_snippet.lower() for tag in ['<table', '<ol', '<ul'])
    local_signals = any(kw in html_snippet.lower() for kw in ['contact', 'address', 'phone', 'location', 'map', 'directions', 'hours'])
    schema_types = page.get('schema_types', [])
    has_local_schema = any(t in str(schema_types) for t in ['LocalBusiness', 'Organization', 'Store', 'Restaurant'])

    user = f"""AI visibility & Google Business Profile audit for: {url}
llms.txt present: {"YES" if llms_txt else "NO — AI crawlers have no content guidance"}
Schema types found: {schema_types}
Has LocalBusiness/Organization schema: {"yes" if has_local_schema else "NO"}
FAQ content visible: {"yes" if has_faq else "no"}
Direct-answer formatting (tables/lists): {"yes" if has_list_formatting else "limited"}
Meta description length: {len(page.get('meta_description', ''))} chars
Local business signals on page: {"yes" if local_signals else "no"}

Identify these specific issues:
1. Google Business Profile — is GBP schema present? Are NAP (Name, Address, Phone) details marked up? Is the business likely missing GBP or under-optimizing it?
2. llms.txt — missing means ChatGPT, Claude, Perplexity don't know what this site wants indexed
3. FAQ schema — missing means no rich results in Google AI Overviews
4. Content passage structure — can AI models extract direct answers from this page?
5. Brand entity markup — is the brand clearly identified with Organization schema?
6. AI citation readiness — does the content have the authority signals AI models use to cite sources?

Return 5-6 high-priority findings as JSON array only."""
    return await claude_findings(system, user, client, "G")


# ── Platform detection ────────────────────────────────────────────────────────

def detect_platform(page: dict) -> str:
    html = page.get("html_snippet", "")
    if "wp-content" in html or "wp-includes" in html:
        return "wordpress"
    if "__NEXT_DATA__" in html:
        return "nextjs"
    if "___gatsby" in html:
        return "gatsby"
    if '<div id="root">' in html:
        return "react"
    return "html"


# ── Main audit orchestrator ───────────────────────────────────────────────────

async def run_audit(url: str, session_id: str, progress_cb=None) -> AuditReport:
    client = anthropic.AsyncAnthropic()

    async def notify(domain: str, status: str, findings: list = None, error: str = None):
        if progress_cb:
            await progress_cb(domain, status, findings or [], error)

    # Fetch page once, share across all auditors
    if progress_cb:
        await notify("page_fetch", "running")
    page = await fetch_page(url)
    if progress_cb:
        await notify("page_fetch", "done")

    platform = detect_platform(page)

    # Run all 6 domain auditors in parallel
    domain_names = ["technical", "content", "keywords", "competitors", "backlinks", "ai_visibility"]
    for d in domain_names:
        await notify(d, "running")

    results = await asyncio.gather(
        technical_audit(page, client),
        content_audit(page, client),
        keyword_audit(url, page, client),
        competitor_audit(url, page, client),
        backlink_audit(url, client),
        geo_audit(url, page, client),
        return_exceptions=True,
    )

    domains = {}
    all_findings = []
    for name, result in zip(domain_names, results):
        if isinstance(result, Exception):
            domains[name] = AuditDomain(
                name=name, status="error", error=str(result)
            )
            await notify(name, "error", error=str(result))
        else:
            findings = []
            for f in result:
                if not isinstance(f, dict):
                    continue
                try:
                    findings.append(Finding(**f))
                except Exception:
                    pass
            domains[name] = AuditDomain(
                name=name,
                status="done",
                score=score_from_findings(result),
                findings_count=len(findings),
                findings=findings,
            )
            all_findings.extend(findings)
            await notify(name, "done", findings=result)

    overall = score_from_findings([f.model_dump() for f in all_findings])

    return AuditReport(
        session_id=session_id,
        url=url,
        platform=platform,
        audited_at=datetime.now(timezone.utc).isoformat(),
        overall_score=overall,
        domains=domains,
        all_findings=all_findings,
    )
