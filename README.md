# Research Finder

An academic paper search and organiser for students and researchers. Search millions of scholarly works, filter by author, year, type, and open-access status, save papers to a persistent library, and generate citations in APA, MLA, Chicago, Harvard, or BibTeX format.

Built with **Python Flask** (backend proxy + caching), **Redis** (response caching), and vanilla **HTML/CSS/JS** (frontend). **No API keys required** — both data sources are free and open.

---

## Features

| Feature | Description |
|---|---|
| **Keyword search** | Search by topic, title, or phrase across 240M+ papers |
| **Author filter** | Filter results by author last name |
| **Year / Type / OA filters** | Narrow by publication year, document type, and open-access status |
| **Sort options** | Relevance, most cited, or newest first |
| **Paper detail modal** | Full abstract, concepts, stats, and links |
| **Citation generator** | APA · MLA · Chicago · Harvard · BibTeX with one-click copy |
| **My Library** | Save papers to browser localStorage — persists across sessions |
| **Library sorting** | Sort saved papers by date added, year, citations, or title |
| **OpenAlex + CrossRef** | Automatic fallback if primary API is unavailable |
| **Redis caching** | Search results cached 1hr, paper metadata cached 24hr |
| **Source badge** | Shows which API served each result |

---

## APIs Used

| API | Purpose | Docs | Key Required |
|---|---|---|---|
| **OpenAlex** | Primary: full-text search, filters, author stats, concepts | https://docs.openalex.org | No |
| **CrossRef** | Fallback: DOI metadata, journal articles | https://api.crossref.org | No |

---

## Project Structure

```
research-finder/
├── backend/
│   ├── app.py              # Flask app — all routes, normalisation, citation logic
│   ├── requirements.txt
│   └── __init__.py
├── frontend/
│   ├── templates/
│   │   └── index.html      # Single-page HTML template
│   └── static/
│       ├── css/main.css    # Styles
│       └── js/main.js      # Frontend logic
├── nginx/
│   └── nginx.conf          # Load balancer config for Lb01
├── docs/
│   └── HOW_IT_WORKS.md     # Full technical documentation
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

---

## Local Setup (Docker — recommended)

### Prerequisites
- Docker Desktop with WSL 2 integration enabled
- No API keys needed

```bash
# 1. Clone or unzip the project
cd ~/projects/research-finder

# 2. Create .env (no keys required, just set your email)
cp .env.example .env
nano .env   # set CONTACT_EMAIL=your@email.com

# 3. Start
docker compose up --build

# 4. Open
# http://localhost:5000
```

---

## Local Setup (without Docker)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

cp .env.example .env
# Start Redis: redis-server &

python -m backend.app
# → http://localhost:5000
```

---

## Deployment to Web Servers

```bash
# Copy to both servers
scp -r research-finder/ user@WEB01_IP:~/research-finder/
scp -r research-finder/ user@WEB02_IP:~/research-finder/

# On each server
cd ~/research-finder
cp .env.example .env && nano .env
docker compose up --build -d

# Verify
curl http://WEB01_IP:5000/health
curl http://WEB02_IP:5000/health
```

## Load Balancer (Lb01)

```bash
sudo apt install -y nginx
scp nginx/nginx.conf user@LB01_IP:/tmp/rf.conf
ssh user@LB01_IP
sudo cp /tmp/rf.conf /etc/nginx/nginx.conf
# Edit: replace WEB01_IP and WEB02_IP with real IPs
sudo nano /etc/nginx/nginx.conf
sudo nginx -t && sudo systemctl reload nginx
```

Test: open `http://LB01_IP` — the app should load and route to both servers.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/search?q=&author=&year=&type=&sort=&oa_only=&page=&per_page=` | Search papers |
| GET | `/api/paper?doi=` | Full paper detail |
| GET | `/api/author?name=` | Author lookup |
| GET | `/api/cite?doi=&format=apa\|mla\|chicago\|harvard\|bibtex` | Generate citation |
| GET | `/api/subjects?q=` | Concept autocomplete |
| GET | `/api/admin/cache/stats` | Redis stats |
| POST | `/api/admin/cache/flush` | Clear cache |

---

## Challenges & Solutions

**OpenAlex abstract format** — OpenAlex stores abstracts as an inverted index (`{word: [positions]}`). The backend reconstructs plain text by building an array indexed by position and joining the words.

**CrossRef HTML in abstracts** — CrossRef wraps abstracts in JATS XML tags. A simple `re.sub(r"<[^>]+>", "")` strips them before returning to the frontend.

**No API keys = no `.env` complexity** — The biggest win. Users can clone, run `docker compose up`, and have a working app immediately.

**Library persistence without a database** — `localStorage` gives per-browser persistence with zero backend complexity, which is ideal for a load-balanced deployment where maintaining session state across servers would be tricky.

---

## Credits & Attribution

- **OpenAlex** — Open scholarly database by OurResearch. https://openalex.org
- **CrossRef** — DOI registration agency and metadata API. https://www.crossref.org
- **Flask** — Python web framework. https://flask.palletsprojects.com
- **Redis** — In-memory cache. https://redis.io
- **Nginx** — Load balancer. https://nginx.org
- **Docker** — Containerisation. https://www.docker.com
- **Google Fonts** — Fraunces, DM Mono, DM Sans. https://fonts.google.com

---

> **Note:** This application is for academic research assistance only. Always verify citations against the original source before submitting academic work.
