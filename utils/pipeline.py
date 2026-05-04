"""
Full post-processing pipeline.

Ties together loading → normalisation → merging → SQLite storage → JSON export.
"""
from __future__ import annotations

import logging
from pathlib import Path

from utils.database import export_json, get_stats, init_db, upsert_merged
from utils.merger import load_all_raw_drugs, merge_drugs

logger = logging.getLogger(__name__)


async def post_process(data_dir: Path = Path('data')) -> dict:
    """
    Run the complete post-processing pipeline for the scraped drug data.

    Steps
    -----
    1.  Load all raw drug records from ``data_dir/*/drugs.json``.
    2.  Normalise and merge duplicates into canonical ``MergedDrug`` records.
    3.  Open (or create) the SQLite database at ``data_dir/mediscrape.db``.
    4.  Upsert every merged record.
    5.  Commit the transaction.
    6.  Export the full dataset as ``data_dir/merged_drugs.json``.
    7.  Print and return database statistics.

    Parameters
    ----------
    data_dir:
        Root data directory containing per-source sub-directories.

    Returns
    -------
    dict
        Statistics dict as returned by :func:`utils.database.get_stats`.
    """
    data_dir = Path(data_dir)

    logger.info('=== Post-processing pipeline starting ===')
    logger.info('Data directory: %s', data_dir.resolve())

    # 1. Load
    raw = load_all_raw_drugs(data_dir)
    if not raw:
        logger.warning('No raw drug records found in %s', data_dir)

    # 2. Merge
    merged = merge_drugs(raw)

    # 3. Init DB
    db_path = data_dir / 'mediscrape.db'
    conn = init_db(db_path)

    # 4 & 5. Upsert + commit
    for drug in merged:
        upsert_merged(conn, drug)
    conn.commit()
    logger.info('Upserted %d merged drugs', len(merged))

    # 6. Export JSON
    json_path = data_dir / 'merged_drugs.json'
    export_json(conn, json_path)

    # 7. Stats
    stats = get_stats(conn)
    conn.close()

    print('\n=== Pipeline Complete ===')
    print(f"  Total canonical drugs : {stats.get('total_drugs', 0)}")
    print(f"  Total brand names     : {stats.get('total_brands', 0)}")
    print(f"  Total price records   : {stats.get('total_prices', 0)}")
    print(f"  Drugs with prices     : {stats.get('drugs_with_prices', 0)}")
    print(f"  Drugs w/ mechanism    : {stats.get('drugs_with_mechanism', 0)}")
    print(f"  Drugs w/ indications  : {stats.get('drugs_with_indications', 0)}")
    print(f"  Drugs w/ chemistry    : {stats.get('drugs_with_chemistry', 0)}")
    print(f"  Sources               : {', '.join(stats.get('sources', []))}")
    print(f"  DB path               : {db_path}")
    print(f"  JSON export           : {json_path}")

    return stats
