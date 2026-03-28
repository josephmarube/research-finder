# Research Finder

A full-stack academic paper search and organiser for students and researchers. Search 240M+ scholarly works, filter by author, year, type, and open-access status, save papers to a persistent library, and generate formatted citations in APA, MLA, Chicago, Harvard, or BibTeX.

**Live URL:** https://youngjmatrix.tech

Built with **Python Flask**, **Redis**, **Docker**, and **HAProxy**. No API keys required.

---

## Table of Contents

1. [Purpose & Value](#purpose--value)
2. [Features](#features)
3. [APIs Used](#apis-used)
4. [Project Structure](#project-structure)
5. [Local Setup — Docker](#local-setup--docker-recommended)
6. [Local Setup — Without Docker](#local-setup--without-docker)
7. [Deployment to Web Servers](#deployment-to-web-servers)
8. [Load Balancer Setup — HAProxy](#load-balancer-setup--haproxy)
9. [CI/CD Pipeline](#cicd-pipeline)
10. [Caching Architecture](#caching-architecture)
11. [Security Measures](#security-measures)
12. [API Endpoints](#api-endpoints)
13. [Error Handling](#error-handling)
14. [Challenges & Solutions](#challenges--solutions)
15. [Bonus Tasks Completed](#bonus-tasks-completed)
16. [Credits & Attribution](#credits--attribution)

---

## Purpose & Value

Research Finder solves a genuine problem for students and researchers: finding, comparing, and citing academic papers is time-consuming and spread across multiple platforms. This app consolidates search, filtering, saving, and citation generation into one clean interface — backed by real scholarly databases covering over 240 million works.

Unlike a simple search box, it provides:
- Multi-field filtering (author, year, type, open-access status)
- Sortable results by relevance, citations, or date
- Full abstract and concept tags for each paper
- Automatic citation generation in 5 academic formats
- A persistent personal library saved across sessions
- Automatic fallback across 3 APIs for maximum coverage

---

## Features

| Feature | Description |
|---|---|
| **Keyword search** | Full-text search across 240M+ papers |
| **Author filter** | Filter by author last name |
| **Year / Type / OA filters** | Narrow by year, document type, open-access status |
| **Sort options** | Relevance, most cited, newest first |
| **Pagination** | Navigate through thousands of results |
| **Paper detail modal** | Full abstract, concepts, citation count, links |
| **Citation generator** | APA · MLA · Chicago · Harvard · BibTeX — one-click copy |
| **My Library** | Save papers to localStorage — persists across sessions |
| **Library sorting** | Sort by date added, year, citations, or title A–Z |
| **Triple API fallback** | OpenAlex → CrossRef → Semantic Scholar |
| **Redis caching** | Responses cached to reduce API calls and latency |
| **Source badge** | Shows which API served the current results |
| **Enter key search** | Press Enter from any filter field to search |
| **HTTPS** | TLS 1.2+ enforced, HSTS header set |
| **CI/CD** | Automated testing and deployment on every git push |

---

## APIs Used

| API | Purpose | Docs | Key Required |
|---|---|---|---|
| **OpenAlex** | Primary search, filters, author lookup, concepts | https://docs.openalex.org | No |
| **CrossRef** | DOI metadata fallback for journal articles | https://api.crossref.org | No |
| **Semantic Scholar** | Third fallback for citations and abstracts | https://api.semanticscholar.org | No |

All three APIs are free, open scholarly infrastructure. No keys needed — clone and run immediately.

---

## Project Structure

```
research-finder/
├── .github/
│   └── workflows/
│       └── deploy.yml          # CI/CD pipeline (GitHub Actions)
├── backend/
│   ├── app.py                  # Flask app — all routes, API proxy, citation logic
│   ├── requirements.txt        # Python dependencies
│   └── __init__.py
├── frontend/
│   ├── templates/
│   │   └── index.html          # Single-page HTML dashboard
│   └── static/
│       ├── css/main.css        # All styles
│       └── js/main.js          # Search, library, modal, citations
├── haproxy/
│   └── haproxy.cfg             # HAProxy load balancer config (Lb01)
├── docs/
│   └── HOW_IT_WORKS.md         # Full technical documentation
├── tests/
│   └── test_app.py             # Pytest test suite (20 tests)
├── Dockerfile                  # Container image
├── docker-compose.yml          # App + Redis orchestration
├── pytest.ini                  # Test runner config
├── .env.example                # Environment variable template
├── .gitignore                  # Excludes .env and build artifacts
└── README.md
```

---

## Local Setup — Docker (recommended)

### Prerequisites
- Docker Desktop with WSL 2 integration enabled
- No API keys needed

```bash
# 1. Clone the repo
git clone https://github.com/josephmarube/research-finder.git
cd research-finder

# 2. Set up environment (just your email — no API keys)
cp .env.example .env
nano .env   # set CONTACT_EMAIL=your@email.com

# 3. Build and start
docker compose up --build

# 4. Open in browser
# http://localhost:5000
```

To stop: `docker compose down`

---

## Local Setup — Without Docker

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r backend/requirements.txt

# 3. Set up environment
cp .env.example .env

# 4. Start Redis (required for caching)
redis-server &

# 5. Run the app
python -m backend.app
# → http://localhost:5000
```

To run tests locally:
```bash
pytest tests/ -v
```

---

## Deployment to Web Servers

Deploy the same Docker Compose stack on both Web01 and Web02.

### Prerequisites on each server
- Docker and Docker Compose installed
- Port 5000 open in the firewall

### Steps

```bash
# SSH into Web01
ssh ubuntu@WEB01_IP
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/josephmarube/research-finder.git
cd research-finder
cp .env.example .env
nano .env   # set CONTACT_EMAIL=your@email.com
docker compose up --build -d

# Repeat for Web02
ssh ubuntu@WEB02_IP
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/josephmarube/research-finder.git
cd research-finder
cp .env.example .env
docker compose up --build -d
```

### Verify both servers are healthy

```bash
curl http://WEB01_IP:5000/health
# {"redis": true, "status": "ok", "timestamp": "..."}

curl http://WEB02_IP:5000/health
# {"redis": true, "status": "ok", "timestamp": "..."}
```

---

## Load Balancer Setup — HAProxy

The load balancer (Lb01) runs HAProxy and distributes HTTPS traffic between Web01 and Web02 using round-robin. SSL is terminated at the load balancer — backend servers communicate over plain HTTP internally.

### Install HAProxy on Lb01

```bash
ssh ubuntu@LB01_IP
sudo apt update && sudo apt install -y haproxy certbot
```

### Get SSL certificates

```bash
# Stop HAProxy temporarily to free port 80
sudo systemctl stop haproxy

# Issue certificates for both domains
sudo certbot certonly --standalone -d youngjmatrix.tech
sudo certbot certonly --standalone -d www.youngjmatrix.tech

# Start HAProxy back up
sudo systemctl start haproxy

# Combine cert + key into single PEM files (HAProxy requires this format)
sudo bash -c "cat /etc/letsencrypt/live/youngjmatrix.tech/fullchain.pem \
  /etc/letsencrypt/live/youngjmatrix.tech/privkey.pem \
  > /etc/haproxy/certs/youngjmatrix.tech.pem"

sudo bash -c "cat /etc/letsencrypt/live/www.youngjmatrix.tech/fullchain.pem \
  /etc/letsencrypt/live/www.youngjmatrix.tech/privkey.pem \
  > /etc/haproxy/certs/www.youngjmatrix.tech.pem"

sudo chmod 600 /etc/haproxy/certs/*.pem
```

### Deploy the HAProxy config

```bash
# Copy config from repo to HAProxy
sudo cp haproxy/haproxy.cfg /etc/haproxy/haproxy.cfg

# Replace placeholder IPs with real server IPs
sudo nano /etc/haproxy/haproxy.cfg
# Update: server web-01 <WEB01_IP>:5000
# Update: server web-02 <WEB02_IP>:5000

# Validate and reload
sudo haproxy -c -f /etc/haproxy/haproxy.cfg
sudo systemctl restart haproxy
```

### How the load balancer works

```
User → http://youngjmatrix.tech      → 301 → https://youngjmatrix.tech
User → http://www.youngjmatrix.tech  → 301 → https://youngjmatrix.tech
User → https://www.youngjmatrix.tech → 301 → https://youngjmatrix.tech
User → https://youngjmatrix.tech     → 200 → App (round-robin to Web01/Web02)
```

HAProxy actively health-checks both servers every 5 seconds via `GET /health`. If a server fails 3 checks, it's removed from rotation automatically and re-added when it recovers — no manual intervention needed.

### Verify traffic is distributed

```bash
# Watch logs on Web01 and Web02 simultaneously while refreshing the browser
# Web01 terminal:
ssh ubuntu@WEB01_IP "docker compose logs -f app"

# Web02 terminal:
ssh ubuntu@WEB02_IP "docker compose logs -f app"
```

Each server should show alternating requests, confirming round-robin is working.

### Test failover

```bash
# Stop app on Web01
ssh ubuntu@WEB01_IP "cd ~/projects/research-finder && docker compose stop app"

# Site should still work — all traffic routes to Web02
curl -I https://youngjmatrix.tech

# Restore Web01
ssh ubuntu@WEB01_IP "cd ~/projects/research-finder && docker compose start app"
```

---

## CI/CD Pipeline

Every push to the `main` branch automatically:

1. **Runs tests** — spins up Redis, starts Flask, runs 20 tests covering all endpoints
2. **Deploys** — only if all tests pass, SSHes into Web01 and Web02, pulls latest code, rebuilds Docker containers
3. **Verifies** — checks `https://youngjmatrix.tech/health` after deployment

```
git push → GitHub Actions
  ├── Run Tests (41s)
  │     ✓ Health check
  │     ✓ Search returns results
  │     ✓ Filters work
  │     ✓ Open access filter
  │     ✓ Citation generation
  │     ✓ Error handling
  │     ✓ Redis caching
  │
  └── Deploy to Servers (only if tests pass)
        ✓ Web01 updated
        ✓ Web02 updated
        ✓ youngjmatrix.tech is live
```

Pipeline config: `.github/workflows/deploy.yml`
Test suite: `tests/test_app.py`

---

## Caching Architecture

Redis caches all API responses to minimise external calls and improve latency.

| Cache Key | TTL | Example |
|---|---|---|
| `search:oa:{params}` | 1 hour | Search results |
| `paper:{doi}` | 24 hours | Paper metadata |
| `paper:openalex:{id}` | 24 hours | OpenAlex paper metadata |
| `author:{name}` | 24 hours | Author stats |
| `subjects:{query}` | 24 hours | Concept autocomplete |

Cache hits are indicated by a **CACHED** badge in the header. The frontend shows **LIVE** for fresh API responses. If Redis is unavailable, the app continues working — it just makes live API calls every time (graceful degradation).

---

## Security Measures

| Measure | Implementation |
|---|---|
| **No API key exposure** | All external API calls go through Flask backend — keys never reach the browser |
| **Input validation** | All query parameters validated and sanitised before use |
| **XSS prevention** | `escHtml()` applied to all user-derived data rendered in the DOM |
| **HTTPS enforced** | HAProxy redirects all HTTP → HTTPS with 301 |
| **HSTS** | `Strict-Transport-Security: max-age=31536000` forces HTTPS in browsers |
| **TLS 1.2+ only** | Older SSL/TLS versions disabled in HAProxy config |
| **Strong ciphers** | Only modern cipher suites enabled |
| **Secrets excluded from git** | `.env` in `.gitignore`; `.env.example` contains only placeholders |

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check — used by HAProxy for active monitoring |
| GET | `/api/search` | Search papers (params: q, author, year, type, sort, oa_only, page, per_page) |
| GET | `/api/paper?doi=` | Full paper detail by DOI or OpenAlex ID |
| GET | `/api/author?name=` | Author lookup with citation stats |
| GET | `/api/cite?doi=&format=` | Citation generation (apa, mla, chicago, harvard, bibtex) |
| GET | `/api/subjects?q=` | Concept/subject autocomplete |
| GET | `/api/admin/cache/stats` | Redis memory and key count |
| POST | `/api/admin/cache/flush` | Clear all cached data |

---

## Error Handling

All errors return JSON with an `error` key and appropriate HTTP status code:

| Scenario | Status | Response |
|---|---|---|
| Missing required parameter | 400 | `{"error": "q parameter is required"}` |
| Paper not found | 404 | `{"error": "Could not find paper..."}` |
| External API down | 502 | `{"error": "Failed to fetch..."}` |
| All APIs unavailable | 502 | `{"error": "Both OpenAlex and CrossRef unavailable..."}` |
| Unknown route | 404 | `{"error": "Endpoint not found"}` |
| Server error | 500 | `{"error": "Internal server error"}` |

The frontend catches all errors and displays a toast notification so the user always gets feedback. The app never crashes silently.

---

## Challenges & Solutions

**OpenAlex abstract format** — Abstracts are stored as inverted indexes `{word: [positions]}`. The backend reconstructs plain text by mapping words back to their positions.

**Papers without DOIs** — Many older papers and books have no DOI. The citation system now accepts OpenAlex IDs directly and falls back through CrossRef and Semantic Scholar to find metadata from any available source.

**CrossRef HTML in abstracts** — CrossRef wraps abstracts in JATS XML tags (`<jats:p>`). Stripped with `re.sub(r"<[^>]+>", "")` before returning to the frontend.

**Alpha Vantage rate limits** — N/A for this project (no API keys needed), but Redis caching was still implemented to reduce load on the free-tier APIs and improve response times.

**HAProxy SSL setup** — HAProxy requires the certificate and private key combined into a single `.pem` file, unlike Nginx which accepts them separately. Certbot certificates are combined with `cat fullchain.pem privkey.pem > combined.pem`.

**Docker on Windows filesystem** — Running Docker Compose from `/mnt/c/` (Windows filesystem) causes performance issues and container startup failures. Fixed by working from the WSL native filesystem (`~/projects/`).

**CI/CD SSH authentication** — Initial pipeline failed because the SSH key had a passphrase. Fixed by generating a dedicated passphrase-free deploy key and adding its public key to both servers' `authorized_keys`.

---

## Bonus Tasks Completed

| Bonus Task | Implementation |
|---|---|
| ✅ **Caching** | Redis caches all API responses with configurable TTLs |
| ✅ **Docker** | Full containerisation with Dockerfile + Docker Compose |
| ✅ **CI/CD Pipeline** | GitHub Actions — automated testing and deployment on every push |
| ✅ **Security measures** | Input validation, XSS prevention, HTTPS, HSTS, TLS 1.2+ |

---

## Credits & Attribution

- **OpenAlex** — Open scholarly database by OurResearch. https://openalex.org · https://docs.openalex.org
- **CrossRef** — DOI registration agency and metadata API. https://www.crossref.org · https://api.crossref.org
- **Semantic Scholar** — AI-powered research tool by Allen Institute for AI. https://www.semanticscholar.org · https://api.semanticscholar.org
- **Flask** — Python web framework. https://flask.palletsprojects.com
- **Redis** — In-memory data store for caching. https://redis.io
- **HAProxy** — Load balancer and proxy server. https://www.haproxy.org
- **Docker** — Containerisation platform. https://www.docker.com
- **GitHub Actions** — CI/CD platform. https://docs.github.com/en/actions
- **Let's Encrypt / Certbot** — Free SSL certificates. https://letsencrypt.org
- **Google Fonts** — Fraunces, DM Mono, DM Sans typefaces. https://fonts.google.com

---

> **Disclaimer:** This application is for academic research assistance only. Always verify citations against original sources before submitting academic work.