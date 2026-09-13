#!/usr/bin/env python3
"""
shop_corroboration.py

Utilise les enseignes commerciales lues par Vision pour CONFIRMER une position
geolocalisee. Jamais pour la produire, et jamais pour la retrograder.

Historique des deux revisions qui ont donne cette forme :

1. Hypothese initiale -- deux enseignes co-visibles a moins de 60 m, position
   = milieu du segment. Abandonnee : sur STK_03 les deux enseignes lues sont
   distantes de 276 m et leur milieu tombait a 120 m de la bonne reponse. La
   co-occurrence sert a lever l'ambiguite entre implantations, pas a produire
   un point.

2. Deuxieme version -- trois verdicts, dont un « doubtful » quand l'enseigne
   la plus proche depassait 400 m. Abandonne apres le backtest de PA_1122 :
   les deux verdicts sortaient inverses. La verite terrain recoltait
   « doubtful » et la position fausse de Vision (6,2 km d'erreur) recoltait
   « unknown ». Vision avait halucine l'enseigne en meme temps que le repere,
   et l'absence d'Europcar pres de la vraie position ne disait rien sur cette
   position -- seulement sur l'enseigne.

   L'absence d'une enseigne a proximite a trois causes indiscernables :
   enseigne halucinee par Vision, enseigne absente d'OSM, ou position fausse.
   Aucun verdict negatif ne peut donc etre emis. Il ne reste que deux issues :
   CORROBORATED ou UNKNOWN.

CE QUI RESTE VRAI
Une enseigne trouvee a 23 m d'une adresse deduite sans lecture de plaque est
une preuve (STK_03, confirme). Une enseigne introuvable n'est pas une preuve
contraire. Le module confirme ou se tait.

PONDERATION PAR LA DENSITE
Une enseigne rare a 23 m est une preuve forte ; une chaine dense a 23 m peut
etre une coincidence. Ur & Penn compte deux implantations dans tout Stockholm,
Europcar trois dans 2 km de Paris. La force de la corroboration est donc
graduee par le nombre d'implantations trouvees dans la boite. Le module
calcule aussi une probabilite de collision fortuite, indicative : elle suppose
une repartition uniforme, alors que les commerces se concentrent sur les axes
passants -- la ou les mosaiques sont posees. Elle sous-estime donc le hasard,
et ne doit pas etre lue comme une p-value.

Usage :
    python shop_corroboration.py --lat 59.3326807 --lng 18.0627056 \
        --shops "Weekday,Ur&Penn" -v

    python shop_corroboration.py --file data/invaders_master.json \
        --id STK_03 --shops "Weekday,Ur&Penn" --apply
"""

import argparse
import hashlib
import json
import math
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "InvaderHunter-shop-corroboration/2.0"

# Distance en dessous de laquelle on considere que la mosaique est sur le
# batiment de l'enseigne ou immediatement a cote.
RADIUS_CORROBORATE_M = 50

# Au-dela de ce nombre d'implantations d'une meme enseigne dans la boite, la
# marque est jugee trop banale pour qu'une proximite vaille preuve a elle
# seule : la corroboration est marquee 'weak' et --apply la refuse.
DENSITY_STRONG_MAX = 3

# Distance maximale d'un recalage. Une enseigne unique dans la boite et situee
# a moins de cette distance de la reponse de Vision DEVIENT la position ; au
# dela, on ne bouge pas. Valeur arbitraire, a calibrer sur une cohorte a verite
# terrain : ROM_61 demandait 233 m, STK_03 seulement 23 m. Trop haut, on
# deplace sur une seule preuve ; trop bas, on laisse l'erreur en place.
SNAP_MAX_M = 500

# Demi-cote de la bbox interrogee autour du point candidat, en degres de
# latitude (~2,2 km). Une enseigne plus loin que ca ne corrobore rien.
BOX_DEG = 0.02

CACHE_DIR = Path.home() / ".cache" / "invader_shop_corroboration"
CACHE_TTL_DAYS = 30

# Duree de vie d'un resultat VIDE, en jours. A zero, une absence n'est jamais
# mise en cache : elle peut venir d'une regex fautive, d'un timeout ou d'une
# donnee OSM pas encore contribuee, et la cacher 30 jours fige une erreur
# transitoire en erreur persistante. Contrepartie : une enseigne reellement
# absente d'OSM est re-interrogee a chaque passe. Monter a 1 si Overpass
# commence a protester.
CACHE_TTL_EMPTY_DAYS = 0

