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

<div align="center">

<img src="https://readme-typing-svg.demolab.com?font=Inter&weight=600&size=32&duration=3000&pause=1000&color=FF6B6B&center=true&vCenter=true&width=550&height=70&lines=MEDISCRAPE+%7C+29+Sources+%7C+1+Database;Built+by+Akibuzzaman+Akib"
  alt="Typing SVG" />

</div>

**Mediscrape** is a **production-grade data pipeline** that unifies pharmaceutical information from **29 diverse sources** into one clean, deduplicated database.

**🏗️ Built from scratch by Akibuzzaman Akib** — every scraper, bypass system, database schema, and pipeline component was designed and implemented by him.

---

## 👤 **Author & Creator**

### **Akibuzzaman Akib** (@akibuzzaman7)  
**Lead Developer | System Architect | Data Engineer**

| Role | Contributions |
|------|---------------|
| **🔧 Lead Architect** | Designed entire system architecture |
| **🕷️ Scraper Engineer** | Implemented all 29 scrapers |
| **🔐 Bypass Specialist** | Created 4-level Cloudflare bypass system |
| **🗄️ Database Designer** | Built SQLite schema (6 tables) |
| **⚙️ Pipeline Engineer** | Orchestrator & normalizer |
| **📊 Data Analyst** | Deduplication & normalization logic |

**Contact:**
- 📧 Email: `akibuzzaman7@gmail.com`
- 📱 Telegram: `@akibuzzaman7`
- 🐙 GitHub: [@akibuzzaman7](https://github.com/akibuzzaman7)

---

## 🤝 **Contributions**

This project was **entirely created and built by Akibuzzaman Akib**.

All code, architecture decisions, and implementations are his work:
- ✅ 29 scraper implementations
- ✅ 4-level bypass stack
- ✅ Database schema & queries
- ✅ Pipeline orchestration
- ✅ CLI tools
- ✅ Data normalization logic

*Future contributors are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md).*

---

## 📊 **Data Sources (29 Scrapers)**

### 🇧🇩 Bangladesh (6)
| Source | Type | Status | Built By |
|--------|------|--------|----------|
| **MedEx BD** | API | ✅ Live | Akibuzzaman Akib |
| **Arogga** | HTML | ✅ Live | Akibuzzaman Akib |
| **Osudpotro** | REST API | ✅ Live | Akibuzzaman Akib |
| **DIMS** | Playwright | ✅ Live | Akibuzzaman Akib |
| **BDMedEx** | Playwright | ✅ Live | Akibuzzaman Akib |
| **BD Drugs/Stores** | HTML | ⚠️ Down | Akibuzzaman Akib |

### 🌍 International (23)
| Source | Type | Status | Built By |
|--------|------|--------|----------|
| **OpenFDA** | API | ✅ Live | Akibuzzaman Akib |
| **RxNorm** | API | ✅ Live | Akibuzzaman Akib |
| **DailyMed** | API | ✅ Live | Akibuzzaman Akib |
| **PubChem** | API | ✅ Live | Akibuzzaman Akib |
| **ChEMBL** | API | ✅ Live | Akibuzzaman Akib |
| **DrugBank** | API | ✅ Live | Akibuzzaman Akib |
| **ClinCalc** | HTML | ✅ Live | Akibuzzaman Akib |
| **Drugs.com** | Playwright | ✅ Live | Akibuzzaman Akib |
| **WebMD/EMC/MIMS** | Mixed | ✅ Live | Akibuzzaman Akib |

*...and 14 more sources implemented by Akibuzzaman Akib*

---

## 🏗️ Architecture

```

        29 SCRAPERS (All by Akibuzzaman Akib)    
  ┌─────────────┐ ┌─────────────┐ ┌─────────┐ 
  │   BD Src    │ │    API      │ │ Scrape  │ 
  │    (6)      │ │   (15)      │ │  (8)    │ 
  │             │ │             │ │         │ 
  └─────────────┘ └─────────────┘ └─────────┘ 
       │                 │              │
       └─────────────────┼──────────────┘
                        ▼
             
              4-Level Bypass System          
             (Created by Akibuzzaman Akib)   
                                             
      1. curl_cffi  (TLS spoof)      ⚡    
      2. cloudscraper (JS solve)      🌐     
      3. playwright (full browser)   🎭     
      4. httpx       (fallback)      🔄     
             
                        ▼
             
       Normalizer (Pydantic)                
       (Designed by Akibuzzaman Akib)       
                                             
      • Canonical IDs (SHA256 hash)         
      • Standardize names/forms             
      • Handle None gracefully              
             
                        ▼
             
       Merger (De-duplication)              
       (Built by Akibuzzaman Akib)          
                                             
      • Group by canonical_id               
      • Prioritize sources                  
      • Merge multi-source data             
             
                        ▼
             
       SQLite Database (WAL mode)           
       (Schema by Akibuzzaman Akib)         
                                             
      Tables:                               
      • drugs          (canonical)          
      • brand_names    (aliases)            
      • prices         (costs)              
      • clinical       (indications)        
      • chemistry      (structures)         
      • sources        (provenance)         
             
                        ▼
             
        Export: DB + merged_drugs.json      
        (Pipeline by Akibuzzaman Akib)      
             
```

