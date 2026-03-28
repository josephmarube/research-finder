"""
Research Finder — Flask Backend
================================
Secure proxy for OpenAlex and CrossRef academic APIs.
Redis caching reduces repeat API calls and improves latency.
No API keys required for either service.
"""

import os
import json
import logging
import re
import requests
from datetime import datetime
from functools import wraps
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import redis

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

app = Flask(
    __name__,
    template_folder=os.path.join(_ROOT, "frontend", "templates"),
    static_folder=os.path.join(_ROOT, "frontend", "static"),
)
CORS(app)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REDIS_HOST         = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT         = int(os.environ.get("REDIS_PORT", 6379))
REDIS_DB           = int(os.environ.get("REDIS_DB", 0))

CACHE_TTL_SEARCH   = int(os.environ.get("CACHE_TTL_SEARCH",   3600))   # 1 hr
CACHE_TTL_PAPER    = int(os.environ.get("CACHE_TTL_PAPER",    86400))  # 24 hr
CACHE_TTL_AUTHOR   = int(os.environ.get("CACHE_TTL_AUTHOR",   86400))  # 24 hr

# External API base URLs — no keys required
OPENALEX_BASE  = "https://api.openalex.org"
CROSSREF_BASE  = "https://api.crossref.org"

# Semantic Scholar API (no key needed, generous rate limits)
SEMANTIC_SCHOLAR_BASE = "https://api.semanticscholar.org/graph/v1"

# Polite pool: identify ourselves to get better rate limits
MAILTO = os.environ.get("CONTACT_EMAIL", "research-finder@example.com")

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

try:
    redis_client = redis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True
    )
    redis_client.ping()
    REDIS_AVAILABLE = True
    logger.info("Redis connected at %s:%s", REDIS_HOST, REDIS_PORT)
except Exception as e:
    redis_client = None
    REDIS_AVAILABLE = False
    logger.warning("Redis unavailable – running without cache: %s", e)


def cache_get(key: str):
    if not REDIS_AVAILABLE:
        return None
    try:
        raw = redis_client.get(key)
        return json.loads(raw) if raw else None
    except Exception as e:
        logger.warning("Cache GET error: %s", e)
        return None


def cache_set(key: str, value, ttl: int):
    if not REDIS_AVAILABLE:
        return
    try:
        redis_client.setex(key, ttl, json.dumps(value))
    except Exception as e:
        logger.warning("Cache SET error: %s", e)


