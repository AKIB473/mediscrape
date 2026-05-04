"""
Normalisation utilities for drug data.

All public functions are pure (no side-effects) and safe to call with None /
empty strings — they always return a str.
"""
from __future__ import annotations

import hashlib
import re


# ─────────────────────────────────────────────────────────────────────────────
# Salt / suffix replacement table for generic names
# Longer patterns first so partial matches don't shadow full ones.
# ─────────────────────────────────────────────────────────────────────────────
_SALT_REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    # Acids
    (re.compile(r'\bhydrochloride\b', re.I),          'HCl'),
    (re.compile(r'\bmonohydrochloride\b', re.I),      'HCl'),
    (re.compile(r'\bdihydrochloride\b', re.I),        '2HCl'),
    (re.compile(r'\bhydrobromide\b', re.I),           'HBr'),
    (re.compile(r'\bsulfate\b', re.I),                'sulfate'),   # keep lowercase
    (re.compile(r'\bsulphate\b', re.I),               'sulfate'),
    (re.compile(r'\bphosphate\b', re.I),              'phosphate'),
    (re.compile(r'\bbisphosphate\b', re.I),           'bisphosphate'),
    (re.compile(r'\bdiphosphate\b', re.I),            'diphosphate'),
    (re.compile(r'\bfumarate\b', re.I),               'fumarate'),
    (re.compile(r'\bmaleate\b', re.I),                'maleate'),
    (re.compile(r'\bsuccinate\b', re.I),              'succinate'),
    (re.compile(r'\bcitrate\b', re.I),                'citrate'),
    (re.compile(r'\btartrate\b', re.I),               'tartrate'),
    (re.compile(r'\blactate\b', re.I),                'lactate'),
    (re.compile(r'\bacetate\b', re.I),                'acetate'),
    (re.compile(r'\bbenzoate\b', re.I),               'benzoate'),
    (re.compile(r'\bgluconolactone\b', re.I),         'gluconolactone'),
    (re.compile(r'\bgluconate\b', re.I),              'gluconate'),
    (re.compile(r'\bglutamate\b', re.I),              'glutamate'),
    (re.compile(r'\boxalate\b', re.I),                'oxalate'),
    (re.compile(r'\bpivalate\b', re.I),               'pivalate'),
    (re.compile(r'\bvalerate\b', re.I),               'valerate'),
    (re.compile(r'\bpropionate\b', re.I),             'propionate'),
    (re.compile(r'\bbutyrate\b', re.I),               'butyrate'),
    (re.compile(r'\bstearate\b', re.I),               'stearate'),
    (re.compile(r'\bpalmitate\b', re.I),              'palmitate'),
    # Metal cations / simple suffixes — strip these entirely
    (re.compile(r'\bsodium\b', re.I),                 ''),
    (re.compile(r'\bpotassium\b', re.I),              ''),
    (re.compile(r'\bcalcium\b', re.I),                ''),
    (re.compile(r'\bmagnesium\b', re.I),              ''),
    (re.compile(r'\bzinc\b', re.I),                   ''),
    (re.compile(r'\biron\b', re.I),                   ''),
    (re.compile(r'\baluminium\b', re.I),              ''),
    (re.compile(r'\baluminum\b', re.I),               ''),
    # Hydration / misc
    (re.compile(r'\bmonohydrate\b', re.I),            ''),
    (re.compile(r'\bdihydrate\b', re.I),              ''),
    (re.compile(r'\banhydrous\b', re.I),              ''),
    (re.compile(r'\bhydrate\b', re.I),                ''),
    (re.compile(r'\bhydrous\b', re.I),                ''),
    (re.compile(r'\bsterile\b', re.I),                ''),
]

