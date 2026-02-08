#!/usr/bin/env python3
"""
🔄 Total Invaders Search - Script de mise à jour v4 (Enhanced Scraping)

Basé sur update_invaders_v3.py avec extraction enrichie des informations.

Améliorations v4:
- Extraction de la date de pose (landing_date) depuis "Landed on : DD/MM/YYYY"
- Extraction de la date/source du statut depuis "Date and source : Month YYYY (source)"
- Conservation de l'historique des statuts (previous_status, previous_status_date)
- Parsing amélioré basé sur la structure textuelle du site

Installation:
    pip install playwright
    playwright install chromium

Usage:
    python update_invaders_v4.py [options]
    
Options:
    --city PA           Scraper une seule ville
    --cities PA,LY,MARS Scraper plusieurs villes (séparées par des virgules)
    --headless          Mode sans interface (défaut)
    --visible           Mode avec navigateur visible (recommandé pour --geolocate)
    --verbose           Afficher plus de détails
    --merge-only        Refaire la fusion sans re-scraper
    --apply-reports     Appliquer les signalements communautaires
    --backup            Créer un backup avant modification
    --dry-run           Simuler sans sauvegarder
    --geolocate         Rechercher les coordonnées des invaders manquants via web
    --add-missing       Ajouter les invaders manquants au JSON
    --discover-new      Découvrir et scraper les nouvelles villes depuis invader-spotter.art
    --geolocate-missing Géolocaliser les invaders depuis invaders_missing_from_github.json
                        Recherche sur AroundUs et IlluminateArt avec test de cohérence
    --missing-file F    Fichier JSON source pour --geolocate-missing (défaut: invaders_missing_from_github.json)
    --merge-geolocated F Fusionner un fichier d'invaders géolocalisés avec invaders_updated.json
    --limit N           Nombre max d'invaders à traiter (pour --geolocate-missing)
    --addresses-file F  Fichier CSV/RTF avec adresses manuelles (prioritaire)
    --max-retries N     Nombre max de tentatives par ville (défaut: 3)
    --pause N           Pause entre villes en ms (défaut: 1000)
    --existing FILE     Charger un JSON existant pour comparer les statuts (historique)

Fichiers générés:
    - invaders_updated.json             → Base fusionnée prête à l'emploi  
    - invaders_scraped_statuses.json    → Données brutes du scraping
    - invaders_report.txt               → Rapport des changements
    - invaders_missing_from_github.json → Invaders sur Spotter mais pas dans GitHub
    - invaders_missing_from_github.txt  → Version lisible des manquants
    - invaders_geolocated.json          → Invaders géolocalisés (si --geolocate)
    - invaders_geolocated.txt           → Version lisible avec liens Google Maps
    - invaders_geoloc_audit.json        → Audit détaillé de géolocalisation
    - invaders_geoloc_audit.txt         → Rapport d'audit lisible
    - invaders_geolocated_missing.json  → Invaders manquants géolocalisés (si --geolocate-missing)
    - invaders_geolocated_missing.txt   → Rapport avec liens Google Maps

Mode --geolocate-missing:
    Recherche les coordonnées GPS des invaders manquants via:
    1. Adresses manuelles (--addresses-file) → confiance HIGH
    2. AroundUs + IlluminateArt cohérents (<200m) → confiance HIGH
    3. AroundUs ou IlluminateArt différents (>200m) → Illuminate prioritaire, confiance MEDIUM
    4. Une seule source → confiance MEDIUM
    5. Centre-ville (fallback) → confiance LOW, location_unknown=true

Nouveaux champs extraits (v4):
    - landing_date      : Date de pose (format DD/MM/YYYY) depuis "Landed on"
    - status_date       : Date du dernier statut (format "Month YYYY")
    - status_source     : Source du statut (report, FlashInvaders, etc.)
    - previous_status   : Statut précédent (si changement détecté)
    - previous_status_date : Date du statut précédent

Exemple de structure JSON enrichie:
    {
        "id": "WN_01",
        "lat": 48.2082,
        "lng": 16.3738,
        "points": 20,
        "status": "OK",
        "city": "WN",
        "landing_date": "06/06/2006",
        "status_date": "December 2025",
        "status_source": "report",
        "previous_status": "damaged",
        "previous_status_date": "July 2022",
        "image_invader": "https://...",
        "image_lieu": "https://..."
    }

Format du fichier d'adresses manuelles (CSV):
    code,URL,adresse
    PA_1529,https://...,10 Rue de Moussy, 75004 Paris
    LDN_163,https://...,37 Brewer St, London W1F 0RY
    
    Les invaders SANS adresse seront placés au centre de leur ville avec:
    - location_unknown: true
    - geo_confidence: very_low
    - geo_source: city_center

Sources de géolocalisation (dans l'ordre de priorité):
    1. Adresses manuelles (--addresses-file) → confiance HIGH
    2. atlas-streetart.com      - Site spécialisé street art
    3. Google + Nominatim       - Recherche d'adresses + géocodage OSM
    4. FlashInvaders/blogs      - Recherche de coordonnées directes
    5. Arrondissement (Paris)   - Approximation par quartier
    6. streetartcities.com      - Base de données street art mondiale
    7. flickr.com               - Photos avec métadonnées GPS
    8. illuminateartofficial.com - Site spécialisé invaders
    9. Centre ville (fallback)  - Si aucune autre source → location_unknown=true

Exemple d'utilisation:
    # Scraper + ajouter les invaders manquants avec adresses manuelles
    python update_invaders_v4.py --verbose --add-missing \\
        --addresses-file adresses_manuelles.csv
    
    # Mode merge uniquement (sans re-scraper)
    python update_invaders_v4.py --merge-only --add-missing \\
        --addresses-file adresses_manuelles.csv --verbose
    
    # Géolocaliser les invaders manquants (AroundUs + IlluminateArt)
    python update_invaders_v4.py --geolocate-missing --visible --verbose
    
    # Géolocaliser une ville spécifique avec limite
    python update_invaders_v4.py --geolocate-missing --city ORLN --limit 10 --visible
    
    # Fusionner les résultats géolocalisés avec la base
    python update_invaders_v4.py --merge-geolocated invaders_geolocated_missing.json --backup
"""

import json
import re
import sys
import os
import time
import math
import asyncio
from datetime import datetime
from collections import defaultdict
from urllib.request import urlopen, Request
from urllib.parse import quote, unquote
from pathlib import Path

# ============================================================================
# CHEMINS DU REPO
# ============================================================================
SCRIPT_DIR = Path(__file__).parent.resolve()
REPO_DIR = SCRIPT_DIR.parent
DATA_DIR = REPO_DIR / "data"

# Fichiers principaux du repo
MASTER_FILE = DATA_DIR / "invaders_master.json"
CHANGELOG_FILE = DATA_DIR / "invaders_changelog.json"
METADATA_FILE = DATA_DIR / "metadata.json"

# Fichiers de travail (générés dans data/)
SCRAPED_FILE = DATA_DIR / "invaders_scraped_statuses.json"
MISSING_FILE = DATA_DIR / "invaders_missing_from_github.json"
MISSING_TXT = DATA_DIR / "invaders_missing_from_github.txt"
REPORT_FILE = DATA_DIR / "invaders_report.txt"
GEOLOCATED_FILE = DATA_DIR / "invaders_geolocated.json"
GEOLOCATED_TXT = DATA_DIR / "invaders_geolocated.txt"
GEOLOC_AUDIT_JSON = DATA_DIR / "invaders_geoloc_audit.json"
GEOLOC_AUDIT_TXT = DATA_DIR / "invaders_geoloc_audit.txt"
GEOLOCATED_MISSING_FILE = DATA_DIR / "invaders_geolocated_missing.json"

def _p(path):
    """Convertit un Path en string pour les fonctions qui attendent str."""
    return str(path)

# Configuration
GITHUB_DB_URL = "https://raw.githubusercontent.com/goguelnikov/SpaceInvaders/main/world_space_invaders_V05.json"
INVADER_SPOTTER_BASE = "https://www.invader-spotter.art"

# Centres des villes (pour fallback si aucune géolocalisation trouvée)
CITY_CENTERS = {
    'PA': {'lat': 48.8566, 'lng': 2.3522, 'name': 'Paris'},
    'LY': {'lat': 45.7640, 'lng': 4.8357, 'name': 'Lyon'},
    'MARS': {'lat': 43.2965, 'lng': 5.3698, 'name': 'Marseille'},
    'LDN': {'lat': 51.5074, 'lng': -0.1278, 'name': 'London'},
    'NY': {'lat': 40.7128, 'lng': -74.0060, 'name': 'New York'},
    'LA': {'lat': 34.0522, 'lng': -118.2437, 'name': 'Los Angeles'},
    'TK': {'lat': 35.6762, 'lng': 139.6503, 'name': 'Tokyo'},
    'ROM': {'lat': 41.9028, 'lng': 12.4964, 'name': 'Rome'},
    'BCN': {'lat': 41.3851, 'lng': 2.1734, 'name': 'Barcelona'},
    'BKK': {'lat': 13.7563, 'lng': 100.5018, 'name': 'Bangkok'},
    'HK': {'lat': 22.3193, 'lng': 114.1694, 'name': 'Hong Kong'},
    'MIA': {'lat': 25.7617, 'lng': -80.1918, 'name': 'Miami'},
    'SD': {'lat': 32.7157, 'lng': -117.1611, 'name': 'San Diego'},
    'RAV': {'lat': 44.4184, 'lng': 12.2035, 'name': 'Ravenna'},
    'BIL': {'lat': 43.2630, 'lng': -2.9350, 'name': 'Bilbao'},
    'AMS': {'lat': 52.3676, 'lng': 4.9041, 'name': 'Amsterdam'},
    'TLS': {'lat': 43.6047, 'lng': 1.4442, 'name': 'Toulouse'},
    'BDX': {'lat': 44.8378, 'lng': -0.5792, 'name': 'Bordeaux'},
    'NTE': {'lat': 47.2184, 'lng': -1.5536, 'name': 'Nantes'},
    'NA': {'lat': 47.2184, 'lng': -1.5536, 'name': 'Nantes'},
    'LIL': {'lat': 50.6292, 'lng': 3.0573, 'name': 'Lille'},
    'LILE': {'lat': 50.6292, 'lng': 3.0573, 'name': 'Lille'},
    'STR': {'lat': 48.5734, 'lng': 7.7521, 'name': 'Strasbourg'},
    'MTP': {'lat': 43.6108, 'lng': 3.8767, 'name': 'Montpellier'},
    'MPL': {'lat': 43.6108, 'lng': 3.8767, 'name': 'Montpellier'},
    'NICE': {'lat': 43.7102, 'lng': 7.2620, 'name': 'Nice'},
    'REIM': {'lat': 49.2583, 'lng': 4.0317, 'name': 'Reims'},
    'VER': {'lat': 48.8014, 'lng': 2.1301, 'name': 'Versailles'},
    'VRS': {'lat': 48.8014, 'lng': 2.1301, 'name': 'Versailles'},
    'AMI': {'lat': 49.8941, 'lng': 2.2958, 'name': 'Amiens'},
    'ORLN': {'lat': 47.9029, 'lng': 1.9039, 'name': 'Orléans'},
    'DIJ': {'lat': 47.3220, 'lng': 5.0415, 'name': 'Dijon'},
    'GRN': {'lat': 45.1885, 'lng': 5.7245, 'name': 'Grenoble'},
    'AIX': {'lat': 43.5297, 'lng': 5.4474, 'name': 'Aix-en-Provence'},
    'AVI': {'lat': 43.9493, 'lng': 4.8055, 'name': 'Avignon'},
    'NIM': {'lat': 43.8367, 'lng': 4.3601, 'name': 'Nîmes'},
    'CLR': {'lat': 45.7772, 'lng': 3.0870, 'name': 'Clermont-Ferrand'},
    'RN': {'lat': 48.1173, 'lng': -1.6778, 'name': 'Rennes'},
    'BRL': {'lat': 52.5200, 'lng': 13.4050, 'name': 'Berlin'},
    'MUN': {'lat': 48.1351, 'lng': 11.5820, 'name': 'Munich'},
    'KLN': {'lat': 50.9375, 'lng': 6.9603, 'name': 'Cologne'},
    'WN': {'lat': 48.2082, 'lng': 16.3738, 'name': 'Vienna'},
    'BXL': {'lat': 50.8503, 'lng': 4.3517, 'name': 'Brussels'},
    'BSL': {'lat': 47.5596, 'lng': 7.5886, 'name': 'Basel'},
    'GNV': {'lat': 46.2044, 'lng': 6.1432, 'name': 'Geneva'},
    'LSN': {'lat': 46.5197, 'lng': 6.6323, 'name': 'Lausanne'},
    'RTD': {'lat': 51.9244, 'lng': 4.4777, 'name': 'Rotterdam'},
    'PRT': {'lat': 41.1579, 'lng': -8.6291, 'name': 'Porto'},
    'FAO': {'lat': 37.0194, 'lng': -7.9322, 'name': 'Faro'},
    'BRC': {'lat': 41.3874, 'lng': 2.1686, 'name': 'Barcelona'},
    'MLGA': {'lat': 36.7213, 'lng': -4.4214, 'name': 'Malaga'},
    'BBO': {'lat': 43.2630, 'lng': -2.9350, 'name': 'Bilbao'},
    'MAN': {'lat': 53.4808, 'lng': -2.2426, 'name': 'Manchester'},
    'NCL': {'lat': 54.9783, 'lng': -1.6178, 'name': 'Newcastle'},
    'IST': {'lat': 41.0082, 'lng': 28.9784, 'name': 'Istanbul'},
    'RAV': {'lat': 44.4184, 'lng': 12.2035, 'name': 'Ravenna'},
    'VRN': {'lat': 45.4384, 'lng': 10.9916, 'name': 'Verona'},
}

# Mapping des codes ville
CITY_CODES = {
    "SPACE": "SPACE",
    "BRL": "BRL", "FKF": "FKF", "KLN": "KLN", "MUN": "MUN",
    "MLB": "MLB", "PRT": "PRT", "WN": "WN", "DHK": "DHK",
    "ANVR": "ANVR", "BXL": "BXL", "CHAR": "CHAR", "RDU": "RDU",
    "BT": "BT", "POTI": "POTI", "GRU": "GRU", "SP": "SP", "HK": "HK",
    "DJN": "DJN", "SL": "SL",
    "BRC": "BRC", "BBO": "BBO", "MLGA": "MLGA", "MEN": "MEN",
    "LA": "LA", "MIA": "MIA", "NY": "NY", "SD": "SD",
    "AIX": "AIX", "AMI": "AMI", "AVI": "AVI", "BTA": "BTA", "BAB": "BAB",
    "CAPF": "CAPF", "CLR": "CLR", "CON": "CON", "CAZ": "CAZ", "DIJ": "DIJ",
    "FTBL": "FTBL", "FRQ": "FRQ", "GRN": "GRN", "LCT": "LCT", "REUN": "REUN",
    "LIL": "LIL", "LBR": "LBR", "LY": "LY", "MARS": "MARS", "MTB": "MTB",
    "MPL": "MPL", "NA": "NA", "NIM": "NIM", "ORLN": "ORLN", "PA": "PA",
    "PAU": "PAU", "PRP": "PRP", "RN": "RN", "TLS": "TLS", "VLMO": "VLMO",
    "VRS": "VRS",
    "LDN": "LDN", "MAN": "MAN", "NCL": "NCL",
    "VRN": "VRN", "ELT": "ELT",
    "RA": "RA", "ROM": "ROM", "TK": "TK", "MBSA": "MBSA",
    "MRAK": "MRAK", "RBA": "RBA", "CCU": "CCU", "KAT": "KAT",
    "AMS": "AMS", "NOO": "NOO", "RTD": "RTD", "FAO": "FAO", "LJU": "LJU",
    "HALM": "HALM", "VSB": "VSB",
    "ANZR": "ANZR", "BSL": "BSL", "BRN": "BRN", "GNV": "GNV", "LSN": "LSN",
    "GRTI": "GRTI", "BGK": "BGK", "DJBA": "DJBA", "IST": "IST",
}

CITY_NAMES = {
    # France
    "PA": "Paris", "LY": "Lyon", "MARS": "Marseille", "TLS": "Toulouse",
    "AIX": "Aix-en-Provence", "AMI": "Amiens", "AVI": "Avignon", "BTA": "Bastia",
    "BAB": "Biarritz", "CLR": "Clermont-Ferrand", "CON": "Cannes", "DIJ": "Dijon",
    "GRN": "Grenoble", "LIL": "Lille", "LBR": "Le Bras", "MTP": "Montpellier",
    "MPL": "Montpellier", "NA": "Nantes", "NIM": "Nîmes", "ORLN": "Orléans",
    "PAU": "Pau", "RN": "Rennes", "VRS": "Versailles", "REUN": "Réunion",
    # Belgique
    "BXL": "Bruxelles", "ANVR": "Anvers", "CHAR": "Charleroi",
    # UK
    "LDN": "Londres", "MAN": "Manchester", "NCL": "Newcastle",
    # Allemagne
    "BRL": "Berlin", "KLN": "Cologne", "MUN": "Munich", "FKF": "Francfort",
    # USA
    "NY": "New York", "LA": "Los Angeles", "MIA": "Miami", "SD": "San Diego",
    # Asie
    "TK": "Tokyo", "HK": "Hong Kong", "BGK": "Bangkok",
    # Autres
    "ROM": "Rome", "BRC": "Barcelone", "AMS": "Amsterdam", "WN": "Vienne",
    "LJU": "Ljubljana", "IST": "Istanbul", "RAV": "Ravenne",
}


