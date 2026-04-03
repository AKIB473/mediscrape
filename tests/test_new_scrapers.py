from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scrapers.bangladesh.dghs_shr import DGHSSHRScraper
from scrapers.international.epocrates import EpocratesScraper
from scrapers.international.epocrates import _extract_sections_from_h2 as _extract_epocrates_sections
from scrapers.international.medscape import _extract_sections_from_h2


def test_dghs_codesystem_concept_mapping(tmp_path: Path):
    scraper = DGHSSHRScraper(data_dir=tmp_path)
    concept = {"code": "394-0010-030", "display": "Tubutol", "definition": "Ethambutol"}
    code_system = {"url": "https://fhir.dghs.gov.bd/core/CodeSystem/bd-medication-code", "version": "0.3.0"}
    value_set = {"url": "https://fhir.dghs.gov.bd/core/ValueSet/bd-medication-valueset"}

    drug = scraper._parse_codesystem_concept(
        concept=concept,
        code_system=code_system,
        value_set=value_set,
        med_profile={},
        med_request_profile={},
    )

    assert drug is not None
    assert drug.source == "dghs_shr"
    assert drug.source_id == "394-0010-030"
    assert drug.generic_name == "Ethambutol"
    assert drug.brand_name == "Tubutol"
    assert drug.extra["concept"]["code"] == "394-0010-030"


def test_epocrates_build_drug_uses_union_fields(tmp_path: Path):
    scraper = EpocratesScraper(data_dir=tmp_path)
    item = {"id": 139, "name": "amoxicillin", "generic": {"name": "amoxicillin"}, "drugType": {"id": 1}}
    card = {
        "drugId": 139,
        "drugName": "amoxicillin",
        "genericName": "View brands",
        "deaFdaStatusCode": "Rx",
        "deaFdaStatusDesc": "Requires prescription",
        "subSections": [{"name": "Adult Dosing", "link": "/online/drugs/139/amoxicillin#adult-dosing"}],
        "monographLink": "/online/drugs/139/amoxicillin",
    }
    sections = {
        "dosing & uses": "Used for susceptible infections.",
        "contraindications/cautions": "Do not use with severe allergy to penicillins.",
        "adverse reactions": "Rash; nausea.",
    }

    brands = [
        {"id": 139, "name": "amoxicillin"},
        {"id": 389, "name": "Amoxil"},
        {"id": 4915, "name": "Moxatag"},
    ]
    drug = scraper._build_drug(item=item, card=card, sections=sections, brands=brands)

    assert drug is not None
    assert drug.source == "epocrates"
    assert drug.source_id == "139"
    assert drug.generic_name == "amoxicillin"
    assert drug.schedule == "Rx"
    assert "Amoxil" in drug.synonyms
    assert "sub_sections" in drug.extra
    assert "brand_names" in drug.extra
    assert drug.monograph_url.endswith("/online/drugs/139/amoxicillin")


def test_medscape_section_extraction_from_h2_html():
    html = """
    <h2>Dosing &amp; Uses</h2>
    <div><p>Adult: 500 mg orally.</p></div>
    <h2>Interactions</h2>
    <div><p>Warfarin may increase INR.</p></div>
    """
    sections = _extract_sections_from_h2(html)

    assert "dosing & uses" in sections
    assert "interactions" in sections
    assert "500 mg orally" in sections["dosing & uses"]


def test_epocrates_section_extraction_removes_script_payload():
    html = """
    <h2>Peds Dosing</h2>
    <div><p>Weight-based dosing applies.</p><script>console.log("debug");</script></div>
    """
    sections = _extract_epocrates_sections(html)
    assert "peds dosing" in sections
    assert "Weight-based dosing applies." in sections["peds dosing"]
    assert "console.log" not in sections["peds dosing"]