# ─────────────────────────────────────────────────────────────────────────────
# Dosage-form normalisation map  (key: lower-stripped, value: canonical)
# ─────────────────────────────────────────────────────────────────────────────
_FORM_MAP: dict[str, str] = {
    # Tablet variants
    'tab':          'Tablet',
    'tablet':       'Tablet',
    'tablets':      'Tablet',
    'tabs':         'Tablet',
    'fc tab':       'Film-coated Tablet',
    'fc tablet':    'Film-coated Tablet',
    'film coated tablet': 'Film-coated Tablet',
    'film-coated tablet': 'Film-coated Tablet',
    'ec tab':       'Enteric-coated Tablet',
    'ec tablet':    'Enteric-coated Tablet',
    'enteric coated tablet': 'Enteric-coated Tablet',
    'sr tab':       'Sustained-release Tablet',
    'sr tablet':    'Sustained-release Tablet',
    'xr tab':       'Extended-release Tablet',
    'er tab':       'Extended-release Tablet',
    'chewable tab': 'Chewable Tablet',
    'dispersible tab': 'Dispersible Tablet',
    'effervescent tab': 'Effervescent Tablet',
    # Capsule variants
    'cap':          'Capsule',
    'capsule':      'Capsule',
    'capsules':     'Capsule',
    'caps':         'Capsule',
    'sr cap':       'Sustained-release Capsule',
    'xr cap':       'Extended-release Capsule',
    'er cap':       'Extended-release Capsule',
    # Injection / infusion
    'inj':          'Injection',
    'injection':    'Injection',
    'iv':           'Injection',
    'im':           'Injection',
    'infusion':     'Infusion',
    'vial':         'Vial',
    # Liquid oral
    'syr':          'Syrup',
    'syrup':        'Syrup',
    'sus':          'Suspension',
    'susp':         'Suspension',
    'suspension':   'Suspension',
    'oral sus':     'Suspension',
    'oral suspension': 'Suspension',
    'sol':          'Solution',
    'solution':     'Solution',
    'oral sol':     'Oral Solution',
    'oral solution': 'Oral Solution',
    'elixir':       'Elixir',
    'emulsion':     'Emulsion',
    'linctus':      'Linctus',
    'mixture':      'Mixture',
    'drops':        'Drop',
    'drp':          'Drop',
    'drop':         'Drop',
    'oral drops':   'Oral Drops',
    # Topical
    'oint':         'Ointment',
    'ointment':     'Ointment',
    'crm':          'Cream',
    'cream':        'Cream',
    'gel':          'Gel',
    'lotion':       'Lotion',
    'paste':        'Paste',
    'foam':         'Foam',
    'mousse':       'Mousse',
    'spray':        'Spray',
    'nasal spray':  'Nasal Spray',
    'inhaler':      'Inhaler',
    'inhaler (mdi)': 'MDI Inhaler',
    'nebuliser':    'Nebuliser Solution',
    # Rectal / vaginal
    'sup':          'Suppository',
    'supp':         'Suppository',
    'suppository':  'Suppository',
    'enema':        'Enema',
    'pessary':      'Pessary',
    # Transdermal
    'patch':        'Patch',
    'transdermal patch': 'Patch',
    # Powder
    'pwd':          'Powder',
    'powder':       'Powder',
    'granules':     'Granules',
    'sachet':       'Sachet',
    # Ophthalmic / otic
    'eye drop':     'Eye Drops',
    'eye drops':    'Eye Drops',
    'ear drop':     'Ear Drops',
    'ear drops':    'Ear Drops',
    'eye oint':     'Eye Ointment',
    'eye ointment': 'Eye Ointment',
}