def fetch_url(url, timeout=30, retries=3):
    """Télécharge une URL avec retry"""
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout) as response:
                content = response.read()
                for enc in ['utf-8-sig', 'utf-8', 'latin-1']:
                    try:
                        return content.decode(enc)
                    except:
                        continue
        except Exception as e:
            print(f"   ⚠️ Tentative {attempt + 1}/{retries}: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


def load_github_database():
    """Charge la base depuis GitHub"""
    print("📥 Téléchargement de la base GitHub goguelnikov...")
    data = fetch_url(GITHUB_DB_URL)
    if data:
        try:
            invaders = json.loads(data)
            print(f"✅ {len(invaders)} invaders chargés")
            return invaders
        except json.JSONDecodeError as e:
            print(f"❌ Erreur JSON: {e}")
    return None


def load_master_file():
    """Charge la base depuis le fichier master local du repo."""
    if not MASTER_FILE.exists():
        print(f"❌ Fichier master introuvable: {MASTER_FILE}")
        print(f"   Fallback vers GitHub...")
        return load_github_database()
    
    print(f"📂 Chargement du master local: {MASTER_FILE}")
    with open(MASTER_FILE, 'r', encoding='utf-8') as f:
        invaders = json.load(f)
    print(f"✅ {len(invaders)} invaders chargés depuis le master")
    return invaders


def get_cities_from_github(github_db):
    """Extrait les villes depuis la base GitHub"""
    cities = defaultdict(int)
    for inv in github_db:
        name = inv.get('id', inv.get('name', ''))
        match = re.match(r'^([A-Z]+)[-_]', name)
        if match:
            cities[match.group(1)] += 1
    return dict(cities)


def load_community_reports(filepath="community_reports.json"):
    """Charge les signalements communautaires"""
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []


def load_manual_addresses(filepath):
    """Charge le fichier d'adresses manuelles (CSV ou RTF)"""
    if not os.path.exists(filepath):
        print(f"❌ Fichier non trouvé: {filepath}")
        return {}
    
    addresses = {}
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Nettoyer le contenu RTF si nécessaire
        if content.startswith('{\\rtf'):
            # Supprimer les headers RTF
            # Trouver le début du contenu réel (après les définitions de police, couleur, etc.)
            import re
            
            # Supprimer les groupes RTF de définition
            content = re.sub(r'\{\\fonttbl[^}]*\}', '', content)
            content = re.sub(r'\{\\colortbl[^}]*\}', '', content)
            content = re.sub(r'\{\\\*\\expandedcolortbl[^}]*\}', '', content)
            
            # Supprimer les commandes RTF
            content = re.sub(r'\\rtf1[^\\]*', '', content)
            content = re.sub(r'\\ansi[^\\s]*', '', content)
            content = re.sub(r'\\cocoartf\d+', '', content)
            content = re.sub(r'\\cocoatextscaling\d+', '', content)
            content = re.sub(r'\\cocoaplatform\d+', '', content)
            content = re.sub(r'\\paperw\d+', '', content)
            content = re.sub(r'\\paperh\d+', '', content)
            content = re.sub(r'\\margl\d+', '', content)
            content = re.sub(r'\\margr\d+', '', content)
            content = re.sub(r'\\vieww\d+', '', content)
            content = re.sub(r'\\viewh\d+', '', content)
            content = re.sub(r'\\viewkind\d+', '', content)
            content = re.sub(r'\\pard[^\\]*', '', content)
            content = re.sub(r'\\tx\d+', '', content)
            content = re.sub(r'\\pardirnatural', '', content)
            content = re.sub(r'\\partightenfactor\d+', '', content)
            content = re.sub(r'\\f\d+', '', content)
            content = re.sub(r'\\fs\d+', '', content)
            content = re.sub(r'\\cf\d+', '', content)
            
            # Remplacer les retours à la ligne RTF
            content = content.replace('\\\n', '\n')
            content = content.replace('\\', '')
            
            # Supprimer les accolades restantes
            content = content.replace('{', '').replace('}', '')
            
            # Nettoyer les espaces multiples
            content = re.sub(r' +', ' ', content)
            content = re.sub(r'\n+', '\n', content)
        
        # Parser ligne par ligne
        lines = content.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            
            # Skip header ou lignes vides
            if line.startswith('code,') or not line or len(line) < 5:
                continue
            
            # Parser la ligne CSV (avec gestion des guillemets)
            parts = []
            current = ''
            in_quotes = False
            
            for char in line:
                if char == '"':
                    in_quotes = not in_quotes
                elif char == ',' and not in_quotes:
                    parts.append(current.strip())
                    current = ''
                else:
                    current += char
            parts.append(current.strip())
            
            if len(parts) >= 3:
                code = parts[0].strip().upper().replace('-', '_')
                url = parts[1].strip()
                address = parts[2].strip().strip('"')
                
                # Nettoyer l'adresse des artefacts RTF résiduels
                address = re.sub(r'^[\s\d]*\s*', '', address) if address.startswith(' ') else address
                
                if code and re.match(r'^[A-Z]+_\d+$', code):
                    addresses[code] = {
                        'address': address,
                        'image_url': url
                    }
        
        print(f"📋 {len(addresses)} adresses manuelles chargées")
        return addresses
        
    except Exception as e:
        print(f"❌ Erreur lecture fichier adresses: {e}")
        import traceback
        traceback.print_exc()
        return {}


def standardize_address(address, city_code, verbose=False):
    """
    Standardise et complète une adresse pour améliorer le géocodage.
    
    Opérations:
    - Expansion des abréviations (Bd → Boulevard, Gal → Galerie, etc.)
    - Suppression des mentions de pays
    - Ajout de la ville si manquante
    - Nettoyage des caractères spéciaux
    - Normalisation du format
    """
    
    if not address:
        return None, "Adresse vide"
    
    original = address
    changes = []
    
    # Mapping code ville → infos
    city_info = {
        'PA': {'name': 'Paris', 'country': 'France', 'patterns': [r'75\d{3}', r'paris']},
        'LY': {'name': 'Lyon', 'country': 'France', 'patterns': [r'69\d{3}', r'lyon']},
        'MARS': {'name': 'Marseille', 'country': 'France', 'patterns': [r'13\d{3}', r'marseille']},
        'LDN': {'name': 'London', 'country': 'UK', 'patterns': [r'[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}', r'london']},
        'NY': {'name': 'New York', 'country': 'USA', 'patterns': [r'NY\s*\d{5}', r'new york', r'nyc', r'brooklyn', r'manhattan']},
        'LA': {'name': 'Los Angeles', 'country': 'USA', 'patterns': [r'CA\s*\d{5}', r'los angeles']},
        'TK': {'name': 'Tokyo', 'country': 'Japan', 'patterns': [r'tokyo']},
        'ROM': {'name': 'Rome', 'country': 'Italy', 'patterns': [r'roma', r'rome']},
        'BCN': {'name': 'Barcelona', 'country': 'Spain', 'patterns': [r'barcelona']},
        'BKK': {'name': 'Bangkok', 'country': 'Thailand', 'patterns': [r'bangkok']},
        'HK': {'name': 'Hong Kong', 'country': 'China', 'patterns': [r'hong kong']},
        'MIA': {'name': 'Miami', 'country': 'USA', 'patterns': [r'FL\s*\d{5}', r'miami']},
        'SD': {'name': 'San Diego', 'country': 'USA', 'patterns': [r'san diego']},
        'RAV': {'name': 'Ravenna', 'country': 'Italy', 'patterns': [r'ravenna']},
        'BIL': {'name': 'Bilbao', 'country': 'Spain', 'patterns': [r'bilbao']},
        'AMS': {'name': 'Amsterdam', 'country': 'Netherlands', 'patterns': [r'amsterdam']},
        'TLS': {'name': 'Toulouse', 'country': 'France', 'patterns': [r'31\d{3}', r'toulouse']},
        'BDX': {'name': 'Bordeaux', 'country': 'France', 'patterns': [r'33\d{3}', r'bordeaux']},
        'NTE': {'name': 'Nantes', 'country': 'France', 'patterns': [r'44\d{3}', r'nantes']},
        'LILE': {'name': 'Lille', 'country': 'France', 'patterns': [r'59\d{3}', r'lille']},
        'STR': {'name': 'Strasbourg', 'country': 'France', 'patterns': [r'67\d{3}', r'strasbourg']},
        'MTP': {'name': 'Montpellier', 'country': 'France', 'patterns': [r'34\d{3}', r'montpellier']},
        'NICE': {'name': 'Nice', 'country': 'France', 'patterns': [r'06\d{3}', r'nice']},
        'REIM': {'name': 'Reims', 'country': 'France', 'patterns': [r'51\d{3}', r'reims']},
        'VER': {'name': 'Versailles', 'country': 'France', 'patterns': [r'78\d{3}', r'versailles']},
    }
    
    city = city_info.get(city_code, {})
    city_name = city.get('name', '')
    country = city.get('country', '')
    
    # 1. Nettoyer les caractères spéciaux RTF résiduels
    # Convertir les codes hexadécimaux RTF en caractères
    rtf_chars = {
        "'e0": "à", "'e1": "á", "'e2": "â", "'e3": "ã", "'e4": "ä",
        "'e8": "è", "'e9": "é", "'ea": "ê", "'eb": "ë",
        "'ec": "ì", "'ed": "í", "'ee": "î", "'ef": "ï",
        "'f2": "ò", "'f3": "ó", "'f4": "ô", "'f5": "õ", "'f6": "ö",
        "'f9": "ù", "'fa": "ú", "'fb": "û", "'fc": "ü",
        "'e7": "ç", "'f1": "ñ",
        "'c0": "À", "'c1": "Á", "'c2": "Â", "'c3": "Ã", "'c4": "Ä",
        "'c8": "È", "'c9": "É", "'ca": "Ê", "'cb": "Ë",
        "'d4": "Ô", "'d9": "Ù",
    }
    for rtf_code, char in rtf_chars.items():
        if rtf_code in address:
            address = address.replace(rtf_code, char)
            changes.append(f"RTF {rtf_code} → {char}")
    
    # Nettoyer les codes RTF restants non reconnus
    address = re.sub(r"'[a-f0-9]{2}", "", address)
    address = address.replace("'", "'").replace("'", "'")
    
    # 2. Supprimer les mentions de pays (elles peuvent perturber Nominatim)
    countries_to_remove = [
        r',?\s*Royaume-Uni\s*$', r',?\s*United Kingdom\s*$', r',?\s*UK\s*$',
        r',?\s*France\s*$', r',?\s*Italia\s*$', r',?\s*Italy\s*$',
        r',?\s*España\s*$', r',?\s*Spain\s*$', r',?\s*USA\s*$',
        r',?\s*United States\s*$', r',?\s*England\s*$',
    ]
    for pattern in countries_to_remove:
        if re.search(pattern, address, re.IGNORECASE):
            address = re.sub(pattern, '', address, flags=re.IGNORECASE)
            changes.append("Pays supprimé")
    
    # 3. Expansion des abréviations françaises
    fr_abbreviations = [
        (r'\bBd\b\.?', 'Boulevard'),
        (r'\bBoul\b\.?', 'Boulevard'),
        (r'\bAv\b\.?', 'Avenue'),
        (r'\bGal\b\.?', 'Galerie'),
        (r'\bPl\b\.?', 'Place'),
        (r'\bR\b\.(?=\s)', 'Rue'),
        (r'\bSt\b\.?(?=\s+[A-Z])', 'Saint'),
        (r'\bSte\b\.?(?=\s+[A-Z])', 'Sainte'),
        (r'\bImp\b\.?', 'Impasse'),
        (r'\bPass\b\.?', 'Passage'),
        (r'\bFbg\b\.?', 'Faubourg'),
        (r'\bCrs\b\.?', 'Cours'),
    ]
    
    for pattern, replacement in fr_abbreviations:
        if re.search(pattern, address):
            address = re.sub(pattern, replacement, address)
            changes.append(f"{pattern} → {replacement}")
    
    # 4. Expansion des abréviations anglaises
    en_abbreviations = [
        (r'\bSt\b\.?(?=\s*,|\s*$|\s+[A-Z][a-z])', 'Street'),  # "Brewer St," → "Brewer Street"
        (r'\bRd\b\.?', 'Road'),
        (r'\bAve\b\.?', 'Avenue'),
        (r'\bBlvd\b\.?', 'Boulevard'),
        (r'\bLn\b\.?', 'Lane'),
        (r'\bDr\b\.?(?=\s*,|\s*$)', 'Drive'),
        (r'\bCt\b\.?(?=\s*,|\s*$)', 'Court'),
        (r'\bPl\b\.?(?=\s*,|\s*$)', 'Place'),
        (r'\bSq\b\.?', 'Square'),
    ]
    
    if city_code in ['LDN', 'NY', 'LA', 'MIA', 'SD']:
        for pattern, replacement in en_abbreviations:
            if re.search(pattern, address):
                address = re.sub(pattern, replacement, address)
                changes.append(f"{pattern} → {replacement}")
    
    # 5. Normaliser "Londres" → "London"
    if 'Londres' in address:
        address = address.replace('Londres', 'London')
        changes.append("Londres → London")
    
    # 6. Traiter les descriptions textuelles
    # "in the 9th arrondissement" → ", 75009 Paris"
    arr_match = re.search(r'in the (\d+)(?:st|nd|rd|th)?\s*arrondissement', address, re.IGNORECASE)
    if arr_match and city_code == 'PA':
        arr_num = int(arr_match.group(1))
        address = re.sub(r'\s*in the \d+(?:st|nd|rd|th)?\s*arrondissement\s*', '', address, flags=re.IGNORECASE)
        address = f"{address}, 750{arr_num:02d} Paris"
        changes.append(f"Arrondissement {arr_num} → code postal")
    
    # 7. Vérifier si la ville est présente
    has_city = False
    if city_name:
        for pattern in city.get('patterns', []):
            if re.search(pattern, address, re.IGNORECASE):
                has_city = True
                break
    
    # 8. Ajouter la ville si manquante
    if not has_city and city_name:
        # Vérifier si c'est juste un nom de rue sans ville
        address = address.strip().rstrip(',')
        address = f"{address}, {city_name}"
        changes.append(f"Ville ajoutée: {city_name}")
    
    # 9. Nettoyer les espaces et ponctuations multiples
    address = re.sub(r'\s+', ' ', address)
    address = re.sub(r',\s*,', ',', address)
    address = re.sub(r'\s*,\s*', ', ', address)
    address = address.strip().strip(',').strip()
    
    # 10. Supprimer les codes route (A501, A5201, A41) qui perturbent le géocodage
    if re.match(r'^\d+\s+A\d+\s', address):
        # "16 A501, London" → problème, garder tel quel mais noter
        changes.append("⚠️ Code route détecté")
    
    # Log des changements
    if verbose and changes:
        print(f"      📝 {original[:40]}...")
        print(f"         → {address[:40]}...")
        print(f"         Modifications: {', '.join(changes)}")
    
    return address, changes


def geocode_address_sync(address, city_name=None):
    """Géocode une adresse via Nominatim (synchrone)"""
    import urllib.request
    import urllib.parse
    
    if not address or len(address.strip()) < 3:
        return None
    
    try:
        query = address
        if city_name and city_name.lower() not in address.lower():
            query += f", {city_name}"
        
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&limit=1"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'InvaderHunter/1.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            if data:
                return {
                    'lat': float(data[0]['lat']),
                    'lng': float(data[0]['lon']),
                    'display_name': data[0].get('display_name', ''),
                    'source': 'nominatim',
                    'confidence': 'high'
                }
    except Exception as e:
        pass
    return None


def geocode_manual_addresses(manual_addresses, verbose=False):
    """Géocode toutes les adresses manuelles avec standardisation préalable"""
    
    # Centres des villes pour les adresses inconnues
    city_centers = {
        'PA': {'lat': 48.8566, 'lng': 2.3522, 'name': 'Paris'},
        'LY': {'lat': 45.7640, 'lng': 4.8357, 'name': 'Lyon'},
        'MARS': {'lat': 43.2965, 'lng': 5.3698, 'name': 'Marseille'},
        'LDN': {'lat': 51.5074, 'lng': -0.1278, 'name': 'London'},
        'NY': {'lat': 40.7128, 'lng': -74.0060, 'name': 'New York'},
        'LA': {'lat': 34.0522, 'lng': -118.2437, 'name': 'Los Angeles'},
        'TK': {'lat': 35.6762, 'lng': 139.6503, 'name': 'Tokyo'},
        'ROM': {'lat': 41.9028, 'lng': 12.4964, 'name': 'Rome'},
        'BCN': {'lat': 41.3851, 'lng': 2.1734, 'name': 'Barcelona'},
        'BKK': {'lat': 13.7563, 'lng': 100.5018, 'name': 'Bangkok'},
        'HK': {'lat': 22.3193, 'lng': 114.1694, 'name': 'Hong Kong'},
        'MIA': {'lat': 25.7617, 'lng': -80.1918, 'name': 'Miami'},
        'SD': {'lat': 32.7157, 'lng': -117.1611, 'name': 'San Diego'},
        'RAV': {'lat': 44.4184, 'lng': 12.2035, 'name': 'Ravenna'},
        'BIL': {'lat': 43.2630, 'lng': -2.9350, 'name': 'Bilbao'},
        'AMS': {'lat': 52.3676, 'lng': 4.9041, 'name': 'Amsterdam'},
        'TLS': {'lat': 43.6047, 'lng': 1.4442, 'name': 'Toulouse'},
        'BDX': {'lat': 44.8378, 'lng': -0.5792, 'name': 'Bordeaux'},
        'NTE': {'lat': 47.2184, 'lng': -1.5536, 'name': 'Nantes'},
        'LILE': {'lat': 50.6292, 'lng': 3.0573, 'name': 'Lille'},
        'STR': {'lat': 48.5734, 'lng': 7.7521, 'name': 'Strasbourg'},
        'MTP': {'lat': 43.6108, 'lng': 3.8767, 'name': 'Montpellier'},
        'NICE': {'lat': 43.7102, 'lng': 7.2620, 'name': 'Nice'},
        'REIM': {'lat': 49.2583, 'lng': 4.0317, 'name': 'Reims'},
        'VER': {'lat': 48.8014, 'lng': 2.1301, 'name': 'Versailles'},
    }
    
    results = {}
    success_count = 0
    unknown_count = 0
    standardized_count = 0
    
    print(f"\n📍 Géocodage de {len(manual_addresses)} adresses manuelles...")
    print(f"   (Étape 1: Standardisation → Étape 2: Géocodage Nominatim)")
    
    for i, (code, data) in enumerate(manual_addresses.items()):
        address = data.get('address', '')
        
        # Extraire le code ville
        city_match = re.match(r'^([A-Z]+)[-_]', code)
        city_code = city_match.group(1) if city_match else None
        city_info = city_centers.get(city_code, {})
        city_name = city_info.get('name', '')
        
        if verbose:
            print(f"\n   [{i+1}/{len(manual_addresses)}] {code}")
            print(f"      Original: {address[:60]}{'...' if len(address) > 60 else ''}")
        
        # Étape 1: Standardiser l'adresse
        if address and len(address) > 3:
            standardized, changes = standardize_address(address, city_code, verbose=False)
            
            if changes and verbose:
                print(f"      Standardisé: {standardized[:60]}{'...' if len(standardized) > 60 else ''}")
                print(f"      Modifications: {', '.join(changes[:3])}{'...' if len(changes) > 3 else ''}")
            
            if changes:
                standardized_count += 1
            
            # Étape 2: Géocoder l'adresse standardisée
            if standardized:
                geo = geocode_address_sync(standardized, None)  # Ville déjà dans l'adresse
                
                if geo:
                    results[code] = {
                        'lat': geo['lat'],
                        'lng': geo['lng'],
                        'address_original': address,
                        'address_standardized': standardized,
                        'address_geocoded': geo.get('display_name', ''),
                        'source': 'manual_address',
                        'confidence': 'high',
                        'location_unknown': False
                    }
                    success_count += 1
                    if verbose:
                        print(f"      ✅ Géocodé: ({geo['lat']:.6f}, {geo['lng']:.6f})")
                else:
                    # Géocodage échoué, utiliser centre ville
                    if city_code and city_code in city_centers:
                        results[code] = {
                            'lat': city_info['lat'],
                            'lng': city_info['lng'],
                            'address_original': address,
                            'address_standardized': standardized,
                            'source': 'city_center_fallback',
                            'confidence': 'very_low',
                            'location_unknown': True
                        }
                        unknown_count += 1
                        if verbose:
                            print(f"      ⚠️ Échec géocodage → centre {city_name}")
                    else:
                        if verbose:
                            print(f"      ❌ Échec géocodage, pas de fallback")
            else:
                if verbose:
                    print(f"      ❌ Adresse invalide après standardisation")
        else:
            # Pas d'adresse, utiliser centre ville
            if city_code and city_code in city_centers:
                results[code] = {
                    'lat': city_info['lat'],
                    'lng': city_info['lng'],
                    'address_original': '',
                    'source': 'city_center',
                    'confidence': 'very_low',
                    'location_unknown': True
                }
                unknown_count += 1
                if verbose:
                    print(f"      📍 Pas d'adresse → centre {city_name}")
            else:
                if verbose:
                    print(f"      ❌ Pas d'adresse ni de ville connue")
        
        # Pause pour respecter rate limit Nominatim (1 req/sec)
        time.sleep(1.1)
    
    print(f"\n   📊 Résumé:")
    print(f"      ✅ {success_count} géolocalisés avec succès")
    print(f"      ⚠️ {unknown_count} au centre ville (position inconnue)")
    print(f"      📝 {standardized_count} adresses standardisées")
    
    return results


# ============================================================================
# GÉOLOCALISATION PAR RECHERCHE WEB
# ============================================================================

async def accept_google_consent(page):
    """Accepte les cookies Google si la page de consentement apparaît"""
    try:
        # Différents boutons possibles pour accepter
        consent_selectors = [
            'button:has-text("Tout accepter")',
            'button:has-text("Accept all")',
            'button:has-text("Accepter tout")',
            'button:has-text("J\'accepte")',
            'button:has-text("I agree")',
            '[aria-label="Tout accepter"]',
            '[aria-label="Accept all"]',
            '#L2AGLb',  # ID du bouton Google
            'button[id*="accept"]',
        ]
        
        for selector in consent_selectors:
            try:
                btn = page.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(1000)
                    return True
            except:
                continue
        return False
    except:
        return False


async def check_for_captcha(page):
    """Vérifie si Google affiche un CAPTCHA"""
    try:
        html = await page.content()
        captcha_indicators = [
            'captcha', 'recaptcha', 'unusual traffic',
            'trafic inhabituel', 'robot', 'automated',
            'verify you\'re human', 'vérifier que vous'
        ]
        html_lower = html.lower()
        for indicator in captcha_indicators:
            if indicator in html_lower:
                return True
        return False
    except:
        return False


async def geocode_address(address, city_name=None):
    """Convertit une adresse en coordonnées via Nominatim (OpenStreetMap)"""
    import urllib.request
    import urllib.parse
    
    try:
        query = address
        if city_name:
            query += f", {city_name}"
        
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&limit=1"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'InvaderHunter/1.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            if data:
                return {
                    'lat': float(data[0]['lat']),
                    'lng': float(data[0]['lon']),
                    'display_name': data[0].get('display_name', '')
                }
    except Exception as e:
        pass
    return None


async def geolocate_invader(page, invader_name, city_code, verbose=False):
    """Recherche les coordonnées d'un invader via plusieurs sources"""
    
    # Structure d'audit pour cet invader
    audit = {
        'invader': invader_name,
        'city_code': city_code,
        'timestamp': datetime.now().isoformat(),
        'sources_tried': [],
        'addresses_found': [],
        'coordinates_found': [],
        'errors': [],
        'captcha_detected': False,
        'final_result': None
    }
    
    # Mapping des codes ville vers noms complets
    city_names = {
        'PA': 'Paris', 'LY': 'Lyon', 'MARS': 'Marseille', 'TLS': 'Toulouse',
        'BDX': 'Bordeaux', 'NTE': 'Nantes', 'LILE': 'Lille', 'STR': 'Strasbourg',
        'LDN': 'London', 'NY': 'New York', 'LA': 'Los Angeles', 'TK': 'Tokyo',
        'ROM': 'Rome', 'BCN': 'Barcelona', 'BKK': 'Bangkok', 'HK': 'Hong Kong',
        'MIA': 'Miami', 'SD': 'San Diego', 'RAV': 'Ravenna', 'BIL': 'Bilbao',
        'MTP': 'Montpellier', 'NICE': 'Nice', 'REIM': 'Reims', 'AMS': 'Amsterdam',
        'VER': 'Versailles', 'CLER': 'Clermont-Ferrand', 'AVIGN': 'Avignon',
    }
    city_name = city_names.get(city_code, city_code)
    audit['city_name'] = city_name
    
    results = []
    
    # Source 1: Atlas du Street Art (spécialisé invaders)
    source1 = {'name': 'atlas-streetart', 'url': None, 'result': None, 'error': None}
    try:
        search_url = f"https://www.google.com/search?q=site:atlas-streetart.com+{invader_name}"
        source1['url'] = search_url
        
        await page.goto(search_url, timeout=10000)
        await accept_google_consent(page)
        await page.wait_for_timeout(1500)
        
        if await check_for_captcha(page):
            audit['captcha_detected'] = True
            source1['error'] = 'CAPTCHA detected'
        else:
            html = await page.content()
            
            # Chercher des coordonnées dans les snippets
            coord_match = re.search(r'(\d{1,2}\.\d{4,})[°,\s]+(-?\d{1,3}\.\d{4,})', html)
            if coord_match:
                lat, lng = float(coord_match.group(1)), float(coord_match.group(2))
                if 40 <= lat <= 60 and -10 <= lng <= 20:  # Plausible pour Europe
                    result = {'lat': lat, 'lng': lng, 'source': 'atlas-streetart', 'confidence': 'medium'}
                    results.append(result)
                    source1['result'] = result
                    audit['coordinates_found'].append({'source': 'atlas-streetart', 'lat': lat, 'lng': lng})
    except Exception as e:
        source1['error'] = str(e)
        audit['errors'].append(f"atlas-streetart: {e}")
    audit['sources_tried'].append(source1)
    
    # Source 2: Recherche Google avec nom ville pour trouver adresse
    source2 = {'name': 'google_address_search', 'url': None, 'result': None, 'error': None}
    try:
        search_query = f"{invader_name} {city_name} street art adresse rue"
        search_url = f"https://www.google.com/search?q={search_query.replace(' ', '+')}"
        source2['url'] = search_url
        
        await page.goto(search_url, timeout=10000)
        await accept_google_consent(page)
        await page.wait_for_timeout(1500)
        
        if await check_for_captcha(page):
            audit['captcha_detected'] = True
            source2['error'] = 'CAPTCHA detected'
        else:
            html = await page.content()
            
            # Chercher des adresses françaises/internationales
            address_patterns = [
                r'(\d+[\s,]+(?:rue|avenue|boulevard|place|passage|impasse|quai|cours|allée)[^<,]{5,60})',
                r'(\d+[\s,]+(?:street|road|avenue|lane|drive|way|place)[^<,]{5,60})',
                r'(\d+[\s,]+(?:via|piazza|corso|viale)[^<,]{5,60})',
                r'(\d+[\s,]+(?:calle|avenida|plaza|paseo)[^<,]{5,60})',
            ]
            
            addresses_found = []
            for pattern in address_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches[:3]:
                    address = match.strip()
                    address = re.sub(r'<[^>]+>', '', address)  # Supprimer HTML
                    address = re.sub(r'\s+', ' ', address)
                    if len(address) > 10 and address not in addresses_found:
                        addresses_found.append(address)
                        audit['addresses_found'].append({'source': 'google', 'address': address})
            
            # Géocoder la première adresse valide
            for address in addresses_found[:3]:
                geo = await geocode_address(address, city_name)
                if geo:
                    result = {
                        'lat': geo['lat'],
                        'lng': geo['lng'],
                        'address': address,
                        'geocoded_address': geo.get('display_name', ''),
                        'source': 'google+nominatim',
                        'confidence': 'medium'
                    }
                    results.append(result)
                    source2['result'] = result
                    audit['coordinates_found'].append({
                        'source': 'nominatim',
                        'address': address,
                        'lat': geo['lat'],
                        'lng': geo['lng']
                    })
                    break
                await page.wait_for_timeout(500)  # Respecter rate limit Nominatim
    except Exception as e:
        source2['error'] = str(e)
        audit['errors'].append(f"google_address: {e}")
    audit['sources_tried'].append(source2)
    
    # Source 3: FlashInvaders / blogs spécialisés
    source3 = {'name': 'flashinvaders_blogs', 'url': None, 'result': None, 'error': None}
    try:
        search_url = f"https://www.google.com/search?q={invader_name}+flashinvaders+OR+streetart+OR+space+invader+coordinates+OR+location"
        source3['url'] = search_url
        
        await page.goto(search_url, timeout=10000)
        await accept_google_consent(page)
        await page.wait_for_timeout(1500)
        
        if await check_for_captcha(page):
            audit['captcha_detected'] = True
            source3['error'] = 'CAPTCHA detected'
        else:
            html = await page.content()
            
            # Coordonnées décimales directes
            coord_matches = re.findall(r'(\d{1,2}\.\d{4,})[°,\s]+(-?\d{1,3}\.\d{4,})', html)
            for match in coord_matches[:5]:
                lat, lng = float(match[0]), float(match[1])
                plausible = False
                
                # Vérifier plausibilité selon la ville
                if city_code == 'PA' and 48.5 <= lat <= 49.2 and 1.5 <= lng <= 3.0:
                    plausible = True
                elif city_code == 'LDN' and 51.2 <= lat <= 51.8 and -0.6 <= lng <= 0.4:
                    plausible = True
                elif city_code == 'NY' and 40.4 <= lat <= 41.0 and -74.5 <= lng <= -73.5:
                    plausible = True
                elif -90 <= lat <= 90 and -180 <= lng <= 180:
                    plausible = True
                
                if plausible:
                    result = {'lat': lat, 'lng': lng, 'source': 'web_search', 'confidence': 'low'}
                    results.append(result)
                    source3['result'] = result
                    audit['coordinates_found'].append({'source': 'web_search', 'lat': lat, 'lng': lng})
                    break
    except Exception as e:
        source3['error'] = str(e)
        audit['errors'].append(f"flashinvaders: {e}")
    audit['sources_tried'].append(source3)
    
    # Source 4: Recherche de l'arrondissement/quartier pour Paris
    source4 = {'name': 'arrondissement', 'url': None, 'result': None, 'error': None}
    if city_code == 'PA':
        try:
            search_url = f"https://www.google.com/search?q={invader_name}+paris+arrondissement+quartier"
            source4['url'] = search_url
            
            await page.goto(search_url, timeout=10000)
            await accept_google_consent(page)
            await page.wait_for_timeout(1500)
            
            if await check_for_captcha(page):
                audit['captcha_detected'] = True
                source4['error'] = 'CAPTCHA detected'
            else:
                html = await page.content()
                
                # Chercher l'arrondissement
                arr_patterns = [
                    r'(\d{1,2})(?:e|ème|er|eme|è)\s*(?:arrondissement)?',
                    r'(?:arrondissement|arr\.?)\s*(\d{1,2})',
                    r'paris\s*(\d{1,2})(?:e|ème)?',
                ]
                
                arr_found = None
                for pattern in arr_patterns:
                    arr_match = re.search(pattern, html, re.IGNORECASE)
                    if arr_match:
                        arr = int(arr_match.group(1))
                        if 1 <= arr <= 20:
                            arr_found = arr
                            break
                
                if arr_found:
                    audit['arrondissement'] = arr_found
                    
                    # Centres approximatifs des arrondissements de Paris
                    arr_centers = {
                        1: (48.8606, 2.3376), 2: (48.8683, 2.3441), 3: (48.8640, 2.3614),
                        4: (48.8539, 2.3582), 5: (48.8462, 2.3472), 6: (48.8510, 2.3329),
                        7: (48.8566, 2.3130), 8: (48.8744, 2.3106), 9: (48.8767, 2.3378),
                        10: (48.8762, 2.3598), 11: (48.8597, 2.3793), 12: (48.8396, 2.3876),
                        13: (48.8322, 2.3561), 14: (48.8331, 2.3264), 15: (48.8421, 2.2993),
                        16: (48.8637, 2.2769), 17: (48.8867, 2.3166), 18: (48.8925, 2.3444),
                        19: (48.8871, 2.3824), 20: (48.8638, 2.3986),
                    }
                    
                    if arr_found in arr_centers:
                        lat, lng = arr_centers[arr_found]
                        result = {
                            'lat': lat, 'lng': lng,
                            'address': f"{arr_found}e arrondissement, Paris",
                            'source': 'arrondissement',
                            'confidence': 'very_low',
                            'arrondissement': arr_found
                        }
                        results.append(result)
                        source4['result'] = result
                        audit['coordinates_found'].append({
                            'source': 'arrondissement',
                            'arrondissement': arr_found,
                            'lat': lat,
                            'lng': lng
                        })
        except Exception as e:
            source4['error'] = str(e)
            audit['errors'].append(f"arrondissement: {e}")
        audit['sources_tried'].append(source4)
    
    # Source 5: Street Art Cities (très bonne source avec coordonnées)
    source5 = {'name': 'streetartcities', 'url': None, 'result': None, 'error': None}
    try:
        search_url = f"https://www.google.com/search?q=site:streetartcities.com+{invader_name}+OR+%22{invader_name.replace('_', '-')}%22"
        source5['url'] = search_url
        
        await page.goto(search_url, timeout=10000)
        await accept_google_consent(page)
        await page.wait_for_timeout(1500)
        
        if await check_for_captcha(page):
            audit['captcha_detected'] = True
            source5['error'] = 'CAPTCHA detected'
        else:
            html = await page.content()
            
            # Chercher des coordonnées dans les snippets ou URLs
            # streetartcities.com utilise des URLs avec coordonnées parfois
            coord_patterns = [
                r'(\d{1,2}\.\d{4,})[,\s°]+(-?\d{1,3}\.\d{4,})',
                r'lat[=:]\s*(\d{1,2}\.\d+)[&,\s]+(?:lng|lon)[=:]\s*(-?\d{1,3}\.\d+)',
            ]
            
            for pattern in coord_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches[:3]:
                    lat, lng = float(match[0]), float(match[1])
                    if 40 <= lat <= 60 and -10 <= lng <= 20:  # Europe
                        result = {'lat': lat, 'lng': lng, 'source': 'streetartcities', 'confidence': 'medium'}
                        results.append(result)
                        source5['result'] = result
                        audit['coordinates_found'].append({'source': 'streetartcities', 'lat': lat, 'lng': lng})
                        break
                if source5['result']:
                    break
            
            # Chercher aussi des adresses
            if not source5['result']:
                address_match = re.search(r'(\d+[,\s]+(?:rue|avenue|boulevard|street|road)[^<,]{5,50})', html, re.IGNORECASE)
                if address_match:
                    address = re.sub(r'<[^>]+>', '', address_match.group(1)).strip()
                    audit['addresses_found'].append({'source': 'streetartcities', 'address': address})
                    geo = await geocode_address(address, city_name)
                    if geo:
                        result = {'lat': geo['lat'], 'lng': geo['lng'], 'address': address, 'source': 'streetartcities+nominatim', 'confidence': 'medium'}
                        results.append(result)
                        source5['result'] = result
    except Exception as e:
        source5['error'] = str(e)
        audit['errors'].append(f"streetartcities: {e}")
    audit['sources_tried'].append(source5)
    
    # Source 6: Flickr (photos avec géolocalisation EXIF)
    source6 = {'name': 'flickr', 'url': None, 'result': None, 'error': None}
    try:
        # Rechercher sur Flickr via Google
        search_url = f"https://www.google.com/search?q=site:flickr.com+{invader_name}+invader+OR+space+invader"
        source6['url'] = search_url
        
        await page.goto(search_url, timeout=10000)
        await accept_google_consent(page)
        await page.wait_for_timeout(1500)
        
        if await check_for_captcha(page):
            audit['captcha_detected'] = True
            source6['error'] = 'CAPTCHA detected'
        else:
            html = await page.content()
            
            # Flickr montre parfois les coordonnées dans les snippets
            coord_match = re.search(r'(\d{1,2}\.\d{4,})[,\s°]+(-?\d{1,3}\.\d{4,})', html)
            if coord_match:
                lat, lng = float(coord_match.group(1)), float(coord_match.group(2))
                if -90 <= lat <= 90 and -180 <= lng <= 180:
                    result = {'lat': lat, 'lng': lng, 'source': 'flickr', 'confidence': 'medium'}
                    results.append(result)
                    source6['result'] = result
                    audit['coordinates_found'].append({'source': 'flickr', 'lat': lat, 'lng': lng})
            
            # Essayer d'extraire un lien Flickr et le visiter directement
            if not source6['result']:
                flickr_links = re.findall(r'https://(?:www\.)?flickr\.com/photos/[^"\s<>]+', html)
                for flickr_url in flickr_links[:2]:  # Max 2 liens
                    try:
                        await page.goto(flickr_url, timeout=10000)
                        await page.wait_for_timeout(2000)
                        flickr_html = await page.content()
                        
                        # Chercher les coordonnées dans la page Flickr
                        # Flickr affiche souvent "Taken in [location]" ou des coords dans les métadonnées
                        geo_patterns = [
                            r'data-lat="(\d{1,2}\.\d+)"[^>]*data-lon="(-?\d{1,3}\.\d+)"',
                            r'"latitude":(\d{1,2}\.\d+),"longitude":(-?\d{1,3}\.\d+)',
                            r'geo:(\d{1,2}\.\d+),(-?\d{1,3}\.\d+)',
                        ]
                        
                        for pattern in geo_patterns:
                            match = re.search(pattern, flickr_html)
                            if match:
                                lat, lng = float(match.group(1)), float(match.group(2))
                                if -90 <= lat <= 90 and -180 <= lng <= 180:
                                    result = {'lat': lat, 'lng': lng, 'source': 'flickr_direct', 'confidence': 'high', 'flickr_url': flickr_url}
                                    results.append(result)
                                    source6['result'] = result
                                    audit['coordinates_found'].append({'source': 'flickr_direct', 'lat': lat, 'lng': lng, 'url': flickr_url})
                                    break
                        if source6['result']:
                            break
                    except:
                        continue
    except Exception as e:
        source6['error'] = str(e)
        audit['errors'].append(f"flickr: {e}")
    audit['sources_tried'].append(source6)
    
    # Source 7: Illuminate Art Official
    source7 = {'name': 'illuminateart', 'url': None, 'result': None, 'error': None}
    try:
        search_url = f"https://www.google.com/search?q=site:illuminateartofficial.com+{invader_name}"
        source7['url'] = search_url
        
        await page.goto(search_url, timeout=10000)
        await accept_google_consent(page)
        await page.wait_for_timeout(1500)
        
        if await check_for_captcha(page):
            audit['captcha_detected'] = True
            source7['error'] = 'CAPTCHA detected'
        else:
            html = await page.content()
            
            # Chercher des coordonnées ou adresses
            coord_match = re.search(r'(\d{1,2}\.\d{4,})[,\s°]+(-?\d{1,3}\.\d{4,})', html)
            if coord_match:
                lat, lng = float(coord_match.group(1)), float(coord_match.group(2))
                if -90 <= lat <= 90 and -180 <= lng <= 180:
                    result = {'lat': lat, 'lng': lng, 'source': 'illuminateart', 'confidence': 'medium'}
                    results.append(result)
                    source7['result'] = result
                    audit['coordinates_found'].append({'source': 'illuminateart', 'lat': lat, 'lng': lng})
            
            # Chercher des liens vers le site et les visiter
            if not source7['result']:
                illuminate_links = re.findall(r'https://illuminateartofficial\.com/[^"\s<>]+invader[^"\s<>]*', html, re.IGNORECASE)
                for link in illuminate_links[:1]:
                    try:
                        await page.goto(link, timeout=10000)
                        await page.wait_for_timeout(2000)
                        page_html = await page.content()
                        
                        # Chercher coordonnées ou adresses dans la page
                        geo_match = re.search(r'(\d{1,2}\.\d{4,})[,\s]+(-?\d{1,3}\.\d{4,})', page_html)
                        if geo_match:
                            lat, lng = float(geo_match.group(1)), float(geo_match.group(2))
                            result = {'lat': lat, 'lng': lng, 'source': 'illuminateart_direct', 'confidence': 'medium'}
                            results.append(result)
                            source7['result'] = result
                            audit['coordinates_found'].append({'source': 'illuminateart_direct', 'lat': lat, 'lng': lng})
                        
                        # Chercher adresse
                        if not source7['result']:
                            addr_match = re.search(r'(\d+[,\s]+(?:rue|avenue|boulevard|street)[^<,]{5,50})', page_html, re.IGNORECASE)
                            if addr_match:
                                address = re.sub(r'<[^>]+>', '', addr_match.group(1)).strip()
                                audit['addresses_found'].append({'source': 'illuminateart', 'address': address})
                                geo = await geocode_address(address, city_name)
                                if geo:
                                    result = {'lat': geo['lat'], 'lng': geo['lng'], 'address': address, 'source': 'illuminateart+nominatim', 'confidence': 'medium'}
                                    results.append(result)
                                    source7['result'] = result
                    except:
                        continue
    except Exception as e:
        source7['error'] = str(e)
        audit['errors'].append(f"illuminateart: {e}")
    audit['sources_tried'].append(source7)
    
    # Retourner le meilleur résultat
    if results:
        # Trier par confiance
        confidence_order = {'high': 0, 'medium': 1, 'low': 2, 'very_low': 3}
        results.sort(key=lambda x: confidence_order.get(x.get('confidence', 'low'), 2))
        audit['final_result'] = results[0]
        audit['all_results'] = results
        return results[0], audit
    
    audit['final_result'] = None
    return None, audit


async def geolocate_missing_invaders(not_in_github, headless=True, verbose=False, max_count=50):
    """Géolocalise les invaders manquants via recherche web"""
    if not not_in_github:
        return [], []
    
    print(f"\n🔍 Géolocalisation de {min(len(not_in_github), max_count)} invaders...")
    
    from playwright.async_api import async_playwright
    
    geolocated = []
    all_audits = []
    captcha_count = 0
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
        page = await context.new_page()
        
        for i, inv in enumerate(not_in_github[:max_count]):
            name = inv.get('name', '')
            city = inv.get('city', '')
            
            if verbose:
                print(f"   [{i+1}/{min(len(not_in_github), max_count)}] {name}...", end='', flush=True)
            
            result, audit = await geolocate_invader(page, name, city, verbose)
            
            # Ajouter les infos de l'invader à l'audit
            audit['image_invader'] = inv.get('image_invader')
            audit['image_lieu'] = inv.get('image_lieu')
            audit['status'] = inv.get('status', 'OK')
            audit['points'] = inv.get('points', 0)
            all_audits.append(audit)
            
            if audit.get('captcha_detected'):
                captcha_count += 1
            
            if result:
                inv_copy = inv.copy()
                inv_copy.update(result)
                geolocated.append(inv_copy)
                if verbose:
                    confidence = result.get('confidence', '?')
                    if result.get('lat'):
                        print(f" ✓ ({result['lat']:.4f}, {result['lng']:.4f}) [{confidence}]")
                    elif result.get('address'):
                        print(f" ✓ {result['address'][:30]}... [{confidence}]")
                    else:
                        print(f" ✓ [{confidence}]")
            else:
                if verbose:
                    if audit.get('captcha_detected'):
                        print(" ⚠️ CAPTCHA")
                    else:
                        print(" ○")
            
            # Pause plus longue si CAPTCHA détecté
            if audit.get('captcha_detected'):
                await page.wait_for_timeout(5000)
            else:
                await page.wait_for_timeout(1500)
            
            # Si trop de CAPTCHAs, arrêter
            if captcha_count >= 5:
                print(f"\n   ⚠️ Trop de CAPTCHAs détectés ({captcha_count}), arrêt de la géolocalisation")
                break
        
        await browser.close()
    
    print(f"   ✅ {len(geolocated)}/{min(len(not_in_github), max_count)} géolocalisés")
    if captcha_count > 0:
        print(f"   ⚠️ {captcha_count} CAPTCHAs rencontrés")
    
    return geolocated, all_audits
    
    print(f"   ✅ {len(geolocated)}/{min(len(not_in_github), max_count)} géolocalisés")
    return geolocated


# ============================================================================
# SCRAPING PLAYWRIGHT (logique éprouvée)
# ============================================================================

async def scrape_city_playwright(page, city_code, verbose=False, max_retries=3):
    """Scrape une ville - logique de update_invaders_playwright.py"""
    statuses = {}
    
    for attempt in range(max_retries):
        try:
            if verbose:
                print(f"\n      Tentative {attempt + 1} pour {city_code}...")
            
            # Aller sur villes.php
            await page.goto(f"{INVADER_SPOTTER_BASE}/villes.php", wait_until='networkidle', timeout=30000)
            await page.wait_for_timeout(1000)
            
            # Trouver et cliquer sur le lien de la ville
            # Pattern 1: a[href^="javascript:envoi"]
            links = await page.query_selector_all('a[href^="javascript:envoi"]')
            link = None
            for l in links:
                href = await l.get_attribute('href')
                if href:
                    href_upper = href.upper()
                    # Chercher le code en majuscules ou minuscules
                    if f'"{city_code.upper()}"' in href_upper or f"'{city_code.upper()}'" in href_upper:
                        link = l
                        break
            
            # Pattern 2: a[onclick*="envoi"] si le premier n'a pas marché
            if not link:
                onclick_links = await page.query_selector_all('a[onclick*="envoi"]')
                for l in onclick_links:
                    onclick = await l.get_attribute('onclick')
                    if onclick:
                        onclick_upper = onclick.upper()
                        if f'"{city_code.upper()}"' in onclick_upper or f"'{city_code.upper()}'" in onclick_upper:
                            link = l
                            break
            
            # Pattern 3: Chercher par texte du lien (nom de la ville)
            if not link:
                city_name = CITY_NAMES.get(city_code, city_code)
                try:
                    link = await page.query_selector(f'a:text-is("{city_name}")')
                except:
                    pass
            
            if not link:
                if verbose:
                    print(f"      ⚠️ Lien non trouvé pour {city_code}")
                    # Afficher les codes disponibles pour debug
                    available_codes = []
                    for l in links:
                        href = await l.get_attribute('href')
                        if href:
                            match = re.search(r'envoi\([\'"]([^"\']+)[\'"]\)', href)
                            if match:
                                available_codes.append(match.group(1))
                    if available_codes:
                        print(f"         Codes disponibles: {available_codes[:20]}...")
                return statuses
            
            # Cliquer et attendre
            try:
                async with page.expect_navigation(wait_until='load', timeout=15000):
                    await link.click()
                await page.wait_for_load_state('networkidle')
            except:
                await page.wait_for_timeout(3000)
            await page.wait_for_timeout(1000)
            
            # Récupérer le HTML
            html_content = None
            for _ in range(5):
                try:
                    html_content = await page.content()
                    break
                except:
                    await page.wait_for_timeout(1000)
            
            if not html_content:
                continue
            
            # Détecter le nombre de pages de plusieurs façons
            # 1. Via les liens changepage
            page_links = re.findall(r'changepage\((\d+)\)', html_content)
            max_page_from_links = max([int(p) for p in page_links]) if page_links else 1
            
            # 2. Via le texte "résultats X-Y / Z"
            total_match = re.search(r'résultats?\s*\d+-(\d+)\s*/\s*(\d+)', html_content, re.IGNORECASE)
            if total_match:
                per_page = int(total_match.group(1))
                total = int(total_match.group(2))
                max_page_from_total = (total + per_page - 1) // per_page  # Arrondi supérieur
            else:
                max_page_from_total = 1
            
            # Prendre le maximum des deux méthodes
            max_page = max(max_page_from_links, max_page_from_total)
            
            if verbose:
                total_str = total_match.group(2) if total_match else '?'
                print(f"      {total_str} invaders sur {max_page} pages")
            
            # Parcourir les pages
            for page_num in range(1, max_page + 1):
                if page_num > 1:
                    success = False
                    
                    for nav_attempt in range(3):
                        try:
                            # Attendre que la page soit stable avant de naviguer
                            await page.wait_for_load_state('domcontentloaded', timeout=5000)
                        except:
                            pass
                        
                        try:
                            # Déclencher la navigation et attendre qu'elle se termine
                            async with page.expect_navigation(timeout=30000, wait_until='domcontentloaded'):
                                await page.evaluate(f'changepage({page_num})')
                            
                            # Attendre que la page soit complètement chargée
                            await page.wait_for_load_state('load', timeout=15000)
                            await page.wait_for_timeout(1000)
                            
                            html_content = await page.content()
                            test_statuses = extract_statuses_from_html(html_content, city_code)
                            if len(test_statuses) > 0:
                                success = True
                                break
                            
                        except Exception as e:
                            if verbose:
                                print(f"      ⚠️ Tentative {nav_attempt+1}: {str(e)[:60]}")
                            
                            # Attendre que la page se stabilise avant de réessayer
                            await page.wait_for_timeout(5000)
                            
                            # Essayer de récupérer le contenu quand même
                            try:
                                await page.wait_for_load_state('load', timeout=10000)
                                html_content = await page.content()
                                test_statuses = extract_statuses_from_html(html_content, city_code)
                                if len(test_statuses) > 0:
                                    success = True
                                    break
                            except:
                                pass
                    
                    if not success:
                        if verbose:
                            print(f"      ⚠️ Skip page {page_num}")
                        continue
                
                page_statuses = extract_statuses_from_html(html_content, city_code)
                
                # Éviter les doublons
                new_count = 0
                for name, data in page_statuses.items():
                    if name not in statuses:
                        statuses[name] = data
                        new_count += 1
                
                if verbose:
                    print(f"      Page {page_num}/{max_page}: {len(page_statuses)} invaders (+{new_count} nouveaux)")
            
            if verbose:
                print(f"      ✓ {len(statuses)} invaders")
            break
            
        except Exception as e:
            if verbose:
                print(f"      ❌ Erreur: {e}")
            if attempt < max_retries - 1:
                await page.wait_for_timeout(2000)
    
    return statuses


def extract_statuses_from_html(html_content, city_code):
    """
    Extrait les invaders et statuts depuis le HTML.
    
    Version v4 : Extraction enrichie avec :
    - landing_date : Date de pose depuis "Landed on : DD/MM/YYYY"
    - status_date : Date du statut depuis "Date and source : Month YYYY (source)"
    - status_source : Source du statut (report, FlashInvaders, etc.)
    
    Format attendu sur le site :
        WN_01 [20 pts]
        Landed on : 06/06/2006
        Last known state :  OK
        Date and source : December 2025 (report)
        Instagram: hashtag #WN_01
    """
    statuses = {}
    
    # Le format réel est :
    # <b>PA_01 [10 pts]</b> ... <img src='nav/spot_invader_destroyed.png'> ...
    # <img src="grosplan/PA/PA_0001-grosplan.png">
    # <img src='photos/PA/PA_0001-mai2025.jpg'>
    
    # Pattern pour trouver les blocs d'invaders (dans <td> ou sections)
    # Cherche le nom en bold : <b>PA_01 [10 pts]</b>
    invader_pattern = rf'<b>\s*({city_code}[-_]?\d+)\s*\[(\d+|\?\?)\s*pts?\]</b>'
    
    for match in re.finditer(invader_pattern, html_content, re.IGNORECASE):
        inv_name_raw = match.group(1).upper().replace('-', '_')
        points_raw = match.group(2)
        
        name_match = re.match(r'([A-Z]+)[-_]?(\d+)', inv_name_raw)
        if name_match:
            prefix, num = name_match.groups()
            inv_name = f"{prefix}_{num}"
            num_padded = num.zfill(4)  # Pour les images: PA_0001
        else:
            inv_name = inv_name_raw
            num = ''
            num_padded = ''
        
        # Points: 0 si inconnu (??)
        points = 0 if points_raw == '??' else int(points_raw)
        
        # Chercher le contexte délimité jusqu'au PROCHAIN invader
        # Cela évite de capturer les informations d'un autre invader par erreur
        match_pos = match.start()
        
        # Chercher la position du prochain invader après celui-ci (avec un offset de 50 pour éviter de se re-matcher)
        next_invader = re.search(rf'{city_code}[-_]?\d+\s*\[', html_content[match_pos + 50:], re.IGNORECASE)
        if next_invader:
            # Le contexte s'arrête au début du prochain invader
            context_end = match_pos + 50 + next_invader.start()
        else:
            # Pas de prochain invader, prendre 1500 chars max (dernier de la page)
            context_end = min(len(html_content), match_pos + 1500)
        
        context = html_content[match_pos:context_end]
        context_lower = context.lower()
        
        # ============================================
        # V4: Extraction de la date de pose (landing_date)
        # Format EN: "Landed on : DD/MM/YYYY"
        # Format FR: "Date de pose : DD/MM/YYYY"
        # ============================================
        landing_date = None
        landing_match = re.search(r'(?:Landed\s+on|Date\s+de\s+pose)\s*:\s*(\d{1,2}/\d{1,2}/\d{4})', context, re.IGNORECASE)
        if landing_match:
            landing_date = landing_match.group(1).strip()
        
        # ============================================
        # V4: Extraction du statut depuis "Last known state" / "Dernier état connu"
        # Format EN: "Last known state :  OK"
        # Format FR: "Dernier état connu :  Dégradé"
        # Note: On capture jusqu'au prochain label (Date, Instagram) car pas de retour ligne
        # ============================================
        status = 'OK'
        status_match = re.search(r'(?:Last\s+known\s+state|Dernier\s+[ée]tat\s+connu)\s*:\s*(.+?)(?=Date|Instagram|$)', context, re.IGNORECASE)
        if status_match:
            raw_status = status_match.group(1).strip()
            raw_status_lower = raw_status.lower()
            
            # Normaliser le statut (FR + EN)
            if 'very degraded' in raw_status_lower or 'très dégradé' in raw_status_lower:
                status = 'destroyed'
            elif 'a little degraded' in raw_status_lower or 'slightly degraded' in raw_status_lower or 'peu dégradé' in raw_status_lower or 'légèrement dégradé' in raw_status_lower:
                status = 'a little damaged'
            elif 'degraded' in raw_status_lower or 'dégradé' in raw_status_lower:
                status = 'damaged'
            elif 'destroyed' in raw_status_lower or 'détruit' in raw_status_lower:
                status = 'destroyed'
            elif 'hidden' in raw_status_lower or 'not visible' in raw_status_lower or 'non visible' in raw_status_lower or 'masked' in raw_status_lower or 'masqué' in raw_status_lower or 'caché' in raw_status_lower:
                status = 'hidden'
            elif 'ok' in raw_status_lower:
                status = 'OK'
            else:
                # Garder le statut tel quel si non reconnu
                status = raw_status.strip()
        else:
            # Fallback: Détecter le statut via l'image nav/spot_invader_*.png
            if 'spot_invader_destroyed' in context_lower or 'détruit' in context_lower or 'destroyed' in context_lower:
                status = 'destroyed'
            elif 'spot_invader_degraded' in context_lower or 'dégradé' in context_lower or 'degraded' in context_lower:
                if 'très dégradé' in context_lower or 'very degraded' in context_lower:
                    status = 'destroyed'
                elif 'peu dégradé' in context_lower or 'a little' in context_lower or 'slightly' in context_lower:
                    status = 'a little damaged'
                else:
                    status = 'damaged'
            elif 'spot_invader_neutre' in context_lower or 'spot_invader_hidden' in context_lower or 'masqué' in context_lower or 'caché' in context_lower:
                status = 'hidden'
        
        # ============================================
        # V4: Extraction de la date et source du statut
        # Format EN: "Date and source : December 2025 (report)"
        # Format FR: "Date et source : juin 2025 (report)"
        # ============================================
        status_date = None
        status_source = None
        date_source_match = re.search(r'Date\s+(?:and|et)\s+source\s*:\s*([^\n<(]+)(?:\s*\(([^)]+)\))?', context, re.IGNORECASE)
        if date_source_match:
            status_date = date_source_match.group(1).strip()
            if date_source_match.group(2):
                status_source = date_source_match.group(2).strip()
        
        # Chercher les images
        image_invader = image_lieu = None
        if num:
            # Image grosplan : grosplan/PA/PA_0001-grosplan.png
            grosplan = re.search(
                rf'grosplan/{city_code}/{city_code}[-_]?0*{num}-grosplan\.(png|jpg|jpeg)',
                html_content, re.IGNORECASE
            )
            if grosplan:
                image_invader = f"{INVADER_SPOTTER_BASE}/{grosplan.group(0)}"
            
            # Image lieu : photos/PA/PA_0001-*.jpg (la plus récente, après le match)
            # Utiliser le même contexte délimité au prochain invader
            photo = re.search(
                rf'photos/{city_code}/{city_code}[-_]?0*{num}-[^"\'>\s]+\.(jpg|jpeg|png)',
                context, re.IGNORECASE
            )
            image = re.search(
                rf'images/{city_code}/{city_code}[-_]?0*{num}-[^"\'>\s]+\.(jpg|jpeg|png)',
                context, re.IGNORECASE
            )
            if photo:
                image_lieu = f"{INVADER_SPOTTER_BASE}/{photo.group(0)}"
            elif image:
                image_lieu = f"{INVADER_SPOTTER_BASE}/{image.group(0)}"  
        
        # Construire l'objet avec toutes les informations
        inv_data = {
            'status': status,
            'points': points,
            'image_invader': image_invader,
            'image_lieu': image_lieu
        }
        
        # Ajouter les champs v4 s'ils sont présents
        if landing_date:
            inv_data['landing_date'] = landing_date
        if status_date:
            inv_data['status_date'] = status_date
        if status_source:
            inv_data['status_source'] = status_source
        
        statuses[inv_name] = inv_data
    
    # Pattern 2: Fallback - chercher aussi le format avec lien <a>
    # Au cas où certaines pages utilisent un format différent
    link_pattern = rf'<a[^>]*>.*?({city_code}[-_]?\d+)\s*\[(\d+|\?\?)\s*pts?\].*?</a>'
    
    for match in re.finditer(link_pattern, html_content, re.IGNORECASE | re.DOTALL):
        inv_name_raw = match.group(1).upper().replace('-', '_')
        points_raw = match.group(2)
        
        name_match = re.match(r'([A-Z]+)[-_]?(\d+)', inv_name_raw)
        if name_match:
            prefix, num = name_match.groups()
            inv_name = f"{prefix}_{num}"
        else:
            inv_name = inv_name_raw
            num = ''
        
        # Skip si déjà trouvé
        if inv_name in statuses:
            continue
        
        points = 0 if points_raw == '??' else int(points_raw)
        
        # Contexte délimité jusqu'au prochain invader (même logique que pattern principal)
        match_pos = match.start()
        next_invader = re.search(rf'{city_code}[-_]?\d+\s*\[', html_content[match_pos + 50:], re.IGNORECASE)
        if next_invader:
            context_end = match_pos + 50 + next_invader.start()
        else:
            context_end = min(len(html_content), match_pos + 1500)
        
        context = html_content[match_pos:context_end]
        context_lower = context.lower()
        
        # V4: Extraction des dates et statuts pour le pattern fallback (FR + EN)
        landing_date = None
        landing_match = re.search(r'(?:Landed\s+on|Date\s+de\s+pose)\s*:\s*(\d{1,2}/\d{1,2}/\d{4})', context, re.IGNORECASE)
        if landing_match:
            landing_date = landing_match.group(1).strip()
        
        status = 'OK'
        status_match = re.search(r'(?:Last\s+known\s+state|Dernier\s+[ée]tat\s+connu)\s*:\s*(.+?)(?=Date|Instagram|$)', context, re.IGNORECASE)
        if status_match:
            raw_status = status_match.group(1).strip().lower()
            if 'very degraded' in raw_status or 'très dégradé' in raw_status:
                status = 'destroyed'
            elif 'a little degraded' in raw_status or 'peu dégradé' in raw_status or 'légèrement dégradé' in raw_status:
                status = 'a little damaged'
            elif 'degraded' in raw_status or 'dégradé' in raw_status:
                status = 'damaged'
            elif 'destroyed' in raw_status or 'détruit' in raw_status:
                status = 'destroyed'
            elif 'hidden' in raw_status or 'masked' in raw_status or 'masqué' in raw_status or 'caché' in raw_status:
                status = 'hidden'
        else:
            if 'spot_invader_destroyed' in context_lower or 'détruit' in context_lower:
                status = 'destroyed'
            elif 'spot_invader_degraded' in context_lower or 'dégradé' in context_lower:
                if 'très dégradé' in context_lower:
                    status = 'destroyed'
                elif 'peu dégradé' in context_lower:
                    status = 'a little damaged'
                else:
                    status = 'damaged'
            elif 'spot_invader_neutre' in context_lower or 'masqué' in context_lower or 'caché' in context_lower:
                status = 'hidden'
        
        status_date = None
        status_source = None
        date_source_match = re.search(r'Date\s+(?:and|et)\s+source\s*:\s*([^\n<(]+)(?:\s*\(([^)]+)\))?', context, re.IGNORECASE)
        if date_source_match:
            status_date = date_source_match.group(1).strip()
            if date_source_match.group(2):
                status_source = date_source_match.group(2).strip()
        
        image_invader = image_lieu = None
        if num:
            grosplan = re.search(
                rf'grosplan/{city_code}/{city_code}[-_]?0*{num}-grosplan\.(png|jpg|jpeg)',
                html_content, re.IGNORECASE
            )
            if grosplan:
                image_invader = f"{INVADER_SPOTTER_BASE}/{grosplan.group(0)}"
        
        inv_data = {
            'status': status,
            'points': points,
            'image_invader': image_invader,
            'image_lieu': image_lieu
        }
        
        if landing_date:
            inv_data['landing_date'] = landing_date
        if status_date:
            inv_data['status_date'] = status_date
        if status_source:
            inv_data['status_source'] = status_source
        
        statuses[inv_name] = inv_data
    
    return statuses


async def discover_cities_from_spotter(page, verbose=False):
    """
    Découvre toutes les villes disponibles sur invader-spotter.art
    Retourne un dict {city_code: city_name}
    """
    discovered = {}
    
    try:
        print("🔍 Découverte des villes sur invader-spotter.art...")
        await page.goto(f"{INVADER_SPOTTER_BASE}/villes.php", wait_until='networkidle', timeout=30000)
        await page.wait_for_timeout(2000)
        
        # Récupérer le HTML
        html_content = await page.content()
        
        if verbose:
            print(f"   HTML récupéré: {len(html_content)} caractères")
        
        # Pattern 1: javascript:envoi('CITY_CODE') - case insensitive
        city_pattern = r'javascript:envoi\([\'"]([A-Za-z0-9_]+)[\'"]\)'
        matches = re.findall(city_pattern, html_content, re.IGNORECASE)
        
        # Pattern 2: Liens avec noms - format <a href="javascript:envoi('PA')">Paris</a>
        link_pattern = r'href=["\']javascript:envoi\([\'"]([A-Za-z0-9_]+)[\'"]\)["\'][^>]*>([^<]+)</a>'
        link_matches = re.findall(link_pattern, html_content, re.IGNORECASE)
        
        # Pattern 3: Avec onclick - onclick="envoi('PA')"
        onclick_pattern = r'onclick=["\']envoi\([\'"]([A-Za-z0-9_]+)[\'"]\)["\'][^>]*>([^<]*)</a>'
        onclick_matches = re.findall(onclick_pattern, html_content, re.IGNORECASE)
        
        # Pattern 4: data attributes - data-city="PA" ou data-code="PA"
        data_pattern = r'data-(?:city|code)=["\']([A-Za-z0-9_]+)["\'][^>]*>([^<]*)<'
        data_matches = re.findall(data_pattern, html_content, re.IGNORECASE)
        
        # Pattern 5: Format liste option - <option value="PA">Paris</option>
        option_pattern = r'<option[^>]*value=["\']([A-Za-z0-9_]+)["\'][^>]*>([^<]+)</option>'
        option_matches = re.findall(option_pattern, html_content, re.IGNORECASE)
        
        # Pattern 6: Chercher les codes dans les URLs
        url_pattern = r'/([A-Z]{2,4})[-_]?\d+|ville[=/]([A-Z]{2,4})'
        url_matches = re.findall(url_pattern, html_content)
        
        # Combiner tous les résultats avec noms
        for code, name in link_matches + onclick_matches + data_matches + option_matches:
            code_upper = code.upper()
            if name.strip():
                discovered[code_upper] = name.strip()
        
        # Ajouter les codes sans nom
        for code in matches:
            code_upper = code.upper()
            if code_upper not in discovered:
                discovered[code_upper] = code_upper
        
        # Ajouter depuis les URLs
        for match in url_matches:
            for code in match:
                if code:
                    code_upper = code.upper()
                    if code_upper not in discovered and len(code_upper) >= 2:
                        discovered[code_upper] = code_upper
        
        if verbose:
            print(f"   {len(discovered)} villes découvertes")
            # Afficher les nouvelles villes pas dans CITY_CODES
            known = set(CITY_CODES.keys())
            new_cities = {k: v for k, v in discovered.items() if k not in known}
            if new_cities:
                print(f"   🆕 Nouvelles villes: {list(new_cities.keys())[:10]}...")
        
        # Debug: si aucune ville trouvée, afficher un extrait du HTML
        if not discovered and verbose:
            print("   ⚠️ Aucune ville trouvée! Extrait HTML:")
            print(html_content[:1000])
            
    except Exception as e:
        print(f"⚠️ Erreur découverte villes: {e}")
        import traceback
        traceback.print_exc()
    
    return discovered


async def scrape_all_cities(github_db, cities_filter=None, headless=True, verbose=False, max_retries=3, pause_ms=1000, discover_new=False):
    """Scrape toutes les villes (avec option de découverte des nouvelles)"""
    from playwright.async_api import async_playwright
    
    github_cities = get_cities_from_github(github_db)
    
    all_statuses = {}
    success_count = 0
    new_cities_found = {}
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
        page = await context.new_page()
        
        # Découvrir les nouvelles villes si demandé
        if discover_new:
            spotter_cities = await discover_cities_from_spotter(page, verbose)
            
            # Trouver les villes qui ne sont ni dans GitHub ni dans CITY_CODES
            all_known = set(github_cities.keys()) | set(CITY_CODES.keys())
            new_cities = {c: n for c, n in spotter_cities.items() if c not in all_known}
            
            if new_cities:
                print(f"\n🆕 {len(new_cities)} nouvelles villes découvertes:")
                for code, name in sorted(new_cities.items()):
                    print(f"   - {code}: {name}")
                new_cities_found = new_cities
                
                # Ajouter les nouvelles villes à CITY_CODES dynamiquement
                for code in new_cities:
                    CITY_CODES[code] = code
                    if new_cities[code] != code:
                        CITY_NAMES[code] = new_cities[code]
        
        # Déterminer les villes à scraper
        if cities_filter:
            cities_to_scrape = {c: github_cities.get(c, 0) for c in cities_filter}
        elif discover_new:
            # Scraper toutes les villes connues + nouvelles découvertes
            all_cities = set(github_cities.keys()) | set(CITY_CODES.keys())
            cities_to_scrape = {c: github_cities.get(c, 0) for c in all_cities}
        else:
            # Par défaut: scraper GitHub + toutes les villes de CITY_CODES
            # (certaines villes comme AMI peuvent être dans CITY_CODES mais pas encore dans GitHub)
            all_cities = set(github_cities.keys()) | set(CITY_CODES.keys())
            cities_to_scrape = {c: github_cities.get(c, 0) for c in all_cities}
        
        # Marquer les villes absentes de GitHub
        cities_not_in_github = set(CITY_CODES.keys()) - set(github_cities.keys())
        if cities_not_in_github and verbose:
            print(f"   ℹ️ {len(cities_not_in_github)} villes dans CITY_CODES mais pas dans GitHub: {sorted(cities_not_in_github)[:10]}...")
        
        print(f"\n🌐 Scraping {len(cities_to_scrape)} villes...")
        
        for i, (city_code, count) in enumerate(sorted(cities_to_scrape.items()), 1):
            city_name = CITY_NAMES.get(city_code, city_code)
            is_new = city_code in new_cities_found
            is_not_in_github = city_code in cities_not_in_github
            marker = "🆕 " if is_new else ("📍 " if is_not_in_github else "")
            print(f"   [{i}/{len(cities_to_scrape)}] {marker}{city_code} ({city_name})...", end='', flush=True)
            
            statuses = await scrape_city_playwright(page, city_code, verbose, max_retries)
            
            if statuses:
                all_statuses.update(statuses)
                print(f" ✓ {len(statuses)}")
                success_count += 1
            else:
                print(f" ○")
            
            if i < len(cities_to_scrape):
                await page.wait_for_timeout(pause_ms)
        
        await browser.close()
    
    print(f"\n✅ {success_count}/{len(cities_to_scrape)} villes, {len(all_statuses)} invaders")
    
    if new_cities_found:
        print(f"🆕 {len(new_cities_found)} nouvelles villes ajoutées: {', '.join(sorted(new_cities_found.keys()))}")
    
    return all_statuses


# ============================================================================
# TRAITEMENT DES ISSUES GITHUB
# ============================================================================

# Mapping des statuts depuis les issues
ISSUE_STATUS_MAP = {
    'ok': 'OK', 'good': 'OK', 'good condition': 'OK',
    'damaged': 'damaged', 'degraded': 'damaged', 'abîmé': 'damaged', 'dégradé': 'damaged',
    'destroyed': 'destroyed', 'gone': 'destroyed', 'détruit': 'destroyed', 'disparu': 'destroyed',
    'hidden': 'hidden', 'covered': 'hidden', 'caché': 'hidden', 'masqué': 'hidden',
    'a little damaged': 'a little damaged', 'slightly damaged': 'a little damaged',
}


def fetch_github_issues(repo, token=None, labels=None):
    """
    Récupère les issues ouvertes du repo GitHub.
    
    Args:
        repo: 'user/repo'
        token: GitHub Personal Access Token (optionnel mais recommandé)
        labels: Liste de labels à récupérer (OR logic — fait plusieurs appels)
                Défaut: ['status-update', 'new-invader']
    
    Returns:
        Liste d'issues parsées avec données extraites
    """
    if labels is None:
        labels = ['status-update', 'new-invader']
    elif isinstance(labels, str):
        labels = [labels]
    
    headers = {
        'User-Agent': 'SpaceInvadersDB/1.0',
        'Accept': 'application/vnd.github.v3+json',
    }
    if token:
        headers['Authorization'] = f'token {token}'
    
    print(f"\n📋 Récupération des issues GitHub ({repo})...")
    
    all_issues_raw = []
    seen_ids = set()
    
    for label in labels:
        url = f"https://api.github.com/repos/{repo}/issues?state=open&labels={label}&per_page=100"
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=30) as response:
                issues_raw = json.loads(response.read().decode())
            for issue in issues_raw:
                if issue['id'] not in seen_ids:
                    all_issues_raw.append(issue)
                    seen_ids.add(issue['id'])
        except Exception as e:
            print(f"   ⚠️ Erreur API GitHub (label={label}): {e}")
    
    if not all_issues_raw:
        print(f"   ✅ Aucune issue ouverte")
        return []
    
    print(f"   📥 {len(all_issues_raw)} issues ouvertes trouvées")
    
    parsed_issues = []
    for issue in all_issues_raw:
        parsed = parse_github_issue(issue)
        if parsed:
            parsed_issues.append(parsed)
    
    print(f"   ✅ {len(parsed_issues)} issues parsées avec succès")
    return parsed_issues


