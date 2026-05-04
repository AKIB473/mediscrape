# 🎯 Contributing to Mediscrape

## 🙏 Acknowledgment

**This project was initiated and is maintained by:**
- **Akibuzzaman Akib** (@akibuzzaman7) — Lead Developer
- All drug data aggregation, bypass engineering, and pipeline architecture by Akib

We welcome contributions from everyone! Please note that all contributors will be properly credited in the AUTHORS file and commit history.

## 🚀 Getting Started

### For New Contributors

1. **Read this entire guide**
2. **Pick an issue** from [GitHub Issues](https://github.com/AKIB473/mediscrape/issues) or start with "good first issue"
3. **Ask questions** in Discussions if stuck
4. **Submit PR** following the process below

### Setup Your Development Environment

```bash
# Fork the repository on GitHub
# Clone your fork
git clone https://github.com/YOUR_USERNAME/mediscrape.git
cd mediscrape

# Add upstream remote
git remote add upstream https://github.com/AKIB473/mediscrape.git

# Install dependencies
pip install -e .
playwright install chromium --with-deps
```

## 📋 Contribution Types

### 1. Add a New Scraper (Most Needed!)

We need more sources! Here's how:

#### Step 1: Create Scraper Skeleton

```python
# scrapers/[category]/your_source.py
from __future__ import annotations

import logging
from typing import AsyncIterator

from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseScrapingScraper  # or BaseAPIScraper

logger = logging.getLogger(__name__)

class YourSourceScraper(BaseScrapingScraper):
    name = "your_source"  # lowercase, underscore
    base_url = "https://example.com"
    rate_limit = 1.0  # seconds between requests
    use_stealth = True  # use Playwright stealth if needed

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Your scraping logic here
        # Yield Drug objects
        ...
```

#### Step 2: Use Bypass Stack

```python
# For API-based scrapers
page = await self.fetch_page(url)

# For custom requests
from utils.bypass import fetch_bypass
html = await fetch_bypass(url, use_playwright_fallback=True)
```

#### Step 3: Parse Drug Data

```python
# Extract fields
drug = Drug(
    source=self.name,
    source_url=url,
    brand_name="Brand Name",  # optional
    generic_name="Generic Name",  # important!
    dosage_form="Tablet",  # optional
    strength="500mg",  # optional
    manufacturer=Manufacturer(name="Mfr", country="Country"),
    price=DrugPrice(amount=10.0, currency="USD"),
    indications=["Indication 1", "Indication 2"],
    # ... other fields
)

yield drug
```

#### Step 4: Register Your Scraper

```python
# scrapers/__init__.py

# Add your scraper to appropriate category
BANGLADESH_SCRAPERS = [
    ...
    "your_source",
]

# Or for international
INTERNATIONAL_SCRAPERS = [
    ...
    "your_source",
]
```

#### Step 5: Test It

```bash
python main.py test-source your_source
```

### 2. Improve Data Quality

#### Improve Field Extraction

```python
# Add better parsing logic
# Use regex for structured text
# Clean up noisy data

def _clean_strength(text: str) -> str:
    """Extract and standardize strength."""
    # Example: "500 mg" -> "500mg"
    match = re.search(r'(\d+(?:\.\d+)?)\s*(mg|mcg|g|iu|unit)', text, re.I)
    return f"{match.group(1)}{match.group(2).lower()}" if match else text
```

#### Add Normalization Rules

```python
# utils/normalizer.py

def normalize_generic_name(name: str) -> str:
    """Standardize generic drug names."""
    # Add your normalization logic
    # e.g., "Vitamin B1" -> "thiamine"
    ...
```

### 3. Enhance Pipeline

#### Add New Export Format

```python
# utils/pipeline.py

async def export_csv(self, output_path: str):
    """Export drugs to CSV."""
    import csv
    
    drugs = await self.load_raw()
    drugs = await self.normalize(drugs)
    merged = await self.merge(drugs)
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=DRUG_FIELDS)
        writer.writeheader()
        for drug in merged:
            writer.writerow(drug.to_dict())
```

#### Improve Search

```python
# utils/database.py

# Add FTS5 full-text search
CREATE VIRTUAL TABLE drugs_fts USING fts5(
    generic_name, brand_names, indications
);
```

### 4. Fix Bugs

1. **Reproduce the bug**
2. **Write a test** (if possible)
3. **Fix the code**
4. **Verify the fix**

### 5. Documentation

- Improve README
- Add docstrings
- Write tutorials
- Create examples

## 🛠 Development Workflow

### 1. Create a Branch

```bash
git checkout -b feature/add-xyz-scraper
# or
git checkout -b fix/parsing-bug
```

### 2. Make Changes

```bash
# Edit files
vim scrapers/category/my_scraper.py

# Test as you go
python main.py test-source my_scraper
```

### 3. Commit Changes

```bash
git add .
git commit -m "feat: add XYZ scraper for ABC drugs

- Implemented XYZ API scraper
- Handles pagination
- Extracts 15 fields
- Test: 100+ drugs collected"
```

### 4. Push and PR

```bash
git push origin feature/add-xyz-scraper
```

Then open a Pull Request on GitHub.

## ✅ PR Requirements

### Must-Have

- [ ] Code follows existing style (Black format)
- [ ] Scrapers use bypass stack (`fetch_bypass` or `fetch_page`)
- [ ] No hardcoded secrets or API keys
- [ ] Handles `None`/empty gracefully (no crashes)
- [ ] Yield `Drug` objects (not raw dicts)
- [ ] Tested locally (sample run works)

### Nice-to-Have

- [ ] Docstrings for public functions
- [ ] Type hints
- [ ] Error handling with logging
- [ ] Rate limiting respect
- [ ] Comments for complex logic

## 📦 Code Style

### Format with Black

```bash
black .
```

### Type Check (Optional)

```bash
mypy .
```

### Import Order

```python
# Standard library
import logging
from typing import AsyncIterator

# Third-party
import httpx

# Local
from models.drug import Drug
from scrapers.base import BaseScrapingScraper
```

## 🧪 Testing

### Test Your Scraper

```bash
# Test single scraper
python main.py test-source your_source

# Test all scrapers (quick sample)
python main.py test-all
```

### Expected Output

```
Source           Drugs  Score  Brand  Generic   Form  Price  Clinical Status
your_source        5    85%      5        5      5      3         5 ✅
```

## 🔒 Security

- **Never commit secrets** (API keys, tokens, passwords)
- Use environment variables for sensitive data
- The GitHub token is auto-provided in Actions
- Don't scrape aggressively (respect `rate_limit`)

## 🌍 Translation

All code comments and documentation should be in English.

## 📝 License

By contributing, you agree your contributions are licensed under MIT License.

## 🙏 Thank You!

We appreciate all contributions, from bug reports to new scrapers! Every contribution helps make Mediscrape better.

---

**Need Help?**
- Open an Issue: [Report Bug](https://github.com/AKIB473/mediscrape/issues/new?template=bug.md)
- Ask Question: [Discussion](https://github.com/AKIB473/mediscrape/discussions)
- Contact: @akibuzzaman7 (GitHub)