# ─────────────────────────────────────────────────────────────────────────────
# Manufacturer name normalisation map
# ─────────────────────────────────────────────────────────────────────────────
_MANUFACTURER_MAP: dict[str, str] = {
    # Square
    'square pharma':                    'Square Pharmaceuticals',
    'square pharmaceuticals ltd':       'Square Pharmaceuticals',
    'square pharmaceuticals limited':   'Square Pharmaceuticals',
    'square pharmaceuticals plc':       'Square Pharmaceuticals',
    # Beximco
    'beximco pharma':                   'Beximco Pharmaceuticals',
    'beximco pharmaceuticals ltd':      'Beximco Pharmaceuticals',
    'beximco pharmaceuticals limited':  'Beximco Pharmaceuticals',
    'beximco pharma ltd':               'Beximco Pharmaceuticals',
    # ACME
    'acme laboratories':                'ACME Laboratories',
    'acme laboratories ltd':            'ACME Laboratories',
    'the acme laboratories':            'ACME Laboratories',
    'acme pharma':                      'ACME Laboratories',
    # Incepta
    'incepta pharma':                   'Incepta Pharmaceuticals',
    'incepta pharmaceuticals ltd':      'Incepta Pharmaceuticals',
    'incepta pharmaceuticals limited':  'Incepta Pharmaceuticals',
    # Opsonin
    'opsonin pharma':                   'Opsonin Pharma',
    'opsonin pharma ltd':               'Opsonin Pharma',
    # Eskayef
    'eskayef pharma':                   'Eskayef Bangladesh',
    'eskayef bangladesh ltd':           'Eskayef Bangladesh',
    'sk+f':                             'Eskayef Bangladesh',
    # General
    'general pharmaceuticals':         'General Pharmaceuticals',
    'general pharma':                   'General Pharmaceuticals',
    # Renata
    'renata limited':                   'Renata Pharmaceuticals',
    'renata ltd':                       'Renata Pharmaceuticals',
    'renata pharma':                    'Renata Pharmaceuticals',
    # ACI
    'aci limited':                      'ACI Pharmaceuticals',
    'aci pharmaceuticals ltd':          'ACI Pharmaceuticals',
    'advanced chemical industries':     'ACI Pharmaceuticals',
    # Healthcare
    'healthcare pharmaceuticals':       'Healthcare Pharmaceuticals',
    'healthcare pharma':                'Healthcare Pharmaceuticals',
    # Aristopharma
    'aristopharma ltd':                 'Aristopharma',
    'aristopharma limited':             'Aristopharma',
    # Ibn Sina
    'ibn sina pharma':                  'Ibn Sina Pharmaceutical',
    'ibn sina pharmaceutical ind':      'Ibn Sina Pharmaceutical',
    # Nuvista
    'nuvista pharma':                   'Nuvista Pharma',
    'nuvista pharmaceuticals':          'Nuvista Pharma',
    # Popular
    'popular pharmaceuticals':          'Popular Pharmaceuticals',
    'popular pharma':                   'Popular Pharmaceuticals',
    # Drug International
    'drug international ltd':           'Drug International',
    'drug intl':                        'Drug International',
}

# ─────────────────────────────────────────────────────────────────────────────
# Strength normalisation: unit regex
# ─────────────────────────────────────────────────────────────────────────────
_STRENGTH_PATTERN = re.compile(
    r'(\d+(?:\.\d+)?)\s*'          # numeric value (integer or decimal)
    r'(mcg|μg|ug|mg|g|kg|ml|l|iu|meq|mmol|%|units?)'  # unit
    r'(?:\s*/\s*(\d+(?:\.\d+)?)\s*(ml|l|g|mg|dose|tablet|cap|application))?',  # optional denominator
    re.I,
)


def normalize_generic_name(name: str | None) -> str:
    """
    Normalise a generic drug name:

    1. Strip leading/trailing whitespace.
    2. Replace common salt suffixes (see ``_SALT_REPLACEMENTS``).
    3. Collapse extra whitespace.
    4. Lowercase.

    Examples
    --------
    >>> normalize_generic_name('Paracetamol Hydrochloride')
    'paracetamol hcl'
    >>> normalize_generic_name('Metoprolol Succinate')
    'metoprolol succinate'
    >>> normalize_generic_name('Amoxicillin Sodium')
    'amoxicillin'
    """
    if not name:
        return ''
    result = name.strip()
    for pattern, replacement in _SALT_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    # Collapse whitespace
    result = re.sub(r'\s+', ' ', result).strip()
    return result.lower()