# Etranglement : intervalle minimal entre deux requetes, applique AVANT l'appel.
# Une pause posee apres la requete ne regule rien quand les appels s'enchainent
# en boucle -- 40 % d'echecs reseau observes sur un lot de dix invaders.
OVERPASS_MIN_INTERVAL_S = 4.0
OVERPASS_RETRIES = 3
OVERPASS_BACKOFF_S = (5, 15, 40)
_last_overpass_call = 0.0


# ─── Geometrie ──────────────────────────────────────────────────────────────

def haversine_m(a, b):
    """Distance en metres entre deux couples (lat, lng)."""
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dphi = p2 - p1
    dlam = math.radians(b[1] - a[1])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def box_area_km2(bbox):
    """Aire approximative de la bbox, en km carres."""
    lat_mid = (bbox[0] + bbox[2]) / 2
    h = (bbox[2] - bbox[0]) * 111.32
    w = (bbox[3] - bbox[1]) * 111.32 * math.cos(math.radians(lat_mid))
    return abs(h * w)


def chance_probability(n_implantations, radius_m, area_km2):
    """
    Probabilite grossiere qu'une implantation tombe par hasard dans le rayon.

    Modele uniforme : p = n * pi * r^2 / A. Indicatif seulement -- les
    commerces se concentrent sur les axes passants, donc le hasard reel est
    superieur a cette valeur. Ne pas interpreter comme une p-value.
    """
    if area_km2 <= 0:
        return None
    disc_km2 = math.pi * (radius_m / 1000.0) ** 2
    return min(1.0, n_implantations * disc_km2 / area_km2)


# ─── Normalisation des noms d'enseigne ──────────────────────────────────────

def build_name_regex(brand):
    """
    Construit une regex Overpass tolerante pour un nom d'enseigne.

    Les contributeurs OSM ecrivent « Ur & Penn », « Ur&Penn » ou « Ur-Penn ».
    On rend souples les separateurs entre mots et on echappe le reste.

    ATTENTION : Overpass evalue les regex en POSIX etendu, PAS en PCRE.
    Les echappements Perl n'y existent pas -- un « \\s » y est lu comme la
    classe {antislash, s}, ce qui fait silencieusement manquer toutes les
    graphies espacees. On n'utilise donc que des caracteres litteraux dans
    la classe de separateurs (le tiret est place en dernier pour ne pas
    former un intervalle).
    """
    parts = [p for p in re.split(r"[\s&]+", brand.strip()) if p]
    if not parts:
        return None
    escaped = [re.escape(p) for p in parts]
    return r"[ &._-]*".join(escaped)


def normalize_name(value):
    """Minuscule, separateurs retires, pour comparer des graphies d'enseigne."""
    return re.sub(r"[ &._\-']+", "", (value or "")).casefold()


def name_matches_brand(tag_value, brand):
    """
    Vrai si tag_value designe bien l'enseigne demandee.

    Overpass matche le motif n'importe ou dans le nom, ce qui a fait passer
    « Sessad Le Passage » (service medico-social) pour « Le Passage », et
    « Regal Kebab » pour « Kebab ». Ancrer sur une frontiere de mot ne suffit
    pas : « Le Passage » EST sur une frontiere dans « Sessad Le Passage ».
    On exige donc que le nom COMMENCE par l'enseigne, convention OSM usuelle
    (« Klattermusen Kungsgatan » passe, « Sessad Le Passage » non).

    Consequence assumee : un « Cafe Le Passage » serait rejete. Manquer une
    enseigne coute moins cher que de recaler une mosaique sur la mauvaise.
    """
    a, b = normalize_name(tag_value), normalize_name(brand)
    return bool(b) and a.startswith(b)


# ─── Overpass ───────────────────────────────────────────────────────────────

