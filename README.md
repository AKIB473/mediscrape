# MediScrape

Comprehensive medicine database scraper for **29 sources** across Bangladesh and international drug databases. Uses [Scrapling](https://github.com/D4Vinci/Scrapling) for HTML scraping and `httpx` for REST APIs.

## Sources

### Bangladesh (11 scrapers)

| Source | URL | Data | Method |
|--------|-----|------|--------|
| MedEx | medex.com.bd | 25k+ brands, generics, prices, side effects | Scrapling (paginated) |
| DIMS | dimsbd.com | 28k+ brands, FDA pregnancy categories | Scrapling |
| DGDA | dgda.gov.bd | Official govt drug prices | Scrapling + Stealth |
| BD Medex | bdmedex.com | 35k+ brands, herbal + veterinary | Scrapling |
| BDdrugs | bddrugs.com | Drug index, prices, dosage forms | Scrapling |
| BD Drugstore | bddrugstore.com | Drug index + doctors directory | Scrapling |
| Arogga | arogga.com | 32k+ medicines | Stealth + sitemap/`__NEXT_DATA__` |
| MedEasy | medeasy.health | Online pharmacy | Stealth + API discovery |
| Osudpotro | osudpotro.com | 7 lakh+ items | Stealth + `__NEXT_DATA__` JSON |
| Lazz Pharma | lazzpharma.com | Online pharmacy | Stealth + WooCommerce/JSON-LD |
| DGHS SHR | fhir.dghs.gov.bd | FHIR medication terminology + optional live Medication feed | API (FHIR/JSON) |

### International APIs (7 scrapers)

| Source | URL | Data | Notes |
|--------|-----|------|-------|
| OpenFDA | open.fda.gov | US drugs, adverse events, labeling | No API key needed |
| RxNorm | lhncbc.nlm.nih.gov/RxNav | Drug names, interactions, classes | Free REST API |
| DailyMed | dailymed.nlm.nih.gov | FDA-approved labeling | Free REST API v2 |
| PubChem | pubchem.ncbi.nlm.nih.gov | 286M+ substances, chemical data | PUG-REST API |
| ChEMBL | ebi.ac.uk/chembl | 1.6M compounds, bioactivities | Free REST API |
| KEGG DRUG | genome.jp/kegg/drug | Approved drugs, pathways | Free REST API |
| EMA | ema.europa.eu | EU-authorized medicines | Static JSON dumps |

### International Scraping (8 scrapers)

| Source | URL | Data | Method |
|--------|-----|------|--------|
| Drugs.com | drugs.com | 24k+ drugs, interactions | Stealth + JSON-LD |
| RxList | rxlist.com | US prescribing info | Stealth |
| WebMD | webmd.com/drugs | A-Z database, interactions | Stealth |
| eMC (UK) | medicines.org.uk/emc | 9k+ UK medicines (SmPC) | Stealth + sitemap |
| MIMS (Asia) | mims.com | Asia-Pacific drug reference | Stealth |
| WHO EML | list.essentialmeds.org | 523 essential medications | Scrapling |
| Medscape | reference.medscape.com | 7k+ monographs, dosing, interactions | Scrapling + JSON-LD |
| Epocrates | epocrates.com | 7k+ drugs, classes, dosing cards | API + monograph scraping |

### Research (3 scrapers)

| Source | URL | Data | Method |
|--------|-----|------|--------|
| DrugBank | go.drugbank.com | 10k+ drugs, 1.4M+ interactions | Stealth |
| PharmGKB | pharmgkb.org | Pharmacogenomics | REST API (CC BY-SA 4.0) |
| ClinCalc | clincalc.com/DrugStats | Top 300 US drugs, trends | Scrapling |

## Installation

```bash
pip install -e .

# For stealth/JS-heavy sites:
python -m playwright install chromium
```

## Usage

```bash
# List all available scrapers
python main.py list

# Scrape specific sources
python main.py scrape medex openfda kegg

# Scrape by category
python main.py scrape --bd        # Bangladesh only (11)
python main.py scrape --intl      # International only (15)
python main.py scrape --research  # Research only (3)
python main.py scrape --all       # All 29 sources
python main.py scrape --fullscrape  # Full run (all sources, cap overrides)

# Full run for selected heavy sources
python main.py scrape --fullscrape medex dims bdmedex

# Check which sources have new data
python main.py check

# Verbose logging
python main.py -v scrape openfda
```

## Data Model

Every drug is normalized into a unified schema with 80+ fields:

```python
Drug(
    # Identity
    source, source_url, source_id, brand_name, generic_name, synonyms,

    # Classification
    drug_class, therapeutic_class, atc_code, schedule,

    # Chemistry
    molecular_formula, molecular_weight, smiles, inchi, cas_number,
    pubchem_cid, chembl_id, drugbank_id, rxcui, ndc,

    # Clinical
    indications, contraindications, side_effects, interactions,
    warnings, precautions, dosage, mechanism_of_action,

    # Pharmacology
    pharmacokinetics, half_life, bioavailability, protein_binding,

    # Safety
    pregnancy_category, black_box_warning, overdose,

    # Pricing
    price, prices,

    # Extras (source-specific fields)
    extra={...},
)
```

Output is saved as JSON in `data/<source>/drugs.json`.

## GitHub Actions

The included workflow (`.github/workflows/scrape.yml`) runs:
- **Daily** at 2 AM UTC: full scrape of all sources
- **Weekly** (Sundays): heavy scrapers with 25k+ drugs
- Auto-commits only when data changes (SHA256 checksums)
- Manual trigger with source/category selection and `fullscrape` toggle

## Architecture

```
mediscrape/
├── main.py                     # CLI entry point (click + rich)
├── models/drug.py              # Pydantic Drug model (80+ fields)
├── scrapers/
│   ├── base.py                 # BaseScraper, BaseAPIScraper, BaseScrapingScraper
│   ├── bangladesh/             # 11 BD scrapers
│   ├── international/          # 15 international scrapers (7 API + 8 scraping)
│   └── research/               # 3 research/academic scrapers
├── utils/
│   ├── storage.py              # JSON file I/O
│   └── change_detector.py      # SHA256 change detection
└── .github/workflows/scrape.yml
```

## Key Features

- **Scrapling** with `Fetcher` and `StealthyFetcher` for anti-bot bypass
- **JSON-LD extraction** on all HTML scrapers
- **Hidden API discovery** for Next.js/React apps (`__NEXT_DATA__`)
- **WooCommerce API** detection for e-commerce pharmacy sites
- **Retry + rate limiting** via tenacity on all scrapers
- **Change detection** via SHA256 checksums
- **Unified data model** - all sources normalized to same schema

## License

MIT
