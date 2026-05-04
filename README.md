# 🏥 Mediscrape — Unified Drug Intelligence Pipeline

<div align="center">

[![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/AKIB473/mediscrape/scrape.yml?branch=master&style=for-the-badge)](https://github.com/AKIB473/mediscrape/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue?style=for-the-badge&logo=python)](https://python.org)
[![Code Style: Black](https://img.shields.io/badge/code%20style-black-black?style=for-the-badge)](https://github.com/psf/black)

[![Total Scrapers](https://img.shields.io/badge/scrapers-29-brightgreen?style=for-the-badge)](https://github.com/AKIB473/mediscrape)
[![BD Sources](https://img.shields.io/badge/BD_sources-6-orange?style=for-the-badge)](https://github.com/AKIB473/mediscrape)
[![Intl Sources](https://img.shields.io/badge/intl_sources-23-cyan?style=for-the-badge)](https://github.com/AKIB473/mediscrape)

</div>

---

## 🌟 Overview

**Mediscrape** is a backend-grade, production-ready data pipeline that **unifies drug information from 29 diverse sources** into one clean, deduplicated, structured database. Built for researchers, pharmacists, developers, and healthcare innovators who need reliable drug data at scale.

### ✨ What It Does

- **Aggregates** drug data from 29 scrapers (6 Bangladesh + 23 International)
- **Normalizes** chaotic, inconsistent raw data into clean structured formats
- **De-duplicates** same drugs with different spellings/brands using canonical IDs
- **Enriches** with clinical info, chemical data, pricing, manufacturers
- **Exports** to SQLite database + JSON REST API format
- **Bypasses** Cloudflare/bot protection automatically (4-level progressive stack)

### 🎯 Use Cases

- Drug price comparison & market research
- Pharmaceutical databases & formularies
- Clinical decision support systems
- Drug interaction checkers
- Medical research & analytics
- Healthcare app backends

---

## 🚀 Quick Start

### Prerequisites

```bash
# Python 3.11+ required
python --version

# Install dependencies (already in pyproject.toml)
pip install -e .

# Install Playwright browsers (for JS-heavy sites)
pip install playwright
playwright install chromium --with-deps
```

### Basic Usage

```bash
# Run the full pipeline (scrape + process)
python main.py run-all

# Or step by step:
python main.py scrape          # Run all scrapers
python main.py post-process    # Merge, normalize, build DB
python main.py search-db "napa" # Search the database
python main.py db-stats        # Show database statistics
```

### Docker (Recommended)

```bash
docker build -t mediscrape .
docker run -v ./data:/app/data mediscrape python main.py run-all
```

---

## 📊 Data Sources (29 Scrapers)

### 🇧🇩 Bangladesh (6)
| Source | Type | Status | Data Points |
|--------|------|--------|-------------|
| **MedEx BD** | API | ✅ Live | Brand, Generic, Form, Price, Clinical |
| **Arogga** | HTML | ✅ Live | 56k+ products, prices, categories |
| **Osudpotro** | REST API | ✅ Live | 7L+ items, JWT auth, slugs |
| **DIMS** | Playwright | ✅ Live | Generic names, browser bypass |
| **BDMedEx** | Playwright | ✅ Live | JS SPA, full render |
| **BD Drugs/Stores** | HTML | ⚠️ Down | Site unreachable |

### 🌍 International (23)
| Source | Type | Status | Highlights |
|--------|------|--------|------------|
| **OpenFDA** | API | ✅ Live | US labels, adverse events |
| **RxNorm** | API | ✅ Live | NLM IDs, cross-references |
| **DailyMed** | API | ✅ Live | SPL documents |
| **PubChem** | API | ✅ Live | 100M+ compounds, CID |
| **ChEMBL** | API | ✅ Live | Bioactivity data |
| **DrugBank** | API | ✅ Live | PharmGKB, pathways |
| **ClinCalc** | HTML | ✅ Live | Top 300 US prescriptions |
| **Drugs.com** | Playwright | ✅ Live | CF bypass, reviews |
| **WebMD/EMC/MIMS** | Mixed | ✅ Live | Monographs, PIL |

---

## 🏗️ Architecture

```

        29 SCRAPERS (Parallel)             
  ┌───────────┐ ┌───────────┐ ┌─────────┐ 
  │           │ │           │ │         │ 
  │ BD Sources│ │  API      │ │  Scrape │ 
  │ 6 total   │ │ 15 total  │ │ 8 total │ 
  │           │ │           │ │         │ 
  └───────────┘ └───────────┘ └─────────┘ 
       │                 │              │
       └─────────────────┼──────────────┘
                        ▼
             
        Bypass Stack (4 Levels)        
             
      1. curl_cffi  (TLS spoof)      ⚡
      2. cloudscraper (JS solve)      🌐
      3. playwright (full browser)   🎭
      4. httpx       (fallback)      🔄
             
                        ▼
             
       Normalizer (Pydantic)          
             
      • Standardize names             
      • Canonical IDs (hash)          
      • Clean strengths/forms         
      • Handle None gracefully        
             
                        ▼
             
       Merger (De-duplication)        
             
      • Group by canonical_id         
      • Prioritize sources            
      • Merge multi-source fields     
      • Preserve all metadata         
             
                        ▼
             
       SQLite Database (WAL)          
             
      Tables:                         
      • drugs          (canonical)    
      • brand_names    (aliases)      
      • prices         (currency)     
      • clinical       (indications)  
      • chemistry      (formula)      
      • sources        (provenance)   
             
                        ▼
             
        Export: DB + merged_drugs.json
             
```

---

## 🔐 Anti-Bot & Cloudflare Bypass

**Progressive 4-Level Stack** — Automatic, no manual intervention:

```python
# utils/bypass.py
1️⃣ curl_cffi    → TLS/HTTP2 impersonation (0.5-2s) ⚡ Fastest
   ↓ (if rate-limited / JS challenge)
2️⃣ cloudscraper → Direct Cloudflare solver (2-5s) 🌐
   ↓ (if blocked / CAPTCHA)
3️⃣ playwright   → Headless Chrome (5-10s) 🎭 Full render
   ↓ (if all else fails)
4️⃣ httpx        → Simple fallback (no CF) 🔄
```

- **Per-domain sessions** — Maintains cookies/CF clearance
- **Automatic retry** — Transparent to scraper code
- **No API keys** — Fully self-contained

---

## 🗄️ Database Schema

### Main Tables

```sql
-- Canonical drugs (one row per unique drug)
CREATE TABLE drugs (
    id INTEGER PRIMARY KEY,
    canonical_id TEXT UNIQUE,      -- SHA256(generic+form+strength)
    generic_name TEXT,
    dosage_form TEXT,
    strength TEXT,
    manufacturer_id INTEGER,
    drug_class TEXT,
    pharmacological_class TEXT,
    therapeutic_class TEXT,
    molecular_formula TEXT,
    pubchem_cid INTEGER,
    rxcui TEXT,
    unii TEXT,
    ndc TEXT[],
    created_at TIMESTAMP
);

-- Brand name aliases
CREATE TABLE brand_names (
    drug_id INTEGER REFERENCES drugs(id),
    brand_name TEXT,
    source TEXT,
    is_primary BOOLEAN
);

-- Pricing data
CREATE TABLE prices (
    drug_id INTEGER REFERENCES drugs(id),
    amount REAL,
    currency TEXT,
    unit TEXT,
    source TEXT,
    last_updated TIMESTAMP
);

-- Clinical information
CREATE TABLE clinical (
    drug_id INTEGER REFERENCES drugs(id),
    indications TEXT[],
    contraindications TEXT[],
    side_effects TEXT[],
    dosage TEXT,
    mechanism_of_action TEXT,
    warnings TEXT[],
    pregnancy_category TEXT,
    storage TEXT
);

-- Chemical data
CREATE TABLE chemistry (
    drug_id INTEGER REFERENCES drugs(id),
    molecular_formula TEXT,
    molecular_weight REAL,
    smiles TEXT,
    inchi TEXT,
    chembl_id TEXT,
    kegg_id TEXT
);

-- Source provenance
CREATE TABLE sources (
    drug_id INTEGER REFERENCES drugs(id),
    source_name TEXT,      -- e.g., "openfda", "medex"
    source_url TEXT,
    source_id TEXT,
    scraped_at TIMESTAMP,
    data_completeness JSON
);
```

---

## 🛠 CLI Commands

### Main Commands

```bash
# Full pipeline: scrape → process → DB
python main.py run-all

# Individual steps
python main.py scrape          # Run all scrapers, save raw JSON
python main.py post-process    # Merge, normalize, build SQLite
python main.py search-db <query>  # Search database (SQL + FTS5)
python main.py db-stats        # Show statistics

# Scraper management
python main.py list-sources    # List all available scrapers
python main.py test-source <name>  # Test one scraper (sample 5 drugs)
```

### Output Files

```
data/
├── raw/                      # Raw JSON from each scraper
│   ├── medex.json
│   ├── openfda.json
│   └── ...
├── merged_drugs.json         # Unified, deduplicated JSON
└── mediscrape.db             # SQLite database (WAL mode)
```

---

## 🧬 Data Normalization

### Canonical ID Generation

```python
canonical_id = sha256(
    f"{generic_name.lower()}|{dosage_form.lower()}|{strength}"
).hexdigest()[:16]
```

Same drug from different sources → same canonical ID → merged into one row.

### Field Prioritization (Multi-Source Merge)

| Field | Priority Order |
|-------|----------------|
| Clinical info | MedEx > DIMS > BDMedEx > OpenFDA |
| Chemistry | PubChem > ChEMBL > DrugBank |
| Prices | Arogga > Osudpotro > MedEx |
| Generic names | MedEx > DIMS > RxNorm |

### Graceful None Handling

- Missing fields → `NULL` (never crash)
- Empty lists → `[]` (never `None`)
- Optional fields → Pydantic `Optional[T]`

---

## 🤝 Contribution Guide

### 💡 How to Contribute

We welcome all contributions! Here's how you can help:

#### 1️⃣ Add a New Scraper

**Step 1:** Create scraper file
```python
# scrapers/[category]/new_source.py
from scrapers.base import BaseScrapingScraper
from models.drug import Drug

class NewSourceScraper(BaseScrapingScraper):
    name = "newsource"
    base_url = "https://example.com"
    rate_limit = 1.0
    
    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Your scraping logic
        # Yield Drug objects
        ...
```

**Step 2:** Add to scraper groups
```python
# scrapers/__init__.py
BANGLADESH_SCRAPERS = [
    ...
    "newsource",
]
```

**Step 3:** Test it
```bash
python main.py test-source newsource
```

#### 2️⃣ Improve Bypass

- Add new bypass techniques
- Improve detection handling
- Reduce latency

#### 3️⃣ Fix Data Quality

- Improve field extraction
- Add missing normalization rules
- Fix parsing for specific sources

#### 4️⃣ Enhance Pipeline

- Add new export formats (CSV, Parquet)
- Improve search (add FTS5, synonyms)
- Add data validation rules

### 📋 Coding Standards

```bash
# Format code
black .

# Type check
mypy .

# Lint
ruff check --fix .
```

### 🧪 Testing

```bash
# Test all scrapers (sample mode)
python main.py test-all

# Test specific scraper
python main.py test-source medex
```

### 📝 Pull Request Process

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/new-scraper`)
3. **Commit** your changes (`git commit -m 'feat: add newsource scraper'`)
4. **Push** to your branch (`git push origin feature/new-scraper`)
5. **Open** a Pull Request

**PR Requirements:**
- ✅ Code follows existing style
- ✅ Scrapers use bypass stack
- ✅ No hardcoded secrets
- ✅ Handles None/empty gracefully
- ✅ Includes tests or samples

---

## 🎬 Demo & Usage Examples

### Example 1: Get All Paracetamol Products

```python
import json
from utils.database import DrugDatabase

db = DrugDatabase("data/mediscrape.db")
results = db.search("paracetamol")

for drug in results:
    print(f"Brand: {drug['brand_name']}")
    print(f"Generic: {drug['generic_name']}")
    print(f"Price: {drug.get('price', 'N/A')}")
    print(f"Source: {drug['sources']}")
    print("---")
```

### Example 2: Compare Prices Across Sources

```python
import sqlite3, pandas as pd

conn = sqlite3.connect("data/mediscrape.db")
df = pd.read_sql_query("""
    SELECT d.generic_name, b.brand_name, p.amount, p.currency, s.source_name
    FROM drugs d
    JOIN brand_names b ON d.id = b.drug_id
    JOIN prices p ON d.id = p.drug_id
    JOIN sources s ON d.id = s.drug_id
    WHERE d.generic_name LIKE '%paracetamol%'
    ORDER BY p.amount
""", conn)
print(df)
```

### Example 3: Export to JSON API

```python
from utils.pipeline import DrugPipeline

pipeline = DrugPipeline()
pipeline.run_full_pipeline()

# Output: data/merged_drugs.json
# Ready for REST API serving!
```

---

## 📈 Current Statistics

| Metric | Count |
|--------|-------|
| **Total Scrapers** | 29 |
| **Active Sources** | 23 |
| **Bangladesh Sources** | 6 |
| **International Sources** | 23 |
| **Drugs in DB** | ~200k+ |
| **Brands Tracked** | ~500k+ |
| **Last Update** | Auto-daily |

---

## 🔒 Security & Privacy

- **No personal data** collected
- **Respects robots.txt** (where applicable)
- **Rate limiting** per domain
- **No API keys required** (except optional DrugBank)
- **GitHub token**: Use `secrets.GITHUB_TOKEN` (auto-provided)

### Token Rotation 🔑

**Important:** Rotate exposed tokens immediately:
```bash
gh secret set GITHUB_TOKEN --body "ghp_your_new_token"
```

---

## 📜 License

MIT License - free for research, commercial, and learning use.

---

## ❤️ Acknowledgments

- **Contributors:** [@akibuzzaman7](https://github.com/akibuzzaman7)
- **Inspired by:** OpenFDA, RxNav, DailyMed
- **Special thanks:** Bangladesh pharmaceutical community

---

<div align="center">

**Built with ❤️ for the healthcare community**  
Mediscrape — Unified Drug Intelligence  

</div>
