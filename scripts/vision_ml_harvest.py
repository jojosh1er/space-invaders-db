#!/usr/bin/env python3
"""
Vision ML Feature Harvester
============================
Fait tourner Claude Vision (1 shot) sur des invaders déjà géolocalisés
et extrait les features pour entraîner un modèle de fiabilité.

Usage:
    python vision_ml_harvest.py --n 200 --output features.csv
    python vision_ml_harvest.py --n 50 --cities PA,LDN,NY --output test_features.csv
    python vision_ml_harvest.py --resume features.csv  # reprendre un harvest interrompu

Coût estimé: ~0.01$/invader (1 shot Vision) → 200 invaders = ~2$
"""

import json
import os
import sys
import csv
import time
import math
import random
import re
import argparse
from pathlib import Path
from datetime import datetime

# ─── Import depuis geolocate_missing ───────────────────────────────────────

# Ajouter le répertoire parent au path si nécessaire
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from geolocate_missing import (
    VisionAnalyzer,
    ImageOCRAnalyzer,
    CITY_CENTERS,
    CITY_MAX_RADIUS,
    DEFAULT_CITY_RADIUS,
    calculate_distance,
    validate_city_coherence,
)

# ─── Configuration ──────────────────────────────────────────────────────────

DATA_DIR = SCRIPT_DIR / "data"
MASTER_FILE = DATA_DIR / "invaders_master.json"

# Fallback paths
MASTER_FALLBACKS = [
    MASTER_FILE,
    SCRIPT_DIR / "invaders_master.json",
    SCRIPT_DIR.parent / "data" / "invaders_master.json",  # repo root/data/
    Path.home() / "data" / "invaders_master.json",
    Path("/mnt/user-data/uploads/invaders_master.json"),
]

# Business keywords (same as in scoring)
BUSINESS_KEYWORDS = [
    'restaurant', 'hotel', 'hôtel', 'shop', 'store', 'market', 'bar',
    'café', 'cafe', 'station-service', 'station service',
    'gas station', 'petrol station', 'liquor',
    'phare', 'lighthouse', 'museum', 'musée',
    'chevron', 'shell', 'total', 'bp',
    'academy', 'cinema', 'cinéma', 'theater', 'théâtre',
    'church', 'église', 'mosque', 'mosquée', 'temple', 'synagogue',
    'pharmacy', 'pharmacie', 'boulangerie', 'bakery',
    'supermarket', 'carrefour', 'monoprix', 'aldi', 'lidl',
]

# ─── Helpers ────────────────────────────────────────────────────────────────

def haversine_km(lat1, lon1, lat2, lon2):
    """Distance en km entre deux points GPS."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(min(1.0, math.sqrt(a)))


def classify_error(dist_km):
    """Classe de distance pour le ML."""
    if dist_km < 0.1:
        return 'EXCELLENT'
    elif dist_km < 0.5:
        return 'GOOD'
    elif dist_km < 1.0:
        return 'OK'
    elif dist_km < 3.0:
        return 'APPROX'
    elif dist_km < 10.0:
        return 'ZONE'
    else:
        return 'FAR'


def has_street_number(address):
    """Détecte si l'adresse contient un numéro de rue."""
    if not address:
        return False
    return bool(re.search(r'\b\d{1,4}\b', address))


def count_business_keywords(text):
    """Compte les mots-clés business dans un texte."""
    if not text:
        return 0
    text_lower = text.lower()
    return sum(1 for kw in BUSINESS_KEYWORDS if kw in text_lower)


def has_any_business_keyword(text):
    """Vérifie si un texte contient un mot-clé business."""
    return count_business_keywords(text) > 0


# ─── Sélection stratifiée ──────────────────────────────────────────────────

