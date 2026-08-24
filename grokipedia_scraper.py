#!/usr/bin/env python3
"""
Grokipedia Crawler / Scraper
============================
Scrape a Grokipedia page and RECURSIVELY follow the hyperlinks inside the
article, downloading each linked page so you end up with a fully local,
offline-friendly mirror.

Output tree (default in ./grokipedia_mirror/):

    grokipedia_mirror/
    ├── README.md              # master index + per-page link lists
    ├── Hitomila.md            # the start page (rewritten local links)
    ├── pages/
    │   ├── Another_Term.md    # a linked page (rewritten local links)
    │   └── ...
    └── html/
        ├── Hitomila.html      # raw HTML copies of every page
        └── ...

Dependencies:
    pip install requests beautifulsoup4 lxml

For JS-rendered (client-side) pages - recommended for accurate content:
    pip install playwright
    playwright install chromium

Usage:
    # Crawl everything linked from a page (renders each page via browser)
    python grokipedia_crawler.py "https://grokipedia.com/page/Hitomila"

    # Only follow links whose anchor text contains a word/phrase
    python grokipedia_crawler.py "https://grokipedia.com/page/Hitomila" \
        --match "Hitomila" --max-pages 25

    # Force the fast requests-based fetcher (faster, but content may be empty)
    python grokipedia_crawler.py "https://grokipedia.com/page/Hitomila" --static

    # Options
    python grokipedia_crawler.py URL \
        -o mirror/            # output dir
        --max-pages 50        # max pages to download
        --max-depth 4         # max link hops from start
        --match "phrase"      # only follow links whose text contains this
        --no-html             # skip raw .html copies
        --delay 1.0           # seconds between requests (be polite)
        --static              # use requests instead of a real browser
"""

import argparse
import os
import re
import sys
import time
from collections import deque
from datetime import datetime
from urllib.parse import urljoin, urlsplit, unquote, urlparse

import requests
from bs4 import BeautifulSoup, Comment, NavigableString

# Use the built-in parser so no extra library (lxml) is required.
PARSER = "html.parser"

BASE_HOSTS = {"grokipedia.com", "www.grokipedia.com"}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

CONTENT_SELECTORS = [
    "article",
    '[itemprop="articleBody"]',
    "main",
    "main article",
    "#content",
    ".prose",
    "[data-testid='article']",
]


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
def fetch(url: str, timeout: int = 30):
    """Static fetch via requests. Returns (html, soup)."""
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    html = resp.text
    soup = BeautifulSoup(html, PARSER)
    return html, soup