def _overpass_post(query, verbose=False):
    """
    Envoie une requete Overpass en respectant un debit minimal, avec reprise.

    L'instance publique est un service communautaire a quotas. Les erreurs
    429 (trop de requetes), 503 et 504 sont transitoires : on retente avec un
    recul croissant. Une erreur definitive est propagee -- l'appelant doit
    pouvoir distinguer « panne » de « enseigne absente », sans quoi une coupure
    reseau serait lue comme une preuve.
    """
    global _last_overpass_call
    last_error = None
    for attempt in range(OVERPASS_RETRIES):
        delta = time.time() - _last_overpass_call
        if delta < OVERPASS_MIN_INTERVAL_S:
            time.sleep(OVERPASS_MIN_INTERVAL_S - delta)
        try:
            resp = requests.post(OVERPASS_URL, data={"data": query},
                                 headers={"User-Agent": USER_AGENT}, timeout=90)
            _last_overpass_call = time.time()
            if resp.status_code in (429, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.json().get("elements", [])
        except Exception as e:
            _last_overpass_call = time.time()
            last_error = e
            if attempt < OVERPASS_RETRIES - 1:
                wait = OVERPASS_BACKOFF_S[min(attempt, len(OVERPASS_BACKOFF_S) - 1)]
                if verbose:
                    print(f"    [overpass] {e} — nouvelle tentative dans {wait}s "
                          f"({attempt + 2}/{OVERPASS_RETRIES})")
                time.sleep(wait)
    raise last_error


def _cache_path(brand, bbox):
    key = f"{brand.lower()}|{bbox[0]:.3f},{bbox[1]:.3f},{bbox[2]:.3f},{bbox[3]:.3f}"
    return CACHE_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".json")


