Script 1 — grokipedia_scraper.py (single page)
python


Grokipedia Scraper
==================
Scrape a Grokipedia page (e.g. https://grokipedia.com/page/page-name)
and convert its main article content into a Markdown file.

Dependencies:
    pip install requests beautifulsoup4 lxml

Usage:
    python grokipedia_scraper.py "https://grokipedia.com/page/page-name"
    python grokipedia_scraper.py "https://grokipedia.com/page/page-name" --output page-name.md
    python grokipedia_scraper.py "https://grokipedia.com/page/page-name" --delay 2 --verbose


import re
import sys
import time
import argparse
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Comment, NavigableString

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
    "article",
    ".prose",
    "[data-testid='article']",
]


def fetch(url: str, timeout: int = 30, delay: float = 0.0):
    """Fetch the page HTML as text, waiting `delay` seconds first."""
    if delay:
        time.sleep(delay)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def clean_text(text: str) -> str:
    return " ".join(text.split())


def candidates(soup: BeautifulSoup):
    return soup.find_all(["div", "section", "article", "main"])


def find_main_content(soup: BeautifulSoup):
    """Pick the best candidate element that holds the article body."""
    # First pass: explicit selectors
    for sel in CONTENT_SELECTORS:
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) > 500:
            return el

    # Fallback: the container with the most textual content.
    best, best_len = None, 0
    for c in candidates(soup):
        t = len(c.get_text(strip=True))
        if t > best_len and t > 800:
            best, best_len = c, t
    return best


def render_list(list_el, ordered: bool, base_indent: str) -> str:
    """Render a <ul>/<ol> (including nested lists) as markdown list lines."""
    lines = []
    marker_fmt = "%d." if ordered else "-"
    items = list_el.find_all("li", recursive=False)
    for i, li in enumerate(items, 1):
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


def element_to_md(element) -> str:
    """Recursively convert a DOM element tree into markdown text."""
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
        if tag == "br":
            parts.append("\n")
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
            ordered = tag == "ol"
            rendered = render_list(child, ordered, base_indent="")
            if rendered:
                parts.append(f"\n{rendered}\n")

        elif tag == "a":
            href = child.get("href", "").strip()
            text = clean_text(child.get_text())
            if href:
                parts.append(f"[{text or href}]({href})")
            elif text:
                parts.append(f"`{text}`")

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

        elif tag == "hr":
            parts.append("\n")

        else:
            # Unknown element: recurse into its children.
            sub = element_to_md(child).strip()
            if sub:
                parts.append(sub)

    return " ".join(parts)


def build_markdown(url: str, html: str, verbose: bool = False) -> str:
    soup = BeautifulSoup(html, "lxml")

    # --- metadata ---
    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = title or og["content"].strip()
    h1 = soup.find("h1")
    title = title or (h1.get_text(strip=True) if h1 else "Grokipedia Article")

    description = None
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        description = og_desc["content"].strip()
    if not description:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            description = meta_desc["content"].strip()

    # --- main content ---
    content_el = find_main_content(soup)
    if content_el is None:
        content_el = soup.body or soup

    body_md = element_to_md(content_el).strip()

    if not body_md:
        body_md = ("<!-- Could not extract visible content. "
                   "The page may be fully client-rendered. "
                   "Try the Playwright version. -->")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    md = (
        f"# {title}\n\n"
        f"> Source: {url}\n"
        f"> Scraped on: {now}\n\n"
    )
    if description:
        md += f"> {description}\n\n"
        md += "---\n\n"
    md += body_md + "\n"

    if verbose:
        sys.stderr.write(
            f"[info] title={title!r} content_chars={len(body_md)}\n"
        )
    return md


def main():
    ap = argparse.ArgumentParser(description="Scrape a Grokipedia page to Markdown.")
    ap.add_argument("url", help="Grokipedia page URL")
    ap.add_argument("-o", "--output", help="Output .md file path", default=None)
    ap.add_argument("--delay", type=float, default=0.0,
                    help="seconds to wait before fetching (default 0)")
    ap.add_argument("-v", "--verbose", action="store_true", help="Print diagnostics")
    args = ap.parse_args()

    if not args.url.startswith(("http://", "https://")):
        args.url = "https://" + args.url

    try:
        html = fetch(args.url, delay=args.delay)
    except Exception as e:
        print(f"[error] Failed to fetch {args.url}: {e}", file=sys.stderr)
        sys.exit(1)

    md = build_markdown(args.url, html, verbose=args.verbose)

    if args.output:
        out_path = args.output
    else:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", urlparse(args.url).path).strip("-") or "article"
        out_path = f"{slug}.md"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"[done] Saved -> {out_path}  ({len(md)} chars)")