def parse_github_issue(issue):
    """
    Parse le body d'une issue GitHub pour extraire les données structurées.
    
    Retourne un dict avec:
        - issue_number, issue_url, issue_date
        - invader_id, city
        - new_status
        - lat, lng, accuracy (si géolocalisation)
        - image_invader, image_lieu (si photos)
        - notes
    """
    body = issue.get('body', '') or ''
    title = issue.get('title', '') or ''
    issue_number = issue.get('number')
    issue_url = issue.get('html_url', '')
    issue_date = issue.get('created_at', '')  # ISO 8601
    
    result = {
        'issue_number': issue_number,
        'issue_url': issue_url,
        'issue_date': issue_date,
        'invader_id': None,
        'city': None,
        'new_status': None,
        'points': None,
        'is_new_invader': False,
        'lat': None,
        'lng': None,
        'accuracy': None,
        'image_invader': None,
        'image_lieu': None,
        'notes': None,
        'labels': [l.get('name', '') for l in issue.get('labels', [])],
    }
    
    # Détecter si c'est un nouvel invader
    result['is_new_invader'] = 'new-invader' in result['labels'] or '[New Invader]' in title
    
    # Extraire l'invader ID depuis le title ou le body
    # Title format: "[Status Update] PA_1529: OK → Destroyed"
    title_match = re.search(r'\]\s*([A-Z]+[-_]\d+)', title, re.IGNORECASE)
    if title_match:
        result['invader_id'] = title_match.group(1).upper().replace('-', '_')
    
    # Body format: **Invader:** `PA_1529`
    body_match = re.search(r'\*\*Invader:\*\*\s*`?([A-Z]+[-_]\d+)`?', body, re.IGNORECASE)
    if body_match:
        result['invader_id'] = body_match.group(1).upper().replace('-', '_')
    
    if not result['invader_id']:
        return None  # Pas un report d'invader valide
    
    # Extraire la ville
    city_match = re.search(r'\*\*City:\*\*\s*(.+)', body)
    if city_match:
        result['city'] = city_match.group(1).strip()
    
    # Extraire le nouveau statut
    # Format table: | New observed status | **Destroyed** |
    status_match = re.search(r'New observed status\s*\|\s*\*?\*?([^|*\n]+)', body, re.IGNORECASE)
    if status_match:
        raw_status = status_match.group(1).strip()
        # Nettoyer les emojis et espaces
        raw_status = re.sub(r'[✅⚠️💀👁🔨]', '', raw_status).strip()
        result['new_status'] = ISSUE_STATUS_MAP.get(raw_status.lower(), raw_status)
    
    # Format new-invader: **Status:** OK
    if not result['new_status']:
        simple_status = re.search(r'\*\*Status:\*\*\s*(.+)', body)
        if simple_status:
            raw = simple_status.group(1).strip()
            raw = re.sub(r'[✅⚠️💀👁🔨]', '', raw).strip()
            result['new_status'] = ISSUE_STATUS_MAP.get(raw.lower(), raw)
    
    # Aussi chercher dans le titre: "OK → Destroyed"
    if not result['new_status']:
        arrow_match = re.search(r'→\s*(\w+)', title)
        if arrow_match:
            raw = arrow_match.group(1).strip()
            result['new_status'] = ISSUE_STATUS_MAP.get(raw.lower(), raw)
    
    # Extraire les points (new-invader)
    points_match = re.search(r'\*\*Points:\*\*\s*(\d+)', body)
    if points_match:
        result['points'] = int(points_match.group(1))
    
    # Extraire les coordonnées GPS
    lat_match = re.search(r'\*\*Latitude:\*\*\s*([-\d.]+)', body)
    lng_match = re.search(r'\*\*Longitude:\*\*\s*([-\d.]+)', body)
    if lat_match and lng_match:
        try:
            result['lat'] = float(lat_match.group(1))
            result['lng'] = float(lng_match.group(1))
        except ValueError:
            pass
    
    acc_match = re.search(r'\*\*GPS Accuracy:\*\*\s*±(\d+)', body)
    if acc_match:
        result['accuracy'] = int(acc_match.group(1))
    
    # Extraire les images
    img_inv_match = re.search(r'\*\*Image invader:\*\*\s*(https?://\S+)', body)
    if img_inv_match:
        result['image_invader'] = img_inv_match.group(1)
    
    img_lieu_match = re.search(r'\*\*Image location:\*\*\s*(https?://\S+)', body)
    if img_lieu_match:
        result['image_lieu'] = img_lieu_match.group(1)
    
    # Extraire les notes
    notes_match = re.search(r'### Notes\s*\n(.+?)(?:\n###|\n---|\Z)', body, re.DOTALL)
    if notes_match:
        notes = notes_match.group(1).strip()
        if notes and notes != '_No additional notes_':
            result['notes'] = notes
    
    return result


