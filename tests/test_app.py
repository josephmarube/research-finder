"""
Research Finder — Test Suite
=============================
Run locally:  pytest tests/ -v
Run in CI:    automatically triggered by GitHub Actions on every push
"""

import pytest
import sys
import os

# Add project root to path so we can import backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app as flask_app


@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        yield client


# ─────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────

def test_health_endpoint(client):
    """Health endpoint should return 200 with status ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "redis" in data
    assert "timestamp" in data


# ─────────────────────────────────────────────────────────────
# Frontend
# ─────────────────────────────────────────────────────────────

def test_index_returns_html(client):
    """Root route should return the HTML dashboard."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Research Finder" in resp.data
    assert b"text/html" in resp.content_type.encode()


# ─────────────────────────────────────────────────────────────
# Search endpoint — input validation
# ─────────────────────────────────────────────────────────────

def test_search_requires_query(client):
    """Search with no q or author should return 400."""
    resp = client.get("/api/search")
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data


def test_search_invalid_per_page_clamped(client):
    """per_page > 25 should be clamped to 25, not error."""
    resp = client.get("/api/search?q=test&per_page=999")
    # Should not return 400 — per_page is clamped internally
    assert resp.status_code in (200, 502)  # 502 if API is down in test env


def test_search_returns_expected_shape(client):
    """Search response should have the expected keys."""
    resp = client.get("/api/search?q=machine+learning&per_page=3")
    if resp.status_code == 200:
        data = resp.get_json()
        assert "results" in data
        assert "total" in data
        assert "page" in data
        assert "per_page" in data
        assert "source" in data
        assert "query" in data
        assert isinstance(data["results"], list)
    else:
        # API might be unavailable in test environment
        pytest.skip("External API unavailable in test environment")


def test_search_result_shape(client):
    """Each result should have the normalised fields."""
    resp = client.get("/api/search?q=biology&per_page=2")
    if resp.status_code == 200:
        data = resp.get_json()
        if data["results"]:
            result = data["results"][0]
            required_fields = ["title", "authors", "year", "cited_by", "is_oa", "source"]
            for field in required_fields:
                assert field in result, f"Missing field: {field}"
    else:
        pytest.skip("External API unavailable in test environment")


def test_search_oa_filter(client):
    """OA-only filter should return only open access papers."""
    resp = client.get("/api/search?q=physics&oa_only=true&per_page=5")
    if resp.status_code == 200:
        data = resp.get_json()
        for result in data["results"]:
            assert result["is_oa"] is True, \
                f"Non-OA result returned: {result.get('title')}"
    else:
        pytest.skip("External API unavailable in test environment")


def test_search_sort_options(client):
    """All sort options should be accepted without error."""
    for sort in ["relevance", "cited_by", "year"]:
        resp = client.get(f"/api/search?q=climate&sort={sort}&per_page=2")
        assert resp.status_code in (200, 502), \
            f"Sort '{sort}' returned unexpected status {resp.status_code}"


# ─────────────────────────────────────────────────────────────
# Citation endpoint — input validation
# ─────────────────────────────────────────────────────────────

def test_cite_requires_doi(client):
    """Citation endpoint without DOI should return 400."""
    resp = client.get("/api/cite")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_cite_invalid_format(client):
    """Unknown citation format should return 400."""
    resp = client.get("/api/cite?doi=10.1234/test&format=invalidfmt")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_cite_valid_formats_accepted(client):
    """All valid citation formats should be accepted (not 400)."""
    for fmt in ["apa", "mla", "chicago", "harvard", "bibtex"]:
        resp = client.get(f"/api/cite?doi=10.48550/arxiv.1201.0490&format={fmt}")
        # 400 = bad request (our error), 200 = success, 502 = upstream issue
        assert resp.status_code != 400, \
            f"Format '{fmt}' incorrectly rejected with 400"


# ─────────────────────────────────────────────────────────────
# Paper detail endpoint
# ─────────────────────────────────────────────────────────────

def test_paper_requires_doi(client):
    """Paper detail without DOI should return 400."""
    resp = client.get("/api/paper")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


# ─────────────────────────────────────────────────────────────
# Author endpoint
# ─────────────────────────────────────────────────────────────

def test_author_requires_name(client):
    """Author lookup without name should return 400."""
    resp = client.get("/api/author")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_author_returns_results(client):
    """Author search should return a list of authors."""
    resp = client.get("/api/author?name=Hinton")
    if resp.status_code == 200:
        data = resp.get_json()
        assert "results" in data
        assert isinstance(data["results"], list)
        if data["results"]:
            author = data["results"][0]
            assert "name" in author
            assert "works_count" in author
    else:
        pytest.skip("External API unavailable in test environment")


# ─────────────────────────────────────────────────────────────
# Subjects endpoint
# ─────────────────────────────────────────────────────────────

def test_subjects_requires_query(client):
    """Subjects endpoint without q should return 400."""
    resp = client.get("/api/subjects")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


# ─────────────────────────────────────────────────────────────
# 404 handler
# ─────────────────────────────────────────────────────────────

def test_unknown_route_returns_404(client):
    """Unknown routes should return JSON 404."""
    resp = client.get("/api/doesnotexist")
    assert resp.status_code == 404
    data = resp.get_json()
    assert "error" in data


# ─────────────────────────────────────────────────────────────
# Citation format logic (unit tests — no API calls)
# ─────────────────────────────────────────────────────────────

def test_apa_citation_format():
    """APA citation should contain author, year, and title."""
    from backend.app import format_citation
    paper = {
        "authors": ["Geoffrey Hinton", "Yann LeCun"],
        "title":   "Deep Learning",
        "year":    2015,
        "venue":   "Nature",
        "doi":     "10.1038/nature14539",
    }
    citation = format_citation(paper, "apa")
    assert "Hinton" in citation
    assert "2015" in citation
    assert "Deep Learning" in citation


def test_bibtex_citation_format():
    """BibTeX citation should start with @article."""
    from backend.app import format_citation
    paper = {
        "authors": ["Alan Turing"],
        "title":   "Computing Machinery and Intelligence",
        "year":    1950,
        "venue":   "Mind",
        "doi":     "10.1093/mind/LIX.236.433",
    }
    citation = format_citation(paper, "bibtex")
    assert citation.startswith("@article")
    assert "turing1950" in citation
    assert "Alan Turing" in citation


def test_citation_handles_no_authors():
    """Citation generator should handle missing authors gracefully."""
    from backend.app import format_citation
    paper = {
        "authors": [],
        "title":   "Anonymous Work",
        "year":    2020,
        "venue":   "",
        "doi":     "",
    }
    for fmt in ["apa", "mla", "chicago", "harvard", "bibtex"]:
        citation = format_citation(paper, fmt)
        assert citation is not None
        assert len(citation) > 0


def test_abstract_reconstruction():
    """Abstract inverted index should reconstruct correctly."""
    from backend.app import reconstruct_abstract
    inverted = {
        "The":     [0],
        "cat":     [1],
        "sat":     [2],
        "on":      [3],
        "the":     [4],
        "mat":     [5],
    }
    result = reconstruct_abstract(inverted)
    assert result == "The cat sat on the mat"


def test_abstract_reconstruction_handles_none():
    """Abstract reconstruction should handle None gracefully."""
    from backend.app import reconstruct_abstract
    assert reconstruct_abstract(None) == ""
    assert reconstruct_abstract({}) == ""