def fetch_rendered(url: str, timeout: int = 60000, settle_ms: int = 2000):
    """Client-rendered fetch via a headless browser. Returns (html, soup)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.stderr.write(
            "[warn] playwright not installed; falling back to static requests fetch.\n"
        )
        return fetch(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout)
        page.wait_for_timeout(settle_ms)
        html = page.content()
        browser.close()
    soup = BeautifulSoup(html, PARSER)
    return html, soup


def clean_text(text: str) -> str:
    return " ".join(text.split())


def find_main_content(soup: BeautifulSoup):
    for sel in CONTENT_SELECTORS:
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) > 500:
            return el
    best, best_len = None, 0
    for c in soup.find_all(["div", "section", "article", "main"]):
        t = len(c.get_text(strip=True))
        if t > best_len and t > 800:
            best, best_len = c, t
    return best


def get_title(soup: BeautifulSoup) -> str:
    if soup.title and soup.title.string and soup.title.string.strip():
        return soup.title.string.strip()
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    h1 = soup.find("h1")
    if h1:
        return clean_text(h1.get_text())
    return "Grokipedia Article"


# --------------------------------------------------------------------------- #
# URL / slug helpers
# --------------------------------------------------------------------------- #
def slugify_path(path: str):
    m = re.search(r"^/page/(.+?)(?:/|\?|$)", path)
    if not m:
        return None
    raw = unquote(m.group(1))
    s = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_")
    return s or "article"


def canonical(url: str) -> str:
    u = urlsplit(url)
    netloc = u.netloc.lower()
    path = u.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return f"{u.scheme}://{netloc}{path}"


def make_link_prefix(rel_path: str) -> str:
    """Prefix needed so that '{prefix}pages/<slug>.md' resolves from a file."""
    return "../" if os.path.dirname(rel_path) else ""


def make_resolver(current_url: str, prefix: str):
    """Turn an <a href> into a LOCAL path if it points to a Grokipedia page."""
    def resolve(href: str):
        if not href or href.startswith("#"):
            return href
        abs_url = urljoin(current_url, href)
        p = urlparse(abs_url)
        if p.netloc and p.netloc.lower() not in BASE_HOSTS:
            return None  # external link -> leave as-is
        if not p.path.startswith("/page/"):
            return None
        slug = slugify_path(p.path)
        if not slug:
            return None
        return f"{prefix}pages/{slug}.md"
    return resolve


# --------------------------------------------------------------------------- #
# Link extraction
# --------------------------------------------------------------------------- #
def _safe_join(base, href):
    """urljoin that never raises on weird/empty hrefs."""
    if not href or not href.strip():
        return None
    try:
        return urljoin(base, href)
    except Exception:
        return None


def internal_links(soup, current_url, match=None):
    """Return list of (slug, target_url, anchor_text) for internal pages.

    Gathers links from the rendered <a> tags AND from embedded JSON payloads
    (e.g. __NEXT_DATA__ for Next.js apps that don't server-render their DOM).
    """
    found = {}  # canonical_url -> (slug, target_url, anchor_text)

    # 1) From <a> tags in the DOM
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        joined = _safe_join(current_url, href)
        if joined:
            _add_from_href(found, joined)

    # 2) From embedded JSON payloads in <script> tags (client-rendered pages)
    for script in soup.find_all("script"):
        text = script.string or ""
        for m in re.finditer(r"/page/([^\"'\\)<>\s]+)", text):
            joined = _safe_join(current_url, "/page/" + m.group(1))
            if joined:
                _add_from_href(found, joined)

    out = []
    for slug, url, text in found.values():
        if match and match.lower() not in text.lower():
            continue
        out.append((slug, url, text))
    return out


def _add_from_href(container, abs_url):
    """Record an internal /page/ link into the `found` dict (deduped)."""
    p = urlparse(abs_url)
    if p.netloc and p.netloc.lower() not in BASE_HOSTS:
        return
    if not p.path.startswith("/page/"):
        return
    slug = slugify_path(p.path)
    if not slug:
        return
    if abs_url in container:
        return
    container[abs_url] = (slug, abs_url, "")


# --------------------------------------------------------------------------- #
# MD conversion (recursive)
# --------------------------------------------------------------------------- #
def render_list(list_el, ordered: bool, base_indent: str) -> str:
    lines = []
    marker_fmt = "%d." if ordered else "-"
    for i, li in enumerate(list_el.find_all("li", recursive=False), 1):
        marker = marker_fmt.format(i)
        chunks = []
        for child in li.children:
            if isinstance(child, NavigableString):
                s = str(child).strip()
                if s:
                    chunks.append(s)
            elif child.name not in ("ul", "ol"):
                chunks.append(element_to_md(child).strip())
        text = clean_text(" ".join(c for c in chunks if c))
        if text:
            lines.append(f"{base_indent}{marker} {text}")
        for nested in li.find_all(("ul", "ol")):
            lines.append(render_list(nested, nested.name == "ol", base_indent + "  "))
    return "\n".join(lines)


def element_to_md(element, resolve_href=None) -> str:
    parts = []
    for child in element.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            text = str(child).strip("\n").strip()
            if text:
                parts.append(text)
            continue

        tag = child.name
        if tag in ("script", "style"):
            continue

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            text = clean_text(child.get_text())
            if text:
                parts.append(f"\n{'#' * level} {text}\n")

        elif tag == "p":
            text = clean_text(child.get_text())
            if text:
                parts.append(f"\n{text}\n")

        elif tag in ("ul", "ol"):
            rendered = render_list(child, tag == "ol", base_indent="")
            if rendered:
                parts.append(f"\n{rendered}\n")

        elif tag == "a":
            href = child.get("href", "").strip()
            text = clean_text(child.get_text())
            if href:
                local = resolve_href(href) if resolve_href else None
                target = local if local else href
                parts.append(f"[{text or href}]({target})")

        elif tag == "img":
            src = child.get("src", "").strip()
            alt = child.get("alt", "").strip()
            if src:
                parts.append(f"\n![{alt}]({src})\n")

        elif tag in ("blockquote", "figure"):
            inner = clean_text(child.get_text())
            if inner:
                quoted = "\n".join(f"> {line}" for line in inner.split("\n") if line.strip())
                parts.append(f"\n{quoted}\n")

        elif tag == "pre":
            code = child.get_text()
            lang = ""
            for c in child.get("class", []):
                if c.startswith("language-"):
                    lang = c.split("-", 1)[1]
                    break
            parts.append(f"\n```{lang}\n{code.strip()}\n```\n")

        elif tag in ("br", "hr"):
            parts.append("\n" if tag == "hr" else "\n")

        else:
            sub = element_to_md(child).strip()
            if sub:
                parts.append(sub)

    return " ".join(parts)


# --------------------------------------------------------------------------- #
# Crawler
# --------------------------------------------------------------------------- #
class GrokipediaCrawler:
    def __init__(self, start_url, output_dir, max_pages=30, max_depth=4,
                 delay=0.5, match=None, include_html=True, use_render=True):
        self.start_url = start_url if start_url.startswith("http") else "https://" + start_url
        self.output_dir = output_dir
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.delay = delay
        self.match_phrase = match
        self.include_html = include_html
        self.use_render = use_render

        self.pages = {}      # canonical_url -> meta dict
        self.link_index = {} # slug -> set(linked slugs)
        self.visited = set()
        self.queued = set()

    def crawl(self):
        queue = deque([(self.start_url, 0)])
        self.queued.add(canonical(self.start_url))

        while queue and len(self.pages) < self.max_pages:
            url, depth = queue.popleft()
            can = canonical(url)
            if can in self.visited or depth > self.max_depth:
                continue
            self.visited.add(can)

            try:
                if self.use_render:
                    html, soup = fetch_rendered(url)
                else:
                    html, soup = fetch(url)
            except Exception as e:  # noqa: BLE001
                print(f"[warn] failed to fetch {url}: {e}", file=sys.stderr)
                continue

            content_el = find_main_content(soup)
            content_el = content_el or (soup.body or soup)

            slug = slugify_path(urlsplit(url).path) or "index"
            rel = f"{slug}.md" if depth == 0 else os.path.join("pages", f"{slug}.md")
            prefix = make_link_prefix(rel)
            resolve = make_resolver(url, prefix)

            md = element_to_md(content_el, resolve_href=resolve).strip()
            links = internal_links(soup, url, match=self.match_phrase)
            link_slugs = {s for s, _, _ in links}

            # Diagnostic: shows how many links were found per page.
            print(f"[debug] {url} -> {len(links)} internal link(s) found",
                  file=sys.stderr)

            self.pages[can] = {
                "md": md,
                "html": html,
                "slug": slug,
                "depth": depth,
                "rel": rel,
                "title": get_title(soup),
                "links": link_slugs,
            }
            self.link_index[slug] = link_slugs

            for _, target, _ in links:
                tc = canonical(target)
                if tc not in self.visited and tc not in self.queued:
                    self.queued.add(tc)
                    queue.append((target, depth + 1))

            if self.delay:
                time.sleep(self.delay)

    def _slug_to_rel(self, slug: str) -> str:
        if slug == self.start_slug:
            return f"{slug}.md"
        return os.path.join("pages", f"{slug}.md")

    def build(self):
        self.start_slug = next(
            (d["slug"] for d in self.pages.values() if d["depth"] == 0), "index"
        )

        html_dir = os.path.join(self.output_dir, "html")
        pages_dir = os.path.join(self.output_dir, "pages")
        os.makedirs(html_dir, exist_ok=True)
        os.makedirs(pages_dir, exist_ok=True)

        # raw HTML copies
        for data in self.pages.values():
            if not self.include_html:
                break
            with open(os.path.join(html_dir, f"{data['slug']}.html"),
                      "w", encoding="utf-8") as f:
                f.write(data["html"])

        # markdown files (links already rewritten to local during crawl)
        for data in self.pages.values():
            dest = os.path.join(self.output_dir, data["rel"])
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            header = (
                f"# {data['title']}\n\n"
                f"> Source: https://grokipedia.com/page/{data['slug']}\n"
                f"> Scraped: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"---\n\n"
            )
            with open(dest, "w", encoding="utf-8") as f:
                f.write(header + data["md"] + "\n")

        self._write_readme()
        return len(self.pages)

    def _write_readme(self):
        lines = [
            "# Grokipedia Local Mirror",
            "",
            f"**Start page:** [{self.start_slug}]({self.start_slug}.md)",
            f"**Pages downloaded:** {len(self.pages)}",
            "",
            "---",
            "",
            "## All Pages",
            "",
        ]
        for data in sorted(self.pages.values(), key=lambda d: (d["depth"], d["slug"])):
            lines.append(f"- **[{data['title'] or data['slug']}]({data['rel']})**"
                         f"  _(depth {data['depth']})_")

        lines += ["", "## Links Found Per Page", ""]
        for data in sorted(self.pages.values(), key=lambda d: (d["depth"], d["slug"])):
            targets = {s for s in data["links"] if s != data["slug"]}
            if not targets:
                continue
            lines.append(f"### [{data['title'] or data['slug']}]({data['rel']})")
            for slug in sorted(targets):
                lines.append(f"- → **[{slug}]({self._slug_to_rel(slug)})**")
            lines.append("")

        with open(os.path.join(self.output_dir, "README.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines).rstrip() + "\n")


def main():
    ap = argparse.ArgumentParser(
        description="Crawl a Grokipedia page to local Markdown.")
    ap.add_argument("url", help="Grokipedia page URL (or bare slug like 'Hitomila')")
    ap.add_argument("-o", "--output-dir", default="grokipedia_mirror")
    ap.add_argument("--max-pages", type=int, default=30)
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument("--delay", type=float, default=0.5,
                    help="seconds to wait between requests")
    ap.add_argument("--match", default=None,
                    help="only follow links whose text contains this phrase")
    ap.add_argument("--no-html", action="store_true",
                    help="skip raw .html copies")
    ap.add_argument("--static", action="store_true",
                    help="use the fast requests fetcher instead of a browser "
                         "(faster, but page content may be empty on JS-rendered sites)")
    args = ap.parse_args()

    crawler = GrokipediaCrawler(
        start_url=args.url,
        output_dir=args.output_dir,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        delay=args.delay,
        match=args.match,
        include_html=not args.no_html,
        use_render=not args.static,
    )
    crawler.crawl()
    n = crawler.build()
    print(f"[done] Crawled {n} page(s) -> {os.path.abspath(args.output_dir)}")
    print(f"       Open {os.path.join(args.output_dir, 'README.md')} to navigate.")


if __name__ == "__main__":
    main()