def close_github_issue(repo, issue_number, token, comment=None):
    """Ferme une issue GitHub avec un commentaire optionnel."""
    if not token:
        print(f"   ⚠️ Pas de token GitHub, issue #{issue_number} non fermée")
        return False
    
    headers = {
        'User-Agent': 'SpaceInvadersDB/1.0',
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': f'token {token}',
        'Content-Type': 'application/json',
    }
    
    # Ajouter un commentaire
    if comment:
        comment_url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
        comment_data = json.dumps({'body': comment}).encode()
        try:
            req = Request(comment_url, data=comment_data, headers=headers, method='POST')
            urlopen(req, timeout=15)
        except Exception as e:
            print(f"   ⚠️ Erreur commentaire issue #{issue_number}: {e}")
    
    # Fermer l'issue
    close_url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    close_data = json.dumps({'state': 'closed'}).encode()
    try:
        req = Request(close_url, data=close_data, headers=headers, method='PATCH')
        urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"   ⚠️ Erreur fermeture issue #{issue_number}: {e}")
        return False


def apply_github_issues(master_db, issues, repo=None, token=None, verbose=False, dry_run=False):
    """
    Applique les issues GitHub au master.
    
    Pour chaque issue:
    - Met à jour le statut si renseigné
    - Met à jour les coordonnées si fournies
    - Met à jour les images si fournies
    - Marque status_source='community_issue' et status_updated avec la date de l'issue
    - Ferme l'issue après traitement
    
    Returns:
        (master_db modifié, liste des changements appliqués)
    """
    if not issues:
        return master_db, []
    
    print(f"\n🐙 Application de {len(issues)} issues GitHub...")
    
    # Indexer le master par ID
    master_index = {}
    for i, inv in enumerate(master_db):
        inv_id = inv.get('id', inv.get('name', '')).upper().replace('-', '_')
        master_index[inv_id] = i
    
    changes = []
    applied = 0
    new_invaders = 0
    
    for issue in issues:
        inv_id = issue['invader_id']
        if not inv_id:
            continue
        
        if verbose:
            print(f"\n   📋 Issue #{issue['issue_number']}: {inv_id}")
        
        if inv_id in master_index:
            idx = master_index[inv_id]
            inv = master_db[idx]
            
            # Mettre à jour le statut
            if issue['new_status']:
                old_status = inv.get('status', 'OK')
                new_status = issue['new_status']
                
                if old_status.lower() != new_status.lower():
                    # Sauvegarder l'historique
                    inv['previous_status'] = old_status
                    if inv.get('status_date'):
                        inv['previous_status_date'] = inv['status_date']
                    
                    inv['status'] = new_status
                    inv['status_source'] = 'community_issue'
                    inv['status_updated'] = issue['issue_date']
                    inv['status_issue'] = issue['issue_number']
                    
                    changes.append({
                        'name': inv_id,
                        'old_status': old_status,
                        'new_status': new_status,
                        'source': f"issue #{issue['issue_number']}",
                        'date': issue['issue_date'],
                    })
                    if verbose:
                        print(f"      🔄 Statut: {old_status} → {new_status}")
            
            # Mettre à jour les coordonnées
            if issue['lat'] is not None and issue['lng'] is not None:
                old_lat = inv.get('lat', 0)
                old_lng = inv.get('lng', 0)
                inv['lat'] = issue['lat']
                inv['lng'] = issue['lng']
                inv['geo_source'] = 'community_issue'
                inv['geo_confidence'] = 'high' if (issue.get('accuracy', 999) < 50) else 'medium'
                inv['location_unknown'] = False
                if verbose:
                    print(f"      📍 GPS: ({old_lat:.4f},{old_lng:.4f}) → ({issue['lat']:.6f},{issue['lng']:.6f})")
            
            # Mettre à jour les images
            if issue.get('image_invader'):
                inv['image_invader'] = issue['image_invader']
                if verbose:
                    print(f"      📸 Image invader ajoutée")
            if issue.get('image_lieu'):
                inv['image_lieu'] = issue['image_lieu']
                if verbose:
                    print(f"      📸 Image lieu ajoutée")
            
            master_db[idx] = inv
            applied += 1
            
        else:
            # Invader inconnu — l'ajouter comme nouveau
            city_match = re.match(r'^([A-Z]+)[-_]', inv_id)
            city_code = city_match.group(1) if city_match else None
            
            new_inv = {
                'id': inv_id,
                'status': issue.get('new_status', 'OK'),
                'city': city_code,
                'points': issue.get('points', 0),
                'lat': issue.get('lat', 0),
                'lng': issue.get('lng', 0),
                'status_source': 'community_issue',
                'status_updated': issue['issue_date'],
                'status_issue': issue['issue_number'],
                'missing_from_github': True,
                'added_date': datetime.now().isoformat(),
            }
            if issue.get('image_invader'):
                new_inv['image_invader'] = issue['image_invader']
            if issue.get('image_lieu'):
                new_inv['image_lieu'] = issue['image_lieu']
            if issue.get('lat') is not None:
                new_inv['geo_source'] = 'community_issue'
                new_inv['geo_confidence'] = 'high' if (issue.get('accuracy', 999) < 50) else 'medium'
                new_inv['location_unknown'] = False
            else:
                new_inv['location_unknown'] = True
            
            master_db.append(new_inv)
            master_index[inv_id] = len(master_db) - 1
            new_invaders += 1
            applied += 1
            
            if verbose:
                print(f"      ➕ Nouvel invader ajouté")
        
        # Fermer l'issue
        if not dry_run and repo and token:
            comment = f"✅ **Applied to database**\n\n"
            if issue['new_status']:
                comment += f"- Status updated to: **{issue['new_status']}**\n"
            if issue.get('lat') is not None:
                comment += f"- Location updated: ({issue['lat']:.6f}, {issue['lng']:.6f})\n"
            if issue.get('image_invader') or issue.get('image_lieu'):
                comment += f"- Images updated\n"
            comment += f"\n_Processed by update_from_spotter.py on {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC_"
            
            if close_github_issue(repo, issue['issue_number'], token, comment):
                if verbose:
                    print(f"      ✅ Issue #{issue['issue_number']} fermée")
    
    print(f"\n   📊 Résumé issues:")
    print(f"      ✅ {applied} issues appliquées")
    print(f"      🔄 {len(changes)} changements de statut")
    print(f"      ➕ {new_invaders} nouveaux invaders")
    
    return master_db, changes