def select_invaders(master_db, n=200, cities=None, seed=42, recent_only=False, min_points=None):
    """
    Sélection stratifiée par ville, avec image_lieu requise.
    Priorise la diversité des villes et des niveaux de points.
    
    Args:
        recent_only: Si True, ne garde que les invaders avec status 'active' ou récent
                     (proxy: points >= 10, ce qui exclut les flashes anciens/détruits)
        min_points: Seuil minimum de points (proxy de notoriété et fraîcheur des données)
    """
    random.seed(seed)
    
    # Filtrer: coords + image_lieu requis
    eligible = []
    for inv in master_db:
        lat = inv.get('lat')
        lng = inv.get('lng')
        image_lieu = inv.get('image_lieu')
        city = inv.get('city', '')
        
        # Coords valides
        if lat is None or lng is None:
            continue
        try:
            lat, lng = float(lat), float(lng)
        except (ValueError, TypeError):
            continue
        if lat == 0 and lng == 0:
            continue
        
        # Image requise
        if not image_lieu or 'http' not in str(image_lieu):
            continue
        
        # Filtre ville si demandé
        if cities and city not in cities:
            continue
        
        # Exclure les sources "city_center" (ground truth trop imprécis)
        geo_source = inv.get('geo_source', '')
        if geo_source == 'city_center':
            continue
        
        # Filtre récence: exclure les invaders détruits/anciens
        if recent_only:
            status = (inv.get('status') or '').lower()
            if status in ('destroyed', 'détruit', 'removed', 'gone'):
                continue
        
        # Filtre points minimum (proxy de fraîcheur et fiabilité des données)
        if min_points is not None:
            pts = inv.get('points', 0)
            try:
                if int(pts) < min_points:
                    continue
            except (ValueError, TypeError):
                continue
        
        eligible.append(inv)
    
    print(f"📊 {len(eligible)} invaders éligibles (avec coords + image_lieu)")
    
    # Stratification par ville
    by_city = {}
    for inv in eligible:
        city = inv.get('city', 'UNKNOWN')
        by_city.setdefault(city, []).append(inv)
    
    print(f"   {len(by_city)} villes représentées")
    
    # Répartir proportionnellement, minimum 2 par ville
    selected = []
    total_eligible = len(eligible)
    
    for city, invs in sorted(by_city.items(), key=lambda x: -len(x[1])):
        # Proportion de la ville dans le total
        proportion = len(invs) / total_eligible
        city_n = max(2, round(n * proportion))
        city_n = min(city_n, len(invs))
        
        # Mélanger pour diversité
        random.shuffle(invs)
        selected.extend(invs[:city_n])
        
        if len(selected) >= n:
            break
    
    # Si pas assez, compléter aléatoirement
    if len(selected) < n:
        remaining = [inv for inv in eligible if inv not in selected]
        random.shuffle(remaining)
        selected.extend(remaining[:n - len(selected)])
    
    # Tronquer si trop
    selected = selected[:n]
    
    # Stats
    cities_in_sample = {}
    for inv in selected:
        city = inv.get('city', '?')
        cities_in_sample[city] = cities_in_sample.get(city, 0) + 1
    
    print(f"   {len(selected)} sélectionnés:")
    for city, count in sorted(cities_in_sample.items(), key=lambda x: -x[1])[:15]:
        print(f"     {city:8s}: {count}")
    if len(cities_in_sample) > 15:
        print(f"     ... et {len(cities_in_sample) - 15} autres villes")
    
    return selected


# ─── Feature extraction ────────────────────────────────────────────────────

