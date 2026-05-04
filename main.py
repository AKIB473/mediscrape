#!/usr/bin/env python3
"""Drug scraper CLI - scrapes medicine data from 25+ Bangladesh and international sources."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.logging import RichHandler

# Bangladesh scrapers
from scrapers.bangladesh.medex import MedExScraper
from scrapers.bangladesh.dims import DIMSScraper
from scrapers.bangladesh.dgda import DGDAScraper
from scrapers.bangladesh.bdmedex import BDMedExScraper
from scrapers.bangladesh.bddrugs import BDDrugsScraper
from scrapers.bangladesh.bddrugstore import BDDrugstoreScraper
from scrapers.bangladesh.arogga import AroggaScraper
from scrapers.bangladesh.medeasy import MedEasyScraper
from scrapers.bangladesh.osudpotro import OsudpotroScraper
from scrapers.bangladesh.lazzpharma import LazzPharmaScraper
from scrapers.bangladesh.dghs_shr import DGHSSHRScraper

# International API scrapers
from scrapers.international.openfda import OpenFDAScraper
from scrapers.international.rxnorm import RxNormScraper
from scrapers.international.dailymed import DailyMedScraper
from scrapers.international.pubchem import PubChemScraper
from scrapers.international.chembl import ChEMBLScraper
from scrapers.international.kegg import KEGGScraper
from scrapers.international.ema import EMAScraper

# International scraping scrapers
from scrapers.international.drugs_com import DrugsComScraper
from scrapers.international.rxlist import RxListScraper
from scrapers.international.webmd import WebMDScraper
from scrapers.international.emc import EMCScraper
from scrapers.international.mims import MIMSScraper
from scrapers.international.who_eml import WHOEMLScraper
from scrapers.international.medscape import MedscapeScraper
from scrapers.international.epocrates import EpocratesScraper

# Research scrapers
from scrapers.research.drugbank import DrugBankScraper
from scrapers.research.pharmgkb import PharmGKBScraper
from scrapers.research.clincalc import ClinCalcScraper

from utils.change_detector import ChangeDetector
from utils.pipeline import post_process as _post_process

console = Console()

ALL_SCRAPERS = {
    # Bangladesh
    "medex": MedExScraper,
    "dims": DIMSScraper,
    "dgda": DGDAScraper,
    "bdmedex": BDMedExScraper,
    "bddrugs": BDDrugsScraper,
    "bddrugstore": BDDrugstoreScraper,
    "arogga": AroggaScraper,
    "medeasy": MedEasyScraper,
    "osudpotro": OsudpotroScraper,
    "lazzpharma": LazzPharmaScraper,
    "dghs_shr": DGHSSHRScraper,
    # International APIs
    "openfda": OpenFDAScraper,
    "rxnorm": RxNormScraper,
    "dailymed": DailyMedScraper,
    "pubchem": PubChemScraper,
    "chembl": ChEMBLScraper,
    "kegg": KEGGScraper,
    "ema": EMAScraper,
    # International scraping
    "drugs_com": DrugsComScraper,
    "rxlist": RxListScraper,
    "webmd": WebMDScraper,
    "emc": EMCScraper,
    "mims": MIMSScraper,
    "who_eml": WHOEMLScraper,
    "medscape": MedscapeScraper,
    "epocrates": EpocratesScraper,
    # Research
    "drugbank": DrugBankScraper,
    "pharmgkb": PharmGKBScraper,
    "clincalc": ClinCalcScraper,
}

BD_SCRAPERS = [
    "medex", "dims", "dgda", "bdmedex", "bddrugs",
    "bddrugstore", "arogga", "medeasy", "osudpotro", "lazzpharma", "dghs_shr",
]
INTL_SCRAPERS = [
    "openfda", "rxnorm", "dailymed", "pubchem", "chembl",
    "kegg", "ema", "drugs_com", "rxlist", "webmd",
    "emc", "mims", "who_eml", "medscape", "epocrates",
]
RESEARCH_SCRAPERS = ["drugbank", "pharmgkb", "clincalc"]


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging")
def cli(verbose: bool):
    """Drug Scraper - Comprehensive medicine database scraper."""
    setup_logging(verbose)


@cli.command()
@click.argument("sources", nargs=-1)
@click.option("--all", "run_all", is_flag=True, help="Run all scrapers")
@click.option("--fullscrape", is_flag=True, help="Disable source caps; if used alone, runs all sources")
@click.option("--bd", is_flag=True, help="Run Bangladesh scrapers only")
@click.option("--intl", is_flag=True, help="Run international scrapers only")
@click.option("--research", is_flag=True, help="Run research scrapers only")
@click.option("--data-dir", type=Path, default=Path("data"), help="Output directory")
def scrape(
    sources: tuple,
    run_all: bool,
    fullscrape: bool,
    bd: bool,
    intl: bool,
    research: bool,
    data_dir: Path,
):
    """Run scrapers for specified sources."""
    if run_all:
        selected = list(ALL_SCRAPERS.keys())
    elif bd:
        selected = BD_SCRAPERS
    elif intl:
        selected = INTL_SCRAPERS
    elif research:
        selected = RESEARCH_SCRAPERS
    elif sources:
        selected = list(sources)
    elif fullscrape:
        selected = list(ALL_SCRAPERS.keys())
    else:
        console.print("[red]Specify sources, or use --all, --fullscrape, --bd, --intl, --research[/red]")
        sys.exit(1)

    invalid = [s for s in selected if s not in ALL_SCRAPERS]
    if invalid:
        console.print(f"[red]Unknown sources: {', '.join(invalid)}[/red]")
        sys.exit(1)

    if fullscrape:
        _enable_fullscrape_mode()

    asyncio.run(_run_scrapers(selected, data_dir))


def _enable_fullscrape_mode():
    """Force scraper cap env vars off for true full-dataset runs."""
    cap_env_vars = [
        "EPOCRATES_MAX_DRUGS",
        "MEDSCAPE_MAX_DRUGS",
        "DGHS_SHR_MAX_MEDICATIONS",
    ]
    for var in cap_env_vars:
        os.environ[var] = "0"
    logging.info("Full scrape mode enabled: source caps disabled.")


async def _run_scrapers(sources: list[str], data_dir: Path):
    results = []
    for source_name in sources:
        scraper_cls = ALL_SCRAPERS[source_name]
        scraper = scraper_cls(data_dir=data_dir)
        try:
            meta = await scraper.run()
            results.append(meta)
        except Exception as e:
            console.print(f"[red][{source_name}] Failed: {e}[/red]")
            logging.exception(f"Scraper {source_name} failed")

    # Print summary
    table = Table(title="Scrape Results")
    table.add_column("Source")
    table.add_column("Drugs", justify="right")
    table.add_column("Errors", justify="right")
    table.add_column("Time (s)", justify="right")
    table.add_column("Changed")

    detector = ChangeDetector(data_dir)
    for meta in results:
        changed = detector.has_changed(meta.source)
        table.add_row(
            meta.source,
            str(meta.total_drugs),
            str(meta.errors),
            f"{meta.duration_seconds:.1f}",
            "[green]Yes[/green]" if changed else "No",
        )
        detector.update_checksum(meta.source)

    console.print(table)


@cli.command()
@click.option("--data-dir", type=Path, default=Path("data"))
def check(data_dir: Path):
    """Check which sources have changed data since last run."""
    detector = ChangeDetector(data_dir)
    changed = detector.get_changed_sources(list(ALL_SCRAPERS.keys()))
    if changed:
        console.print(f"[yellow]Changed sources:[/yellow] {', '.join(changed)}")
    else:
        console.print("[green]No changes detected.[/green]")


@cli.command(name="post-process")
@click.option("--data-dir", type=Path, default=Path("data"), help="Data directory")
def post_process_cmd(data_dir: Path):
    """Normalize + merge all sources → SQLite DB + merged JSON."""
    import asyncio
    from utils.pipeline import post_process
    stats = asyncio.run(post_process(data_dir))
    table = Table(title="Post-Process Results")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for k, v in stats.items():
        if isinstance(v, dict):
            for sk, sv in v.items():
                table.add_row(f"  {k}.{sk}", str(sv))
        else:
            table.add_row(k, str(v))
    console.print(table)


@cli.command()
@click.argument("query")
@click.option("--data-dir", type=Path, default=Path("data"))
@click.option("--limit", default=20, help="Max results")
def search_db(query: str, data_dir: Path, limit: int):
    """Search the merged drug database."""
    import sqlite3
    from utils.database import search
    db_path = data_dir / "mediscrape.db"
    if not db_path.exists():
        console.print(f"[red]DB not found: {db_path}. Run 'post-process' first.[/red]")
        return
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    results = search(conn, query, limit)
    conn.close()
    if not results:
        console.print(f"[yellow]No results for '{query}'[/yellow]")
        return
    table = Table(title=f"Search: {query} ({len(results)} results)")
    table.add_column("Generic Name")
    table.add_column("Form")
    table.add_column("Strength")
    table.add_column("Class")
    table.add_column("Min Price (BDT)", justify="right")
    table.add_column("Sources", justify="right")
    for r in results:
        table.add_row(
            r.get("generic_name") or "",
            r.get("dosage_form") or "",
            r.get("strength") or "",
            (r.get("therapeutic_class") or "")[:30],
            str(r.get("min_price") or ""),
            str(r.get("source_count") or ""),
        )
    console.print(table)


@cli.command()
@click.option("--data-dir", type=Path, default=Path("data"))
def db_stats(data_dir: Path):
    """Show statistics about the merged drug database."""
    import sqlite3
    from utils.database import get_stats
    db_path = data_dir / "mediscrape.db"
    if not db_path.exists():
        console.print(f"[red]DB not found: {db_path}. Run 'post-process' first.[/red]")
        return
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    stats = get_stats(conn)
    conn.close()
    table = Table(title="Database Statistics")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for k, v in stats.items():
        if isinstance(v, dict):
            for sk, sv in list(v.items())[:10]:
                table.add_row(f"  {k}: {sk}", str(sv))
        else:
            table.add_row(k, str(v))
    console.print(table)


@cli.command(name="list")
def list_sources():
    """List all available scraper sources."""
    table = Table(title="Available Scrapers")
    table.add_column("Name")
    table.add_column("Category")
    table.add_column("Type")

    def scraper_type(name: str) -> str:
        cls = ALL_SCRAPERS[name]
        return "API" if any("API" in base.__name__ for base in cls.__mro__) else "scraping"

    for name in BD_SCRAPERS:
        table.add_row(name, "Bangladesh", scraper_type(name))
    for name in INTL_SCRAPERS:
        table.add_row(name, "International", scraper_type(name))
    for name in RESEARCH_SCRAPERS:
        table.add_row(name, "Research", scraper_type(name))

    console.print(table)


@cli.command(name="post-process")
@click.option("--data-dir", type=Path, default=Path("data"), help="Data directory")
def post_process_cmd(data_dir: Path):
    """Normalize, merge all sources, build SQLite DB and merged JSON."""
    asyncio.run(_post_process(data_dir))


@cli.command(name="search")
@click.argument("query")
@click.option("--data-dir", type=Path, default=Path("data"), help="Data directory")
@click.option("--limit", default=20, show_default=True, help="Max results")
def search_cmd(query: str, data_dir: Path, limit: int):
    """Search the merged drug database."""
    import sqlite3 as _sqlite3
    from utils.database import search as _search

    db_path = data_dir / "mediscrape.db"
    if not db_path.exists():
        console.print(f"[red]Database not found at {db_path}. Run 'post-process' first.[/red]")
        sys.exit(1)

    conn = _sqlite3.connect(str(db_path))
    conn.row_factory = _sqlite3.Row
    results = _search(conn, query, limit)
    conn.close()

    if not results:
        console.print(f"[yellow]No results for '{query}'[/yellow]")
        return

    table = Table(title=f"Search: {query} ({len(results)} results)")
    table.add_column("Generic Name", style="cyan")
    table.add_column("Dosage Form")
    table.add_column("Strength")
    table.add_column("Brand Names")
    table.add_column("Sources")
    table.add_column("Min Price", justify="right")

    for r in results:
        brands = r.get("brand_names", []) if isinstance(r.get("brand_names"), list) else []
        sources = r.get("sources", []) if isinstance(r.get("sources"), list) else []
        table.add_row(
            r.get("generic_name") or "",
            r.get("dosage_form") or "",
            r.get("strength") or "",
            ", ".join(brands[:3]) + ("…" if len(brands) > 3 else ""),
            ", ".join(sources),
            f"{r['min_price']:.2f} BDT" if r.get("min_price") is not None else "",
        )

    console.print(table)


@cli.command(name="stats")
@click.option("--data-dir", type=Path, default=Path("data"), help="Data directory")
def stats_cmd(data_dir: Path):
    """Show database statistics."""
    import sqlite3 as _sqlite3
    from utils.database import get_stats as _get_stats

    db_path = data_dir / "mediscrape.db"
    if not db_path.exists():
        console.print(f"[red]Database not found at {db_path}. Run 'post-process' first.[/red]")
        sys.exit(1)

    conn = _sqlite3.connect(str(db_path))
    conn.row_factory = _sqlite3.Row
    stats = _get_stats(conn)
    conn.close()

    table = Table(title="MediScrape Database Statistics")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Total canonical drugs",   str(stats.get("total_drugs", 0)))
    table.add_row("Total brand names",        str(stats.get("total_brands", 0)))
    table.add_row("Total price records",      str(stats.get("total_prices", 0)))
    table.add_row("Drugs with prices",        str(stats.get("drugs_with_prices", 0)))
    table.add_row("Drugs w/ mechanism",       str(stats.get("drugs_with_mechanism", 0)))
    table.add_row("Drugs w/ indications",     str(stats.get("drugs_with_indications", 0)))
    table.add_row("Drugs w/ chemistry data",  str(stats.get("drugs_with_chemistry", 0)))
    table.add_row("Active sources",           str(len(stats.get("sources", []))))

    console.print(table)

    if stats.get("sources"):
        console.print("[bold]Sources:[/bold] " + ", ".join(stats["sources"]))


if __name__ == "__main__":
    cli()