# ============================================================================
# FUSION
# ============================================================================

def merge_databases(github_db, spotter_statuses, community_reports=None, previous_db=None):
    """
    Fusionne les données avec préservation des anciennes données.
    
    Version v4 : Gestion de l'historique des statuts
    - Quand un statut change, sauvegarde previous_status et previous_status_date
    - Copie les nouveaux champs v4 : landing_date, status_date, status_source
    """
    print("\n🔀 Fusion des données...")
    
    changes, updated_db = [], []
    matched = 0
    preserved_count = 0
    v4_fields_added = {'landing_date': 0, 'status_date': 0, 'status_source': 0}
    status_history_saved = 0
    
    # Charger l'ancienne version si elle existe
    if previous_db is None and MASTER_FILE.exists():
        try:
            with open(_p(MASTER_FILE), 'r', encoding='utf-8') as f:
                previous_db = json.load(f)
            print(f"   📂 Ancienne version chargée: {len(previous_db)} invaders")
        except:
            previous_db = []
    
    # Indexer l'ancienne version par nom
    previous_by_name = {}
    if previous_db:
        for inv in previous_db:
            name = inv.get('id', inv.get('name', '')).upper().replace('-', '_')
            previous_by_name[name] = inv
    
    # Construire l'ensemble des noms GitHub (toutes variantes)
    github_names = set()
    for inv in github_db:
        name = inv.get('id', inv.get('name', '')).upper().replace('-', '_')
        github_names.add(name)
        m = re.match(r'([A-Z]+)[-_]?(\d+)', name, re.IGNORECASE)
        if m:
            prefix, num = m.group(1).upper(), m.group(2)
            github_names.add(f"{prefix}_{num}")
            github_names.add(f"{prefix}_{num.zfill(4)}")
            github_names.add(f"{prefix}{num}")
    
    # Tracker les invaders spotter matchés
    matched_spotter = set()
    
    # Tracker les noms traités
    processed_names = set()
    
    reports_by_name = {}
    if community_reports:
        for r in community_reports:
            name = r.get('invader_name', '').upper().replace('-', '_')
            if name and r.get('verified'):
                reports_by_name[name] = r
    
    for inv in github_db:
        name = inv.get('id', inv.get('name', ''))
        old_status = inv.get('status', 'OK')
        
        updated_inv = {
            'id': name.upper().replace('-', '_'),
            'lat': inv.get('lat', inv.get('latitude', 0)),
            'lng': inv.get('lng', inv.get('lon', inv.get('longitude', 0))),
            'points': inv.get('points', inv.get('pts', 0)),
            'status': old_status,
        }
        
        for field in ['hint', 'image_invader', 'image_lieu', 'city']:
            if inv.get(field):
                updated_inv[field] = inv[field]
        
        # Préserver les champs v4 existants depuis l'ancienne version
        norm_name = updated_inv['id']
        if norm_name in previous_by_name:
            prev_inv = previous_by_name[norm_name]
            for v4_field in ['landing_date', 'status_date', 'status_source', 'status_updated', 'status_issue',
                            'previous_status', 'previous_status_date',
                            'geo_source', 'geo_confidence', 'location_unknown', 'address',
                            'image_invader', 'image_lieu']:
                if prev_inv.get(v4_field) and not updated_inv.get(v4_field):
                    updated_inv[v4_field] = prev_inv[v4_field]
        
        if not updated_inv.get('city'):
            m = re.match(r'^([A-Z]+)[-_]', name)
            if m:
                updated_inv['city'] = m.group(1)
        
        # Variantes de noms
        variants = [name]
        m = re.match(r'([A-Z]+)[-_]?(\d+)', name, re.IGNORECASE)
        if m:
            prefix, num = m.group(1).upper(), m.group(2)
            variants.extend([f"{prefix}_{num}", f"{prefix}_{num.zfill(4)}", name.upper().replace('-', '_')])
        
        # Chercher dans scraping
        spotter_data = None
        for v in variants:
            if v in spotter_statuses:
                spotter_data = spotter_statuses[v]
                matched_spotter.add(v)  # Tracker les matchés
                matched += 1
                break
        
        if spotter_data:
            new_status = spotter_data.get('status', 'OK')
            old_status_lower = old_status.lower()
            new_status_lower = new_status.lower()
            
            # V5: Vérifier si le statut actuel vient d'une issue communautaire récente
            # Si oui, ne PAS écraser avec le statut Spotter (l'issue est plus fiable/récente)
            skip_status_update = False
            if norm_name in previous_by_name:
                prev = previous_by_name[norm_name]
                if prev.get('status_source') == 'community_issue' and prev.get('status_updated'):
                    try:
                        issue_date = datetime.fromisoformat(prev['status_updated'].replace('Z', '+00:00'))
                        # L'issue a moins de 90 jours → on la respecte
                        days_since_issue = (datetime.now(issue_date.tzinfo) - issue_date).days if issue_date.tzinfo else (datetime.now() - issue_date).days
                        if days_since_issue < 90:
                            skip_status_update = True
                            # Conserver le statut de l'issue
                            updated_inv['status'] = prev['status']
                            updated_inv['status_source'] = prev.get('status_source')
                            updated_inv['status_updated'] = prev.get('status_updated')
                            updated_inv['status_issue'] = prev.get('status_issue')
                    except (ValueError, TypeError):
                        pass
            
            # V4: Le parsing textuel est fiable, on fait confiance au nouveau statut
            if not skip_status_update and new_status_lower != old_status_lower:
                # ============================================
                # V4: Sauvegarder l'historique du statut
                # ============================================
                # Récupérer l'ancienne date du statut si disponible
                old_status_date = updated_inv.get('status_date')
                
                # Sauvegarder le statut précédent
                updated_inv['previous_status'] = old_status
                if old_status_date:
                    updated_inv['previous_status_date'] = old_status_date
                status_history_saved += 1
                
                changes.append({
                    'name': name, 
                    'old_status': old_status, 
                    'new_status': new_status, 
                    'source': 'scraping',
                    'old_status_date': old_status_date
                })
                updated_inv['status'] = new_status
                updated_inv['status_updated'] = datetime.now().isoformat()
            
            # ============================================
            # V4: Copier les nouveaux champs
            # ============================================
            if spotter_data.get('landing_date'):
                updated_inv['landing_date'] = spotter_data['landing_date']
                v4_fields_added['landing_date'] += 1
            
            if spotter_data.get('status_date'):
                updated_inv['status_date'] = spotter_data['status_date']
                v4_fields_added['status_date'] += 1
            
            if spotter_data.get('status_source'):
                updated_inv['status_source'] = spotter_data['status_source']
                v4_fields_added['status_source'] += 1
            
            # Copier les images
            if spotter_data.get('image_invader'):
                updated_inv['image_invader'] = spotter_data['image_invader']
            if spotter_data.get('image_lieu'):
                updated_inv['image_lieu'] = spotter_data['image_lieu']
        
        # Signalements communautaires
        norm_name = updated_inv['id']
        if norm_name in reports_by_name:
            r = reports_by_name[norm_name]
            new_status = r.get('reported_status', '')
            if new_status and new_status.lower() != updated_inv['status'].lower():
                # V4: Sauvegarder l'historique avant mise à jour communautaire
                old_status_date = updated_inv.get('status_date')
                updated_inv['previous_status'] = updated_inv['status']
                if old_status_date:
                    updated_inv['previous_status_date'] = old_status_date
                status_history_saved += 1
                
                changes.append({'name': name, 'old_status': updated_inv['status'], 'new_status': new_status, 'source': 'community'})
                updated_inv['status'] = new_status
                updated_inv['status_updated'] = datetime.now().isoformat()
        
        # Tracker le nom comme traité
        processed_names.add(norm_name)
        updated_db.append(updated_inv)
    
    # Préserver les invaders de l'ancienne version qui ne sont plus dans GitHub
    if previous_by_name:
        for prev_name, prev_inv in previous_by_name.items():
            if prev_name not in processed_names:
                # Cet invader était dans l'ancienne version mais plus dans GitHub
                # On le préserve avec un tag
                preserved_inv = prev_inv.copy()
                preserved_inv['preserved'] = True
                preserved_inv['preserved_date'] = datetime.now().isoformat()
                updated_db.append(preserved_inv)
                preserved_count += 1
    
    # Trouver les invaders sur Spotter mais pas dans GitHub
    not_in_github = []
    for spotter_name, spotter_data in spotter_statuses.items():
        # Vérifier si cet invader a été matché
        if spotter_name not in matched_spotter:
            # Vérifier aussi avec les variantes
            norm_name = spotter_name.upper().replace('-', '_')
            m = re.match(r'([A-Z]+)[-_]?(\d+)', norm_name)
            if m:
                prefix, num = m.group(1), m.group(2)
                variants_check = [norm_name, f"{prefix}_{num}", f"{prefix}{num}", f"{prefix}_{num.zfill(4)}"]
                if not any(v in github_names for v in variants_check):
                    inv_data = {
                        'name': spotter_name,
                        'status': spotter_data.get('status', 'OK'),
                        'points': spotter_data.get('points', 0),
                        'image_invader': spotter_data.get('image_invader'),
                        'image_lieu': spotter_data.get('image_lieu'),
                        'city': prefix if m else None
                    }
                    # V4: Inclure les nouveaux champs pour les invaders manquants
                    for v4_field in ['landing_date', 'status_date', 'status_source']:
                        if spotter_data.get(v4_field):
                            inv_data[v4_field] = spotter_data[v4_field]
                    not_in_github.append(inv_data)
            else:
                inv_data = {
                    'name': spotter_name,
                    'status': spotter_data.get('status', 'OK'),
                    'points': spotter_data.get('points', 0),
                    'image_invader': spotter_data.get('image_invader'),
                    'image_lieu': spotter_data.get('image_lieu'),
                    'city': None
                }
                for v4_field in ['landing_date', 'status_date', 'status_source']:
                    if spotter_data.get(v4_field):
                        inv_data[v4_field] = spotter_data[v4_field]
                not_in_github.append(inv_data)
    
    # V4: Afficher les statistiques enrichies
    print(f"   {matched} matchés, {len(changes)} changements, {preserved_count} préservés, {len(not_in_github)} non référencés")
    print(f"   📅 V4: {v4_fields_added['landing_date']} dates de pose, {v4_fields_added['status_date']} dates de statut, {status_history_saved} historiques sauvés")
    return updated_db, changes, not_in_github


