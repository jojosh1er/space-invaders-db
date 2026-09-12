#!/usr/bin/env python3
"""
update_from_csv.py
──────────────────
Met à jour invaders_master.json à partir d'un CSV de coordonnées manuelles.

Format CSV attendu (avec ou sans en-tête) :
    invader_id,lat,lng
    PA_1228,48.856234,2.352890
    PA_1530,48.871234,2.341234

Usage :
    python3 update_from_csv.py corrections.csv                  # dry-run
    python3 update_from_csv.py corrections.csv --apply          # écrit le master
    python3 update_from_csv.py corrections.csv --apply --verbose
"""

import csv
import json
import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime

MASTER_FILE = Path("data/invaders_master.json")


def main():
    parser = argparse.ArgumentParser(description="Met à jour le master JSON depuis un CSV GPS")
    parser.add_argument('csv_file', help='Fichier CSV (invader_id, lat, lng)')
    parser.add_argument('--apply', action='store_true', help='Écrire les modifications (sans = dry-run)')
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"❌ CSV non trouvé : {csv_path}")
        sys.exit(1)

    if not MASTER_FILE.exists():
        print(f"❌ Master non trouvé : {MASTER_FILE}")
        sys.exit(1)

    # ── Lire le CSV ──────────────────────────────────────────────────────────
    rows = []
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        for i, row in enumerate(reader):
            if not row or row[0].strip().startswith('#'):
                continue
            # Ignorer la ligne d'en-tête si présente
            if i == 0 and row[0].strip().lower() in ('invader_id', 'id', 'invader'):
                continue
            if len(row) < 3:
                print(f"⚠️  Ligne {i+1} ignorée (moins de 3 colonnes) : {row}")
                continue
            inv_id = row[0].strip().upper().replace('-', '_')
            try:
                lat = float(row[1].strip().replace(',', '.'))
                lng = float(row[2].strip().replace(',', '.'))
            except ValueError:
                print(f"⚠️  Ligne {i+1} ignorée (coordonnées invalides) : {row}")
                continue
            rows.append({'id': inv_id, 'lat': lat, 'lng': lng})

    if not rows:
        print("❌ Aucune ligne valide dans le CSV")
        sys.exit(1)

    print(f"📋 {len(rows)} entrées lues depuis {csv_path}")

    # ── Charger le master ────────────────────────────────────────────────────
    with open(MASTER_FILE, encoding='utf-8') as f:
        db = json.load(f)

    # Index par ID
    index = {}
    for i, inv in enumerate(db):
        inv_id = inv.get('id') or inv.get('name') or ''
        index[inv_id.upper().replace('-', '_')] = i

    # ── Appliquer les corrections ─────────────────────────────────────────────
    updated = []
    not_found = []

    for row in rows:
        inv_id = row['id']
        if inv_id not in index:
            not_found.append(inv_id)
            print(f"❌ Non trouvé dans le master : {inv_id}")
            continue

        idx = index[inv_id]
        inv = db[idx]
        old_lat = inv.get('lat')
        old_lng = inv.get('lng')
        old_src = inv.get('geo_source', 'N/A')

        if args.apply:
            db[idx]['lat']            = row['lat']
            db[idx]['lng']            = row['lng']
            db[idx]['geo_source']     = 'manual'
            db[idx]['geo_confidence'] = 'high'
            db[idx]['geo_locked']     = True
            db[idx]['geo_lock_date']  = datetime.now().isoformat()
            db[idx]['geo_lock_reason']= 'manual_csv'
            db[idx]['location_unknown']    = False
            db[idx]['geo_search_exhausted']= False

        updated.append(inv_id)
        if args.verbose or not args.apply:
            print(f"  {'✅' if args.apply else '🔍'} {inv_id}")
            print(f"      lat: {old_lat} → {row['lat']}")
            print(f"      lng: {old_lng} → {row['lng']}")
            print(f"      source: {old_src} → manual/high/locked")

    # ── Résumé ────────────────────────────────────────────────────────────────
    print()
    if args.apply:
        print(f"✅ {len(updated)} invaders mis à jour")
    else:
        print(f"🔍 {len(updated)} invaders à mettre à jour (dry-run)")
    if not_found:
        print(f"❌ {len(not_found)} IDs non trouvés : {', '.join(not_found)}")

    # ── Écriture ──────────────────────────────────────────────────────────────
    if args.apply and updated:
        backup = MASTER_FILE.with_suffix(
            f".backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        shutil.copy(MASTER_FILE, backup)
        print(f"💾 Backup → {backup}")

        with open(MASTER_FILE, 'w', encoding='utf-8') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
        print(f"✅ {MASTER_FILE} mis à jour")
    elif not args.apply:
        print("\n💡 Relancez avec --apply pour appliquer les changements")


if __name__ == '__main__':
    main()