def normalize_brand_name(name: str | None) -> str:
    """
    Normalise a brand (trade) name:

    1. Strip embedded dosage/strength suffixes (e.g. "Napa 500mg" → "Napa").
    2. Title-case.

    Examples
    --------
    >>> normalize_brand_name('napa 500mg tablet')
    'Napa'
    >>> normalize_brand_name('MOXACIL 250mg/5ml')
    'Moxacil'
    """
    if not name:
        return ''
    result = name.strip()
    # Strip trailing dosage+form patterns like "500mg", "250mg/5ml Tablet", etc.
    result = re.sub(
        r'\s+\d+(?:\.\d+)?\s*(?:mcg|μg|ug|mg|g|ml|l|iu|meq|mmol|%)'
        r'(?:\s*/\s*\d+(?:\.\d+)?\s*(?:ml|l|g|mg|dose))?'
        r'(?:\s+(?:tablet|cap(?:sule)?|syrup|suspension|injection|solution|cream|ointment|gel|drop|patch|powder|granule|sachet|inhaler|spray)s?)?$',
        '',
        result,
        flags=re.I,
    )
    return result.strip().title()


def normalize_dosage_form(form: str | None) -> str:
    """
    Normalise a dosage form string to a canonical label.

    Falls back to title-casing the input if the value is not in the map.

    Examples
    --------
    >>> normalize_dosage_form('tab')
    'Tablet'
    >>> normalize_dosage_form('inj')
    'Injection'
    >>> normalize_dosage_form('FC Tab')
    'Film-coated Tablet'
    """
    if not form:
        return ''
    key = form.strip().lower()
    # Try exact match first
    if key in _FORM_MAP:
        return _FORM_MAP[key]
    # Try removing trailing 's' (plurals)
    if key.rstrip('s') in _FORM_MAP:
        return _FORM_MAP[key.rstrip('s')]
    # Partial match against map keys
    for map_key, canonical in _FORM_MAP.items():
        if map_key in key:
            return canonical
    # Fallback: title-case the original
    return form.strip().title()


def normalize_strength(s: str | None) -> str:
    """
    Normalise a strength string so there is a space between number and unit,
    and units are lowercase.

    Examples
    --------
    >>> normalize_strength('100mg')
    '100 mg'
    >>> normalize_strength('500MG/5ML')
    '500 mg/5 ml'
    >>> normalize_strength('1.5mcg/kg')
    '1.5 mcg/kg'
    """
    if not s:
        return ''

    def _replace_match(m: re.Match) -> str:
        num = m.group(1)
        unit = m.group(2).lower()
        if m.group(3) and m.group(4):
            return f'{num} {unit}/{m.group(3)} {m.group(4).lower()}'
        return f'{num} {unit}'

    result = _STRENGTH_PATTERN.sub(_replace_match, s.strip())
    # Collapse extra spaces
    result = re.sub(r'  +', ' ', result)
    return result.strip()


def normalize_manufacturer(name: str | None) -> str:
    """
    Normalise a manufacturer name to a canonical form using a curated mapping
    of common Bangladeshi pharmaceutical companies.

    Falls back to title-casing the input if no mapping is found.

    Examples
    --------
    >>> normalize_manufacturer('Square Pharma')
    'Square Pharmaceuticals'
    >>> normalize_manufacturer('beximco pharma ltd')
    'Beximco Pharmaceuticals'
    """
    if not name:
        return ''
    key = name.strip().lower()
    if key in _MANUFACTURER_MAP:
        return _MANUFACTURER_MAP[key]
    # Try prefix match (handles trailing commas, "Ltd.", etc.)
    for map_key, canonical in _MANUFACTURER_MAP.items():
        if key.startswith(map_key) or map_key.startswith(key):
            return canonical
    return name.strip().title()


def drug_canonical_id(generic: str | None, form: str | None, strength: str | None) -> str:
    """
    Return a stable, 32-character MD5 hex-digest that uniquely identifies a
    (generic_name, dosage_form, strength) combination.

    Inputs are normalised before hashing so minor spelling differences do not
    produce different IDs.

    Examples
    --------
    >>> drug_canonical_id('Paracetamol', 'Tablet', '500 mg')
    '...'  # deterministic 32-char hex string
    """
    g = normalize_generic_name(generic)
    f = normalize_dosage_form(form)
    s = normalize_strength(strength)
    payload = f'{g}|{f}|{s}'.lower()
    return hashlib.md5(payload.encode('utf-8')).hexdigest()
