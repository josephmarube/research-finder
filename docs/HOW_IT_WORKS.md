# HOW IT WORKS — Research Finder

> Technical reference for developers. Covers architecture, API integration, caching, citation generation, the localStorage library, and deployment.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Request Lifecycle](#request-lifecycle)
3. [Backend: Flask Application](#backend-flask-application)
4. [External APIs](#external-apis)
   - [OpenAlex](#openalex)
   - [CrossRef](#crossref)
   - [Fallback Strategy](#fallback-strategy)
5. [Data Normalisation](#data-normalisation)
6. [Caching Layer: Redis](#caching-layer-redis)
7. [Citation Generation](#citation-generation)
8. [Frontend Application](#frontend-application)
   - [Search & Filters](#search--filters)
   - [Paper Cards](#paper-cards)
   - [Modal Detail View](#modal-detail-view)
   - [localStorage Library](#localstorage-library)
9. [Docker Setup](#docker-setup)
10. [Deployment & Load Balancer](#deployment--load-balancer)
11. [Extending the App](#extending-the-app)

---

## Architecture Overview

```
BROWSER
  └─ HTML/CSS/JS (frontend)
       │ fetch("/api/...")
       ▼
Lb01: NGINX (round-robin load balancer)
  ├─► Web01: Flask + Gunicorn + Redis
  └─► Web02: Flask + Gunicorn + Redis
                │
                ├─► OpenAlex API  (primary)   — no key
                └─► CrossRef API  (fallback)  — no key
```

**Key design principle:** No API keys are required. Both OpenAlex and CrossRef are free, open scholarly infrastructure. The Flask backend still acts as a proxy to centralise caching, normalise responses, and enforce the "polite pool" email header that improves rate limits.

The library (saved papers) lives entirely in **browser localStorage** — nothing is persisted server-side. This keeps the backend stateless, which is perfect for a load-balanced deployment.

---

## Request Lifecycle

Search for "transformer neural networks":

```
1. User types query, hits Search

2. Frontend builds:
   GET /api/search?q=transformer+neural+networks&sort=relevance&page=1&per_page=10

3. Nginx forwards to Web01 or Web02 (round-robin)

4. Flask: search() handler
   ├─ Builds Redis cache key:
   │  "search:oa:transformer neural networks::::false:relevance:1:10"
   ├─ Redis HIT → return cached result immediately (_cached: true)
   └─ Redis MISS:
       ├─ Try OpenAlex /works?search=transformer neural networks&...
       │   ├─ Success → normalise results → cache for 1hr → return
       │   └─ Failure → fall through to CrossRef
       └─ CrossRef /works?query=transformer neural networks&...
           ├─ Success → normalise → cache → return
           └─ Both failed → 502 error with user-friendly message

5. Frontend receives JSON
   └─ Renders paper cards, pagination, source badge
```

---

## Backend: Flask Application

`backend/app.py` is organised into these sections:

```
1.  App setup (absolute path resolution for templates/static)
2.  Configuration (from environment variables)
3.  Redis client + graceful fallback if unavailable
4.  cache_get / cache_set / @cached decorator
5.  HTTP helpers: fetch_json(), api_error()
6.  Data normalisation: normalise_openalex(), normalise_crossref()
7.  Abstract reconstruction: reconstruct_abstract()
8.  Routes:
    GET /                          → renders index.html
    GET /health                    → health check
    GET /api/search                → main search (OpenAlex + CrossRef)
    GET /api/paper?doi=            → single paper detail
    GET /api/author?name=          → author lookup
    GET /api/cite?doi=&format=     → citation generation
    GET /api/subjects?q=           → concept autocomplete
    GET /api/admin/cache/stats     → Redis stats
    POST /api/admin/cache/flush    → clear cache
9.  Error handlers (404, 500)
```

### Path resolution (important for Docker)

```python
_HERE = os.path.dirname(os.path.abspath(__file__))  # .../backend/
_ROOT = os.path.dirname(_HERE)                       # .../research-finder/

app = Flask(
    __name__,
    template_folder=os.path.join(_ROOT, "frontend", "templates"),
    static_folder=os.path.join(_ROOT, "frontend", "static"),
)
```

Using `os.path.abspath(__file__)` ensures the paths resolve correctly regardless of the working directory — which differs between `python backend/app.py` (local) and `gunicorn backend.app:app` (Docker).

---

## External APIs

### OpenAlex

**Base URL:** `https://api.openalex.org`
**Auth:** None. Use `mailto` param for polite pool (better rate limits).
**Rate limit:** 10 req/sec polite pool, 100k/day.
**Docs:** https://docs.openalex.org

OpenAlex is a fully open index of 240M+ scholarly works, built by OurResearch as a replacement for the now-defunct Microsoft Academic.

**Endpoints used:**

| Endpoint | Purpose |
|---|---|
| `GET /works` | Main search with filters, sorting, pagination |
| `GET /works/{doi_url}` | Single paper by DOI |
| `GET /authors` | Author search with stats |
| `GET /concepts` | Concept/subject autocomplete |

**Search parameters used:**

```python
params = {
    "search":   "transformer neural networks",  # full-text search
    "filter":   "publication_year:2023,type:journal-article,is_oa:true",
    "sort":     "cited_by_count:desc",
    "per-page": 10,
    "page":     1,
    "select":   "id,title,authorships,...",  # only fetch needed fields
    "mailto":   "your@email.com",
}
```

The `select` parameter is critical — without it, OpenAlex returns very large objects. We request only the fields we actually use, cutting response size by ~70%.

### CrossRef

**Base URL:** `https://api.crossref.org`
**Auth:** None. Use `mailto` param for polite pool.
**Rate limit:** 50 req/sec polite pool.
**Docs:** https://api.crossref.org/swagger-ui/index.html

CrossRef is the DOI registration agency. It has excellent DOI resolution and metadata for journal articles, but fewer preprints and books than OpenAlex.

**Endpoints used:**

| Endpoint | Purpose |
|---|---|
| `GET /works` | Search with filters |
| `GET /works/{doi}` | Single paper by DOI |

### Fallback Strategy

```python
try:
    results, total = _search_openalex(...)
    source = "openalex"
except Exception as e:
    logger.warning("OpenAlex failed, trying CrossRef: %s", e)
    try:
        results, total = _search_crossref(...)
        source = "crossref"
    except Exception as e2:
        return api_error("Both APIs unavailable. Please try again later.")
```

The frontend shows a coloured **source badge** (green for OpenAlex, amber for CrossRef) so users know which database served their results.

---

## Data Normalisation

Both APIs return differently structured JSON. The backend normalises both into an identical flat shape before caching and returning to the frontend:

```python
{
    "id":       str,   # OpenAlex URL or DOI URL
    "doi":      str,   # just the DOI, e.g. "10.1038/nature12345"
    "title":    str,
    "authors":  list[str],
    "year":     int | None,
    "venue":    str,   # journal or conference name
    "issn":     str,
    "cited_by": int,
    "is_oa":    bool,
    "oa_url":   str,   # URL to free full text if available
    "abstract": str,
    "concepts": list[str],
    "type":     str,   # "journal-article", "preprint", etc.
    "url":      str,   # canonical URL
    "source":   str,   # "openalex" or "crossref"
}
```

### Abstract reconstruction

OpenAlex stores abstracts as an **inverted index** (a space-efficient format):

```json
{"The": [0, 12], "results": [1, 8], "show": [2], "that": [3, 9], ...}
```

This maps each word to the list of positions it appears at. We reconstruct the original text:

```python
def reconstruct_abstract(inverted_index):
    max_pos = max(pos for positions in inverted_index.values() for pos in positions)
    words   = [""] * (max_pos + 1)
    for word, positions in inverted_index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(w for w in words if w)
```

CrossRef sometimes includes HTML tags in abstracts (e.g., `<jats:p>text</jats:p>`). These are stripped with a simple regex: `re.sub(r"<[^>]+>", "", abstract_raw)`.

---

## Caching Layer: Redis

### Cache keys

```
search:oa:{q}:{author}:{year}:{type}:{oa_only}:{sort}:{page}:{per_page}
paper:{doi}
author:{name_lowercase}
subjects:{query_lowercase}
```

### TTLs

| Key pattern | TTL | Why |
|---|---|---|
| `search:oa:*` | 1 hour | Search results change slowly |
| `paper:*` | 24 hours | Paper metadata is stable |
| `author:*` | 24 hours | Author stats rarely change |
| `subjects:*` | 24 hours | Concept taxonomy is static |

### Cache miss flow

```
cache_get(key)
    │
    ├── HIT  → add _cached:true → return immediately
    │
    └── MISS → call route handler → if success → cache_set(key, data, ttl)
```

The `@cached` decorator handles this transparently. Routes that need custom key logic pass a `key_fn`:

```python
@cached(CACHE_TTL_SEARCH, key_fn=lambda r: f"search:oa:{r.args.get('q')}:...")
def search():
    ...
```

---

## Citation Generation

The `/api/cite` endpoint generates formatted citations from paper metadata. It supports five formats.

### APA 7th edition
```
Last, F. M.; Last, F. M. (Year). Title. *Journal Name*. https://doi.org/...
```

### MLA 9th edition
```
Last, First, and First Last. "Title." *Journal Name*, Year, https://doi.org/...
```

### Chicago 17th edition
```
Last, First, and First Last. "Title." *Journal Name* (Year). https://doi.org/...
```

### Harvard
```
Last, F. M. et al. (Year) 'Title', *Journal Name*. Available at: https://doi.org/...
```

### BibTeX
```bibtex
@article{lastname2023,
  title   = {Title},
  author  = {First Last and First Last},
  year    = {2023},
  journal = {Journal Name},
  doi     = {10.1234/example},
}
```

The citation endpoint re-uses the `paper:{doi}` cache entry if it already exists from a previous detail view — avoiding a redundant API call.

---

## Frontend Application

### Search & Filters

All search state is held in the `currentQuery` object. Pagination calls `runSearch(page)` with the same query object, only changing the page number.

```javascript
async function runSearch(page = 1) {
    const params = new URLSearchParams();
    params.set("q",        $("queryInput").value.trim());
    params.set("author",   $("authorInput").value.trim());
    params.set("year",     $("yearInput").value.trim());
    params.set("type",     $("typeSelect").value);
    params.set("oa_only",  $("oaOnly").checked);
    params.set("sort",     $("sortSelect").value);
    params.set("page",     page);
    params.set("per_page", 10);
    const data = await apiFetch(`/api/search?${params}`);
    renderResults(data);
}
```

### Paper Cards

Cards are generated as HTML strings and inserted via `innerHTML`. User-supplied data (titles, author names) is always run through `escHtml()` to prevent XSS:

```javascript
function escHtml(str) {
    return String(str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}
```

Event listeners are attached after each render via `attachCardListeners()` — this is necessary because `innerHTML` replaces the DOM nodes, removing previously attached listeners.

### Modal Detail View

The modal opens when a user clicks a paper title or the "Details" button. If the paper is already in `lastResults` or the library, it renders immediately from the cached JS object. Otherwise it fetches `/api/paper?doi=...`.

```javascript
function openModal(doi) {
    const cached = findPaper(doi);   // check memory first
    if (cached) {
        renderModal(cached);
        loadCitation(doi, currentCitFormat);
        return;
    }
    // Fall through to API fetch
    apiFetch(`/api/paper?doi=${doi}`).then(renderModal);
}
```

The modal also loads a citation immediately in the last-used format. Switching format buttons calls `loadCitation()` which hits `/api/cite`.

### localStorage Library

The library is stored as a JSON array under the key `rf_library_v1`. Each item is a normalised paper object plus a `_savedAt` timestamp.

```javascript
// Save
function saveToLibrary(paper) {
    const lib = getLibrary();
    if (!lib.find(p => (p.doi || p.id) === (paper.doi || paper.id))) {
        lib.unshift({ ...paper, _savedAt: Date.now() });
        localStorage.setItem("rf_library_v1", JSON.stringify(lib));
    }
}

// The "Save" button on a card turns into "✓ Saved" immediately
btn.textContent = "✓ Saved";
btn.classList.add("saved");
```

Library sorting is done client-side over the stored array — no server round-trip needed. Supported sort keys: recently added, year, citations, title A–Z.

---

## Docker Setup

**Dockerfile** — same pattern as GlobalMarket:
- `python:3.12-slim` base
- Dependencies installed before source (layer caching)
- Gunicorn with 4 workers
- `HEALTHCHECK` via curl to `/health`

**docker-compose.yml** — two services:
- `redis` — Redis 7 Alpine with AOF persistence and healthcheck
- `app` — Flask app, depends on Redis being healthy first

**No API key environment variables needed.** The only optional variable is `CONTACT_EMAIL`, used as the polite pool identifier in request headers.

```bash
# Start everything
docker compose up --build

# Check health
curl http://localhost:5000/health
# {"status":"ok","redis":true,"timestamp":"..."}
```

---

## Deployment & Load Balancer

Identical to the GlobalMarket project — deploy the same Docker Compose stack on Web01 and Web02, then configure Nginx on Lb01:

```nginx
upstream research_backend {
    server WEB01_IP:5000 max_fails=3 fail_timeout=30s;
    server WEB02_IP:5000 max_fails=3 fail_timeout=30s;
    keepalive 32;
}
```

One important note for this project: because the library lives in **browser localStorage**, users get a consistent experience regardless of which server handles their requests — there's no session state on the server side that could cause inconsistency.

---

## Extending the App

### Add a new citation format
Add a new `elif fmt == "vancouver":` block to `format_citation()` in `app.py`, then add a `<button class="cite-btn" data-fmt="vancouver">Vancouver</button>` to the modal HTML.

### Add full-text PDF viewer
When `p.is_oa` is true and `p.oa_url` is set, you can embed the PDF in the modal using an `<iframe>` or link to Unpaywall for the best available open-access copy.

### Export library to BibTeX file
Add a button in the library tab that iterates over `getLibrary()`, calls `/api/cite?format=bibtex` for each DOI, and combines the results into a downloadable `.bib` file.

### Add subject/concept filtering
The `/api/subjects?q=` endpoint already supports concept autocomplete from OpenAlex. Wire it up to an autocomplete input that appends a `filter=concept.id:{id}` parameter to OpenAlex search calls.

---

*Last updated: March 2026*
