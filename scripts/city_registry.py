#!/usr/bin/env python3
"""
city_registry.py

Derive une ville inconnue (centre, pays, rayon) depuis Nominatim, en repli des
dictionnaires maintenus a la main.

POURQUOI
Toute ville nouvelle exige aujourd'hui des entrees manuelles dans quatre
dictionnaires de centres (trois dans update_from_spotter.py, un dans
geolocate_missing.py) plus CITY_COUNTRIES. Quand elles manquent, rien ne
plante : les mosaiques sortent en lat=0, lng=0, le gate detect_new du workflow
les ignore, et Nominatim recoit countrycodes=fr par defaut. C'est arrive trois
fois -- Stockholm en septembre, Halmstad et Visby qui etaient cassees sans que
personne le voie, et la Laponie en octobre.

Le nom de la ville, lui, est toujours connu : il vient de villes.php. Le
geocoder par Nominatim donne le centroide, le code pays ISO et la bounding box
administrative, donc un rayon derive de l'etendue reelle au lieu des 25 km en
dur.

CE QUE CE MODULE NE FAIT PAS
Il ne remplace JAMAIS une entree curee. Les dictionnaires manuels font foi ;
ce repli ne sert que lorsqu'ils sont muets. Une valeur derivee porte
source='nominatim' pour rester distinguable d'une valeur verifiee.

LIMITE ASSUMEE
Pour une region etendue -- la Laponie couvre plusieurs centaines de
kilometres -- le centroide est arbitraire et le rayon derive est si grand que
validate_city_coherence n'y discriminera plus grand-chose. Ce n'est pas un
defaut du code : pour une emprise pareille, ce controle ne PEUT pas
discriminer. Mieux vaut un garde-fou large et honnete qu'un rayon de 25 km qui
rejette silencieusement des coordonnees valides.

Usage en ligne de commande (diagnostic) :
    python city_registry.py --name Lapland
    python city_registry.py --code STK --name Stockholm -v
"""

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "InvaderHunter-city-registry/1.0 (https://github.com/jojosh1er/space-invaders-db)"

CACHE_DIR = Path.home() / ".cache" / "invader_city_registry"

# Un centre-ville ne bouge pas : on peut cacher longtemps un resultat positif.
CACHE_TTL_DAYS = 180

# Un resultat VIDE n'est jamais cache. Il peut venir d'un nom mal orthographie,
# d'un timeout ou d'une indisponibilite : le figer ferait d'une erreur passagere
# une erreur permanente. Lecon de la mise au point de shop_corroboration, ou une
# regex fautive avait ete cachee 30 jours avec son resultat vide.
CACHE_TTL_EMPTY_DAYS = 0

# Politique d'usage Nominatim : au plus une requete par seconde, User-Agent
# identifiable obligatoire. On prend une marge.
MIN_INTERVAL_S = 1.5
RETRIES = 3
BACKOFF_S = (3, 10, 30)

# Rayon plancher : meme une petite ville merite une tolerance raisonnable.
RADIUS_FLOOR_KM = 15.0

# Pas de plafond volontairement : plafonner reintroduirait le rejet silencieux
# de coordonnees valides pour une region etendue, qui est le bug qu'on repare.

_last_call = 0.0


def _haversine_km(a, b):
    R = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dphi = p2 - p1
    dlam = math.radians(b[1] - a[1])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(h)))


def _cache_path(name):
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "vide"
    return CACHE_DIR / f"{slug}.json"


def _nominatim_get(name, verbose=False):
    """Interroge Nominatim en respectant sa politique de debit, avec reprise.

    Leve une exception sur echec definitif : l'appelant doit pouvoir
    distinguer « panne » de « ville introuvable », sans quoi une coupure
    reseau serait lue comme une absence de resultat et cachee comme telle.
    """
    global _last_call
    if requests is None:
        raise RuntimeError("module requests indisponible")

    last_error = None
    for attempt in range(RETRIES):
        delta = time.time() - _last_call
        if delta < MIN_INTERVAL_S:
            time.sleep(MIN_INTERVAL_S - delta)
        try:
            resp = requests.get(
                NOMINATIM_URL,
                params={"q": name, "format": "json", "limit": 1,
                        "addressdetails": 1, "polygon_bbox": 1},
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            _last_call = time.time()
            if resp.status_code in (429, 502, 503, 504):
                raise RuntimeError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            _last_call = time.time()
            last_error = e
            if attempt < RETRIES - 1:
                wait = BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)]
                if verbose:
                    print(f"   [nominatim] {e} — nouvelle tentative dans {wait}s")
                time.sleep(wait)
    raise last_error


