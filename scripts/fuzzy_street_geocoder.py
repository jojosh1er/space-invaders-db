#!/usr/bin/env python3
"""
Fuzzy Street Geocoder — Prototype Étape 1
==========================================
Quand Nominatim échoue sur une adresse précise extraite par Vision,
au lieu de retomber sur le centroïde d'arrondissement, on :
  1. Extrait le nom de rue + arrondissement de l'adresse Vision
  2. Interroge Overpass API pour récupérer TOUTES les rues de l'arrondissement
  3. Fuzzy match (RapidFuzz) entre la rue Vision et les rues OSM réelles
  4. Géocode la meilleure correspondance → centroïde de rue (pas d'arrondissement)

Cible: PA_1228 ("Rue Marteau" introuvable → "Rue Watt"?) et PA_1331
       ("34 Rue Malcote" → "Rue Marcotte"?) — erreur attendue 0.7 km → ~0.15 km

Usage:
    python fuzzy_street_geocoder.py --test
    python fuzzy_street_geocoder.py --address "Rue Marteau, 75013 Paris"
"""

import re
import json
import time
import argparse
import urllib.parse
import urllib.request
from pathlib import Path
from functools import lru_cache

try:
    from rapidfuzz import process, fuzz
except ImportError:
    print("⚠️  pip install rapidfuzz requis")
    raise

CACHE_DIR = Path.home() / ".cache" / "invader_overpass"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "InvaderGeocoder/1.0 (research)"

# ─── Parsing adresse Vision ────────────────────────────────────────────────

ARRDT_RE = re.compile(r"750(0[1-9]|1[0-9]|20)\b")
STREET_PREFIX_RE = re.compile(
    r"^\s*(\d+\s*(bis|ter|quater)?\s*,?\s*)?"
    r"(rue|avenue|av\.?|boulevard|bd\.?|bvd\.?|place|pl\.?|impasse|"
    r"passage|quai|allée|allee|cours|square|villa|cité|cite|"
    r"chemin|route|sentier|galerie|parvis)\s+",
    re.IGNORECASE,
)

def parse_vision_address(addr: str):
    """Extrait (street_name_clean, arrondissement_code) d'une adresse Vision."""
    m = ARRDT_RE.search(addr)
    arrdt = m.group(0) if m else None  # "75013"

    # Enlève le code postal et "Paris"
    cleaned = re.sub(r",?\s*750\d{2}\s*Paris?\s*,?.*$", "", addr, flags=re.IGNORECASE).strip(" ,")

    # Enlève numéro de rue en début
    cleaned = re.sub(r"^\s*\d+\s*(bis|ter|quater)?\s*,?\s*", "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip(), arrdt


# ─── Overpass: rues d'un arrondissement ────────────────────────────────────

@lru_cache(maxsize=32)
def fetch_arrondissement_streets(postcode: str):
    """
    Récupère toutes les rues nommées d'un arrondissement parisien.
    Retourne liste de (name, center_lat, center_lon).
    Cache disque pour éviter de marteler Overpass.
    """
    cache_file = CACHE_DIR / f"streets_{postcode}.json"
    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)

    # Requête Overpass: toutes les highway avec name dans la zone postcode
    query = f"""
    [out:json][timeout:60];
    area["postal_code"="{postcode}"]["boundary"="postal_code"]->.a;
    (
      way(area.a)["highway"]["name"];
    );
    out tags center;
    """

    print(f"  🌍 Overpass: fetching streets for {postcode}...")
    req = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read())

    # Dédup par nom (une rue = plusieurs segments)
    streets = {}
    for el in data.get("elements", []):
        name = el.get("tags", {}).get("name")
        center = el.get("center")
        if not name or not center:
            continue
        if name not in streets:
            streets[name] = {"lats": [], "lons": []}
        streets[name]["lats"].append(center["lat"])
        streets[name]["lons"].append(center["lon"])

    result = [
        (name, sum(d["lats"]) / len(d["lats"]), sum(d["lons"]) / len(d["lons"]))
        for name, d in streets.items()
    ]

    with open(cache_file, "w") as f:
        json.dump(result, f)

    print(f"  ✅ {len(result)} rues cachées pour {postcode}")
    return result