def save_files(updated_db, scraped_data, changes, not_in_github=None, geolocated=None, geo_audits=None, backup=False, dry_run=False):
    """Sauvegarde les fichiers"""
    if dry_run:
        print(f"\n🔍 Dry-run: {len(updated_db)} invaders, {len(changes)} changements")
        if not_in_github:
            print(f"   {len(not_in_github)} invaders non référencés dans GitHub")
        if geolocated:
            print(f"   {len(geolocated)} géolocalisés")
        if geo_audits:
            print(f"   {len(geo_audits)} audits de géolocalisation")
        return
    
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if backup and MASTER_FILE.exists():
        backup_path = DATA_DIR / f'invaders_backup_{ts}.json'
        os.rename(_p(MASTER_FILE), _p(backup_path))
        print(f"\n💾 Backup créé: {backup_path.name}")
    
    with open(_p(MASTER_FILE), 'w', encoding='utf-8') as f:
        json.dump(updated_db, f, ensure_ascii=False, indent=2)
    print(f"\n💾 {MASTER_FILE.name} ({len(updated_db)} invaders)")
    
    if scraped_data:
        with open(_p(SCRAPED_FILE), 'w', encoding='utf-8') as f:
            json.dump(scraped_data, f, ensure_ascii=False, indent=2)
        print(f"💾 {SCRAPED_FILE.name} ({len(scraped_data)} invaders)")
    
    # Sauvegarder les invaders non référencés dans GitHub
    if not_in_github:
        # Trier par ville puis par nom
        not_in_github_sorted = sorted(not_in_github, key=lambda x: (x.get('city') or 'ZZZ', x.get('name', '')))
        
        with open(_p(MISSING_FILE), 'w', encoding='utf-8') as f:
            json.dump(not_in_github_sorted, f, ensure_ascii=False, indent=2)
        print(f"💾 {MISSING_FILE.name} ({len(not_in_github)} invaders)")
        
        # Créer aussi un fichier texte lisible
        with open(_p(MISSING_TXT), 'w', encoding='utf-8') as f:
            f.write(f"Invaders présents sur invader-spotter.art mais absents de GitHub\n")
            f.write(f"Généré le {datetime.now()}\n")
            f.write(f"{'='*60}\n\n")
            f.write(f"Total: {len(not_in_github)} invaders sans géolocalisation\n\n")
            
            # Grouper par ville
            by_city = defaultdict(list)
            for inv in not_in_github_sorted:
                city = inv.get('city') or 'INCONNU'
                by_city[city].append(inv)
            
            for city in sorted(by_city.keys()):
                invs = by_city[city]
                f.write(f"\n{city} ({len(invs)} invaders)\n")
                f.write(f"{'-'*40}\n")
                for inv in invs:
                    status = inv.get('status', 'OK')
                    status_str = f" [{status}]" if status != 'OK' else ""
                    f.write(f"  • {inv['name']}{status_str}\n")
                    # V4: Afficher les dates si disponibles
                    if inv.get('landing_date'):
                        f.write(f"    📅 Posé le: {inv['landing_date']}\n")
                    if inv.get('status_date'):
                        source = f" ({inv['status_source']})" if inv.get('status_source') else ""
                        f.write(f"    📆 Statut: {inv['status_date']}{source}\n")
                    if inv.get('image_invader'):
                        f.write(f"    📷 {inv['image_invader']}\n")
        print(f"📄 {MISSING_TXT.name}")
    
    with open(_p(REPORT_FILE), 'w', encoding='utf-8') as f:
        f.write(f"Rapport de mise à jour v4 - {datetime.now()}\n{'='*60}\n")
        f.write(f"Total: {len(updated_db)}, Changements: {len(changes)}\n")
        if not_in_github:
            f.write(f"Non référencés dans GitHub: {len(not_in_github)}\n")
        
        # V4: Statistiques des nouveaux champs
        landing_count = sum(1 for inv in updated_db if inv.get('landing_date'))
        status_date_count = sum(1 for inv in updated_db if inv.get('status_date'))
        status_source_count = sum(1 for inv in updated_db if inv.get('status_source'))
        history_count = sum(1 for inv in updated_db if inv.get('previous_status'))
        
        f.write(f"\n📅 Informations v4:\n")
        f.write(f"   Avec date de pose (landing_date): {landing_count}\n")
        f.write(f"   Avec date de statut (status_date): {status_date_count}\n")
        f.write(f"   Avec source de statut (status_source): {status_source_count}\n")
        f.write(f"   Avec historique de statut: {history_count}\n")
        
        f.write("\n")
        if changes:
            f.write(f"\n🔄 Changements de statut:\n")
            f.write(f"{'-'*50}\n")
            for c in changes:
                old_date = c.get('old_status_date', '')
                date_info = f" (était: {old_date})" if old_date else ""
                f.write(f"{c['name']}: {c['old_status']} → {c['new_status']}{date_info} [{c.get('source','')}]\n")
    print(f"📄 {REPORT_FILE.name}")
    
    if changes:
        print(f"\n📊 {len(changes)} changements:")
        for c in changes[:10]:
            print(f"   {c['name']}: {c['old_status']} → {c['new_status']}")
        if len(changes) > 10:
            print(f"   ... +{len(changes)-10}")
    
    if not_in_github:
        print(f"\n🆕 {len(not_in_github)} invaders non référencés dans GitHub:")
        by_city = defaultdict(int)
        for inv in not_in_github:
            by_city[inv.get('city') or 'INCONNU'] += 1
        for city, count in sorted(by_city.items(), key=lambda x: -x[1])[:10]:
            print(f"   {city}: {count}")
        if len(by_city) > 10:
            print(f"   ... +{len(by_city)-10} villes")
    
    # Sauvegarder les résultats de géolocalisation
    if geolocated:
        with open(_p(GEOLOCATED_FILE), 'w', encoding='utf-8') as f:
            json.dump(geolocated, f, ensure_ascii=False, indent=2)
        print(f"\n📍 {GEOLOCATED_FILE.name} ({len(geolocated)} invaders)")
        
        # Créer aussi un fichier texte
        with open(_p(GEOLOCATED_TXT), 'w', encoding='utf-8') as f:
            f.write(f"Invaders géolocalisés par recherche web\n")
            f.write(f"Généré le {datetime.now()}\n")
            f.write(f"{'='*60}\n\n")
            f.write(f"⚠️ ATTENTION: Ces coordonnées sont approximatives et doivent être vérifiées!\n\n")
            
            for inv in geolocated:
                f.write(f"{inv.get('name', '?')}\n")
                if inv.get('lat') and inv.get('lng'):
                    f.write(f"  📍 {inv['lat']:.6f}, {inv['lng']:.6f}\n")
                    f.write(f"  🔗 https://www.google.com/maps?q={inv['lat']},{inv['lng']}\n")
                if inv.get('address_hint'):
                    f.write(f"  🏠 {inv['address_hint']}\n")
                f.write(f"  Confiance: {inv.get('geo_confidence', 'inconnue')}\n\n")
        print(f"📄 {GEOLOCATED_TXT.name}")
    
    # Sauvegarder le fichier d'audit détaillé
    if geo_audits:
        with open(_p(GEOLOC_AUDIT_JSON), 'w', encoding='utf-8') as f:
            json.dump(geo_audits, f, ensure_ascii=False, indent=2)
        print(f"📋 {GEOLOC_AUDIT_JSON.name} ({len(geo_audits)} audits)")
        
        # Créer un fichier texte lisible pour l'audit
        with open(_p(GEOLOC_AUDIT_TXT), 'w', encoding='utf-8') as f:
            f.write(f"AUDIT DE GÉOLOCALISATION - Rapport détaillé\n")
            f.write(f"Généré le {datetime.now()}\n")
            f.write(f"{'='*80}\n\n")
            
            # Stats globales
            found_count = sum(1 for a in geo_audits if a.get('final_result'))
            captcha_count = sum(1 for a in geo_audits if a.get('captcha_detected'))
            f.write(f"📊 STATISTIQUES\n")
            f.write(f"   Total traités: {len(geo_audits)}\n")
            f.write(f"   Géolocalisés: {found_count}\n")
            f.write(f"   Non trouvés: {len(geo_audits) - found_count}\n")
            f.write(f"   CAPTCHAs rencontrés: {captcha_count}\n\n")
            f.write(f"{'='*80}\n\n")
            
            for audit in geo_audits:
                f.write(f"{'─'*80}\n")
                f.write(f"🔍 {audit.get('invader', '?')}\n")
                f.write(f"{'─'*80}\n")
                f.write(f"   Ville: {audit.get('city_name', audit.get('city_code', '?'))}\n")
                f.write(f"   Statut: {audit.get('status', 'OK')}\n")
                f.write(f"   Points: {audit.get('points', '?')}\n")
                
                if audit.get('image_invader'):
                    f.write(f"   📷 Image invader: {audit['image_invader']}\n")
                if audit.get('image_lieu'):
                    f.write(f"   📷 Image lieu: {audit['image_lieu']}\n")
                
                f.write(f"\n   📡 SOURCES TESTÉES:\n")
                for source in audit.get('sources_tried', []):
                    status_icon = '✓' if source.get('result') else ('⚠️' if source.get('error') else '○')
                    f.write(f"      {status_icon} {source.get('name', '?')}\n")
                    if source.get('url'):
                        f.write(f"         URL: {source['url'][:80]}...\n")
                    if source.get('result'):
                        r = source['result']
                        if r.get('lat'):
                            f.write(f"         → Coordonnées: {r['lat']:.6f}, {r['lng']:.6f}\n")
                        if r.get('address'):
                            f.write(f"         → Adresse: {r['address']}\n")
                        f.write(f"         → Confiance: {r.get('confidence', '?')}\n")
                    if source.get('error'):
                        f.write(f"         ❌ Erreur: {source['error']}\n")
                
                if audit.get('addresses_found'):
                    f.write(f"\n   🏠 ADRESSES TROUVÉES:\n")
                    for addr in audit['addresses_found']:
                        f.write(f"      • {addr.get('address', '?')} (source: {addr.get('source', '?')})\n")
                
                if audit.get('coordinates_found'):
                    f.write(f"\n   📍 COORDONNÉES TROUVÉES:\n")
                    for coord in audit['coordinates_found']:
                        f.write(f"      • {coord.get('lat', '?')}, {coord.get('lng', '?')} (source: {coord.get('source', '?')})\n")
                
                if audit.get('arrondissement'):
                    f.write(f"\n   🗺️ ARRONDISSEMENT: {audit['arrondissement']}e\n")
                
                if audit.get('captcha_detected'):
                    f.write(f"\n   ⚠️ CAPTCHA DÉTECTÉ!\n")
                
                if audit.get('errors'):
                    f.write(f"\n   ❌ ERREURS:\n")
                    for err in audit['errors']:
                        f.write(f"      • {err}\n")
                
                # Résultat final
                f.write(f"\n   🎯 RÉSULTAT FINAL: ")
                if audit.get('final_result'):
                    r = audit['final_result']
                    if r.get('lat'):
                        f.write(f"✓ ({r['lat']:.6f}, {r['lng']:.6f}) [{r.get('confidence', '?')}]\n")
                        f.write(f"      🔗 https://www.google.com/maps?q={r['lat']},{r['lng']}\n")
                    elif r.get('address'):
                        f.write(f"✓ Adresse: {r['address']} [{r.get('confidence', '?')}]\n")
                else:
                    f.write(f"○ Non trouvé\n")
                
                f.write(f"\n")
        
        print(f"📄 invaders_geoloc_audit.txt")


# =============================================================================
# GÉOLOCALISATION DES INVADERS MANQUANTS (depuis invaders_missing_from_github.json)
# =============================================================================

def calculate_distance(lat1, lng1, lat2, lng2):
    """Calcule la distance en mètres entre deux points GPS (formule Haversine)"""
    R = 6371000  # Rayon de la Terre en mètres
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    
    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c


class MissingInvaderSearcher:
    """Recherche de coordonnées GPS pour les invaders manquants via AroundUs et IlluminateArt"""
    
    def __init__(self, page, verbose=False):
        self.page = page
        self.verbose = verbose
        self.google_consent_handled = False
    
    def log(self, msg):
        if self.verbose:
            print(f"      {msg}")
    
    def _format_invader_id(self, invader_id):
        """Normalise l'ID: PA_01 → PA_01, PA1 → PA_01"""
        match = re.match(r'^([A-Z]+)[_-]?(\d+)$', invader_id.upper())
        if match:
            prefix = match.group(1)
            num = int(match.group(2))
            return f"{prefix}_{num:02d}"
        return invader_id.upper()
    
    def _handle_google_consent(self):
        """Gère le popup de consentement Google"""
        if self.google_consent_handled:
            return
        try:
            buttons = self.page.locator('button')
            for i in range(buttons.count()):
                text = buttons.nth(i).text_content().lower()
                if any(x in text for x in ['accept', 'accepter', 'tout accepter', 'accept all']):
                    buttons.nth(i).click()
                    self.google_consent_handled = True
                    time.sleep(1)
                    break
        except:
            pass
    
    def _handle_site_consent(self):
        """Gère les popups de consentement des sites"""
        try:
            for selector in ['button:has-text("Accept")', 'button:has-text("Accepter")', 
                            '.accept-cookies', '#accept-cookies', '[aria-label="Accept"]']:
                btn = self.page.locator(selector).first
                if btn.is_visible():
                    btn.click()
                    time.sleep(0.5)
                    break
        except:
            pass
    
    def _extract_urls_from_google(self, content):
        """Extrait les URLs des résultats Google"""
        results = []
        
        # Pattern 1: URLs dans les redirections Google
        redirect_pattern = r'/url\?q=([^&]+)&'
        for url in re.findall(redirect_pattern, content):
            decoded = unquote(url)
            if decoded.startswith('http') and decoded not in [r['url'] for r in results]:
                results.append({'url': decoded, 'extraction_method': 'google_redirect'})
        
        # Pattern 2: URLs directes
        direct_pattern = r'href="(https?://[^"]+)"'
        for url in re.findall(direct_pattern, content):
            if url not in [r['url'] for r in results]:
                if not any(x in url for x in ['google.com/search', 'accounts.google']):
                    results.append({'url': url, 'extraction_method': 'direct_href'})
        
        return results
    
    def search_aroundus(self, invader_id, city_name=None):
        """Recherche sur AroundUs via Google"""
        result = {'source': 'aroundus', 'found': False, 'lat': None, 'lng': None, 'address': None, 'url': None}
        
        try:
            formatted_id = self._format_invader_id(invader_id)
            google_query = f"site:aroundus.com {invader_id}"
            google_url = f"https://www.google.com/search?q={quote(google_query)}"
            
            self.log(f"[AroundUs] Google: {google_query}")
            self.page.goto(google_url, timeout=20000)
            time.sleep(2)
            self._handle_google_consent()
            
            content = self.page.content()
            urls = self._extract_urls_from_google(content)
            
            # Filtrer pour ne garder que https://xx.aroundus.com/p/...
            target_urls = []
            for item in urls:
                url = item['url'].lower()
                if re.match(r'https?://[a-z]{2}\.aroundus\.com/p/', url):
                    if formatted_id.lower() in url or invader_id.lower() in url:
                        target_urls.append(item['url'])
            
            self.log(f"[AroundUs] {len(target_urls)} URLs valides trouvées")
            
            # Visiter la première URL valide
            for url in target_urls[:2]:
                self.log(f"[AroundUs] → Visite: {url[:60]}...")
                self.page.goto(url, timeout=20000)
                time.sleep(3)
                
                page_content = self.page.content()
                
                # Méthode 1: JSON-LD (le plus fiable)
                json_match = re.search(
                    r'"geo"\s*:\s*\{\s*"@type"\s*:\s*"GeoCoordinates"\s*,\s*"latitude"\s*:\s*"?([-\d.]+)"?\s*,\s*"longitude"\s*:\s*"?([-\d.]+)"?',
                    page_content
                )
                if json_match:
                    lat, lng = float(json_match.group(1)), float(json_match.group(2))
                    if -90 <= lat <= 90 and -180 <= lng <= 180:
                        result['found'] = True
                        result['lat'] = lat
                        result['lng'] = lng
                        result['url'] = url
                        self.log(f"[AroundUs] ✅ GPS (JSON-LD): {lat:.6f}, {lng:.6f}")
                
                # Méthode 2: Patterns HTML
                if not result['found']:
                    for pattern in [
                        r'<strong>GPS\s*coordinates?:</strong>\s*([-\d.]+)\s*,\s*([-\d.]+)',
                        r'<strong>Coordonn[ée]es\s*GPS\s*:</strong>\s*([-\d.]+)\s*,\s*([-\d.]+)',
                    ]:
                        match = re.search(pattern, page_content, re.IGNORECASE)
                        if match:
                            lat, lng = float(match.group(1)), float(match.group(2))
                            if -90 <= lat <= 90 and -180 <= lng <= 180:
                                result['found'] = True
                                result['lat'] = lat
                                result['lng'] = lng
                                result['url'] = url
                                self.log(f"[AroundUs] ✅ GPS (HTML): {lat:.6f}, {lng:.6f}")
                                break
                
                # Extraire l'adresse
                for pattern in [r'<strong>Address:</strong>\s*([^<]+)', r'<strong>Adresse\s*:</strong>\s*([^<]+)']:
                    addr_match = re.search(pattern, page_content, re.IGNORECASE)
                    if addr_match:
                        result['address'] = addr_match.group(1).strip()
                        self.log(f"[AroundUs] 📫 Adresse: {result['address']}")
                        break
                
                if result['found']:
                    break
        
        except Exception as e:
            self.log(f"[AroundUs] ❌ Erreur: {e}")
        
        return result
    
    def search_illuminate(self, invader_id, city_name=None):
        """Recherche sur IlluminateArt via Google"""
        result = {'source': 'illuminate', 'found': False, 'lat': None, 'lng': None, 'address': None, 'url': None}
        
        try:
            formatted_id = self._format_invader_id(invader_id)
            google_query = f"site:illuminateartofficial.com {invader_id}"
            google_url = f"https://www.google.com/search?q={quote(google_query)}"
            
            self.log(f"[Illuminate] Google: {google_query}")
            self.page.goto(google_url, timeout=20000)
            time.sleep(2)
            self._handle_google_consent()
            
            content = self.page.content()
            urls = self._extract_urls_from_google(content)
            
            # Filtrer pour ne garder que https://illuminateartofficial.com/blogs/...
            target_urls = []
            for item in urls:
                url = item['url'].lower()
                if url.startswith('https://illuminateartofficial.com/'):
                    if '/blogs/' in url or re.search(r'/\d{4}/\d{2}/\d{2}/', url):
                        target_urls.append(item['url'])
            
            self.log(f"[Illuminate] {len(target_urls)} URLs valides trouvées")
            
            # Visiter la première URL valide
            for url in target_urls[:2]:
                self.log(f"[Illuminate] → Visite: {url[:60]}...")
                self.page.goto(url, timeout=20000)
                time.sleep(2)
                
                # Scroll vers la section de l'invader
                match = re.match(r'([A-Z]+)[_-]?(\d+)', invader_id.upper())
                if match:
                    prefix, num = match.group(1), int(match.group(2))
                    try:
                        header = self.page.locator(f"h4:has-text('{prefix}_{num:02d}')").first
                        if header.is_visible():
                            header.scroll_into_view_if_needed()
                            self.log(f"[Illuminate] 📜 Scrollé vers {prefix}_{num:02d}")
                            time.sleep(2)
                    except:
                        pass
                
                page_content = self.page.content()
                
                # Trouver la section de l'invader
                invader_section = self._find_invader_section(page_content, invader_id)
                search_content = invader_section if invader_section else page_content
                
                if invader_section:
                    self.log(f"[Illuminate] 📍 Section trouvée ({len(invader_section)} chars)")
                
                # Chercher les coordonnées @lat,lng
                coord_match = re.search(r'@([-\d.]+),([-\d.]+)', search_content)
                if coord_match:
                    lat, lng = float(coord_match.group(1)), float(coord_match.group(2))
                    if -90 <= lat <= 90 and -180 <= lng <= 180:
                        result['found'] = True
                        result['lat'] = lat
                        result['lng'] = lng
                        result['url'] = url
                        self.log(f"[Illuminate] ✅ GPS: {lat:.6f}, {lng:.6f}")
                
                # Chercher dans les liens Google Maps
                if not result['found']:
                    maps_pattern = r'(https?://(?:goo\.gl/maps|maps\.app\.goo\.gl|(?:www\.)?google\.[a-z.]+/maps)[^\s"<>]+)'
                    for maps_url in re.findall(maps_pattern, search_content):
                        coords = self._extract_coords_from_maps_url(maps_url)
                        if coords:
                            result['found'] = True
                            result['lat'] = coords['lat']
                            result['lng'] = coords['lng']
                            result['url'] = url
                            self.log(f"[Illuminate] ✅ GPS (Maps): {coords['lat']:.6f}, {coords['lng']:.6f}")
                            break
                
                if result['found']:
                    break
        
        except Exception as e:
            self.log(f"[Illuminate] ❌ Erreur: {e}")
        
        return result
    
    def _find_invader_section(self, content, invader_id):
        """Trouve la section HTML correspondant à un invader spécifique"""
        match = re.match(r'([A-Z]+)[_-]?(\d+)', invader_id.upper())
        if not match:
            return None
        
        prefix = match.group(1)
        current_num = int(match.group(2))
        
        # Chercher tous les headers h3/h4 contenant des IDs d'invaders
        header_pattern = rf'<h[34][^>]*>([^<]*{prefix}_\d+[^<]*)</h[34]>'
        headers = list(re.finditer(header_pattern, content, re.IGNORECASE))
        
        if headers:
            target_idx = None
            for i, h in enumerate(headers):
                if f'{prefix}_{current_num:02d}' in h.group(1).upper():
                    target_idx = i
                    break
            
            if target_idx is not None:
                start_pos = headers[target_idx].start()
                end_pos = headers[target_idx + 1].start() if target_idx + 1 < len(headers) else len(content)
                return content[start_pos:end_pos]
        
        return None
    
    def _extract_coords_from_maps_url(self, url):
        """Extrait les coordonnées depuis une URL Google Maps"""
        # Suivre les redirections courtes
        if 'goo.gl' in url or 'maps.app' in url:
            try:
                self.page.goto(url, timeout=15000)
                time.sleep(3)
                url = self.page.url
            except:
                return None
        
        # Patterns d'extraction
        for pattern in [
            r'@(-?\d+\.\d+),(-?\d+\.\d+)',
            r'll=(-?\d+\.\d+),(-?\d+\.\d+)',
            r'q=(-?\d+\.\d+),(-?\d+\.\d+)',
        ]:
            match = re.search(pattern, url)
            if match:
                lat, lng = float(match.group(1)), float(match.group(2))
                if -90 <= lat <= 90 and -180 <= lng <= 180:
                    return {'lat': lat, 'lng': lng}
        
        return None
    
    def search(self, invader_id, city_name=None):
        """
        Recherche un invader sur AroundUs ET IlluminateArt
        Retourne un résultat combiné avec test de cohérence
        """
        result = {
            'invader_id': invader_id,
            'found': False,
            'lat': None,
            'lng': None,
            'address': None,
            'source': None,
            'geo_confidence': 'low',
            'aroundus': None,
            'illuminate': None,
            'coherence': None
        }
        
        # 1. Chercher sur AroundUs
        print(f"   🔍 AroundUs...", end='', flush=True)
        aroundus = self.search_aroundus(invader_id, city_name)
        result['aroundus'] = aroundus
        if aroundus['found']:
            print(f" ✅ GPS: {aroundus['lat']:.5f}, {aroundus['lng']:.5f}")
        else:
            print(f" ❌")
        
        time.sleep(1)
        
        # 2. Chercher sur IlluminateArt (TOUJOURS)
        print(f"   🔍 IlluminateArt...", end='', flush=True)
        illuminate = self.search_illuminate(invader_id, city_name)
        result['illuminate'] = illuminate
        if illuminate['found']:
            print(f" ✅ GPS: {illuminate['lat']:.5f}, {illuminate['lng']:.5f}")
        else:
            print(f" ❌")
        
        # 3. Test de cohérence et décision
        au_found = aroundus['found']
        il_found = illuminate['found']
        
        if au_found and il_found:
            # Les deux sources ont trouvé - calculer la distance
            distance = calculate_distance(aroundus['lat'], aroundus['lng'], illuminate['lat'], illuminate['lng'])
            result['coherence'] = {'distance_m': round(distance, 1)}
            
            if distance < 200:
                # Sources cohérentes → HIGH confidence
                result['found'] = True
                result['lat'] = aroundus['lat']  # Préférer AroundUs (a souvent l'adresse)
                result['lng'] = aroundus['lng']
                result['address'] = aroundus.get('address') or illuminate.get('address')
                result['source'] = 'aroundus+illuminate'
                result['geo_confidence'] = 'high'
                print(f"   🟢 Cohérence: GPS identiques à {distance:.0f}m - HIGH confidence")
            else:
                # Sources différentes → préférer Illuminate, MEDIUM confidence
                result['found'] = True
                result['lat'] = illuminate['lat']
                result['lng'] = illuminate['lng']
                result['address'] = illuminate.get('address') or aroundus.get('address')
                result['source'] = 'illuminate'
                result['geo_confidence'] = 'medium'
                print(f"   🟡 Conflit: {distance:.0f}m - Illuminate prioritaire - MEDIUM confidence")
        
        elif au_found:
            # Seulement AroundUs → MEDIUM confidence
            result['found'] = True
            result['lat'] = aroundus['lat']
            result['lng'] = aroundus['lng']
            result['address'] = aroundus.get('address')
            result['source'] = 'aroundus'
            result['geo_confidence'] = 'medium'
            print(f"   🔵 Source unique: AroundUs - MEDIUM confidence")
        
        elif il_found:
            # Seulement IlluminateArt → MEDIUM confidence
            result['found'] = True
            result['lat'] = illuminate['lat']
            result['lng'] = illuminate['lng']
            result['address'] = illuminate.get('address')
            result['source'] = 'illuminate'
            result['geo_confidence'] = 'medium'
            print(f"   🔵 Source unique: IlluminateArt - MEDIUM confidence")
        
        else:
            # Rien trouvé
            print(f"   ⚪ Aucune source n'a trouvé de GPS")
        
        return result