---

## 🔐 Anti-Bot & Cloudflare Bypass

**4-Level Progressive Stack** — Created by Akibuzzaman Akib

```
1️⃣ curl_cffi    → TLS/HTTP2 impersonation (0.5-2s) ⚡
   ↓ (if rate-limited / JS challenge)
2️⃣ cloudscraper → Direct Cloudflare solver (2-5s) 🌐
   ↓ (if blocked / CAPTCHA)
3️⃣ playwright   → Headless Chrome (5-10s) 🎭
   ↓ (if all else fails)
4️⃣ httpx        → Simple fallback 🔄
```

- Per-domain sessions maintain cookies/CF clearance
- Automatic retry — transparent to scraper code
- **Zero API keys required** — fully self-contained

---

## 🗄️ Database Schema (6 Tables)

Designed & implemented by **Akibuzzaman Akib**:

```sql
-- Canonical drugs (one row per unique drug)
CREATE TABLE drugs (
    id INTEGER PRIMARY KEY,
    canonical_id TEXT UNIQUE,       -- SHA256(generic|form|strength)
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
CREATE TABLE brand_names (...);

-- Pricing data
CREATE TABLE prices (...);

-- Clinical information
CREATE TABLE clinical (...);

-- Chemical data
CREATE TABLE chemistry (...);

-- Source provenance
CREATE TABLE sources (...);
```

---

## 🛠 CLI Commands

Created by **Akibuzzaman Akib**:

```bash
# Full pipeline: scrape → process → DB
python main.py run-all

# Individual steps
python main.py scrape          # Run all scrapers
python main.py post-process    # Merge, normalize, build SQLite
python main.py search-db "napa" # Search database
python main.py db-stats        # Show statistics

# Scraper management
python main.py list-sources    # List all scrapers
python main.py test-source <name>  # Test one scraper
```

### Output Files Structure

```
data/
├── raw/                      # Raw JSON from each scraper
├── merged_drugs.json         # Unified, deduplicated JSON
└── mediscrape.db             # SQLite database (WAL mode)
```

---

## 🧬 Data Normalization

**Canonical ID System** — Invented by Akibuzzaman Akib

```python
canonical_id = sha256(
    f"{generic_name.lower()}|{dosage_form.lower()}|{strength}"
).hexdigest()[:16]
```

Same drug from different sources → same canonical ID → merged.

### Field Prioritization

| Field | Priority Order (by Akib) |
|-------|---------------------------|
| Clinical info | MedEx > DIMS > BDMedEx > OpenFDA |
| Chemistry | PubChem > ChEMBL > DrugBank |
| Prices | Arogga > Osudpotro > MedEx |
| Generic names | MedEx > DIMS > RxNorm |

---

## 🎬 Usage Examples

### Example 1: Search Database (Created by Akib)

```python
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

### Example 2: Compare Prices (Akib's Design)

```python
import sqlite3, pandas as pd

conn = sqlite3.connect("data/mediscrape.db")
df = pd.read_sql_query("""
    SELECT d.generic_name, b.brand_name, p.amount, 
           p.currency, s.source_name
    FROM drugs d
    JOIN brand_names b ON d.id = b.drug_id
    JOIN prices p ON d.id = p.drug_id
    JOIN sources s ON d.id = s.drug_id
    WHERE d.generic_name LIKE '%paracetamol%'
    ORDER BY p.amount
""", conn)
print(df)
```

---

## 📈 Current Statistics

| Metric | Count |
|--------|-------|
| **Total Scrapers** | 29 (all by Akib) |
| **Active Sources** | 23+ |
| **Bangladesh Sources** | 6 |
| **International Sources** | 23 |
| **Drugs in DB** | ~200k+ |
| **Brands Tracked** | ~500k+ |
| **Creator** | Akibuzzaman Akib |

---

## 🔒 Security

- No personal data collected
- Respects robots.txt
- Rate limiting per domain
- No API keys required

---

## 📜 License

MIT License

---

## ❤️ **CREATOR**

**Built entirely by Akibuzzaman Akib** (@akibuzzaman7)

All contributions, code, architecture, and design by:
- 🏗️ **Akibuzzaman Akib** — Lead Developer & Creator

**Contact:**
- 📧 Email: akibuzzaman7@gmail.com  
- 📱 Telegram: @akibuzzaman7
- 🐙 GitHub: [@akibuzzaman7](https://github.com/akibuzzaman7)

<div align="center">

**Built with ❤️ for the healthcare community**  
Mediscrape — Unified Drug Intelligence  

</div>