# ─── Fuzzy match ───────────────────────────────────────────────────────────

STREET_TYPE_RE = re.compile(
    r"^\s*(rue|avenue|av\.?|boulevard|bd\.?|bvd\.?|place|pl\.?|impasse|"
    r"passage|quai|allée|allee|cours|square|villa|cité|cite|"
    r"chemin|route|sentier|galerie|parvis|port|pont|rond-point)\s+"
    r"(de\s+la\s+|de\s+l'|du\s+|des\s+|de\s+|d'|le\s+|la\s+|les\s+)?",
    re.IGNORECASE,
)

def _distinctive_token(street_name: str) -> str:
    """'Rue du Moulin Joly' → 'Moulin Joly' ; 'Avenue de la République' → 'République'."""
    return STREET_TYPE_RE.sub("", street_name).strip().lower()


def fuzzy_match_street(vision_street: str, candidates: list, threshold: int = 85):
    """
    Match sur le token distinctif (sans 'Rue/Avenue/...') pour éviter que
    le score soit gonflé par les mots communs.

    Garde-fous contre les matches dégénérés :
      - core >= 4 chars (évite 'Quai E', 'Rue A', etc.)
      - ratio de longueur core_vision/core_candidat ∈ [0.5, 2.0]
        (évite que 'marteau' (7) matche 'e' (1) via partial_ratio=100)
    """
    if not candidates:
        return None

    vision_core = _distinctive_token(vision_street)
    if not vision_core or len(vision_core) < 4:
        return None

    best_name, best_score, best_coords = None, 0, None
    for name, lat, lon in candidates:
        core = _distinctive_token(name)
        if not core or len(core) < 4:
            continue
        # Contrainte longueur relative
        ratio = len(vision_core) / len(core)
        if ratio < 0.5 or ratio > 2.0:
            continue
        s1 = fuzz.ratio(vision_core, core)
        s2 = fuzz.partial_ratio(vision_core, core)
        score = max(s1, s2)
        if score > best_score:
            best_score = score
            best_name, best_coords = name, (lat, lon)

    if best_score < threshold:
        return None
    return (best_name, best_coords[0], best_coords[1], best_score)


# ─── Pipeline principal ────────────────────────────────────────────────────