def extract_features(invader, clues, geocode_result, city_code):
    """
    Extrait toutes les features d'un résultat Vision pour le ML.
    
    Returns: dict de features plates (prêt pour CSV)
    """
    inv_id = invader.get('id', invader.get('name', '?'))
    gt_lat = float(invader['lat'])
    gt_lng = float(invader['lng'])
    city = invader.get('city', '')
    points = invader.get('points', 0)
    
    # ─── Features Vision brutes ─────────────────────────────────────
    confidence = (clues.get('confidence') or 'LOW').upper() if clues else 'NONE'
    
    street_signs = clues.get('street_signs', []) if clues else []
    shop_signs = clues.get('shop_signs', []) if clues else []
    landmarks = clues.get('landmarks', []) if clues else []
    building_numbers = clues.get('building_numbers', []) if clues else []
    metro_bus = clues.get('metro_bus', []) if clues else []
    other_clues = clues.get('other_clues', []) if clues else []
    district = clues.get('district', '') if clues else ''
    postcode = clues.get('postcode', '') if clues else ''
    best_address = clues.get('best_address_guess', '') if clues else ''
    address_alternatives = clues.get('address_alternatives', []) if clues else []
    reasoning = clues.get('reasoning', '') if clues else ''
    
    # Nettoyer les listes (parfois Vision renvoie des strings vides)
    street_signs = [s for s in street_signs if s and s.strip()] if isinstance(street_signs, list) else []
    shop_signs = [s for s in shop_signs if s and s.strip()] if isinstance(shop_signs, list) else []
    landmarks = [s for s in landmarks if s and s.strip()] if isinstance(landmarks, list) else []
    building_numbers = [s for s in building_numbers if s and s.strip()] if isinstance(building_numbers, list) else []
    metro_bus = [s for s in metro_bus if s and s.strip()] if isinstance(metro_bus, list) else []
    other_clues = [s for s in other_clues if s and s.strip()] if isinstance(other_clues, list) else []
    
    # ─── Features dérivées ──────────────────────────────────────────
    n_street_signs = len(street_signs)
    n_shop_signs = len(shop_signs)
    n_landmarks = len(landmarks)
    n_building_numbers = len(building_numbers)
    n_metro_bus = len(metro_bus)
    n_other_clues = len(other_clues)
    n_total_clues = n_street_signs + n_shop_signs + n_landmarks + n_building_numbers + n_metro_bus + n_other_clues
    
    has_district = bool(district and district.strip())
    has_postcode = bool(postcode and postcode.strip())
    has_address = bool(best_address and best_address.strip())
    
    # Qualité de l'adresse
    address_has_number = has_street_number(best_address)
    address_has_business = has_any_business_keyword(best_address)
    address_n_business = count_business_keywords(best_address)
    address_length = len(best_address) if best_address else 0
    
    # Qualité des enseignes
    all_signs_text = ' '.join(street_signs + shop_signs + landmarks)
    signs_total_business = count_business_keywords(all_signs_text)
    
    reasoning_length = len(reasoning)
    
    # ─── Features géocodage ─────────────────────────────────────────
    geo_success = geocode_result is not None
    geo_lat = geocode_result['lat'] if geo_success else None
    geo_lng = geocode_result['lng'] if geo_success else None
    
    # Distance au centre-ville
    distance_to_center = None
    if geo_success and city_code in CITY_CENTERS:
        cc = CITY_CENTERS[city_code]
        distance_to_center = haversine_km(geo_lat, geo_lng, cc['lat'], cc['lng'])
    
    # Distance au district géocodé
    distance_to_district = None
    district_geocodes = False
    if geo_success and has_district and city:
        city_name = CITY_CENTERS.get(city_code, {}).get('name', city)
        district_query = f"{district}, {city_name}"
        ocr = ImageOCRAnalyzer(verbose=False)
        geo_d = ocr.geocode_address(district_query, city_code=city_code)
        time.sleep(1)
        if geo_d:
            district_geocodes = True
            distance_to_district = haversine_km(geo_lat, geo_lng, geo_d['lat'], geo_d['lng'])
    
    # ─── Ground truth ───────────────────────────────────────────────
    error_km = None
    error_class = 'NO_GEO'
    if geo_success:
        error_km = haversine_km(geo_lat, geo_lng, gt_lat, gt_lng)
        error_class = classify_error(error_km)
    
    # City coherence
    city_coherent = True
    if geo_success and city_code:
        check = validate_city_coherence(geo_lat, geo_lng, city_code)
        city_coherent = check['valid']
    
    # ─── Assembler ──────────────────────────────────────────────────
    return {
        # Meta
        'invader_id': inv_id,
        'city_code': city,
        'points': points,
        'gt_lat': gt_lat,
        'gt_lng': gt_lng,
        'gt_source': invader.get('geo_source', ''),
        
        # Vision raw
        'confidence': confidence,
        'n_street_signs': n_street_signs,
        'n_shop_signs': n_shop_signs,
        'n_landmarks': n_landmarks,
        'n_building_numbers': n_building_numbers,
        'n_metro_bus': n_metro_bus,
        'n_other_clues': n_other_clues,
        'n_total_clues': n_total_clues,
        'has_district': int(has_district),
        'has_postcode': int(has_postcode),
        'has_address': int(has_address),
        'reasoning_length': reasoning_length,
        
        # Address quality
        'address_length': address_length,
        'address_has_number': int(address_has_number),
        'address_has_business': int(address_has_business),
        'address_n_business': address_n_business,
        'signs_total_business': signs_total_business,
        
        # Geocoding
        'geo_success': int(geo_success),
        'geo_lat': geo_lat,
        'geo_lng': geo_lng,
        'distance_to_center_km': round(distance_to_center, 3) if distance_to_center is not None else None,
        'distance_to_district_km': round(distance_to_district, 3) if distance_to_district is not None else None,
        'district_geocodes': int(district_geocodes),
        'city_coherent': int(city_coherent),
        
        # Ground truth
        'error_km': round(error_km, 4) if error_km is not None else None,
        'error_class': error_class,
        
        # Raw text (pour analyse qualitative)
        'best_address_guess': best_address,
        'address_alternatives': '|'.join(address_alternatives) if isinstance(address_alternatives, list) else str(address_alternatives),
        'n_alternatives': len(address_alternatives) if isinstance(address_alternatives, list) else 0,
        'district': district,
        'street_signs': '|'.join(street_signs),
        'shop_signs': '|'.join(shop_signs),
        'landmarks': '|'.join(landmarks),
    }


