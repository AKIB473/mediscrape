"""SQLite backend for merged drug data."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DDL = [
    """CREATE TABLE IF NOT EXISTS drugs (
        id TEXT PRIMARY KEY, generic_name TEXT NOT NULL,
        dosage_form TEXT, strength TEXT, route TEXT,
        drug_class TEXT, therapeutic_class TEXT, atc_code TEXT,
        pregnancy_category TEXT, black_box_warning INTEGER DEFAULT 0,
        description TEXT, image_url TEXT,
        min_price REAL, max_price REAL,
        source_count INTEGER DEFAULT 0,
        first_seen TEXT, last_updated TEXT)""",
    """CREATE TABLE IF NOT EXISTS brand_names (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        drug_id TEXT NOT NULL REFERENCES drugs(id),
        brand_name TEXT NOT NULL, manufacturer TEXT, country TEXT, source TEXT,
        UNIQUE(drug_id, brand_name))""",
    """CREATE TABLE IF NOT EXISTS prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        drug_id TEXT NOT NULL REFERENCES drugs(id),
        source TEXT NOT NULL, amount REAL, currency TEXT DEFAULT 'BDT',
        unit TEXT, pack_size TEXT, UNIQUE(drug_id, source, unit))""",
    """CREATE TABLE IF NOT EXISTS clinical (
        drug_id TEXT PRIMARY KEY REFERENCES drugs(id),
        indications TEXT, contraindications TEXT, side_effects TEXT,
        warnings TEXT, interactions TEXT, dosage TEXT,
        adult_dose TEXT, pediatric_dose TEXT, mechanism_of_action TEXT,
        pharmacokinetics TEXT, overdose TEXT, storage TEXT,
        lactation TEXT, boxed_warning TEXT)""",
    """CREATE TABLE IF NOT EXISTS chemistry (
        drug_id TEXT PRIMARY KEY REFERENCES drugs(id),
        molecular_formula TEXT, molecular_weight REAL,
        smiles TEXT, inchi TEXT, inchi_key TEXT, cas_number TEXT,
        pubchem_cid INTEGER, chembl_id TEXT, drugbank_id TEXT, rxcui TEXT, ndc TEXT)""",
    """CREATE TABLE IF NOT EXISTS sources (
        drug_id TEXT NOT NULL REFERENCES drugs(id),
        source TEXT NOT NULL, source_url TEXT, source_id TEXT,
        PRIMARY KEY (drug_id, source))""",
    "CREATE INDEX IF NOT EXISTS idx_brand_drug ON brand_names(drug_id)",
    "CREATE INDEX IF NOT EXISTS idx_brand_name ON brand_names(brand_name COLLATE NOCASE)",
    "CREATE INDEX IF NOT EXISTS idx_drugs_generic ON drugs(generic_name COLLATE NOCASE)",
]


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    for ddl in _DDL:
        conn.execute(ddl)
    conn.commit()
    return conn


def upsert_merged(conn: sqlite3.Connection, drug) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO drugs (id,generic_name,dosage_form,strength,route,
           drug_class,therapeutic_class,atc_code,pregnancy_category,black_box_warning,
           description,image_url,min_price,max_price,source_count,first_seen,last_updated)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
           generic_name=excluded.generic_name, dosage_form=excluded.dosage_form,
           strength=excluded.strength, drug_class=excluded.drug_class,
           therapeutic_class=excluded.therapeutic_class, min_price=excluded.min_price,
           max_price=excluded.max_price, source_count=excluded.source_count,
           last_updated=excluded.last_updated""",
        (drug.id, drug.generic_name, drug.dosage_form, drug.strength, drug.route,
         drug.drug_class, drug.therapeutic_class, drug.atc_code,
         drug.pregnancy_category, 1 if drug.black_box_warning else 0,
         drug.description, drug.image_url, drug.min_price, drug.max_price,
         len(drug.sources), drug.first_seen or now, now))

    for brand in drug.brand_names:
        if not brand:
            continue
        mfr = drug.manufacturers[0] if drug.manufacturers else None
        conn.execute(
            """INSERT INTO brand_names(drug_id,brand_name,manufacturer,country,source)
               VALUES(?,?,?,?,?) ON CONFLICT(drug_id,brand_name) DO NOTHING""",
            (drug.id, brand, mfr.name if mfr else "", mfr.country if mfr else "",
             drug.sources[0] if drug.sources else ""))

    for price in drug.bd_prices:
        if price.amount is None:
            continue
        conn.execute(
            """INSERT INTO prices(drug_id,source,amount,currency,unit,pack_size)
               VALUES(?,?,?,?,?,?) ON CONFLICT(drug_id,source,unit) DO UPDATE SET
               amount=excluded.amount""",
            (drug.id, price.source, price.amount, price.currency,
             price.unit or "", price.pack_size))

    conn.execute(
        """INSERT INTO clinical(drug_id,indications,contraindications,side_effects,
           warnings,interactions,dosage,adult_dose,pediatric_dose,
           mechanism_of_action,pharmacokinetics,overdose,storage,lactation,boxed_warning)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(drug_id) DO UPDATE SET
           indications=excluded.indications, contraindications=excluded.contraindications,
           side_effects=excluded.side_effects, mechanism_of_action=excluded.mechanism_of_action,
           dosage=excluded.dosage, overdose=excluded.overdose, storage=excluded.storage""",
        (drug.id, json.dumps(drug.indications), json.dumps(drug.contraindications),
         json.dumps(drug.side_effects), json.dumps(drug.warnings),
         json.dumps(drug.interactions), drug.dosage, drug.adult_dose,
         drug.pediatric_dose, drug.mechanism_of_action,
         json.dumps(drug.pharmacokinetics) if drug.pharmacokinetics else None,
         drug.overdose, drug.storage, drug.lactation, drug.boxed_warning))

    conn.execute(
        """INSERT INTO chemistry(drug_id,molecular_formula,molecular_weight,smiles,
           inchi,inchi_key,cas_number,pubchem_cid,chembl_id,drugbank_id,rxcui,ndc)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(drug_id) DO UPDATE SET
           molecular_formula=excluded.molecular_formula,
           pubchem_cid=excluded.pubchem_cid, chembl_id=excluded.chembl_id,
           drugbank_id=excluded.drugbank_id, rxcui=excluded.rxcui, smiles=excluded.smiles""",
        (drug.id, getattr(drug, 'molecular_formula', None),
         getattr(drug, 'molecular_weight', None),
         getattr(drug, 'smiles', None), getattr(drug, 'inchi', None),
         getattr(drug, 'inchi_key', None), getattr(drug, 'cas_number', None),
         getattr(drug, 'pubchem_cid', None), getattr(drug, 'chembl_id', None),
         getattr(drug, 'drugbank_id', None), getattr(drug, 'rxcui', None),
         json.dumps(getattr(drug, 'ndc', None)) if getattr(drug, 'ndc', None) else None))

    for src in drug.sources:
        conn.execute(
            """INSERT INTO sources(drug_id,source,source_url) VALUES(?,?,?)
               ON CONFLICT(drug_id,source) DO UPDATE SET source_url=excluded.source_url""",
            (drug.id, src, drug.source_urls.get(src, "")))


