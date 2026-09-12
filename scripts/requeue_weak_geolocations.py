#!/usr/bin/env python3
"""
requeue_weak_geolocations.py

Repasse en 'very_low' / location_unknown les entrees geolocalisees qui ne
portent pas d'adresse au niveau de la rue -- typiquement un centroide de
quartier renvoye par Nominatim faute de mieux.

Motif : is_poorly_located() dans geolocate_missing.py ne rattrape que
geo_confidence == 'very_low', jamais 'low'. Une entree ecrite en 'low' avec
location_unknown=False est donc definitivement figee : ni --from-master ni
--retry-failed ne la reprendront. Ce script les remet dans le vivier tout en
conservant leurs coordonnees approximatives, pour qu'elles restent affichables.

Deux regles de detection, volontairement independantes de la langue :

  R1  pas de numero de voie   -> aucun chiffre dans le premier composant de
                                 l'adresse ("Gamla Stan, Stockholm")
  R2  coordonnee partagee     -> au moins deux entrees du fichier pointent
                                 exactement le meme lat/lng

Une entree deja en 'high' ou 'medium' n'est jamais retrogradee : ces tiers
viennent d'une preuve lue (plaque de rue, code postal) et ne sont pas
concernes, meme si R1 s'applique (ex. une place nommee sans numero).

Usage :
    python requeue_weak_geolocations.py data/invaders_relocalized.json
    python requeue_weak_geolocations.py data/invaders_relocalized.json --apply
    python requeue_weak_geolocations.py fichier.json --apply --only STK_01,STK_05

Sans --apply, le script n'ecrit rien : il affiche ce qu'il ferait.
Avec --apply, il ecrit en place apres avoir cree un .bak horodate.
"""

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PROTECTED_TIERS = {"high", "medium"}


def has_street_number(address):
    """R1 : un chiffre dans le premier composant de l'adresse."""
    if not address:
        return False
    first = address.split(",")[0]
    return bool(re.search(r"\d", first))


def analyse(entries):
    """Retourne {id: [regles declenchees]} pour les entrees a retrograder."""
    coord_counts = Counter(
        (e.get("lat"), e.get("lng"))
        for e in entries
        if e.get("lat") or e.get("lng")
    )

    flagged = {}
    for e in entries:
        inv_id = e.get("id")
        tier = (e.get("geo_confidence") or "").lower()
        if tier in PROTECTED_TIERS:
            continue

        rules = []
        if not has_street_number(e.get("address", "")):
            rules.append("R1 pas de numero de voie")
        if coord_counts[(e.get("lat"), e.get("lng"))] > 1:
            rules.append("R2 coordonnee partagee")

        if rules:
            flagged[inv_id] = rules
    return flagged, coord_counts


def report_duplicates(entries, coord_counts):
    dups = {k: v for k, v in coord_counts.items() if v > 1}
    if not dups:
        return
    print("\nCoordonnees partagees (superposition sur la carte) :")
    for coord, n in sorted(dups.items(), key=lambda kv: -kv[1]):
        ids = [e["id"] for e in entries if (e.get("lat"), e.get("lng")) == coord]
        addrs = sorted({e.get("address", "") for e in entries
                        if (e.get("lat"), e.get("lng")) == coord})
        print(f"  {n}x  {coord[0]:.7f}, {coord[1]:.7f}")
        print(f"      {', '.join(ids)}")
        for a in addrs:
            print(f"      \u00ab {a} \u00bb")


def main():
    ap = argparse.ArgumentParser(
        description="Remet dans le vivier les geolocalisations sans adresse de rue."
    )
    ap.add_argument("fichier", help="JSON a traiter (liste d'invaders)")
    ap.add_argument("--apply", action="store_true",
                    help="ecrit les modifications (sinon simulation)")
    ap.add_argument("--only", default=None,
                    help="liste d'ids separes par des virgules ; ignore la detection")
    args = ap.parse_args()

    path = Path(args.fichier)
    if not path.exists():
        sys.exit(f"Fichier introuvable : {path}")

    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        sys.exit("Format inattendu : une liste JSON est attendue.")

    print(f"{path.name} : {len(entries)} entrees")
    print("Tiers :", dict(Counter(e.get("geo_confidence") for e in entries)))

    flagged, coord_counts = analyse(entries)
    report_duplicates(entries, coord_counts)

    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        inconnus = wanted - {e.get("id") for e in entries}
        if inconnus:
            sys.exit(f"Ids absents du fichier : {', '.join(sorted(inconnus))}")
        flagged = {i: ["--only (force manuellement)"] for i in wanted}

    if not flagged:
        print("\nRien a retrograder.")
        return

    print(f"\nA retrograder en very_low / location_unknown : {len(flagged)}")
    for inv_id, rules in sorted(flagged.items()):
        e = next(x for x in entries if x.get("id") == inv_id)
        print(f"  {inv_id:<8} {e.get('geo_confidence'):<7} "
              f"\u00ab {e.get('address', '')} \u00bb")
        for r in rules:
            print(f"           -> {r}")

    if not args.apply:
        print("\nSimulation. Relancer avec --apply pour ecrire.")
        return

    backup = path.with_suffix(path.suffix + f".bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(path, backup)

    for e in entries:
        if e.get("id") in flagged:
            e["geo_confidence"] = "very_low"
            e["location_unknown"] = True
            e["geo_search_exhausted"] = False
            e["geo_requeue_reason"] = "; ".join(flagged[e["id"]])

    path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nEcrit : {path}")
    print(f"Sauvegarde : {backup.name}")
    print("Les coordonnees sont conservees ; seuls les marqueurs de confiance changent.")


if __name__ == "__main__":
    main()