class MissingInvaderSearcherAsync:
    """Version async de MissingInvaderSearcher pour Playwright async API"""
    
    def __init__(self, page, verbose=False):
        self.page = page
        self.verbose = verbose
        self.google_consent_handled = False
    
    def log(self, msg):
        if self.verbose:
            print(f"      {msg}")
    
    def _format_invader_id(self, invader_id):
        """Normalise l'ID: PA_01 → PA_01, PA1 → PA_01"""
        match = re.match(r'^([A-Z]+)[_-]?(\d+)$', invader_id.upper())
        if match:
            prefix = match.group(1)
            num = int(match.group(2))
            return f"{prefix}_{num:02d}"
        return invader_id.upper()
    
    async def _handle_google_consent(self):
        """Gère le popup de consentement Google"""
        if self.google_consent_handled:
            return
        try:
            buttons = self.page.locator('button')
            count = await buttons.count()
            for i in range(count):
                text = await buttons.nth(i).text_content()
                if text and any(x in text.lower() for x in ['accept', 'accepter', 'tout accepter', 'accept all']):
                    await buttons.nth(i).click()
                    self.google_consent_handled = True
                    await asyncio.sleep(1)
                    break
        except:
            pass
    
    def _extract_urls_from_google(self, content):
        """Extrait les URLs des résultats Google"""
        results = []
        
        redirect_pattern = r'/url\?q=([^&]+)&'
        for url in re.findall(redirect_pattern, content):
            decoded = unquote(url)
            if decoded.startswith('http') and decoded not in [r['url'] for r in results]:
                results.append({'url': decoded, 'extraction_method': 'google_redirect'})
        
        direct_pattern = r'href="(https?://[^"]+)"'
        for url in re.findall(direct_pattern, content):
            if url not in [r['url'] for r in results]:
                if not any(x in url for x in ['google.com/search', 'accounts.google']):
                    results.append({'url': url, 'extraction_method': 'direct_href'})
        
        return results
    
    async def search_aroundus(self, invader_id, city_name=None):
        """Recherche sur AroundUs via Google"""

        result = {'source': 'aroundus', 'found': False, 'lat': None, 'lng': None, 'address': None, 'url': None}
        
        try:
            formatted_id = self._format_invader_id(invader_id)
            google_query = f"site:aroundus.com {invader_id}"
            google_url = f"https://www.google.com/search?q={quote(google_query)}"
            
            self.log(f"[AroundUs] Google: {google_query}")
            await self.page.goto(google_url, timeout=20000)
            await asyncio.sleep(2)
            await self._handle_google_consent()
            
            content = await self.page.content()
            urls = self._extract_urls_from_google(content)
            
            target_urls = []
            for item in urls:
                url = item['url'].lower()
                if re.match(r'https?://[a-z]{2}\.aroundus\.com/p/', url):
                    if formatted_id.lower() in url or invader_id.lower() in url:
                        target_urls.append(item['url'])
            
            self.log(f"[AroundUs] {len(target_urls)} URLs valides trouvées")
            
            for url in target_urls[:2]:
                self.log(f"[AroundUs] → Visite: {url[:60]}...")
                await self.page.goto(url, timeout=20000)
                await asyncio.sleep(3)
                
                page_content = await self.page.content()
                
                # Méthode 1: JSON-LD
                json_match = re.search(
                    r'"geo"\s*:\s*\{\s*"@type"\s*:\s*"GeoCoordinates"\s*,\s*"latitude"\s*:\s*"?([-\d.]+)"?\s*,\s*"longitude"\s*:\s*"?([-\d.]+)"?',
                    page_content
                )
                if json_match:
                    lat, lng = float(json_match.group(1)), float(json_match.group(2))
                    if -90 <= lat <= 90 and -180 <= lng <= 180:
                        result['found'] = True
                        result['lat'] = lat
                        result['lng'] = lng
                        result['url'] = url
                        self.log(f"[AroundUs] ✅ GPS (JSON-LD): {lat:.6f}, {lng:.6f}")
                
                # Méthode 2: Patterns HTML
                if not result['found']:
                    for pattern in [
                        r'<strong>GPS\s*coordinates?:</strong>\s*([-\d.]+)\s*,\s*([-\d.]+)',
                        r'<strong>Coordonn[ée]es\s*GPS\s*:</strong>\s*([-\d.]+)\s*,\s*([-\d.]+)',
                    ]:
                        match = re.search(pattern, page_content, re.IGNORECASE)
                        if match:
                            lat, lng = float(match.group(1)), float(match.group(2))
                            if -90 <= lat <= 90 and -180 <= lng <= 180:
                                result['found'] = True
                                result['lat'] = lat
                                result['lng'] = lng
                                result['url'] = url
                                self.log(f"[AroundUs] ✅ GPS (HTML): {lat:.6f}, {lng:.6f}")
                                break
                
                # Extraire l'adresse
                for pattern in [r'<strong>Address:</strong>\s*([^<]+)', r'<strong>Adresse\s*:</strong>\s*([^<]+)']:
                    addr_match = re.search(pattern, page_content, re.IGNORECASE)
                    if addr_match:
                        result['address'] = addr_match.group(1).strip()
                        self.log(f"[AroundUs] 📫 Adresse: {result['address']}")
                        break
                
                if result['found']:
                    break
        
        except Exception as e:
            self.log(f"[AroundUs] ❌ Erreur: {e}")
        
        return result
    
    async def search_illuminate(self, invader_id, city_name=None):
        """Recherche sur IlluminateArt via Google"""

        result = {'source': 'illuminate', 'found': False, 'lat': None, 'lng': None, 'address': None, 'url': None}
        
        try:
            formatted_id = self._format_invader_id(invader_id)
            google_query = f"site:illuminateartofficial.com {invader_id}"
            google_url = f"https://www.google.com/search?q={quote(google_query)}"
            
            self.log(f"[Illuminate] Google: {google_query}")
            await self.page.goto(google_url, timeout=20000)
            await asyncio.sleep(2)
            await self._handle_google_consent()
            
            content = await self.page.content()
            urls = self._extract_urls_from_google(content)
            
            target_urls = []
            for item in urls:
                url = item['url'].lower()
                if url.startswith('https://illuminateartofficial.com/'):
                    if '/blogs/' in url or re.search(r'/\d{4}/\d{2}/\d{2}/', url):
                        target_urls.append(item['url'])
            
            self.log(f"[Illuminate] {len(target_urls)} URLs valides trouvées")
            
            for url in target_urls[:2]:
                self.log(f"[Illuminate] → Visite: {url[:60]}...")
                await self.page.goto(url, timeout=20000)
                await asyncio.sleep(2)
                
                # Scroll vers la section
                match = re.match(r'([A-Z]+)[_-]?(\d+)', invader_id.upper())
                if match:
                    prefix, num = match.group(1), int(match.group(2))
                    try:
                        header = self.page.locator(f"h4:has-text('{prefix}_{num:02d}')").first
                        if await header.is_visible():
                            await header.scroll_into_view_if_needed()
                            self.log(f"[Illuminate] 📜 Scrollé vers {prefix}_{num:02d}")
                            await asyncio.sleep(2)
                    except:
                        pass
                
                page_content = await self.page.content()
                
                # Trouver la section
                invader_section = self._find_invader_section(page_content, invader_id)
                search_content = invader_section if invader_section else page_content
                
                if invader_section:
                    self.log(f"[Illuminate] 📍 Section trouvée ({len(invader_section)} chars)")
                
                # Chercher @lat,lng
                coord_match = re.search(r'@([-\d.]+),([-\d.]+)', search_content)
                if coord_match:
                    lat, lng = float(coord_match.group(1)), float(coord_match.group(2))
                    if -90 <= lat <= 90 and -180 <= lng <= 180:
                        result['found'] = True
                        result['lat'] = lat
                        result['lng'] = lng
                        result['url'] = url
                        self.log(f"[Illuminate] ✅ GPS: {lat:.6f}, {lng:.6f}")
                
                if result['found']:
                    break
        
        except Exception as e:
            self.log(f"[Illuminate] ❌ Erreur: {e}")
        
        return result
    
    def _find_invader_section(self, content, invader_id):
        """Trouve la section HTML correspondant à un invader spécifique"""
        match = re.match(r'([A-Z]+)[_-]?(\d+)', invader_id.upper())
        if not match:
            return None
        
        prefix = match.group(1)
        current_num = int(match.group(2))
        
        header_pattern = rf'<h[34][^>]*>([^<]*{prefix}_\d+[^<]*)</h[34]>'
        headers = list(re.finditer(header_pattern, content, re.IGNORECASE))
        
        if headers:
            target_idx = None
            for i, h in enumerate(headers):
                if f'{prefix}_{current_num:02d}' in h.group(1).upper():
                    target_idx = i
                    break
            
            if target_idx is not None:
                start_pos = headers[target_idx].start()
                end_pos = headers[target_idx + 1].start() if target_idx + 1 < len(headers) else len(content)
                return content[start_pos:end_pos]
        
        return None
    
    async def search(self, invader_id, city_name=None):
        """Recherche sur AroundUs ET IlluminateArt avec test de cohérence"""

        
        result = {
            'invader_id': invader_id,
            'found': False,
            'lat': None,
            'lng': None,
            'address': None,
            'source': None,
            'geo_confidence': 'low',
            'aroundus': None,
            'illuminate': None,
            'coherence': None
        }
        
        # 1. AroundUs
        print(f"   🔍 AroundUs...", end='', flush=True)
        aroundus = await self.search_aroundus(invader_id, city_name)
        result['aroundus'] = aroundus
        if aroundus['found']:
            print(f" ✅ GPS: {aroundus['lat']:.5f}, {aroundus['lng']:.5f}")
        else:
            print(f" ❌")
        
        await asyncio.sleep(1)
        
        # 2. IlluminateArt
        print(f"   🔍 IlluminateArt...", end='', flush=True)
        illuminate = await self.search_illuminate(invader_id, city_name)
        result['illuminate'] = illuminate
        if illuminate['found']:
            print(f" ✅ GPS: {illuminate['lat']:.5f}, {illuminate['lng']:.5f}")
        else:
            print(f" ❌")
        
        # 3. Cohérence et décision
        au_found = aroundus['found']
        il_found = illuminate['found']
        
        if au_found and il_found:
            distance = calculate_distance(aroundus['lat'], aroundus['lng'], illuminate['lat'], illuminate['lng'])
            result['coherence'] = {'distance_m': round(distance, 1)}
            
            if distance < 200:
                result['found'] = True
                result['lat'] = aroundus['lat']
                result['lng'] = aroundus['lng']
                result['address'] = aroundus.get('address') or illuminate.get('address')
                result['source'] = 'aroundus+illuminate'
                result['geo_confidence'] = 'high'
                print(f"   🟢 Cohérence: GPS identiques à {distance:.0f}m - HIGH confidence")
            else:
                result['found'] = True
                result['lat'] = illuminate['lat']
                result['lng'] = illuminate['lng']
                result['address'] = illuminate.get('address') or aroundus.get('address')
                result['source'] = 'illuminate'
                result['geo_confidence'] = 'medium'
                print(f"   🟡 Conflit: {distance:.0f}m - Illuminate prioritaire - MEDIUM confidence")
        
        elif au_found:
            result['found'] = True
            result['lat'] = aroundus['lat']
            result['lng'] = aroundus['lng']
            result['address'] = aroundus.get('address')
            result['source'] = 'aroundus'
            result['geo_confidence'] = 'medium'
            print(f"   🔵 Source unique: AroundUs - MEDIUM confidence")
        
        elif il_found:
            result['found'] = True
            result['lat'] = illuminate['lat']
            result['lng'] = illuminate['lng']
            result['address'] = illuminate.get('address')
            result['source'] = 'illuminate'
            result['geo_confidence'] = 'medium'
            print(f"   🔵 Source unique: IlluminateArt - MEDIUM confidence")
        
        else:
            print(f"   ⚪ Aucune source n'a trouvé de GPS")
        
        return result


