
---

# Grokipedia Downloader

**Turn any Grokipedia article into a Markdown file — or a complete local library of the entire connected graph.**

Grokipedia Downloader is a small, Python toolkit for downloading articles from [Grokipedia](https://grokipedia.com) and converting them into Markdown files. It can scrape a **single article**, or **follow every hyperlink** inside an article to download and preserve the entire web of connected pages as a self‑contained, Locally stored navigable library.

---

## Features

- 📄 **Markdown conversion** — headings, paragraphs, ordered/unordered lists, links, images, blockquotes, and code blocks all converted faithfully.
- 🔗 **Hyperlink following** — automatically discovers and downloads every linked article, preserving links so the whole library navigates offline.
- 🌐 **Full library scraping** — recursively connected articles, building a complete local mirror.
- 🖥️ **JavaScript** — a Playwright‑powered fetcher renders client‑side pages so you get real content, not empty shells.
- 🗂️ **Dual output** — every page is saved as both clean Markdown **and** raw HTML.
- 📍 **Local Path rewriting** — internal links are rewritten to relative local paths, so the entire library works offline.
- ⚙️ **Configurable** — configurable download delays, depth limits, and page caps keep scrapes controlled and respectful.
- 🔎 **Phrase filtering** — follow only links whose anchor text contains a specific word or phrase(optional).

---

## What it does

Grokipedia Downloader comes as **three focused tools**:

| Tool | Purpose |
|------|---------|
| **Scraper** | Scrapes one Grokipedia article and exports it to a single Markdown file. |
| **Scraper(Recursive)** | Follows every hyperlink inside an article, downloading the entire connected web of articles into a local, offline‑navigable mirror. |
| **Playwright Fallback** | Renders JavaScript‑heavy pages so articles that only appear after page load can still be scraped. |

---

## Download/Install

Clone the Repository:
```bash
git clone https://github.com/MrCains26/Grokipedia-Downloader.git
cd grokipedia_downloader
```
Download Dependencies:
```bash
pip install -r requirements.txt
```
**Or**:
```bash
python -m pip install -r requirements.txt
```
Install Headless Chromium for Playwrite:
```bash
playwright install chromium
```
<br>
<details>
<summary>Still Missing Dependencies?</summary>

##### **There was probably an issue whith the bash install script and one of the dependencies did not download**

**alternate download scripts**

Requests:

```bash
pip install requests
python -m pip install requests
pip3 install requests
python3 -m pip install requests
py -m pip install requests       (windows)
py -m pip install -r requests        (windows)
```

Beautifulsoup4:

```bash
pip install beautifulsoup4
python -m pip install beautifulsoup4
pip3 install beautifulsoup4
python3 -m pip install beautifulsoup4
py -m pip install beautifulsoup4       (windows)
py -m pip install -r beautifulsoup4        (windows)
```

lxml:

```bash
pip install lxml
python -m pip install lxml
pip3 install lxml
python3 -m pip install lxml
py -m pip install lxml       (windows)
py -m pip install -r lxml        (windows)
```

Playwright:

```bash
pip install playwright
python -m pip install playwright
pip3 install playwright
python3 -m pip install playwright
py -m pip install playwright       (windows)
py -m pip install -r playwright        (windows)
```

</details>

---



## Commands & What They Do



### Recursive Scraper (full library)

| Command | What it does |
|---------|--------------|
| `python grokipedia_scraper.py "url"` | Crawls every linked article from the page (defaults: up to 30 pages, depth 4). |
| `python grokipedia_scraper.py "url" --max-depth 0`| Saves ONLY the url page. |
| `python grokipedia_scraper.py "url" --max-depth 1`| Saves url page and direct links. |
| `python grokipedia_scraper.py "url" --match "keyword"` | Crawls only links whose anchor text contains the word `keyword`. |
| `python grokipedia_scraper.py "url" --max-pages 100 --max-depth 6` | Crawls up to 100 pages, up to 6 link hops deep. |
| `python grokipedia_scraper.py "url" --delay 2 --no-html` | Crawls with a 2‑second delay between requests and skips saving raw HTML. |

---

## 📁 Where Files Are Saved

### Single‑Page Scraper

The Markdown file is saved in the **folder where you run the command**:

```
currentPage.md
```

Use `--output` to choose a different filename.

### Downloader (Multiple Pages)

By default, a complete mirror folder is created next to where you run the scraper:

```
grokipedia_downloader/
├── README.md               # Master index + per‑page link list (your entry point)
├── PAGE-NAME.md            # The start page(url page), with local links
├── pages/
│   ├── AnotherPage.md      # linked articles, with local links
│   └── ...
└── html/
    ├── PAGE-NAME.html      # Raw HTML copy of every page
    └── ...
```

> 🧭 **Start by opening `README.md`** in the output folder — it contains a clickable index of every downloaded page plus a per‑page map of the links found within each article, so you can navigate the whole library offline.

To change the output location, add `-o mylibrary/` to any Download command.

---

## ⚙️ Options Reference

### Recursive Scraper

| Flag | Default | Description |
|------|---------|-------------|
| `-o`, `--output-dir` | `grokipedia_downloader` | Folder to save the library mirror. |
| `--max-pages` | `30` | Maximum number of pages to download. |
| `--max-depth` | `4` | Maximum number of link hops from the start page. |
| `--delay` | `0.5` | Seconds to wait between downloads. |
| `--match` | *(none)* | Only follow links whose text contains this phrase. |
| `--no-html` | off | Skip saving raw `.html` copies. |

---

## ⚠️ A Note on Responsible Scraping

- Always respect [`grokipedia.com/robots.txt`](https://grokipedia.com/robots.txt). ()
- Use `--delay` to avoid overwhelming the server.
- Review Grokipedia's **Terms of Service** before bulk or commercial use.
- This tool is intended for personal research, offline reading, and archival.



##### ↓ Grokepedia Full Robots.txt ↓ 
```
User-agent: *
Disallow: /api/

Sitemap: https://assets.grokipedia.com/sitemap/sitemap-index.xml
```

---

## Requirements

- Python 3.9+
- `requests`, `beautifulsoup4`, `lxml`, `playwright` + Chromium (core)

All are in `requirements.txt`.

---

*Built for offline reading and personal knowledge archives.*

---