if __name__ == "__main__":
    main()
Script 2 — grokipedia_crawler.py (recursive mirror)
This script goes beyond a single page: it follows every internal hyperlink
in the article, rewrites those links to local files, and downloads each
linked page (Markdown + raw HTML), building an offline navigation index.

python

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

Usage:
    # Crawl everything linked from a page
    python grokipedia_crawler.py "https://grokipedia.com/page/Hitomila"

    # Only follow links whose anchor text contains a word/phrase
    python grokipedia_crawler.py "https://grokipedia.com/page/Hitomila" \
        --match "Hitomila" --max-pages 25

    # Options
    python grokipedia_crawler.py URL \
        -o mirror/            # output dir
        --max-pages 50        # max pages to download
        --max-depth 4         # max link hops from start
        --match "phrase"      # only follow links whose text contains this
        --no-html             # skip raw .html copies
        --delay 1.0           # seconds between requests (be polite)
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
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")
    return resp.text, soup


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
def internal_links(soup, current_url, match=None):
    """Return list of (slug, target_url, anchor_text) for internal pages."""
    out = []
    for a in soup.find_all("a", href=True):
        abs_url = urljoin(current_url, a["href"])
        p = urlparse(abs_url)
        if p.netloc and p.netloc.lower() not in BASE_HOSTS:
            continue
        if not p.path.startswith("/page/"):
            continue
        slug = slugify_path(p.path)
        if not slug:
            continue
        text = clean_text(a.get_text())
        if match and match.lower() not in text.lower():
            continue
        out.append((slug, abs_url, text))
    return out


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
                 delay=0.5, match=None, include_html=True):
        self.start_url = start_url if start_url.startswith("http") else "https://" + start_url
        self.output_dir = output_dir
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.delay = delay
        self.match_phrase = match
        self.include_html = include_html

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
    args = ap.parse_args()

    crawler = GrokipediaCrawler(
        start_url=args.url,
        output_dir=args.output_dir,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        delay=args.delay,
        match=args.match,
        include_html=not args.no_html,
    )
    crawler.crawl()
    n = crawler.build()
    print(f"[done] Crawled {n} page(s) -> {os.path.abspath(args.output_dir)}")
    print(f"       Open {os.path.join(args.output_dir, 'README.md')} to navigate.")


if __name__ == "__main__":
    main()
Script 3 — grokipedia_scraper_playwright.py (JavaScript fallback)
Use this when the simple scraper returns an empty body — the page is then
almost certainly rendered client-side by JavaScript.

python

#!/usr/bin/env python3
"""Playwright-based scraper that waits for JS to render, then extracts content."""
import re
import sys
import argparse
from datetime import datetime
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright


def scrape(url: str, out: str):
    with sync_playwright() as p:
        browser = p.chromium.launch()          # use p.chromium.headless() for no window
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2000)              # extra settle time

        md = page.evaluate("""() => {
            const parser = new DOMParser();
            const html = parser.parseFromString(document.body.innerHTML, 'text/html');

            // title
            let title = document.title;
            const og = document.querySelector('meta[property="og:title"]');
            if (og && og.content) title = og.content;
            const h1 = document.querySelector('h1');
            if (!title && h1) title = h1.textContent.trim();

            // main content
            let bodyEl = null;
            for (const sel of ['article','[itemprop="articleBody"]','main','main article','#content']) {
                const el = document.querySelector(sel);
                if (el && el.textContent.trim().length > 500) { bodyEl = el; break; }
            }
            if (!bodyEl) bodyEl = document.body;

            function clean(s){ return s.replace(/\\s+/g,' ').trim(); }

            function lists(el){
                let out = '';
                el.querySelectorAll(':scope > ul, :scope > ol').forEach(list => {
                    const ordered = list.tagName === 'OL';
                    list.querySelectorAll(':scope > li').forEach((li, i) => {
                        const marker = ordered ? (i+1)+'.' : '-';
                        const txt = clean(li.textContent);
                        if (txt) out += marker + ' ' + txt + '\\n';
                        out += lists(li);
                    });
                });
                return out;
            }

            function walk(el){
                let s = '';
                for (const node of el.childNodes) {
                    if (node.nodeType === 3) { s += node.nodeValue; continue; }
                    if (node.nodeType !== 1) continue;
                    const t = node.tagName.toLowerCase();
                    const txt = clean(node.textContent);
                    if (['h1','h2','h3','h4','h5','h6'].includes(t))
                        s += '\\n' + '#'.repeat(parseInt(t[1])) + ' ' + txt + '\\n';
                    else if (t === 'p') s += '\\n' + txt + '\\n';
                    else if (t === 'ul' || t === 'ol') s += '\\n' + lists(node) + '\\n';
                    else if (t === 'a' && node.href) s += '[' + txt + '](' + node.href + ')';
                    else if (t === 'img') s += '\\n![' + node.alt + '](' + node.src + ')\\n';
                    else s += walk(node);
                }
                return s;
            }

            return { title: title, body: walk(bodyEl).replace(/\\n{3,}/g,'\\n\\n').trim() };
        }""")

        browser.close()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out_md = (
        f"# {md['title']}\n\n> Source: {url}\n> Scraped on: {now}\n\n"
        f"---\n\n{md['body']}\n"
    )
    with open(out, "w", encoding="utf-8") as f:
        f.write(out_md)
    print(f"[done] Saved -> {out}  ({len(out_md)} chars)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("-o", "--output", default=None)
    a = ap.parse_args()
    url = a.url if a.url.startswith("http") else "https://" + a.url
    out = a.output or (
        f"{re.sub(r'[^A-Za-z0-9]+','-',urlparse(url).path).strip('-') or 'article'}.md"
    )
    scrape(url, out)
    d
Bash Commands
Script 1 — grokipedia_scraper.py (single page)
bash

# Basic scrape (auto-named from the URL)
python grokipedia_scraper.py "https://grokipedia.com/page/Hitomila"

# Choose a custom output filename
python grokipedia_scraper.py "https://grokipedia.com/page/Hitomila" --output hitomila.md

# Same, using the short flag
python grokipedia_scraper.py "https://grokipedia.com/page/Hitomila" -o hitomila.md

# Wait 2 seconds before fetching (polite scraping)
python grokipedia_scraper.py "https://grokipedia.com/page/Hitomila" --delay 2

# Fractional-second delay + verbose diagnostics
python grokipedia_scraper.py "https://grokipedia.com/page/Hitomila" \
    --delay 1.5 --output hitomila.md --verbose

# Works with a bare slug too (https:// is prepended automatically)
python grokipedia_scraper.py Hitomila
Script 2 — grokipedia_crawler.py (full recursive mirror)
bash

# Crawl everything linked from a page (default: 30 pages, depth 4)
python grokipedia_crawler.py "https://grokipedia.com/page/Hitomila"

# Custom output folder
python grokipedia_crawler.py "https://grokipedia.com/page/Hitomila" -o mirror

# Only follow links whose anchor text contains a word/phrase
python grokipedia_crawler.py "https://grokipedia.com/page/Hitomila" \
    --match "Hitomila" --max-pages 25

# Deeper & wider crawl, polite 2-second delay, no raw HTML copies
python grokipedia_crawler.py "https://grokipedia.com/page/Hitomila" \
    --max-pages 100 --max-depth 6 --delay 2 --no-html

# Just scrape the start page (no following) + wait before fetching
python grokipedia_crawler.py "https://grokipedia.com/page/Hitomila" \
    --max-depth 0 --delay 1

# Scrape into a folder named after the topic
python grokipedia_crawler.py "https://grokipedia.com/page/Hitomila" -o Hitomila_Mirror
Script 3 — grokipedia_scraper_playwright.py (JavaScript fallback)
bash

pip install playwright && playwright install chromium

# Scrape a JS-rendered page the same way
python grokipedia_scraper_playwright.py "https://grokipedia.com/page/Hitomila"

# Custom output
python grokipedia_scraper_playwright.py "https://grokipedia.com/page/Hitomila" -o js.md
How It Works (In Depth)
1. Fetching the page
Scripts 1 & 2 send an HTTP GET with a realistic browser User-Agent and an
Accept-Language header, then decode the response using apparent_encoding
(so multibyte content decodes correctly). BeautifulSoup parses the HTML with
the lxml backend into a navigable tree.

python

resp = requests.get(url, headers={"User-Agent": USER_AGENT, ...})
soup = BeautifulSoup(resp.text, "lxml")
If a page returns empty content, it's likely JavaScript-rendered. Use the
Playwright version, which launches a real browser and waits for the DOM to
finish rendering before reading it.

2. Locating the article body
A Grokipedia page contains navigation, sidebars, footers, etc. The tool needs to
isolate the actual article. find_main_content() tries this in two phases:

Explicit selectors (in order): <article>, [itemprop="articleBody"],
<main>, #content, .prose, etc. The first match with > 500 chars wins.
Heuristic fallback: if no selector matches, it picks the single DOM
container holding the most text (> 800 chars).
3. Converting HTML → Markdown
element_to_md() walks the DOM tree recursively and emits Markdown, element
by element:

HTML element	Markdown output
<h1>–<h6>	# … ###### headings
<p>	paragraph (blank lines around it)
<ul> / <ol>	- items / N. items
nested lists	indented continuation
<a href>	[anchor](href)
<img>	![alt](src)
<blockquote> / <figure>	> quoted lines
<pre>	fenced code block with language
<hr>	--- rule
Comments (<!-- -->) and <script>/<style> blocks are skipped.
render_list() handles nested ordered/unordered lists with proper indentation.

4. Following & linking hyperlinks (crawler only)
grokipedia_crawler.py does more than scrape — it builds a local mirror.

Discovery: internal_links() scans every <a href>, resolves relative
links with urljoin(), and keeps only those pointing to
grokipedia.com/page/*.
Crawling: a breadth‑first search (collections.deque) follows those links,
respecting --max-pages and --max-depth. It tracks visited/queued URLs to
avoid loops and duplicate downloads.
Local rewriting: make_resolver() rewrites each internal link from an
absolute URL into a relative local path so it works fully offline:
from a top‑level page: pages/SomeTerm.md
from a page inside pages/: ../pages/SomeTerm.md
external links (non‑grokipedia.com) are left untouched.
Raw HTML: every fetched page is also saved verbatim to html/<slug>.html.
5. Generating the index
After crawling, README.md is written as a master index:

All Pages — every downloaded page with a link.
Links Found Per Page — for each page, the list of other pages it links to,
so you can navigate the whole graph offline.
Depth & breadth limits
Option	Default	Meaning
--max-pages	30	total pages downloaded
--max-depth	4	maximum link hops from the start page
--delay	0.5	seconds to sleep between requests
--match	(none)	only follow links whose anchor text contains this phrase
Output Structure
Single-page scraper (grokipedia_scraper.py)
text

Hitomila.md                 # the Markdown file
Crawler (grokipedia_crawler.py)
text

grokipedia_mirror/
├── README.md               # master index + per-page link lists
├── Hitomila.md             # the start page (local links)
├── pages/
│   ├── Another_Term.md     # linked page (local links)
│   └── ...
└── html/
    ├── Hitomila.html       # raw HTML copies
    └── ...
Open README.md first — it's your clickable map of everything that was
downloaded.

Configuration / Options Reference
grokipedia_scraper.py
Flag	Type	Default	Description
url	positional	—	Grokipedia URL (bare slug also works)
-o, --output	string	auto	Output .md filename
--delay	float	0.0	Seconds to wait before fetching
-v, --verbose	flag	off	Print diagnostics to stderr
grokipedia_crawler.py
Flag	Type	Default	Description
url	positional	—	Start URL (bare slug also works)
-o, --output-dir	string	grokipedia_mirror	Output folder
--max-pages	int	30	Maximum pages to download
--max-depth	int	4	Maximum link hops from start
--delay	float	0.5	Seconds between requests
--match	string	none	Only follow links whose text contains this phrase
--no-html	flag	off	Skip saving raw .html copies
Troubleshooting
Symptom	Fix
Output file is nearly empty	The page is JS-rendered — use grokipedia_scraper_playwright.py
ModuleNotFoundError: requests	Run pip install requests beautifulsoup4 lxml
HTML parse is slow/buggy	Install lxml, or swap "lxml" → "html.parser"
403 Forbidden	The site blocked the default UA — tweak USER_AGENT
Too many pages downloaded	Lower --max-pages and/or --max-depth
Wrong content extracted	Open DevTools → Elements, find the real article element, and add its selector to CONTENT_SELECTORS
Ethics & Legal
Respect https://grokipedia.com/robots.txt.
Use --delay (e.g. --delay 1 or more) to avoid hammering the server.
Check Grokipedia's Terms of Service before scraping — especially for
bulk or commercial use.
This tool is intended for personal research, offline reading, and archival.