def parse_result(entry):
    """Transforme une reponse Nominatim en metadonnees de ville.

    boundingbox vient en [sud, nord, ouest, est], en chaines.
    Le rayon est la demi-diagonale de cette boite : il couvre toute l'emprise
    administrative, donc aucune coordonnee legitime n'est rejetee.
    """
    try:
        lat, lng = float(entry["lat"]), float(entry["lon"])
    except (KeyError, TypeError, ValueError):
        return None

    radius_km = RADIUS_FLOOR_KM
    bbox = entry.get("boundingbox")
    if bbox and len(bbox) == 4:
        try:
            s, n, w, e = (float(x) for x in bbox)
            radius_km = max(RADIUS_FLOOR_KM, _haversine_km((s, w), (n, e)) / 2)
        except (TypeError, ValueError):
            pass

    country = ((entry.get("address") or {}).get("country_code") or "").lower()
    # Nominatim rend de l'ISO 3166-1 alpha-2, ce qu'attend son propre filtre
    # countrycodes. Pas de normalisation uk->gb a faire ici : l'anomalie 'uk'
    # du depot vient des dictionnaires manuels, pas de Nominatim.

    return {
        "lat": lat,
        "lng": lng,
        "name": entry.get("display_name", "").split(",")[0] or None,
        "country": country or None,
        "radius_km": round(radius_km, 1),
        "osm_type": entry.get("type"),
        "source": "nominatim",
    }


def resolve(name, use_cache=True, verbose=False):
    """Metadonnees derivees pour un nom de ville, ou None.

    None signifie « pas d'information », jamais « ville invalide » : une panne
    reseau produit None comme une ville introuvable. L'appelant ne doit donc
    jamais en tirer de conclusion negative.
    """
    if not name or not str(name).strip():
        return None
    name = str(name).strip()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp = _cache_path(name)
    if use_cache and cp.exists():
        age_days = (time.time() - cp.stat().st_mtime) / 86400
        try:
            cached = json.loads(cp.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            cached = None
        if cached is not None:
            ttl = CACHE_TTL_DAYS if cached else CACHE_TTL_EMPTY_DAYS
            if age_days < ttl:
                if verbose:
                    print(f"   [cache] {name} ({age_days:.0f} j)")
                return cached or None

    try:
        data = _nominatim_get(name, verbose=verbose)
    except Exception as e:
        if verbose:
            print(f"   [nominatim] indisponible pour « {name} » : {e}")
        return None

    meta = parse_result(data[0]) if data else None
    if meta or CACHE_TTL_EMPTY_DAYS > 0:
        cp.write_text(json.dumps(meta or {}, ensure_ascii=False), encoding="utf-8")
    elif cp.exists():
        cp.unlink()
    return meta


def center_for(code, name, curated, verbose=False):
    """Centre d'une ville : le dictionnaire cure d'abord, Nominatim ensuite.

    `curated` est le dict {code: {lat, lng, name}} du script appelant. Une
    entree curee n'est jamais ecrasee.
    """
    hit = (curated or {}).get(code)
    if hit and hit.get("lat") is not None and hit.get("lng") is not None:
        return dict(hit, source="curated")
    meta = resolve(name or code, verbose=verbose)
    if not meta:
        return None
    return {"lat": meta["lat"], "lng": meta["lng"],
            "name": meta.get("name") or name or code,
            "radius_km": meta["radius_km"], "source": "nominatim"}


def country_for(code, name, curated, verbose=False):
    """Code pays ISO : dictionnaire cure d'abord, Nominatim ensuite.

    Renvoie '' quand rien n'est connu. L'appelant doit traiter '' comme
    « pas de filtre pays », surtout PAS comme un defaut implicite a 'fr' --
    c'est ce defaut qui envoyait countrycodes=fr pour des adresses suedoises.
    """
    hit = (curated or {}).get(code)
    if hit:
        return hit
    meta = resolve(name or code, verbose=verbose)
    return (meta or {}).get("country") or ""


def main():
    ap = argparse.ArgumentParser(
        description="Derive centre, pays et rayon d'une ville via Nominatim.")
    ap.add_argument("--name", required=True, help="nom de la ville a resoudre")
    ap.add_argument("--code", default=None, help="code ville, pour l'affichage")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    meta = resolve(args.name, use_cache=not args.no_cache, verbose=args.verbose)
    if not meta:
        print(f"Aucun resultat pour « {args.name} » "
              f"(introuvable, ou Nominatim indisponible — indiscernable).")
        sys.exit(1)

    label = f"{args.code} — " if args.code else ""
    print(f"\n{label}{args.name}")
    print(f"  centre     : {meta['lat']:.6f}, {meta['lng']:.6f}")
    print(f"  nom OSM    : {meta.get('name')}")
    print(f"  pays       : {meta.get('country') or '(inconnu)'}")
    print(f"  type OSM   : {meta.get('osm_type')}")
    print(f"  rayon      : {meta['radius_km']} km  (demi-diagonale de la bbox)")
    if meta["radius_km"] > 100:
        print("\n  ⚠️  Rayon tres large : l'entite geocodee est une region, pas une")
        print("      ville. Le controle de coherence ne discriminera quasiment")
        print("      rien a cette echelle — il ne rejettera que les erreurs")
        print("      grossieres, type adresse geocodee dans un autre pays.")


if __name__ == "__main__":
    main()
