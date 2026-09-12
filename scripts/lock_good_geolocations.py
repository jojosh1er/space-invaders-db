#!/usr/bin/env python3
"""
lock_good_geolocations.py
─────────────────────────
Pose geo_locked=True sur les invaders du master qui ont une géolocalisation
de qualité, pour les protéger des re-calculs automatiques de la GitHub Action.

Usage :
    python3 lock_good_geolocations.py                        # dry-run
    python3 lock_good_geolocations.py --apply                # écrit le master
    python3 lock_good_geolocations.py --apply --city PA      # une ville seulement
    python3 lock_good_geolocations.py --apply --id PA_1228   # un invader précis
    python3 lock_good_geolocations.py --unlock --id PA_1228  # déverrouiller

Critères de verrouillage automatique (cumulatifs) :
    - geo_source ∈ {exif_image_lieu, vision, instagram_vision,
                    instagram_geotag, manual, fuzzy_overpass}
    - geo_confidence ∈ {high, medium}

On peut aussi verrouiller manuellement n'importe quel invader via --id.
"""

import json
import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime

MASTER_FILE = Path("data/invaders_master.json")

# Sources produites par géolocalisation manuelle ou Vision de qualité
PROTECTED_SOURCES = {
    'exif_image_lieu',
    'vision',
    'instagram_vision',
    'instagram_geotag',
    'manual',
    'fuzzy_overpass',
}

PROTECTED_CONFIDENCES = {'high', 'medium'}


def should_lock(inv: dict) -> tuple[bool, str]:
    """Retourne (True, raison) si l'invader mérite d'être verrouillé."""
    src = inv.get('geo_source', '')
    conf = inv.get('geo_confidence', '')

    if src in PROTECTED_SOURCES and conf in PROTECTED_CONFIDENCES:
        return True, f"{src}/{conf}"

    return False, ''


def main():
    parser = argparse.ArgumentParser(description="Verrouille les bonnes géolocalisations du master")
    parser.add_argument('--apply', action='store_true',
                        help='Écrire les modifications (sans cet arg = dry-run)')
    parser.add_argument('--unlock', action='store_true',
                        help='Déverrouiller (retirer geo_locked) au lieu de verrouiller')
    parser.add_argument('--city', help='Limiter à une ville (ex: PA)')
    parser.add_argument('--id', dest='inv_id', help='Cibler un invader précis (ex: PA_1228)')
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

    if not MASTER_FILE.exists():
        print(f"❌ Master non trouvé : {MASTER_FILE}")
        sys.exit(1)

    with open(MASTER_FILE, 'r', encoding='utf-8') as f:
        db = json.load(f)

    print(f"📂 {len(db)} invaders chargés depuis {MASTER_FILE}")

    if args.apply and not args.unlock:
        # Backup automatique
        backup = MASTER_FILE.with_suffix(
            f".backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        shutil.copy(MASTER_FILE, backup)
        print(f"💾 Backup → {backup}")

    locked = 0
    unlocked = 0
    already = 0
    skipped = 0

    for inv in db:
        inv_id = inv.get('id', inv.get('name', '?'))

        # Filtre ville
        if args.city and inv.get('city', '').upper() != args.city.upper():
            continue

        # Filtre ID spécifique
        if args.inv_id:
            target = args.inv_id.upper().replace('-', '_')
            if inv_id.upper().replace('-', '_') != target:
                continue

        # ── Mode déverrouillage ──────────────────────────────────────────
        if args.unlock:
            if inv.get('geo_locked'):
                if args.apply:
                    inv['geo_locked'] = False
                    inv['geo_lock_date'] = None
                unlocked += 1
                if args.verbose:
                    print(f"   🔓 {inv_id}")
            continue

        # ── Mode verrouillage ────────────────────────────────────────────
        if inv.get('geo_locked'):
            already += 1
            if args.verbose:
                print(f"   ✅ {inv_id} déjà verrouillé")
            continue

        lock, reason = should_lock(inv)
        if lock:
            if args.apply:
                inv['geo_locked'] = True
                inv['geo_lock_date'] = datetime.now().isoformat()
                inv['geo_lock_reason'] = reason
            locked += 1
            if args.verbose or args.inv_id:
                print(f"   🔒 {inv_id}  ({reason})")
        else:
            skipped += 1
            if args.verbose:
                src = inv.get('geo_source', 'N/A')
                conf = inv.get('geo_confidence', 'N/A')
                print(f"   ⬜ {inv_id}  ({src}/{conf}) — non protégé")

    # Résumé
    print()
    if args.unlock:
        action = "déverrouillés" if args.apply else "à déverrouiller (dry-run)"
        print(f"🔓 {unlocked} invaders {action}")
    else:
        action = "verrouillés" if args.apply else "à verrouiller (dry-run)"
        print(f"🔒 {locked} invaders {action}")
        print(f"✅ {already} déjà verrouillés")
        print(f"⬜ {skipped} non éligibles (source/confiance insuffisante)")

    # Écriture
    if args.apply and (locked > 0 or unlocked > 0):
        with open(MASTER_FILE, 'w', encoding='utf-8') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
        print(f"\n✅ {MASTER_FILE} mis à jour")
    elif not args.apply:
        print("\n💡 Relancez avec --apply pour appliquer les changements")


if __name__ == '__main__':
    main()