def overpass_shops(brand, bbox, verbose=False, use_cache=True):
    """
    Renvoie la liste des implantations d'une enseigne dans une bbox.

    bbox : (lat_min, lng_min, lat_max, lng_max)
    Leve une exception en cas d'echec reseau -- l'appelant decide quoi en
    faire, car un echec Overpass ne doit jamais etre confondu avec
    « enseigne absente ».
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp = _cache_path(brand, bbox)
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
                    print(f"    [cache] {brand} ({age_days:.0f} j)")
                return cached
            if not cached and verbose:
                print(f"    [cache] {brand} : entree vide ignoree "
                      f"(TTL {CACHE_TTL_EMPTY_DAYS} j)")

    rx = build_name_regex(brand)
    if not rx:
        return []

    box = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
    clauses = "\n".join(
        f'  nwr["{tag}"~"{rx}",i]({box});' for tag in ("name", "brand", "operator")
    )
    query = f"[out:json][timeout:60];\n(\n{clauses}\n);\nout center tags;"

    if verbose:
        print(f"    [overpass] {brand} dans {box}")
    elements = _overpass_post(query, verbose=verbose)

    seen, out = set(), []
    for e in elements:
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lng = e.get("lon") or (e.get("center") or {}).get("lon")
        if lat is None or lng is None:
            continue
        key = (round(lat, 6), round(lng, 6))
        if key in seen:
            continue
        seen.add(key)
        t = e.get("tags", {})
        # Overpass matche le motif n'importe ou dans la valeur du tag : on
        # refiltre ici, sinon « Sessad Le Passage » passe pour « Le Passage ».
        label = next((t.get(k) for k in ("name", "brand", "operator")
                      if name_matches_brand(t.get(k), brand)), None)
        if label is None:
            continue
        out.append({
            "name": label,
            "lat": lat,
            "lng": lng,
            "street": t.get("addr:street", ""),
            "housenumber": t.get("addr:housenumber", ""),
        })

    if out or CACHE_TTL_EMPTY_DAYS > 0:
        cp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    elif cp.exists():
        cp.unlink()
    return out


# ─── Verdict ────────────────────────────────────────────────────────────────

def corroborate(lat, lng, shop_names, verbose=False, use_cache=True,
                radius_ok=RADIUS_CORROBORATE_M,
                density_strong_max=DENSITY_STRONG_MAX,
                snap_max_m=SNAP_MAX_M, allow_relocate=True):
    """
    Confronte une position candidate aux implantations connues des enseignes.

    Trois verdicts :

      corroborated  une enseigne est a moins de radius_ok. La position ne
                    bouge pas ; elle est confirmee.

      relocated     une enseigne UNIQUE dans la boite est entre radius_ok et
                    snap_max_m. Elle devient la position.

                    Motif : sur ROM_61, VinAllegro etait a 24 m de la verite
                    terrain et a 233 m de la reponse de Vision. L'ancien
                    module mesurait la distance a la reponse de Vision et
                    rejetait donc l'ancrage correct parce que Vision se
                    trompait de 228 m -- l'hypothese implicite etant que
                    Vision est deja juste, celle qu'on ne peut pas faire.

                    Reserve unicite : deux implantations ou plus ne
                    permettent pas de trancher laquelle est la bonne, et un
                    recalage errone est pire que pas de recalage. Reserve
                    distance : la boite fait ~2,2 km autour de la reponse de
                    Vision, donc une erreur de plusieurs kilometres reste
                    hors de portee -- ce module corrige le moyen terrain, pas
                    les hallucinations franches.

      unknown       tout le reste. Aucune retrogradation n'est jamais emise :
                    l'absence d'une enseigne peut venir d'une hallucination
                    de Vision, d'un trou dans OSM ou d'une position fausse,
                    causes indiscernables (cas PA_1122).
    """
    pos = (lat, lng)
    dlng = BOX_DEG / math.cos(math.radians(lat))
    bbox = (lat - BOX_DEG, lng - dlng, lat + BOX_DEG, lng + dlng)
    area = box_area_km2(bbox)

    findings, errors, density = [], [], {}
    for brand in shop_names:
        brand = brand.strip()
        if not brand:
            continue
        try:
            hits = overpass_shops(brand, bbox, verbose=verbose, use_cache=use_cache)
        except Exception as e:
            errors.append(f"{brand}: {e}")
            if verbose:
                print(f"    \u26a0\ufe0f  Overpass indisponible pour {brand} : {e}")
            continue
        density[brand] = len(hits)
        for h in hits:
            h = dict(h)
            h["brand_query"] = brand
            h["distance_m"] = haversine_m(pos, (h["lat"], h["lng"]))
            findings.append(h)

    findings.sort(key=lambda h: h["distance_m"])

    def pack(verdict, strength, reason, nearest, snap=None):
        n = density.get(nearest["brand_query"], 1) if nearest else 0
        return {
            "verdict": verdict, "strength": strength, "reason": reason,
            "nearest": nearest, "findings": findings, "density": density,
            "snap": snap, "box_area_km2": area, "errors": errors,
            "chance_probability": chance_probability(n, radius_ok, area) if nearest else None,
        }

    # 1. Deja sur place : on confirme, on ne bouge pas.
    near = [h for h in findings if h["distance_m"] <= radius_ok]
    if near:
        best = near[0]
        n = density.get(best["brand_query"], 1)
        strength = "strong" if n <= density_strong_max else "weak"
        reason = (f"{best['name']} a {best['distance_m']:.0f} m "
                  f"({n} implantation(s) dans la boite)")
        if strength == "weak":
            reason += f" \u2014 enseigne trop repandue au-dela de {density_strong_max}"
        return pack("corroborated", strength, reason, best)

    # 2. Enseigne unique un peu plus loin : elle devient la position.
    if allow_relocate:
        uniques = [h for h in findings
                   if density.get(h["brand_query"], 0) == 1
                   and h["distance_m"] <= snap_max_m]
        if len(uniques) == 1:
            best = uniques[0]
            return pack("relocated", "strong",
                        f"{best['name']} seule implantation de la boite, a "
                        f"{best['distance_m']:.0f} m \u2014 devient la position",
                        best, snap=(best["lat"], best["lng"]))
        if len(uniques) > 1:
            return pack("unknown", None,
                        f"{len(uniques)} enseignes uniques candidates a moins de "
                        f"{snap_max_m:.0f} m \u2014 impossible de trancher",
                        findings[0])

    if errors and not findings:
        reason = "Overpass injoignable \u2014 aucune conclusion possible"
    elif not findings:
        reason = "aucune enseigne trouvee dans la boite (couverture OSM ou nom errone)"
    else:
        reason = (f"enseigne la plus proche ({findings[0]['name']}) a "
                  f"{findings[0]['distance_m']:.0f} m \u2014 ne prouve rien, "
                  f"ni pour ni contre")
    return pack("unknown", None, reason, findings[0] if findings else None)


# ─── CLI ────────────────────────────────────────────────────────────────────

def _print_report(res, lat, lng):
    icon = {"corroborated": "✅", "relocated": "📍", "unknown": "❔"}[res["verdict"]]
    strength = f" [{res['strength']}]" if res.get("strength") else ""
    print(f"\nPosition testee : {lat:.7f}, {lng:.7f}")
    print(f"{icon} {res['verdict'].upper()}{strength} — {res['reason']}")
    if res.get("chance_probability") is not None:
        print(f"   collision fortuite (modele uniforme, indicatif) : "
              f"{res['chance_probability'] * 100:.2f} %")
    if res["findings"]:
        print("\nImplantations trouvees :")
        for h in res["findings"]:
            addr = f"{h['street']} {h['housenumber']}".strip()
            print(f"  {h['distance_m']:>7.0f} m  {h['name']:<22} "
                  f"{h['lat']:.5f},{h['lng']:.5f}  {addr}")
    if res["errors"]:
        print("\nErreurs Overpass (traitees comme absence d'information) :")
        for e in res["errors"]:
            print(f"  {e}")
    if res.get("snap"):
        print(f"\n   recalage propose : {res['snap'][0]:.7f}, {res['snap'][1]:.7f} "
              f"({res['nearest']['distance_m']:.0f} m de deplacement)")
    if res["verdict"] == "unknown":
        print("\nAucune conclusion. Ce module ne retrograde jamais une position.")


def main():
    ap = argparse.ArgumentParser(
        description="Confirme une position geolocalisee via les enseignes lues par Vision."
    )
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lng", type=float)
    ap.add_argument("--file", help="JSON d'invaders (master ou relocalized)")
    ap.add_argument("--id", help="identifiant de l'invader dans --file")
    ap.add_argument("--shops",
                    help="enseignes separees par des virgules. Par defaut, lit "
                         "vision_shop_signs dans l'enregistrement.")
    ap.add_argument("--apply", action="store_true",
                    help="si corroboration FORTE, cale la position sur l'enseigne")
    ap.add_argument("--radius-ok", type=float, default=RADIUS_CORROBORATE_M)
    ap.add_argument("--density-max", type=int, default=DENSITY_STRONG_MAX)
    ap.add_argument("--snap-max", type=float, default=SNAP_MAX_M,
                    help="distance maximale de recalage sur une enseigne unique")
    ap.add_argument("--no-relocate", action="store_true",
                    help="confirme seulement, ne recale jamais")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    entries, target, path = None, None, None
    if args.file:
        if not args.id:
            sys.exit("--file exige --id")
        path = Path(args.file)
        entries = json.loads(path.read_text(encoding="utf-8"))
        target = next((e for e in entries if e.get("id") == args.id), None)
        if target is None:
            sys.exit(f"{args.id} introuvable dans {path}")
        lat, lng = float(target["lat"]), float(target["lng"])
        print(f"{args.id} — {target.get('address', '(sans adresse)')}")
    elif args.lat is not None and args.lng is not None:
        lat, lng = args.lat, args.lng
    else:
        sys.exit("Fournir soit --lat/--lng, soit --file/--id")

    if args.shops:
        shops = [s for s in args.shops.split(",") if s.strip()]
    elif target and target.get("vision_shop_signs"):
        shops = list(target["vision_shop_signs"])
        print(f"  enseignes persistees : {', '.join(shops)}")
    else:
        sys.exit("Aucune enseigne : passer --shops, ou utiliser un enregistrement "
                 "portant vision_shop_signs.")

    res = corroborate(lat, lng, shops, verbose=args.verbose,
                      use_cache=not args.no_cache,
                      radius_ok=args.radius_ok,
                      density_strong_max=args.density_max,
                      snap_max_m=args.snap_max,
                      allow_relocate=not args.no_relocate)
    _print_report(res, lat, lng)

    if not args.apply:
        if args.file:
            print("\nSimulation. Relancer avec --apply pour ecrire.")
        return

    if res["verdict"] not in ("corroborated", "relocated") or res["strength"] != "strong":
        print("\nPas de corroboration forte : rien n'est modifie.")
        return

    near = res["nearest"]
    target["lat"] = near["lat"]
    target["lng"] = near["lng"]
    target["geo_source"] = ("vision_shop_relocated" if res["verdict"] == "relocated"
                            else "vision_shop_corroborated")
    target["geo_confidence"] = "high"
    target["location_unknown"] = False
    target["geo_search_exhausted"] = False
    addr = f"{near['street']} {near['housenumber']}".strip()
    target["geo_hint"] = (
        f"cale sur {near['name']}" + (f" ({addr})" if addr else "")
        + f" — {near['distance_m']:.0f} m de l'adresse deduite par Vision"
    )
    target["geo_tier_reason"] = f"enseigne corroboree a {near['distance_m']:.0f}m"

    backup = path.with_suffix(path.suffix + f".bak-{datetime.now():%Y%m%d-%H%M%S}")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"\n{args.id} cale sur {near['name']} ({near['lat']:.7f}, {near['lng']:.7f})")
    print(f"Ecrit : {path}\nSauvegarde : {backup.name}")


if __name__ == "__main__":
    main()