def geocode_with_fuzzy_fallback(vision_address: str, verbose: bool = True):
    """
    Essaie Nominatim d'abord (rapide), puis fuzzy Overpass si échec.
    Retourne dict {lat, lon, method, matched_name, confidence}.
    """
    street, arrdt = parse_vision_address(vision_address)
    if verbose:
        print(f"  📝 Parsed: street='{street}', arrdt={arrdt}")

    # 1) Nominatim direct — CONTRAINT à la bbox Paris (sinon matche Laval, etc.)
    PARIS_VIEWBOX = "2.224,48.902,2.470,48.815"  # lon_min,lat_max,lon_max,lat_min
    try:
        url = (
            f"{NOMINATIM_URL}?q={urllib.parse.quote(vision_address)}"
            f"&format=json&limit=1&countrycodes=fr"
            f"&viewbox={PARIS_VIEWBOX}&bounded=1"
        )
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as r:
            results = json.loads(r.read())
        if results:
            r0 = results[0]
            if r0.get("type") not in ("administrative", "postcode"):
                return {
                    "lat": float(r0["lat"]),
                    "lon": float(r0["lon"]),
                    "method": "nominatim_direct",
                    "matched_name": r0.get("display_name", ""),
                    "confidence": 1.0,
                }
            if verbose:
                print(f"  ⚠️  Nominatim retourne seulement du {r0.get('type')} → fuzzy")
        elif verbose:
            print(f"  ⚠️  Nominatim: 0 résultat dans bbox Paris → fuzzy")
    except Exception as e:
        if verbose:
            print(f"  ⚠️  Nominatim erreur: {e}")

    time.sleep(1)  # respect nominatim rate limit

    # 2) Fuzzy fallback via Overpass
    if not arrdt or not street:
        return None

    try:
        candidates = fetch_arrondissement_streets(arrdt)
    except Exception as e:
        if verbose:
            print(f"  ❌ Overpass erreur: {e}")
        return None

    match = fuzzy_match_street(street, candidates)
    if not match:
        if verbose:
            vc = _distinctive_token(street)
            scored = []
            for name, lat, lon in candidates:
                core = _distinctive_token(name)
                if core and len(core) >= 4:
                    ratio = len(vc) / len(core) if core else 0
                    if 0.5 <= ratio <= 2.0:
                        s = max(fuzz.ratio(vc, core), fuzz.partial_ratio(vc, core))
                        scored.append((s, name))
            scored.sort(reverse=True)
            print(f"  ❌ Aucun match > 85 pour '{street}' (core='{vc}'). Top-5:")
            for s, n in scored[:5]:
                print(f"       {s:5.1f}  {n}")

        # Fallback: centroïde arrondissement (= comportement actuel, pas dégradé)
        lats = [c[1] for c in candidates]
        lons = [c[2] for c in candidates]
        if lats:
            return {
                "lat": sum(lats) / len(lats),
                "lon": sum(lons) / len(lons),
                "method": "arrondissement_centroid",
                "matched_name": f"Centroïde {arrdt}",
                "confidence": 0.1,
            }
        return None

    name, lat, lon, score = match
    if verbose:
        print(f"  🎯 Fuzzy match: '{street}' → '{name}' (score={score:.0f})")
    return {
        "lat": lat,
        "lon": lon,
        "method": "fuzzy_overpass",
        "matched_name": name,
        "confidence": score / 100.0,
    }


# ─── Tests sur les cas problématiques ──────────────────────────────────────

TEST_CASES = [
    # (vision_address, true_lat, true_lon, id)
    ("Rue Marteau, 75013 Paris", 48.8246, 2.3668, "PA_1228"),
    ("34 Rue Malcote, 75013 Paris", 48.8296, 2.3700, "PA_1331"),
    # Contrôle: cas où Nominatim marchait déjà
    ("73 Rue de Turenne, 75003 Paris", 48.85964, 2.36445, "PA_503"),
]


def run_tests():
    print("=" * 60)
    print("Test fuzzy geocoder sur cas problématiques")
    print("=" * 60)
    from math import radians, sin, cos, sqrt, atan2

    def hav(a, b, c, d):
        R = 6371
        dlat, dlon = radians(c - a), radians(d - b)
        x = sin(dlat / 2) ** 2 + cos(radians(a)) * cos(radians(c)) * sin(dlon / 2) ** 2
        return 2 * R * atan2(sqrt(x), sqrt(1 - x))

    for addr, tlat, tlon, iid in TEST_CASES:
        print(f"\n[{iid}] {addr}")
        r = geocode_with_fuzzy_fallback(addr)
        if not r:
            print("  ❌ Échec total")
            continue
        err = hav(tlat, tlon, r["lat"], r["lon"])
        print(f"  → {r['method']}: ({r['lat']:.5f}, {r['lon']:.5f}) '{r['matched_name'][:60]}'")
        print(f"  📏 Erreur vs vérité: {err:.2f} km")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--test", action="store_true")
    p.add_argument("--address", help="Adresse à géocoder")
    args = p.parse_args()

    if args.test:
        run_tests()
    elif args.address:
        r = geocode_with_fuzzy_fallback(args.address)
        print(json.dumps(r, indent=2, ensure_ascii=False) if r else "Échec")
    else:
        p.print_help()