def search(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[dict]:
    q = f"%{query.lower()}%"
    rows = conn.execute(
        """SELECT DISTINCT d.id,d.generic_name,d.dosage_form,d.strength,
           d.therapeutic_class,d.min_price,d.max_price,d.source_count
           FROM drugs d LEFT JOIN brand_names b ON d.id=b.drug_id
           WHERE LOWER(d.generic_name) LIKE ? OR LOWER(b.brand_name) LIKE ?
           ORDER BY d.source_count DESC, d.generic_name LIMIT ?""",
        (q, q, limit)).fetchall()
    return [dict(r) for r in rows]


def get_by_generic(conn: sqlite3.Connection, name: str) -> list[dict]:
    rows = conn.execute(
        """SELECT d.*, GROUP_CONCAT(b.brand_name,'|') AS brand_names_csv
           FROM drugs d LEFT JOIN brand_names b ON d.id=b.drug_id
           WHERE LOWER(d.generic_name) LIKE LOWER(?)
           GROUP BY d.id ORDER BY d.dosage_form, d.strength""",
        (f"%{name}%",)).fetchall()
    return [dict(r) for r in rows]


def get_drug_full(conn: sqlite3.Connection, drug_id: str) -> dict | None:
    drug = conn.execute("SELECT * FROM drugs WHERE id=?", (drug_id,)).fetchone()
    if not drug:
        return None
    result = dict(drug)
    result["brand_names"] = [dict(b) for b in conn.execute(
        "SELECT brand_name,manufacturer,country FROM brand_names WHERE drug_id=?", (drug_id,))]
    result["prices"] = [dict(p) for p in conn.execute(
        "SELECT source,amount,currency,unit,pack_size FROM prices WHERE drug_id=?", (drug_id,))]
    clin = conn.execute("SELECT * FROM clinical WHERE drug_id=?", (drug_id,)).fetchone()
    if clin:
        clin_dict = dict(clin)
        for f in ("indications","contraindications","side_effects","warnings","interactions"):
            try: clin_dict[f] = json.loads(clin_dict.get(f) or "[]")
            except: clin_dict[f] = []
        result.update(clin_dict)
    chem = conn.execute("SELECT * FROM chemistry WHERE drug_id=?", (drug_id,)).fetchone()
    if chem:
        result.update(dict(chem))
    result["sources"] = [dict(s) for s in conn.execute(
        "SELECT source,source_url FROM sources WHERE drug_id=?", (drug_id,))]
    return result


def get_stats(conn: sqlite3.Connection) -> dict:
    s: dict[str, Any] = {}
    s["total_drugs"] = conn.execute("SELECT COUNT(*) FROM drugs").fetchone()[0]
    s["total_brand_names"] = conn.execute("SELECT COUNT(*) FROM brand_names").fetchone()[0]
    s["total_prices"] = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    s["drugs_with_price"] = conn.execute("SELECT COUNT(DISTINCT drug_id) FROM prices").fetchone()[0]
    s["drugs_with_mechanism"] = conn.execute(
        "SELECT COUNT(*) FROM clinical WHERE mechanism_of_action IS NOT NULL AND mechanism_of_action!=''").fetchone()[0]
    s["drugs_with_formula"] = conn.execute(
        "SELECT COUNT(*) FROM chemistry WHERE molecular_formula IS NOT NULL").fetchone()[0]
    s["drugs_with_smiles"] = conn.execute(
        "SELECT COUNT(*) FROM chemistry WHERE smiles IS NOT NULL").fetchone()[0]
    s["drugs_with_pubchem"] = conn.execute(
        "SELECT COUNT(*) FROM chemistry WHERE pubchem_cid IS NOT NULL").fetchone()[0]
    rows = conn.execute(
        "SELECT source,COUNT(*) cnt FROM sources GROUP BY source ORDER BY cnt DESC").fetchall()
    s["sources"] = {r["source"]: r["cnt"] for r in rows}
    form_rows = conn.execute(
        "SELECT dosage_form,COUNT(*) cnt FROM drugs WHERE dosage_form IS NOT NULL "
        "GROUP BY dosage_form ORDER BY cnt DESC LIMIT 15").fetchall()
    s["dosage_forms"] = {r["dosage_form"]: r["cnt"] for r in form_rows}
    pr = conn.execute(
        "SELECT MIN(amount),MAX(amount),AVG(amount) FROM prices WHERE currency='BDT'").fetchone()
    if pr:
        s["price_bdt_min"] = pr[0]; s["price_bdt_max"] = pr[1]
        s["price_bdt_avg"] = round(pr[2], 2) if pr[2] else None
    return s


def export_json(conn: sqlite3.Connection, output_path: Path) -> int:
    drugs = conn.execute("SELECT id FROM drugs ORDER BY generic_name").fetchall()
    result = [get_drug_full(conn, r["id"]) for r in drugs]
    result = [r for r in result if r]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    import orjson
    output_path.write_bytes(orjson.dumps(result, option=orjson.OPT_INDENT_2))
    logger.info(f"Exported {len(result)} drugs to {output_path}")
    return len(result)
