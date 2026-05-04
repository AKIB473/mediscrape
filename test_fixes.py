"""Local test script — tests Arogga, DIMS, Osudpotro scrapers quickly."""

import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("test_fixes")

DATA_DIR = Path("/tmp/test_mediscrape_data")
DATA_DIR.mkdir(exist_ok=True)

# Collect up to N drugs per scraper (quick test)
MAX_PER_SCRAPER = 20


async def test_scraper(scraper_cls, name: str) -> int:
    scraper = scraper_cls(data_dir=DATA_DIR)
    count = 0
    errors = 0
    logger.info(f"--- Testing {name} ---")
    try:
        async for drug in scraper.scrape_all():
            count += 1
            if count == 1:
                logger.info(
                    f"  First drug: brand={drug.brand_name!r} "
                    f"generic={drug.generic_name!r} "
                    f"form={drug.dosage_form!r} "
                    f"price={drug.price}"
                )
            if count >= MAX_PER_SCRAPER:
                break
    except Exception as e:
        logger.error(f"  {name} FAILED: {e}")
        errors += 1

    status = "✅" if count > 0 else "❌"
    logger.info(f"  {status} {name}: collected {count} drugs (errors={errors})")
    return count


async def main():
    from scrapers.bangladesh.arogga import AroggaScraper
    from scrapers.bangladesh.dims import DIMSScraper
    from scrapers.bangladesh.osudpotro import OsudpotroScraper

    results = {}

    results["arogga"] = await test_scraper(AroggaScraper, "Arogga")
    results["dims"] = await test_scraper(DIMSScraper, "DIMS")
    results["osudpotro"] = await test_scraper(OsudpotroScraper, "Osudpotro")

    print("\n========== SUMMARY ==========")
    all_ok = True
    for name, count in results.items():
        icon = "✅" if count > 0 else "❌"
        print(f"  {icon} {name:15s}: {count} drugs")
        if count == 0:
            all_ok = False

    print("==============================")
    if all_ok:
        print("All scrapers working! ✅")
    else:
        print("Some scrapers returned 0 drugs ❌ (check logs above)")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