def cached(ttl: int, key_fn=None):
    """Decorator: cache a route's successful JSON response in Redis."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            cache_key = key_fn(request) if key_fn else f"route:{request.full_path}"
            hit = cache_get(cache_key)
            if hit is not None:
                hit["_cached"] = True
                return jsonify(hit)
            result = fn(*args, **kwargs)
            data = result.get_json()
            if data and not data.get("error"):
                cache_set(cache_key, data, ttl)
            return result
        return wrapper
    return decorator

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": f"ResearchFinder/1.0 (mailto:{MAILTO})",
    "Accept": "application/json",
}


def fetch_json(url: str, params: dict = None, timeout: int = 12) -> dict:
    resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def api_error(message: str, status: int = 502):
    return jsonify({"error": message}), status

# ---------------------------------------------------------------------------
# Data normalisation helpers
# ---------------------------------------------------------------------------

def normalise_openalex(work: dict) -> dict:
    """Convert a raw OpenAlex Work object into a clean, flat dict."""
    # Authors
    authors = []
    for a in work.get("authorships", [])[:10]:
        name = a.get("author", {}).get("display_name", "")
        if name:
            authors.append(name)

    # Journal / venue
    primary = work.get("primary_location") or {}
    source  = primary.get("source") or {}
    venue   = source.get("display_name", "")
    issn    = source.get("issn_l", "")

    # DOI — strip URL prefix
    doi_raw = work.get("doi", "") or ""
    doi     = doi_raw.replace("https://doi.org/", "").strip()

    # Abstract — OpenAlex stores it as an inverted index; reconstruct it
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))

    # Concepts / topics for tagging
    concepts = [
        c.get("display_name", "")
        for c in work.get("concepts", [])[:6]
        if c.get("score", 0) > 0.3
    ]

    # Open-access info
    oa = work.get("open_access", {})

    return {
        "id":            work.get("id", ""),
        "doi":           doi,
        "title":         work.get("title", "Untitled"),
        "authors":       authors,
        "year":          work.get("publication_year"),
        "venue":         venue,
        "issn":          issn,
        "cited_by":      work.get("cited_by_count", 0),
        "is_oa":         oa.get("is_oa", False),
        "oa_url":        oa.get("oa_url", ""),
        "abstract":      abstract,
        "concepts":      concepts,
        "type":          work.get("type", ""),
        "url":           work.get("id", ""),   # OpenAlex canonical URL
        "source":        "openalex",
        "_cached":       False,
    }


def normalise_crossref(item: dict) -> dict:
    """Convert a raw CrossRef item into the same flat shape."""
    authors = []
    for a in item.get("author", [])[:10]:
        given  = a.get("given", "")
        family = a.get("family", "")
        name   = f"{given} {family}".strip()
        if name:
            authors.append(name)

    # Year from date-parts
    year = None
    dp = item.get("published", {}).get("date-parts", [[]])
    if dp and dp[0]:
        year = dp[0][0]

    # Journal name
    container = item.get("container-title", [])
    venue = container[0] if container else ""

    doi = item.get("DOI", "")

    # Abstract — CrossRef sometimes returns HTML tags; strip them
    abstract_raw = item.get("abstract", "")
    abstract     = re.sub(r"<[^>]+>", "", abstract_raw).strip()

    # Subject tags
    concepts = item.get("subject", [])[:6]

    return {
        "id":       f"https://doi.org/{doi}" if doi else "",
        "doi":      doi,
        "title":    (item.get("title", ["Untitled"]) or ["Untitled"])[0],
        "authors":  authors,
        "year":     year,
        "venue":    venue,
        "issn":     (item.get("ISSN") or [""])[0],
        "cited_by": item.get("is-referenced-by-count", 0),
        "is_oa":    False,
        "oa_url":   "",
        "abstract": abstract,
        "concepts": concepts,
        "type":     item.get("type", ""),
        "url":      f"https://doi.org/{doi}" if doi else "",
        "source":   "crossref",
        "_cached":  False,
    }


def reconstruct_abstract(inverted_index: dict) -> str:
    """OpenAlex stores abstracts as {word: [positions]}. Reconstruct plain text."""
    if not inverted_index:
        return ""
    try:
        max_pos = max(pos for positions in inverted_index.values() for pos in positions)
        words   = [""] * (max_pos + 1)
        for word, positions in inverted_index.items():
            for pos in positions:
                words[pos] = word
        return " ".join(w for w in words if w)
    except Exception:
        return ""

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({
        "status":    "ok",
        "redis":     REDIS_AVAILABLE,
        "timestamp": datetime.utcnow().isoformat(),
    })

# ---------------------------------------------------------------------------
# Search endpoint — OpenAlex primary, CrossRef fallback
# ---------------------------------------------------------------------------

@app.route("/api/search")
def search():
    """
    GET /api/search
    Query params:
      q        — keyword / phrase (required)
      author   — filter by author name
      year     — filter by publication year
      type     — filter by type: journal-article | book-chapter | proceedings-article
      oa_only  — "true" to show only open-access papers
      sort     — cited_by | year | relevance  (default: relevance)
      page     — page number (default: 1)
      per_page — results per page (default: 10, max: 25)
    """
    q        = request.args.get("q", "").strip()
    author   = request.args.get("author", "").strip()
    year     = request.args.get("year", "").strip()
    doc_type = request.args.get("type", "").strip()
    oa_only  = request.args.get("oa_only", "false").lower() == "true"
    sort     = request.args.get("sort", "relevance").lower()
    page     = max(1, int(request.args.get("page", 1)))
    per_page = min(25, max(1, int(request.args.get("per_page", 10))))

    if not q and not author:
        return api_error("At least one of 'q' or 'author' is required", 400)

    # Cache key encodes all filter parameters
    cache_key = (
        f"search:oa:{q}:{author}:{year}:{doc_type}:{oa_only}:{sort}:{page}:{per_page}"
    )
    hit = cache_get(cache_key)
    if hit:
        hit["_cached"] = True
        return jsonify(hit)

    # ── Try OpenAlex first ────────────────────────────────────────────────
    try:
        results, total = _search_openalex(q, author, year, doc_type, oa_only, sort, page, per_page)
        source = "openalex"
    except Exception as e:
        logger.warning("OpenAlex search failed (%s), falling back to CrossRef", e)
        try:
            results, total = _search_crossref(q, author, year, doc_type, sort, page, per_page)
            source = "crossref"
        except Exception as e2:
            logger.error("CrossRef fallback also failed: %s", e2)
            return api_error("Both OpenAlex and CrossRef are currently unavailable. Please try again later.")

    payload = {
        "query":    {"q": q, "author": author, "year": year, "type": doc_type, "oa_only": oa_only},
        "source":   source,
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "results":  results,
        "_cached":  False,
    }
    cache_set(cache_key, payload, CACHE_TTL_SEARCH)
    return jsonify(payload)


def _search_openalex(q, author, year, doc_type, oa_only, sort, page, per_page):
    params = {
        "mailto":   MAILTO,
        "per-page": per_page,
        "page":     page,
    }

    # Build filter string
    filters = []
    if year:
        filters.append(f"publication_year:{year}")
    if doc_type:
        filters.append(f"type:{doc_type}")
    if oa_only:
        filters.append("is_oa:true")
    if filters:
        params["filter"] = ",".join(filters)

    # Search field
    if q and author:
        params["search"] = q
        params["filter"] = (params.get("filter", "") + f",author.display_name.search:{author}").lstrip(",")
    elif author:
        params["filter"] = (params.get("filter", "") + f",author.display_name.search:{author}").lstrip(",")
    elif q:
        params["search"] = q

    # Sort
    sort_map = {
        "cited_by":  "cited_by_count:desc",
        "year":      "publication_year:desc",
        "relevance": "relevance_score:desc",
    }
    params["sort"] = sort_map.get(sort, "relevance_score:desc")

    params["select"] = (
        "id,title,authorships,publication_year,primary_location,"
        "cited_by_count,open_access,abstract_inverted_index,concepts,type,doi"
    )

    data  = fetch_json(f"{OPENALEX_BASE}/works", params)
    meta  = data.get("meta", {})
    total = meta.get("count", 0)
    works = data.get("results", [])

    return [normalise_openalex(w) for w in works], total


def _search_crossref(q, author, year, doc_type, sort, page, per_page):
    params = {
        "mailto":  MAILTO,
        "rows":    per_page,
        "offset":  (page - 1) * per_page,
    }

    if q:
        params["query"] = q
    if author:
        params["query.author"] = author
    if year:
        params["filter"] = f"from-pub-date:{year},until-pub-date:{year}"
    if doc_type:
        existing = params.get("filter", "")
        type_filter = f"type:{doc_type}"
        params["filter"] = f"{existing},{type_filter}".lstrip(",")

    sort_map = {
        "cited_by":  "is-referenced-by-count",
        "year":      "published",
        "relevance": "score",
    }
    params["sort"]  = sort_map.get(sort, "score")
    params["order"] = "desc"

    data  = fetch_json(f"{CROSSREF_BASE}/works", params)
    msg   = data.get("message", {})
    total = msg.get("total-results", 0)
    items = msg.get("items", [])

    return [normalise_crossref(i) for i in items], total

# ---------------------------------------------------------------------------
# Single paper detail endpoint
# ---------------------------------------------------------------------------

@app.route("/api/paper")
def paper_detail():
    """
    GET /api/paper?doi=<doi>
    Returns full metadata for a single paper. Tries OpenAlex first, CrossRef fallback.
    """
    doi = request.args.get("doi", "").strip().lstrip("https://doi.org/")
    if not doi:
        return api_error("doi parameter is required", 400)

    cache_key = f"paper:{doi}"
    hit = cache_get(cache_key)
    if hit:
        hit["_cached"] = True
        return jsonify(hit)

    # OpenAlex lookup by DOI
    try:
        data = fetch_json(f"{OPENALEX_BASE}/works/https://doi.org/{doi}", {"mailto": MAILTO})
        result = normalise_openalex(data)
        result["_cached"] = False
        cache_set(cache_key, result, CACHE_TTL_PAPER)
        return jsonify(result)
    except Exception as e:
        logger.warning("OpenAlex paper detail failed for %s: %s", doi, e)

    # CrossRef fallback
    try:
        data   = fetch_json(f"{CROSSREF_BASE}/works/{doi}", {"mailto": MAILTO})
        result = normalise_crossref(data.get("message", {}))
        result["_cached"] = False
        cache_set(cache_key, result, CACHE_TTL_PAPER)
        return jsonify(result)
    except Exception as e:
        logger.error("CrossRef paper detail failed for %s: %s", doi, e)
        return api_error(f"Could not find paper with DOI: {doi}", 404)

# ---------------------------------------------------------------------------
# Author lookup endpoint
# ---------------------------------------------------------------------------

@app.route("/api/author")
@cached(CACHE_TTL_AUTHOR, key_fn=lambda r: f"author:{r.args.get('name','').lower().strip()}")
def author_lookup():
    """
    GET /api/author?name=<name>
    Returns top author matches from OpenAlex with stats.
    """
    name = request.args.get("name", "").strip()
    if not name:
        return api_error("name parameter is required", 400)

    try:
        data = fetch_json(f"{OPENALEX_BASE}/authors", {
            "search":   name,
            "per-page": 5,
            "mailto":   MAILTO,
        })
    except Exception as e:
        logger.error("Author lookup failed: %s", e)
        return api_error("Author lookup failed")

    authors = []
    for a in data.get("results", []):
        affils = a.get("last_known_institution") or {}
        authors.append({
            "id":           a.get("id", ""),
            "name":         a.get("display_name", ""),
            "works_count":  a.get("works_count", 0),
            "cited_by":     a.get("cited_by_count", 0),
            "institution":  affils.get("display_name", ""),
            "orcid":        a.get("orcid", ""),
        })

    return jsonify({"results": authors, "_cached": False})

# ---------------------------------------------------------------------------
# Citation generation endpoint
# ---------------------------------------------------------------------------

@app.route("/api/cite")
def generate_citation():
    """
    GET /api/cite?doi=<doi_or_openalex_id>&format=apa|mla|chicago|bibtex|harvard
    Generates a formatted citation string.
    Accepts real DOIs AND OpenAlex IDs (W1234567890).
    Falls back through OpenAlex → CrossRef → Semantic Scholar.
    """
    raw_id = request.args.get("doi", "").strip()
    fmt    = request.args.get("format", "apa").lower()

    if not raw_id:
        return api_error("doi parameter is required", 400)
    if fmt not in ("apa", "mla", "chicago", "bibtex", "harvard"):
        return api_error("format must be: apa, mla, chicago, bibtex, or harvard", 400)

    # Detect if this is an OpenAlex ID or a real DOI
    is_openalex_id = (
        "openalex.org" in raw_id or
        "enalex.org"   in raw_id or
        re.match(r"^W\d+$", raw_id)
    )

    # Clean up the identifier
    if is_openalex_id:
        # Extract just the W-number
        openalex_id = re.search(r"W\d+", raw_id)
        openalex_id = openalex_id.group(0) if openalex_id else raw_id
        doi = None
        cache_key = f"paper:openalex:{openalex_id}"
    else:
        doi = raw_id.replace("https://doi.org/", "").replace("http://doi.org/", "").strip()
        openalex_id = None
        cache_key = f"paper:{doi}"

    # Try cache first
    paper = cache_get(cache_key)
    if paper:
        citation = format_citation(paper, fmt)
        return jsonify({"format": fmt, "citation": citation, "_cached": True})

    paper = None

    # ── Path 1: OpenAlex ID lookup ────────────────────────────────────────
    if is_openalex_id:
        try:
            data  = fetch_json(f"{OPENALEX_BASE}/works/{openalex_id}", {"mailto": MAILTO})
            paper = normalise_openalex(data)
            # If the paper has a DOI, also try to enrich from Semantic Scholar
            if not paper.get("abstract") and paper.get("doi"):
                try:
                    ss = fetch_json(
                        f"{SEMANTIC_SCHOLAR_BASE}/paper/DOI:{paper['doi']}",
                        {"fields": "abstract,year,authors,venue,externalIds"}
                    )
                    if ss.get("abstract") and not paper.get("abstract"):
                        paper["abstract"] = ss["abstract"]
                except Exception:
                    pass
        except Exception as e:
            logger.warning("OpenAlex ID lookup failed for %s: %s", openalex_id, e)

    # ── Path 2: DOI lookup — OpenAlex first ──────────────────────────────
    if not paper and doi:
        try:
            data  = fetch_json(f"{OPENALEX_BASE}/works/https://doi.org/{doi}", {"mailto": MAILTO})
            paper = normalise_openalex(data)
        except Exception as e:
            logger.warning("OpenAlex DOI lookup failed for %s: %s", doi, e)

    # ── Path 3: CrossRef fallback ─────────────────────────────────────────
    if not paper and doi:
        try:
            data  = fetch_json(f"{CROSSREF_BASE}/works/{doi}", {"mailto": MAILTO})
            paper = normalise_crossref(data.get("message", {}))
        except Exception as e:
            logger.warning("CrossRef lookup failed for %s: %s", doi, e)

    # ── Path 4: Semantic Scholar fallback ────────────────────────────────
    if not paper:
        try:
            lookup = f"DOI:{doi}" if doi else f"OPENALEX:{openalex_id}"
            ss = fetch_json(
                f"{SEMANTIC_SCHOLAR_BASE}/paper/{lookup}",
                {"fields": "title,authors,year,venue,externalIds,abstract,citationCount,isOpenAccess"}
            )
            if ss and ss.get("title"):
                paper = {
                    "title":    ss.get("title", "Untitled"),
                    "authors":  [a.get("name", "") for a in ss.get("authors", [])],
                    "year":     ss.get("year"),
                    "venue":    ss.get("venue", ""),
                    "doi":      ss.get("externalIds", {}).get("DOI", doi or ""),
                    "abstract": ss.get("abstract", ""),
                    "cited_by": ss.get("citationCount", 0),
                    "is_oa":    ss.get("isOpenAccess", False),
                    "source":   "semantic_scholar",
                }
        except Exception as e:
            logger.warning("Semantic Scholar lookup failed: %s", e)

    if not paper:
        return api_error("Could not find metadata for this paper from any source", 404)

    cache_set(cache_key, paper, CACHE_TTL_PAPER)
    citation = format_citation(paper, fmt)
    return jsonify({"format": fmt, "citation": citation, "_cached": False})


def format_citation(p: dict, fmt: str) -> str:
    """Generate a citation string in the requested format."""
    authors  = p.get("authors", [])
    title    = p.get("title", "Untitled")
    year     = p.get("year", "n.d.")
    venue    = p.get("venue", "")
    doi      = p.get("doi", "")
    doi_url  = f"https://doi.org/{doi}" if doi else ""

    def author_last_first(name: str) -> str:
        parts = name.strip().split()
        if len(parts) >= 2:
            return f"{parts[-1]}, {' '.join(parts[:-1])}"
        return name

    def initials(name: str) -> str:
        parts = name.strip().split()
        if len(parts) >= 2:
            return f"{parts[-1]}, {'. '.join(p[0] for p in parts[:-1])}."
        return name

    if fmt == "apa":
        if authors:
            author_str = "; ".join(author_last_first(a) for a in authors[:6])
            if len(authors) > 6:
                author_str += " et al."
        else:
            author_str = "Unknown Author"
        venue_part = f" *{venue}*." if venue else ""
        doi_part   = f" {doi_url}" if doi_url else ""
        return f"{author_str} ({year}). {title}.{venue_part}{doi_part}"

    elif fmt == "mla":
        if authors:
            first  = author_last_first(authors[0])
            rest   = ", ".join(authors[1:]) if len(authors) > 1 else ""
            author_str = f"{first}{', and ' + rest if rest else ''}"
        else:
            author_str = "Unknown Author"
        venue_part = f" *{venue}*," if venue else ""
        doi_part   = f" {doi_url}." if doi_url else "."
        return f'{author_str}. "{title}."{venue_part} {year},{doi_part}'

    elif fmt == "chicago":
        if authors:
            first      = author_last_first(authors[0])
            rest_names = ", ".join(authors[1:])
            author_str = f"{first}{', ' + rest_names if rest_names else ''}"
        else:
            author_str = "Unknown Author"
        venue_part = f" *{venue}*" if venue else ""
        doi_part   = f". {doi_url}" if doi_url else ""
        return f'{author_str}. "{title}."{venue_part} ({year}){doi_part}.'

    elif fmt == "harvard":
        if authors:
            author_str = ", ".join(initials(a) for a in authors[:3])
            if len(authors) > 3:
                author_str += " et al."
        else:
            author_str = "Unknown Author"
        venue_part = f", *{venue}*" if venue else ""
        doi_part   = f". Available at: {doi_url}" if doi_url else ""
        return f"{author_str} ({year}) '{title}'{venue_part}{doi_part}."

    elif fmt == "bibtex":
        # Build a BibTeX key: first author last name + year
        key_author = authors[0].split()[-1].lower() if authors else "unknown"
        key        = f"{key_author}{year}"
        author_str = " and ".join(authors) if authors else "Unknown"
        lines = [
            f"@article{{{key},",
            f"  title   = {{{title}}},",
            f"  author  = {{{author_str}}},",
            f"  year    = {{{year}}},",
        ]
        if venue:
            lines.append(f"  journal = {{{venue}}},")
        if doi:
            lines.append(f"  doi     = {{{doi}}},")
        lines.append("}")
        return "\n".join(lines)

    return ""

# ---------------------------------------------------------------------------
# Subjects / concept autocomplete
# ---------------------------------------------------------------------------

@app.route("/api/subjects")
@cached(86400, key_fn=lambda r: f"subjects:{r.args.get('q','').lower()}")
def subjects():
    """
    GET /api/subjects?q=<prefix>
    Returns matching OpenAlex concept names for filter autocomplete.
    """
    q = request.args.get("q", "").strip()
    if not q:
        return api_error("q parameter required", 400)
    try:
        data = fetch_json(f"{OPENALEX_BASE}/concepts", {
            "search":   q,
            "per-page": 8,
            "mailto":   MAILTO,
        })
        concepts = [
            {"id": c.get("id"), "name": c.get("display_name"), "level": c.get("level")}
            for c in data.get("results", [])
        ]
        return jsonify({"results": concepts, "_cached": False})
    except Exception as e:
        return api_error(f"Subject lookup failed: {e}")

# ---------------------------------------------------------------------------
# Cache admin
# ---------------------------------------------------------------------------

@app.route("/api/admin/cache/stats")
def cache_stats():
    if not REDIS_AVAILABLE:
        return jsonify({"available": False})
    try:
        info = redis_client.info("memory")
        return jsonify({
            "available":   True,
            "keys":        redis_client.dbsize(),
            "used_memory": info.get("used_memory_human"),
        })
    except Exception as e:
        return api_error(str(e))


@app.route("/api/admin/cache/flush", methods=["POST"])
def cache_flush():
    if not REDIS_AVAILABLE:
        return api_error("Redis not available", 503)
    redis_client.flushdb()
    return jsonify({"message": "Cache flushed"})

# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(e):
    logger.error("Internal server error: %s", e)
    return jsonify({"error": "Internal server error"}), 500

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "production") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)