async def geolocate_from_missing_file(missing_file, output_file, addresses_file=None, headless=True, verbose=False, limit=None, city_filter=None):
    """
    Géolocalise les invaders depuis invaders_missing_from_github.json
    
    Args:
        missing_file: Chemin vers invaders_missing_from_github.json
        output_file: Chemin de sortie pour les invaders géolocalisés
        addresses_file: Fichier CSV optionnel avec adresses manuelles
        headless: Mode sans interface
        verbose: Mode verbeux
        limit: Nombre max d'invaders à traiter
        city_filter: Filtrer par code ville
    
    Returns:
        Liste des invaders géolocalisés au format compatible avec invaders_updated.json
    """
    from playwright.async_api import async_playwright

    
    # Charger les invaders manquants
    print(f"📂 Chargement de {missing_file}...")
    with open(missing_file, 'r', encoding='utf-8') as f:
        missing_invaders = json.load(f)
    print(f"   {len(missing_invaders)} invaders manquants chargés")
    
    # Charger les adresses manuelles si fournies
    manual_addresses = {}
    if addresses_file and os.path.exists(addresses_file):
        print(f"📂 Chargement des adresses manuelles: {addresses_file}")
        manual_addresses = load_manual_addresses(addresses_file)
        if manual_addresses:
            print(f"   {len(manual_addresses)} adresses manuelles chargées")
    
    # Filtrer par ville si demandé
    if city_filter:
        missing_invaders = [inv for inv in missing_invaders if inv.get('city', '').upper() == city_filter.upper()]
        print(f"   {len(missing_invaders)} invaders pour {city_filter}")
    
    # Limiter si demandé
    if limit:
        missing_invaders = missing_invaders[:limit]
        print(f"   Limité à {len(missing_invaders)} invaders")
    
    if not missing_invaders:
        print("❌ Aucun invader à traiter")
        return []
    
    print(f"\n🔍 Géolocalisation de {len(missing_invaders)} invaders...")
    print("=" * 60)
    
    # Statistiques
    stats = {
        'total': len(missing_invaders),
        'found': 0,
        'found_both': 0,
        'found_aroundus': 0,
        'found_illuminate': 0,
        'found_manual': 0,
        'not_found': 0,
        'confidence': {'high': 0, 'medium': 0, 'low': 0}
    }
    
    results = []
    
    # Démarrer Playwright (async)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=['--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 900},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        page = await context.new_page()
        
        # Wrapper sync pour le searcher (utilise page sync-like via run_sync)
        searcher = MissingInvaderSearcherAsync(page, verbose)
        
        for i, inv in enumerate(missing_invaders, 1):
            inv_name = inv.get('name', '')
            inv_id = inv_name.upper().replace('-', '_')
            city_code = inv.get('city', '')
            city_name = CITY_CENTERS.get(city_code, {}).get('name', city_code)
            
            print(f"\n[{i}/{len(missing_invaders)}] {inv_id}")
            
            # Construire le résultat
            new_inv = {
                'id': inv_id,
                'status': inv.get('status', 'OK'),
                'city': city_code,
                'points': inv.get('points', 0),
                'lat': None,
                'lng': None,
                'geo_source': None,
                'geo_confidence': 'low',
                'location_unknown': True,
                'missing_from_github': True,
                'added_date': datetime.now().isoformat(),
            }
            
            # Ajouter les images si présentes
            if inv.get('image_invader'):
                new_inv['image_invader'] = inv['image_invader']
            if inv.get('image_lieu'):
                new_inv['image_lieu'] = inv['image_lieu']
            if inv.get('landing_date'):
                new_inv['landing_date'] = inv['landing_date']
            if inv.get('status_date'):
                new_inv['status_date'] = inv['status_date']
            
            # 1. Vérifier si adresse manuelle disponible
            if inv_id in manual_addresses:
                addr_data = manual_addresses[inv_id]
                address = addr_data.get('address', '')
                
                if address:
                    print(f"   📝 Adresse manuelle: {address[:50]}...")
                    
                    # Géocoder l'adresse
                    geo = geocode_address_sync(address, city_name)
                    if geo and geo.get('lat'):
                        new_inv['lat'] = geo['lat']
                        new_inv['lng'] = geo['lng']
                        new_inv['address'] = address
                        new_inv['geo_source'] = 'manual_address'
                        new_inv['geo_confidence'] = 'high'
                        new_inv['location_unknown'] = False
                        stats['found_manual'] += 1
                        stats['found'] += 1
                        stats['confidence']['high'] += 1
                        print(f"   ✅ Géocodé: {geo['lat']:.6f}, {geo['lng']:.6f}")
                        results.append(new_inv)
                        continue
            
            # 2. Rechercher sur AroundUs et IlluminateArt
            search_result = await searcher.search(inv_id, city_name)
            
            if search_result['found']:
                new_inv['lat'] = search_result['lat']
                new_inv['lng'] = search_result['lng']
                new_inv['address'] = search_result.get('address')
                new_inv['geo_source'] = search_result['source']
                new_inv['geo_confidence'] = search_result['geo_confidence']
                new_inv['location_unknown'] = False
                
                stats['found'] += 1
                stats['confidence'][search_result['geo_confidence']] += 1
                
                if search_result['source'] == 'aroundus+illuminate':
                    stats['found_both'] += 1
                elif search_result['source'] == 'aroundus':
                    stats['found_aroundus'] += 1
                elif search_result['source'] == 'illuminate':
                    stats['found_illuminate'] += 1
            
            else:
                # 3. Fallback: centre-ville
                if city_code in CITY_CENTERS:
                    new_inv['lat'] = CITY_CENTERS[city_code]['lat']
                    new_inv['lng'] = CITY_CENTERS[city_code]['lng']
                    new_inv['geo_source'] = 'city_center'
                    new_inv['geo_confidence'] = 'low'
                    new_inv['location_unknown'] = True
                    print(f"   ⚠️ Fallback: centre de {CITY_CENTERS[city_code]['name']}")
                else:
                    new_inv['lat'] = 0
                    new_inv['lng'] = 0
                    new_inv['geo_source'] = 'unknown'
                    new_inv['geo_confidence'] = 'low'
                    new_inv['location_unknown'] = True
                    print(f"   ⚠️ Ville inconnue: {city_code}")
                
                stats['not_found'] += 1
                stats['confidence']['low'] += 1
            
            results.append(new_inv)
            await asyncio.sleep(1)
        
        await browser.close()
    
    # Afficher les statistiques
    print("\n" + "=" * 60)
    print("📊 STATISTIQUES")
    print("=" * 60)
    print(f"\n📁 Analyse:")
    print(f"   Total invaders:        {stats['total']}")
    print(f"   GPS trouvés:           {stats['found']} ({100*stats['found']/max(1,stats['total']):.1f}%)")
    print(f"   - via AroundUs+Illum:  {stats['found_both']} (HIGH)")
    print(f"   - via AroundUs seul:   {stats['found_aroundus']} (MEDIUM)")
    print(f"   - via Illuminate seul: {stats['found_illuminate']} (MEDIUM)")
    print(f"   - via adresse manuelle:{stats['found_manual']} (HIGH)")
    print(f"   Non trouvés (centre):  {stats['not_found']} (LOW)")
    
    print(f"\n🎯 Confiance:")
    print(f"   HIGH:   {stats['confidence']['high']}")
    print(f"   MEDIUM: {stats['confidence']['medium']}")
    print(f"   LOW:    {stats['confidence']['low']}")
    
    # Sauvegarder les résultats
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n📄 Résultats: {output_file}")
    
    # Rapport texte
    txt_output = output_file.replace('.json', '.txt')
    with open(txt_output, 'w', encoding='utf-8') as f:
        f.write("GÉOLOCALISATION DES INVADERS MANQUANTS\n")
        f.write("=" * 60 + "\n\n")
        
        f.write(f"Total: {stats['total']}\n")
        f.write(f"Trouvés: {stats['found']} ({100*stats['found']/max(1,stats['total']):.1f}%)\n")
        f.write(f"Non trouvés: {stats['not_found']}\n\n")
        
        f.write("RÉSULTATS PAR INVADER:\n")
        f.write("-" * 40 + "\n\n")
        
        for inv in results:
            conf_icon = {'high': '🟢', 'medium': '🟡', 'low': '🔴'}.get(inv['geo_confidence'], '❓')
            f.write(f"{inv['id']} {conf_icon} ({inv['geo_confidence'].upper()})\n")
            f.write(f"   GPS: {inv['lat']:.6f}, {inv['lng']:.6f}\n")
            f.write(f"   Source: {inv.get('geo_source', '?')}\n")
            if inv.get('address'):
                f.write(f"   Adresse: {inv['address']}\n")
            f.write(f"   Maps: https://www.google.com/maps?q={inv['lat']},{inv['lng']}\n")
            if inv.get('location_unknown'):
                f.write(f"   ⚠️ Localisation inconnue\n")
            f.write("\n")
    
    print(f"📄 Rapport: {txt_output}")
    print("=" * 60)
    
    return results


async def main_async():
    args = sys.argv[1:]
    cities_filter = None
    headless, verbose, merge_only, apply_reports, backup, dry_run = True, False, False, False, False, False
    geolocate, add_missing, discover_new, geolocate_missing = False, False, False, False
    addresses_file = None
    missing_file = _p(MISSING_FILE)
    merge_geolocated_file = None
    max_retries, pause_ms = 3, 1000
    limit = None
    github_repo = os.environ.get('GITHUB_REPO', None)
    github_token = os.environ.get('GITHUB_TOKEN', os.environ.get('PAT_TOKEN', None))
    
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--city' and i+1 < len(args):
            cities_filter = [args[i+1].upper()]; i += 1
        elif a == '--cities' and i+1 < len(args):
            cities_filter = [c.strip().upper() for c in args[i+1].split(',')]; i += 1
        elif a == '--visible': headless = False
        elif a == '--verbose': verbose = True
        elif a == '--merge-only': merge_only = True
        elif a == '--apply-reports': apply_reports = True
        elif a == '--backup': backup = True
        elif a == '--dry-run': dry_run = True
        elif a == '--geolocate': geolocate = True
        elif a == '--add-missing': add_missing = True
        elif a == '--discover-new': discover_new = True
        elif a == '--geolocate-missing': geolocate_missing = True
        elif a == '--merge-geolocated' and i+1 < len(args):
            merge_geolocated_file = args[i+1]; i += 1
        elif a == '--missing-file' and i+1 < len(args):
            missing_file = args[i+1]; i += 1
        elif a == '--addresses-file' and i+1 < len(args):
            addresses_file = args[i+1]; i += 1
        elif a == '--max-retries' and i+1 < len(args): max_retries = int(args[i+1]); i += 1
        elif a == '--pause' and i+1 < len(args): pause_ms = int(args[i+1]); i += 1
        elif a == '--limit' and i+1 < len(args): limit = int(args[i+1]); i += 1
        elif a == '--github-repo' and i+1 < len(args): github_repo = args[i+1]; i += 1
        elif a == '--github-token' and i+1 < len(args): github_token = args[i+1]; i += 1
        elif a in ['--help', '-h']: print(__doc__); return
        i += 1
    
    # Mode spécial: fusionner les invaders géolocalisés
    if merge_geolocated_file:
        print("="*60 + "\n🔗 Fusion des invaders géolocalisés\n" + "="*60)
        
        # Charger invaders_master.json
        updated_file = _p(MASTER_FILE)
        if not os.path.exists(updated_file):
            print(f"❌ Fichier non trouvé: {updated_file}")
            return
        
        if not os.path.exists(merge_geolocated_file):
            print(f"❌ Fichier non trouvé: {merge_geolocated_file}")
            return
        
        print(f"📂 Chargement de {updated_file}...")
        with open(updated_file, 'r', encoding='utf-8') as f:
            updated_db = json.load(f)
        print(f"   {len(updated_db)} invaders existants")
        
        print(f"📂 Chargement de {merge_geolocated_file}...")
        with open(merge_geolocated_file, 'r', encoding='utf-8') as f:
            geolocated = json.load(f)
        print(f"   {len(geolocated)} invaders géolocalisés")
        
        # Créer un index des invaders existants
        existing_ids = {}
        for i, inv in enumerate(updated_db):
            inv_id = inv.get('id', inv.get('name', '')).upper().replace('-', '_')
            existing_ids[inv_id] = i
        
        # Fusionner
        added = 0
        updated = 0
        for geo_inv in geolocated:
            geo_id = geo_inv.get('id', '').upper().replace('-', '_')
            
            if geo_id in existing_ids:
                # Mettre à jour l'existant
                idx = existing_ids[geo_id]
                old_inv = updated_db[idx]
                
                # Ne mettre à jour que si les nouvelles coordonnées sont meilleures
                old_confidence = old_inv.get('geo_confidence', 'low')
                new_confidence = geo_inv.get('geo_confidence', 'low')
                confidence_order = {'high': 3, 'medium': 2, 'low': 1, 'very_low': 0}
                
                if confidence_order.get(new_confidence, 0) >= confidence_order.get(old_confidence, 0):
                    # Mettre à jour les coordonnées
                    updated_db[idx]['lat'] = geo_inv['lat']
                    updated_db[idx]['lng'] = geo_inv['lng']
                    updated_db[idx]['geo_source'] = geo_inv.get('geo_source')
                    updated_db[idx]['geo_confidence'] = new_confidence
                    updated_db[idx]['location_unknown'] = geo_inv.get('location_unknown', False)
                    if geo_inv.get('address'):
                        updated_db[idx]['address'] = geo_inv['address']
                    updated_db[idx]['preserved'] = True
                    updated_db[idx]['preserved_date'] = datetime.now().isoformat()
                    updated += 1
                    if verbose:
                        print(f"   🔄 {geo_id}: mis à jour ({old_confidence} → {new_confidence})")
            else:
                # Ajouter le nouvel invader
                geo_inv['preserved'] = True
                geo_inv['preserved_date'] = datetime.now().isoformat()
                updated_db.append(geo_inv)
                added += 1
                if verbose:
                    print(f"   ➕ {geo_id}: ajouté")
        
        # Sauvegarder
        if backup:
            backup_file = f"{updated_file}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(updated_db, f, indent=2, ensure_ascii=False)
            print(f"💾 Backup: {backup_file}")
        
        if not dry_run:
            with open(updated_file, 'w', encoding='utf-8') as f:
                json.dump(updated_db, f, indent=2, ensure_ascii=False)
            print(f"\n✅ {updated_file} mis à jour:")
        else:
            print(f"\n🔍 Mode dry-run - pas de sauvegarde:")
        
        print(f"   ➕ {added} invaders ajoutés")
        print(f"   🔄 {updated} invaders mis à jour")
        print(f"   📊 Total: {len(updated_db)} invaders")
        return
    
    # Mode spécial: géolocaliser les invaders manquants
    if geolocate_missing:
        print("="*60 + "\n🔍 Géolocalisation des invaders manquants\n" + "="*60)
        
        if not os.path.exists(missing_file):
            print(f"❌ Fichier non trouvé: {missing_file}")
            return
        
        city_filter = cities_filter[0] if cities_filter else None
        output_file = _p(GEOLOCATED_MISSING_FILE)
        
        await geolocate_from_missing_file(
            missing_file=missing_file,
            output_file=output_file,
            addresses_file=addresses_file,
            headless=headless,
            verbose=verbose,
            limit=limit,
            city_filter=city_filter
        )
        
        print(f"\n📋 Pour fusionner avec le master, utilisez:")
        print(f"   python update_from_spotter.py --merge-geolocated {output_file}")
        return
    
    print("="*60 + "\n🔄 Total Invaders Search - Mise à jour v4\n" + "="*60)
    
    github_db = load_master_file()
    if not github_db: return
    
    community_reports = load_community_reports() if apply_reports else []
    
    # Charger et géocoder les adresses manuelles si fournies
    manual_geocoded = {}
    if addresses_file:
        manual_addresses = load_manual_addresses(addresses_file)
        if manual_addresses:
            manual_geocoded = geocode_manual_addresses(manual_addresses, verbose)
    
    if merge_only:
        if SCRAPED_FILE.exists():
            with open(_p(SCRAPED_FILE), 'r') as f:
                scraped_statuses = json.load(f)
            print(f"📂 Chargé: {len(scraped_statuses)} invaders")
        else:
            print(f"❌ {SCRAPED_FILE.name} non trouvé"); return
    else:
        try:
            scraped_statuses = await scrape_all_cities(github_db, cities_filter, headless, verbose, max_retries, pause_ms, discover_new)
        except ImportError:
            print("❌ pip install playwright && playwright install chromium"); return
    
    if not scraped_statuses and not community_reports:
        print("⚠️ Rien à fusionner"); return
    
    updated_db, changes, not_in_github = merge_databases(github_db, scraped_statuses, community_reports)
    
    # Géolocaliser les invaders manquants si demandé (via web)
    geolocated = []
    geo_audits = []
    if geolocate and not_in_github:
        geolocated, geo_audits = await geolocate_missing_invaders(not_in_github, headless, verbose)
    
    # Ajouter les invaders manquants au JSON si demandé
    if add_missing:
        added_count = 0
        manual_count = 0
        unknown_count = 0
        
        # Centres des villes pour les invaders sans géolocalisation
        city_centers = {
            'PA': {'lat': 48.8566, 'lng': 2.3522, 'name': 'Paris'},
            'LY': {'lat': 45.7640, 'lng': 4.8357, 'name': 'Lyon'},
            'MARS': {'lat': 43.2965, 'lng': 5.3698, 'name': 'Marseille'},
            'LDN': {'lat': 51.5074, 'lng': -0.1278, 'name': 'London'},
            'NY': {'lat': 40.7128, 'lng': -74.0060, 'name': 'New York'},
            'LA': {'lat': 34.0522, 'lng': -118.2437, 'name': 'Los Angeles'},
            'TK': {'lat': 35.6762, 'lng': 139.6503, 'name': 'Tokyo'},
            'ROM': {'lat': 41.9028, 'lng': 12.4964, 'name': 'Rome'},
            'BCN': {'lat': 41.3851, 'lng': 2.1734, 'name': 'Barcelona'},
            'BKK': {'lat': 13.7563, 'lng': 100.5018, 'name': 'Bangkok'},
            'HK': {'lat': 22.3193, 'lng': 114.1694, 'name': 'Hong Kong'},
        }
        
        # Créer un index des invaders déjà dans updated_db
        existing_ids = set()
        for inv in updated_db:
            inv_id = inv.get('id', inv.get('name', '')).upper().replace('-', '_')
            existing_ids.add(inv_id)
        
        # 1. D'abord, ajouter les invaders du fichier d'adresses manuelles
        #    qui ne sont pas encore dans la base
        if manual_geocoded:
            print(f"\n📍 Ajout des invaders depuis le fichier d'adresses manuelles...")
            
            for inv_id, geo in manual_geocoded.items():
                if inv_id not in existing_ids:
                    # Extraire le code ville
                    city_match = re.match(r'^([A-Z]+)[-_]', inv_id)
                    city_code = city_match.group(1) if city_match else None
                    
                    # Chercher les infos dans not_in_github ou scraped_statuses
                    inv_info = None
                    for nig in (not_in_github or []):
                        if nig.get('name', '').upper().replace('-', '_') == inv_id:
                            inv_info = nig
                            break
                    
                    new_inv = {
                        'id': inv_id,
                        'status': inv_info.get('status', 'OK') if inv_info else 'OK',
                        'city': city_code,
                        'points': inv_info.get('points', 0) if inv_info else 0,
                        'lat': geo['lat'],
                        'lng': geo['lng'],
                        'geo_source': geo.get('source', 'manual_address'),
                        'geo_confidence': geo.get('confidence', 'high'),
                        'location_unknown': geo.get('location_unknown', False),
                        'missing_from_github': True,
                        'added_date': datetime.now().isoformat(),
                    }
                    
                    # Ajouter les adresses
                    if geo.get('address_original'):
                        new_inv['address'] = geo['address_original']
                    if geo.get('address_standardized'):
                        new_inv['address_standardized'] = geo['address_standardized']
                    if geo.get('address_geocoded'):
                        new_inv['address_geocoded'] = geo['address_geocoded']
                    
                    # Ajouter les images si disponibles
                    if inv_info:
                        if inv_info.get('image_invader'):
                            new_inv['image_invader'] = inv_info['image_invader']
                        if inv_info.get('image_lieu'):
                            new_inv['image_lieu'] = inv_info['image_lieu']
                    
                    updated_db.append(new_inv)
                    existing_ids.add(inv_id)
                    added_count += 1
                    manual_count += 1
                    
                    if geo.get('location_unknown'):
                        unknown_count += 1
                    
                    if verbose:
                        loc_status = "⚠️ approx" if geo.get('location_unknown') else "✅"
                        print(f"   {loc_status} {inv_id} → ({geo['lat']:.4f}, {geo['lng']:.4f})")
        
        # 2. Ensuite, ajouter les invaders de not_in_github qui n'ont pas d'adresse manuelle
        if not_in_github:
            for inv in not_in_github:
                inv_id = inv['name'].upper().replace('-', '_')
                
                # Skip si déjà ajouté via adresses manuelles
                if inv_id in existing_ids:
                    continue
                
                city_code = inv.get('city')
                city_info = city_centers.get(city_code, {})
                
                new_inv = {
                    'id': inv_id,
                    'status': inv.get('status', 'OK'),
                    'city': city_code,
                    'points': inv.get('points', 0),
                    'missing_from_github': True,
                    'added_date': datetime.now().isoformat(),
                }
                
                if inv.get('image_invader'):
                    new_inv['image_invader'] = inv['image_invader']
                if inv.get('image_lieu'):
                    new_inv['image_lieu'] = inv['image_lieu']
                
                # Chercher dans geolocated (si --geolocate a été utilisé)
                geo_data = next((g for g in geolocated if g.get('name') == inv.get('name')), None)
                
                if geo_data and geo_data.get('lat'):
                    new_inv['lat'] = geo_data['lat']
                    new_inv['lng'] = geo_data['lng']
                    new_inv['geo_source'] = geo_data.get('source', 'web_search')
                    new_inv['geo_confidence'] = geo_data.get('confidence', 'low')
                    new_inv['location_unknown'] = False
                    if geo_data.get('address'):
                        new_inv['address'] = geo_data['address']
                elif city_code and city_code in city_centers:
                    # Fallback: centre de la ville
                    new_inv['lat'] = city_info['lat']
                    new_inv['lng'] = city_info['lng']
                    new_inv['geo_source'] = 'city_center'
                    new_inv['geo_confidence'] = 'very_low'
                    new_inv['location_unknown'] = True
                    unknown_count += 1
                else:
                    new_inv['lat'] = 0
                    new_inv['lng'] = 0
                    new_inv['location_unknown'] = True
                    unknown_count += 1
                
                updated_db.append(new_inv)
                existing_ids.add(inv_id)
                added_count += 1
        
        print(f"\n➕ {added_count} invaders manquants ajoutés au JSON")
        if manual_count > 0:
            print(f"   📍 {manual_count} via adresses manuelles")
        if unknown_count > 0:
            print(f"   ⚠️ {unknown_count} avec localisation inconnue (centre ville)")
    
    # =========================================================================
    # Traitement des issues GitHub
    # =========================================================================
    issue_changes = []
    if github_repo:
        issues = fetch_github_issues(github_repo, github_token)
        if issues:
            updated_db, issue_changes = apply_github_issues(
                updated_db, issues,
                repo=github_repo, token=github_token,
                verbose=verbose, dry_run=dry_run
            )
            changes.extend(issue_changes)
    
    save_files(updated_db, scraped_statuses, changes, not_in_github, geolocated, geo_audits, backup, dry_run)
    
    # Mettre à jour metadata.json
    if not dry_run:
        from collections import Counter
        cities_count = Counter(inv.get('city', '?') for inv in updated_db)
        statuts_count = Counter(inv.get('status', '?') for inv in updated_db)
        with_coords = sum(1 for inv in updated_db if inv.get('lat') and inv.get('lng'))
        
        metadata = {}
        if METADATA_FILE.exists():
            with open(_p(METADATA_FILE), 'r', encoding='utf-8') as f:
                metadata = json.load(f)
        
        metadata.update({
            "last_updated": datetime.now().isoformat(),
            "total_invaders": len(updated_db),
            "total_cities": len(cities_count),
            "with_coordinates": with_coords,
            "without_coordinates": len(updated_db) - with_coords,
            "status_counts": dict(statuts_count.most_common()),
            "cities": {city: count for city, count in cities_count.most_common()},
        })
        
        with open(_p(METADATA_FILE), 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print(f"📊 {METADATA_FILE.name} mis à jour")
        
        # Mettre à jour changelog
        if changes:
            changelog = {"changes": [], "last_check": ""}
            if CHANGELOG_FILE.exists():
                with open(_p(CHANGELOG_FILE), 'r', encoding='utf-8') as f:
                    changelog = json.load(f)
            
            for c in changes:
                source = c.get('source', 'invader-spotter.art')
                # Normaliser la source pour le changelog
                if source.startswith('issue'):
                    changelog_source = f"github-{source}"
                else:
                    changelog_source = 'invader-spotter.art'
                
                changelog['changes'].append({
                    "invader_id": c.get('name', ''),
                    "field": "status",
                    "old_value": c.get('old_status', ''),
                    "new_value": c.get('new_status', ''),
                    "detected_at": c.get('date', datetime.now().isoformat()),
                    "source": changelog_source
                })
            changelog['last_check'] = datetime.now().isoformat()
            
            with open(_p(CHANGELOG_FILE), 'w', encoding='utf-8') as f:
                json.dump(changelog, f, indent=2, ensure_ascii=False)
            print(f"📝 {CHANGELOG_FILE.name} mis à jour ({len(changes)} changements)")
    
    print("\n📋 Prochaine étape: git commit & push (ou bash scripts/push_update.sh)")


def main():
    asyncio.run(main_async())


if __name__ == '__main__':
    main()