# ─── Main harvest loop ─────────────────────────────────────────────────────

def harvest(invaders, output_file, anthropic_key=None, verbose=False):
    """
    Fait tourner Vision sur chaque invader et sauve les features en CSV.
    Supporte la reprise (skip les IDs déjà dans le CSV).
    """
    # Charger les IDs déjà traités
    already_done = set()
    if os.path.exists(output_file):
        with open(output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                already_done.add(row['invader_id'])
        print(f"📂 {len(already_done)} invaders déjà traités dans {output_file}")
    
    # Filtrer
    todo = [inv for inv in invaders 
            if inv.get('id', inv.get('name', '')).upper().replace('-', '_') not in already_done]
    
    if not todo:
        print("✅ Tous les invaders sont déjà traités!")
        return
    
    print(f"🚀 {len(todo)} invaders à traiter")
    
    # Init Vision (1 shot pour le harvest)
    vision = VisionAnalyzer(api_key=anthropic_key, verbose=verbose, n_shots=1)
    if not vision.enabled:
        print("❌ Vision non activé. Utilisez --anthropic-key ou ANTHROPIC_API_KEY")
        return
    
    ocr = ImageOCRAnalyzer(verbose=False)
    
    # Préparer le CSV
    fieldnames = [
        'invader_id', 'city_code', 'points', 'gt_lat', 'gt_lng', 'gt_source',
        'confidence', 'n_street_signs', 'n_shop_signs', 'n_landmarks',
        'n_building_numbers', 'n_metro_bus', 'n_other_clues', 'n_total_clues',
        'has_district', 'has_postcode', 'has_address', 'reasoning_length',
        'address_length', 'address_has_number', 'address_has_business',
        'address_n_business', 'signs_total_business',
        'geo_success', 'geo_lat', 'geo_lng',
        'distance_to_center_km', 'distance_to_district_km',
        'district_geocodes', 'city_coherent',
        'error_km', 'error_class',
        'best_address_guess', 'address_alternatives', 'n_alternatives', 'district', 'street_signs', 'shop_signs', 'landmarks',
    ]
    
    write_header = not os.path.exists(output_file) or os.path.getsize(output_file) == 0
    
    # Harvest loop
    n_done = 0
    n_errors = 0
    t_start = time.time()
    
    with open(output_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        if write_header:
            writer.writeheader()
        
        for i, inv in enumerate(todo):
            inv_id = inv.get('id', inv.get('name', '?')).upper().replace('-', '_')
            city = inv.get('city', '')
            city_name = CITY_CENTERS.get(city, {}).get('name', city)
            image_lieu = inv.get('image_lieu', '')
            image_close = inv.get('image_close', inv.get('image_invader', ''))
            
            elapsed = time.time() - t_start
            rate = (n_done / elapsed * 60) if elapsed > 0 and n_done > 0 else 0
            eta = ((len(todo) - i) / rate) if rate > 0 else 0
            
            print(f"\n[{i+1}/{len(todo)}] {inv_id} ({city}) — {rate:.1f}/min, ETA {eta:.0f}min")
            
            try:
                # 1. Appel Vision (1 shot via analyze, mais on veut juste les clues)
                #    On utilise _call_vision directement pour plus de contrôle
                images = []
                
                b64_lieu, mt_lieu = vision._download_image_base64(image_lieu)
                if b64_lieu:
                    images.append((b64_lieu, mt_lieu, "Vue large"))
                
                if image_close and image_close != image_lieu:
                    b64_close, mt_close = vision._download_image_base64(image_close)
                    if b64_close:
                        images.append((b64_close, mt_close, "Gros plan"))
                
                if not images:
                    print(f"  ⚠️ Pas d'images téléchargées, skip")
                    n_errors += 1
                    continue
                
                # Appel Vision 1 shot
                clues = vision._call_vision(images, city_code=city, city_name=city_name)
                
                if not clues:
                    print(f"  ⚠️ Vision: pas de réponse exploitable")
                    # Sauver quand même avec clues=None
                    features = extract_features(inv, None, None, city)
                    writer.writerow(features)
                    f.flush()
                    n_done += 1
                    n_errors += 1
                    time.sleep(2)
                    continue
                
                conf = (clues.get('confidence') or '?').upper()
                addr = (clues.get('best_address_guess') or '?')[:50]
                print(f"  🧠 Vision: conf={conf}, addr=\"{addr}\"")
                
                # 2. Géocoder l'adresse (avec variantes et nettoyage amélioré)
                geocode_result = None
                intersection_hints = []  # Pour stocker les infos d'intersection
                best_addr = clues.get('best_address_guess', '')
                
                if best_addr:
                    # Découper les variantes "ou" / "or"
                    try:
                        raw_variants = vision._split_address_variants(best_addr)
                    except Exception:
                        raw_variants = [best_addr]
                    
                    for variant in raw_variants[:3]:  # Max 3 variantes
                        # Nettoyer l'adresse (utilise le nettoyage amélioré)
                        cleaned, hint = vision._clean_address_for_geocoding(variant, city_name)
                        addr_to_try = cleaned or variant
                        
                        # Capturer les hints d'intersection
                        if hint and 'intersection:' in hint:
                            intersection_hints.append(hint)
                        
                        # Retirer les "11e ou 20e arrondissement" résiduels
                        addr_to_try = re.sub(r'\d+e\s+ou\s+\d+e\s+arrondissement', '', addr_to_try).strip().rstrip(',').strip()
                        
                        if city_name and city_name.lower() not in addr_to_try.lower():
                            addr_to_try = f"{addr_to_try}, {city_name}"
                        
                        geocode_result = ocr.geocode_address(addr_to_try, city_code=city)
                        time.sleep(1)  # Rate limit Nominatim
                        
                        if geocode_result:
                            print(f"  📍 Géocodé: {geocode_result['lat']:.5f}, {geocode_result['lng']:.5f} ({addr_to_try[:50]})")
                            break
                    
                    if not geocode_result:
                        # Fallback 1: Essayer l'adresse brute nettoyée sans ville (parfois le doublon gêne)
                        cleaned_bare, _ = vision._clean_address_for_geocoding(best_addr, city_name)
                        if cleaned_bare and cleaned_bare != best_addr:
                            geocode_result = ocr.geocode_address(cleaned_bare, city_code=city)
                            time.sleep(1)
                            if geocode_result:
                                print(f"  📍 Cleaned: {geocode_result['lat']:.5f}, {geocode_result['lng']:.5f} ({cleaned_bare[:50]})")
                    
                    if not geocode_result:
                        # Fallback 2: Essayer juste le district
                        district_name = clues.get('district', '')
                        if district_name and city_name:
                            fallback_q = f"{district_name}, {city_name}"
                            geocode_result = ocr.geocode_address(fallback_q, city_code=city)
                            time.sleep(1)
                            if geocode_result:
                                print(f"  📍 Fallback district: {geocode_result['lat']:.5f}, {geocode_result['lng']:.5f} ({fallback_q})")
                            else:
                                print(f"  ❌ Nominatim: rien pour \"{best_addr[:60]}\" ni district")
                
                # 3. Extraire les features
                features = extract_features(inv, clues, geocode_result, city)
                
                if features['error_km'] is not None:
                    err = features['error_km']
                    cls = features['error_class']
                    icon = {'EXCELLENT': '🎯', 'GOOD': '✅', 'OK': '🟡', 
                            'APPROX': '🟠', 'ZONE': '🔶', 'FAR': '❌'}.get(cls, '?')
                    print(f"  {icon} Erreur: {err:.2f} km ({cls})")
                
                # 4. Écrire
                writer.writerow(features)
                f.flush()
                n_done += 1
                
                # Rate limiting
                time.sleep(2)
                
            except KeyboardInterrupt:
                print(f"\n\n⏸️  Interrompu après {n_done} invaders. Reprendre avec --resume.")
                break
            except Exception as e:
                print(f"  💥 Erreur: {e}")
                n_errors += 1
                time.sleep(3)
    
    # Résumé
    elapsed = time.time() - t_start
    print(f"\n{'=' * 60}")
    print(f"✅ Harvest terminé: {n_done} traités, {n_errors} erreurs")
    print(f"   Durée: {elapsed/60:.1f} min ({elapsed/max(n_done,1):.1f}s/invader)")
    print(f"   Fichier: {output_file}")
    
    # Stats rapides du CSV
    print_csv_stats(output_file)


def print_csv_stats(csv_file):
    """Affiche les stats du CSV de features."""
    if not os.path.exists(csv_file):
        return
    
    rows = []
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    
    if not rows:
        return
    
    print(f"\n📊 Stats du dataset ({len(rows)} samples):")
    
    # Distribution des classes
    classes = {}
    errors = []
    for row in rows:
        cls = row.get('error_class', 'NO_GEO')
        classes[cls] = classes.get(cls, 0) + 1
        if row.get('error_km') and row['error_km'] != '':
            errors.append(float(row['error_km']))
    
    print(f"   Classes:")
    for cls in ['EXCELLENT', 'GOOD', 'OK', 'APPROX', 'ZONE', 'FAR', 'NO_GEO']:
        count = classes.get(cls, 0)
        if count > 0:
            pct = count / len(rows) * 100
            print(f"     {cls:12s}: {count:4d} ({pct:.0f}%)")
    
    if errors:
        import statistics
        print(f"   Erreur moyenne: {statistics.mean(errors):.2f} km")
        print(f"   Erreur médiane: {statistics.median(errors):.2f} km")
    
    # Distribution par ville
    cities = {}
    for row in rows:
        city = row.get('city_code', '?')
        cities[city] = cities.get(city, 0) + 1
    print(f"   Villes: {len(cities)}")
    
    # Taux de géocodage
    geo_success = sum(1 for r in rows if r.get('geo_success') == '1')
    print(f"   Géocodage réussi: {geo_success}/{len(rows)} ({geo_success/len(rows)*100:.0f}%)")
    
    # Features les plus informatives (preview)
    print(f"\n   📋 Aperçu features clés:")
    for feat in ['n_street_signs', 'address_has_business', 'distance_to_district_km']:
        vals_good = [float(r[feat]) for r in rows 
                     if r.get('error_class') in ('EXCELLENT', 'GOOD', 'OK') and r.get(feat, '') != '']
        vals_bad = [float(r[feat]) for r in rows 
                    if r.get('error_class') in ('ZONE', 'FAR') and r.get(feat, '') != '']
        if vals_good and vals_bad:
            import statistics
            print(f"     {feat}: good={statistics.mean(vals_good):.2f}, bad={statistics.mean(vals_bad):.2f}")


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Vision ML Feature Harvester — collecte des features pour entraîner un modèle de fiabilité',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  python vision_ml_harvest.py --n 50 --output features_test.csv
  python vision_ml_harvest.py --n 200 --output features.csv
  python vision_ml_harvest.py --cities PA,LDN,NY --n 100 --output features_3cities.csv
  python vision_ml_harvest.py --resume features.csv   # reprendre après interruption
  python vision_ml_harvest.py --stats features.csv    # afficher les stats
        """
    )
    
    parser.add_argument('--n', type=int, default=200,
                        help='Nombre d\'invaders à traiter (default: 200)')
    parser.add_argument('--output', '-o', type=str, default='vision_ml_features.csv',
                        help='Fichier CSV de sortie (default: vision_ml_features.csv)')
    parser.add_argument('--cities', type=str, default=None,
                        help='Filtrer par villes (ex: PA,LDN,NY)')
    parser.add_argument('--master', type=str, default=None,
                        help=f'Chemin du master JSON (default: {MASTER_FILE})')
    parser.add_argument('--anthropic-key', type=str, default=None,
                        help='Clé API Anthropic (ou env ANTHROPIC_API_KEY)')
    parser.add_argument('--resume', type=str, default=None,
                        help='Reprendre un harvest interrompu (chemin du CSV)')
    parser.add_argument('--stats', type=str, default=None,
                        help='Afficher les stats d\'un CSV existant et quitter')
    parser.add_argument('--seed', type=int, default=42,
                        help='Seed pour la sélection aléatoire (default: 42)')
    parser.add_argument('--recent', action='store_true',
                        help='Ne garder que les invaders actifs (exclut destroyed/removed)')
    parser.add_argument('--min-points', type=int, default=None,
                        help='Points minimum (proxy de fraîcheur, ex: 10)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Afficher les détails Vision')
    
    args = parser.parse_args()
    
    # Mode stats only
    if args.stats:
        print_csv_stats(args.stats)
        return
    
    # Mode resume
    if args.resume:
        args.output = args.resume
    
    # Charger le master
    master_path = None
    if args.master:
        master_path = Path(args.master)
    else:
        for p in MASTER_FALLBACKS:
            if p.exists():
                master_path = p
                break
    
    if not master_path or not master_path.exists():
        print(f"❌ Master non trouvé. Essayez --master <chemin>")
        print(f"   Cherché dans: {[str(p) for p in MASTER_FALLBACKS]}")
        sys.exit(1)
    
    print(f"📂 Chargement: {master_path.name}...")
    with open(str(master_path), 'r', encoding='utf-8') as f:
        master_db = json.load(f)
    print(f"   {len(master_db)} invaders dans le master")
    
    # Sélection
    cities_filter = args.cities.split(',') if args.cities else None
    selected = select_invaders(
        master_db, n=args.n, cities=cities_filter, seed=args.seed,
        recent_only=args.recent, min_points=args.min_points
    )
    
    # API key
    api_key = args.anthropic_key or os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("❌ Clé API Anthropic requise (--anthropic-key ou ANTHROPIC_API_KEY)")
        sys.exit(1)
    
    # Lancer le harvest
    harvest(selected, args.output, anthropic_key=api_key, verbose=args.verbose)


if __name__ == '__main__':
    main()
