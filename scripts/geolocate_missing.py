#!/usr/bin/env python3
"""
🔍 Recherche de localisation via sources spécialisées Invader - Version 3

Améliorations v3:
- Nouveau fallback: pnote.eu (lookup local ou fetch URL, coordonnées ±10m, hints)
- Nouveau fallback: Flickr scraping (photos geotaggées, sans clé API)
- Pipeline étendu: AroundUs → Illuminate → Pnote → Flickr → EXIF → OCR
- Support fichier pnote aux formats natif (obf_lat/obf_lng) et master-like

Améliorations v2:
- Ignore les coordonnées GPS à zéro (0.00, 0.00) sur AroundUs
- Support multilingue complet (EN, FR, NL, DE, ES, IT, PL, PT)
- Accepte aroundus.com et xx.aroundus.com
- Fallback EXIF: extrait les coordonnées GPS des métadonnées de l'image du lieu
- Fallback OCR: analyse visuelle Tesseract pour détecter plaques de rue, enseignes

Sources (par ordre de priorité):
1. aroundus.com - Données structurées (GPS JSON-LD, adresse)
2. illuminateartofficial.com - Coordonnées Google Maps
3. pnote.eu - Base communautaire crowdsourcée (±10m offset, hints)
4. Flickr scraping - Photos geotaggées via Playwright (tags: flashinvaders, pa_xxxx)
5. EXIF image_lieu - Métadonnées GPS de la photo (fallback)
6. OCR Tesseract - Analyse visuelle + OCR + géocodage (fallback)

Modes d'utilisation:

1. Mode classique (fichier invaders avec coords existantes):
   python geolocate_missing.py invaders_master.json --city AMI --limit 10 --visible

2. Mode invaders manquants (depuis invaders_missing_from_github.json):
   python geolocate_missing.py --from-missing invaders_missing_from_github.json --city ORLN --limit 5 --visible

3. Mode master (invaders sans coords ou au centre-ville):
   python geolocate_missing.py --from-master --city PA --limit 20 --visible

4. Fusion des résultats avec invaders_master.json:
   python geolocate_missing.py --merge invaders_relocalized.json --backup

5. Avec pnote.eu en fallback (fetch URL automatique):
   python geolocate_missing.py --from-master --city LDN --pnote-url

6. Avec pnote.eu depuis un fichier local:
   python geolocate_missing.py --from-master --city LDN --pnote-file data/pnote_invaders.json

7. Avec Flickr en fallback (activé par défaut, scraping Playwright):
   python geolocate_missing.py --from-master --city PA --visible

8. Combo complet:
   python geolocate_missing.py --from-master --pnote-url --visible

9. Sans Flickr (si trop lent):
   python geolocate_missing.py --from-master --pnote-url --no-flickr

10. Avec Claude Vision (analyse IA des images):
   python geolocate_missing.py --from-master --pnote-url --anthropic-key sk-ant-...
   # Ou via variable d'environnement:
   export ANTHROPIC_API_KEY=sk-ant-...
   python geolocate_missing.py --from-master --pnote-url

Options:
    --from-missing FILE   Utiliser ce fichier comme source (format missing_from_github)
    --from-master         Scanner le master et géolocaliser les invaders mal localisés
    --merge FILE          Fusionner FILE avec invaders_master.json
    --city PA             Filtrer par ville
    --limit 100           Limiter le nombre d'invaders
    --verbose             Mode verbeux
    --visible             Afficher le navigateur
    --output FILE         Fichier de sortie JSON
    --backup              Créer un backup avant merge
    --dry-run             Simuler sans sauvegarder
    --pnote-file FILE     Fichier JSON pnote.eu local pour fallback
    --pnote-url [URL]     Fetch pnote.eu depuis URL (défaut: pnote.eu/.../invaders.json)
    --no-flickr           Désactiver le scraping Flickr
    --anthropic-key KEY   Clé API Anthropic pour Claude Vision (ou env ANTHROPIC_API_KEY)

Pipeline de recherche:
1. AroundUs (web scraping Google)
2. IlluminateArt (web scraping Google)
3. Cohérence entre sources web + validation ville
4. [Fallback] Pnote.eu (lookup local, ±10m offset)
5. [Fallback] Flickr (scraping, photos geotaggées)
6. [Fallback] EXIF image_lieu
7. [Fallback] OCR Tesseract + patterns FR/UK
8. [Fallback] Claude Vision (analyse IA de l'image)
9. [Fallback] Google Lens interactif
10. [Fallback] Centre-ville

Logique de confiance:
- HIGH:   AroundUs + Illuminate cohérents (<200m)
- MEDIUM: Une seule source, Pnote, Flickr, EXIF, OCR, Vision
- LOW:    Aucune source (fallback centre-ville)
"""

import argparse
import warnings
import urllib3
warnings.filterwarnings("ignore", category=urllib3.exceptions.NotOpenSSLWarning)

import json
import math
import os
import re
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, unquote

# ============================================================================
# CHEMINS DU REPO
# ============================================================================
SCRIPT_DIR = Path(__file__).parent.resolve()
REPO_DIR = SCRIPT_DIR.parent
DATA_DIR = REPO_DIR / "data"

MASTER_FILE = DATA_DIR / "invaders_master.json"
MISSING_FILE = DATA_DIR / "invaders_missing_from_github.json"

def _p(path):
    """Convertit un Path en string pour les fonctions qui attendent str."""
    return str(path)

import requests

# Tentative d'import PIL pour EXIF (optionnel)
try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Tentative d'import pytesseract pour OCR (optionnel)
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

# Tentative d'import OpenCV et numpy pour prétraitement (optionnel)
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

# Configuration
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Mapping des codes ville vers noms
CITY_NAMES = {
    'PA': 'Paris', 'LDN': 'London', 'NY': 'New York', 'LA': 'Los Angeles',
    'TK': 'Tokyo', 'HK': 'Hong Kong', 'ROM': 'Rome', 'MRS': 'Marseille',
    'LYO': 'Lyon', 'BDX': 'Bordeaux', 'AMI': 'Amiens', 'LIL': 'Lille',
    'NCE': 'Nice', 'TLS': 'Toulouse', 'BRC': 'Barcelona', 'MAD': 'Madrid',
    'BRL': 'Berlin', 'AMS': 'Amsterdam', 'VEN': 'Venice', 'FLR': 'Florence',
}

# Centres des villes (fallback si aucune géolocalisation trouvée)
CITY_CENTERS = {
    # France
    'PA': {'lat': 48.8566, 'lng': 2.3522, 'name': 'Paris'},
    'LY': {'lat': 45.7640, 'lng': 4.8357, 'name': 'Lyon'},
    'MARS': {'lat': 43.2965, 'lng': 5.3698, 'name': 'Marseille'},
    'TLS': {'lat': 43.6047, 'lng': 1.4442, 'name': 'Toulouse'},
    'BDX': {'lat': 44.8378, 'lng': -0.5792, 'name': 'Bordeaux'},
    'NA': {'lat': 47.2184, 'lng': -1.5536, 'name': 'Nantes'},
    'NTE': {'lat': 47.2184, 'lng': -1.5536, 'name': 'Nantes'},
    'LIL': {'lat': 50.6292, 'lng': 3.0573, 'name': 'Lille'},
    'LILE': {'lat': 50.6292, 'lng': 3.0573, 'name': 'Lille'},
    'LILL': {'lat': 50.6292, 'lng': 3.0573, 'name': 'Lille'},
    'STR': {'lat': 48.5734, 'lng': 7.7521, 'name': 'Strasbourg'},
    'STRG': {'lat': 48.5734, 'lng': 7.7521, 'name': 'Strasbourg'},
    'MTP': {'lat': 43.6108, 'lng': 3.8767, 'name': 'Montpellier'},
    'MPL': {'lat': 43.6108, 'lng': 3.8767, 'name': 'Montpellier'},
    'NICE': {'lat': 43.7102, 'lng': 7.2620, 'name': 'Nice'},
    'NP': {'lat': 43.7102, 'lng': 7.2620, 'name': 'Nice'},
    'AMI': {'lat': 49.8941, 'lng': 2.2958, 'name': 'Amiens'},
    'ORLN': {'lat': 47.9029, 'lng': 1.9039, 'name': 'Orléans'},
    'DIJ': {'lat': 47.3220, 'lng': 5.0415, 'name': 'Dijon'},
    'GRN': {'lat': 45.1885, 'lng': 5.7245, 'name': 'Grenoble'},
    'AIX': {'lat': 43.5297, 'lng': 5.4474, 'name': 'Aix-en-Provence'},
    'AVI': {'lat': 43.9493, 'lng': 4.8055, 'name': 'Avignon'},
    'NIM': {'lat': 43.8367, 'lng': 4.3601, 'name': 'Nîmes'},
    'CLR': {'lat': 45.7772, 'lng': 3.0870, 'name': 'Clermont-Ferrand'},
    'RN': {'lat': 48.1173, 'lng': -1.6778, 'name': 'Rennes'},
    'RNS': {'lat': 48.1173, 'lng': -1.6778, 'name': 'Rennes'},
    'VRS': {'lat': 48.8014, 'lng': 2.1301, 'name': 'Versailles'},
    'VER': {'lat': 48.8014, 'lng': 2.1301, 'name': 'Versailles'},
    'REIM': {'lat': 49.2583, 'lng': 4.0317, 'name': 'Reims'},
    'BAB': {'lat': 43.4832, 'lng': -1.5586, 'name': 'Bayonne-Anglet-Biarritz'},
    'FTBL': {'lat': 48.4010, 'lng': 2.7024, 'name': 'Fontainebleau'},
    'PAU': {'lat': 43.2965, 'lng': -0.3708, 'name': 'Pau'},
    'PRP': {'lat': 42.6988, 'lng': 2.8948, 'name': 'Perpignan'},
    'MTB': {'lat': 44.0171, 'lng': 1.3527, 'name': 'Montauban'},
    'CAPF': {'lat': 44.6357, 'lng': -1.2479, 'name': 'Cap Ferret'},
    'CAZ': {'lat': 43.2141, 'lng': 5.5378, 'name': 'Cassis'},
    'LCT': {'lat': 43.1748, 'lng': 5.6095, 'name': 'La Ciotat'},
    'LBR': {'lat': 43.8324, 'lng': 5.3658, 'name': 'Luberon'},
    'FRQ': {'lat': 43.9600, 'lng': 5.7810, 'name': 'Forcalquier'},
    'MEN': {'lat': 43.7764, 'lng': 7.5048, 'name': 'Menton'},
    'CON': {'lat': 44.0900, 'lng': -1.3150, 'name': 'Contis'},
    'VLMO': {'lat': 45.4553, 'lng': 6.4506, 'name': 'Valmorel'},
    'REUN': {'lat': -21.1151, 'lng': 55.5364, 'name': 'La Réunion'},
    # UK
    'LDN': {'lat': 51.5074, 'lng': -0.1278, 'name': 'London'},
    'MAN': {'lat': 53.4808, 'lng': -2.2426, 'name': 'Manchester'},
    'NCL': {'lat': 54.9783, 'lng': -1.6178, 'name': 'Newcastle'},
    # Europe
    'BCN': {'lat': 41.3851, 'lng': 2.1734, 'name': 'Barcelona'},
    'BRC': {'lat': 41.3851, 'lng': 2.1734, 'name': 'Barcelona'},
    'ROM': {'lat': 41.9028, 'lng': 12.4964, 'name': 'Rome'},
    'RAV': {'lat': 44.4184, 'lng': 12.2035, 'name': 'Ravenna'},
    'RA': {'lat': 44.4184, 'lng': 12.2035, 'name': 'Ravenna'},
    'FLRN': {'lat': 43.7696, 'lng': 11.2558, 'name': 'Florence'},
    'MLN': {'lat': 45.4642, 'lng': 9.1900, 'name': 'Milan'},
    'VRN': {'lat': 25.2854, 'lng': 82.9990, 'name': 'Varanasi'},
    'MLGA': {'lat': 36.7213, 'lng': -4.4214, 'name': 'Malaga'},
    'BBO': {'lat': 43.2630, 'lng': -2.9350, 'name': 'Bilbao'},
    'AMS': {'lat': 52.3676, 'lng': 4.9041, 'name': 'Amsterdam'},
    'RTD': {'lat': 51.9225, 'lng': 4.4792, 'name': 'Rotterdam'},
    'NOO': {'lat': 52.2361, 'lng': 4.4303, 'name': 'Noordwijk'},
    'BRL': {'lat': 52.5200, 'lng': 13.4050, 'name': 'Berlin'},
    'MUN': {'lat': 48.1351, 'lng': 11.5820, 'name': 'Munich'},
    'KLN': {'lat': 50.9375, 'lng': 6.9603, 'name': 'Cologne'},
    'FKF': {'lat': 50.1109, 'lng': 8.6821, 'name': 'Frankfurt'},
    'WN': {'lat': 48.2082, 'lng': 16.3738, 'name': 'Vienna'},
    'BXL': {'lat': 50.8503, 'lng': 4.3517, 'name': 'Brussels'},
    'CHAR': {'lat': 50.4108, 'lng': 4.4446, 'name': 'Charleroi'},
    'ANVR': {'lat': 51.2194, 'lng': 4.4025, 'name': 'Antwerp'},
    'BRN': {'lat': 46.9480, 'lng': 7.4474, 'name': 'Bern'},
    'BSL': {'lat': 47.5596, 'lng': 7.5886, 'name': 'Basel'},
    'GNV': {'lat': 46.2044, 'lng': 6.1432, 'name': 'Geneva'},
    'LSN': {'lat': 46.5197, 'lng': 6.6323, 'name': 'Lausanne'},
    'ANZR': {'lat': 46.3100, 'lng': 7.3870, 'name': 'Anzère'},
    'LJU': {'lat': 46.0569, 'lng': 14.5058, 'name': 'Ljubljana'},
    'PRT': {'lat': -31.9505, 'lng': 115.8605, 'name': 'Perth'},
    'FAO': {'lat': 37.0194, 'lng': -7.9322, 'name': 'Faro'},
    'LSN': {'lat': 46.5197, 'lng': 6.6323, 'name': 'Lausanne'},
    'IST': {'lat': 41.0082, 'lng': 28.9784, 'name': 'Istanbul'},
    'RVK': {'lat': 64.1466, 'lng': -21.9426, 'name': 'Reykjavik'},
    'HALM': {'lat': 56.6745, 'lng': 12.8578, 'name': 'Halmstad'},
    'VSB': {'lat': 57.6349, 'lng': 18.2948, 'name': 'Visby'},
    'GRU': {'lat': 43.2615, 'lng': 17.0186, 'name': 'Gruž'},
    # Africa
    'MRAK': {'lat': 31.6295, 'lng': -7.9811, 'name': 'Marrakech'},
    'RBA': {'lat': 34.0209, 'lng': -6.8416, 'name': 'Rabat'},
    'DJBA': {'lat': 33.8076, 'lng': 10.8451, 'name': 'Djerba'},
    'MBSA': {'lat': -4.0435, 'lng': 39.6682, 'name': 'Mombasa'},
    # Asia
    'TK': {'lat': 35.6762, 'lng': 139.6503, 'name': 'Tokyo'},
    'HK': {'lat': 22.3193, 'lng': 114.1694, 'name': 'Hong Kong'},
    'BKK': {'lat': 13.7563, 'lng': 100.5018, 'name': 'Bangkok'},
    'BGK': {'lat': 13.7563, 'lng': 100.5018, 'name': 'Bangkok'},
    'KAT': {'lat': 27.7172, 'lng': 85.3240, 'name': 'Kathmandu'},
    'DHK': {'lat': 23.8103, 'lng': 90.4125, 'name': 'Dhaka'},
    'DJN': {'lat': 36.3504, 'lng': 127.3845, 'name': 'Daejeon'},
    'SL': {'lat': 37.5665, 'lng': 126.9780, 'name': 'Seoul'},
    'BT': {'lat': 27.4712, 'lng': 89.6339, 'name': 'Bhutan'},
    'CCU': {'lat': 21.1619, 'lng': -86.8515, 'name': 'Cancún'},
    # Americas
    'NY': {'lat': 40.7128, 'lng': -74.0060, 'name': 'New York'},
    'LA': {'lat': 34.0522, 'lng': -118.2437, 'name': 'Los Angeles'},
    'MIA': {'lat': 25.7617, 'lng': -80.1918, 'name': 'Miami'},
    'SD': {'lat': 32.7157, 'lng': -117.1611, 'name': 'San Diego'},
    'SP': {'lat': -23.5505, 'lng': -46.6333, 'name': 'São Paulo'},
    'POTI': {'lat': -19.5836, 'lng': -65.7531, 'name': 'Potosí'},
    # Oceania
    'MLB': {'lat': -37.8136, 'lng': 144.9631, 'name': 'Melbourne'},
    # Corse / Méditerranée
    'BTA': {'lat': 42.6973, 'lng': 9.4510, 'name': 'Bastia'},
    # Autres / Spéciaux
    'ELT': {'lat': 29.5577, 'lng': 34.9519, 'name': 'Eilat'},
    'GRTI': {'lat': 29.0333, 'lng': -13.6333, 'name': 'Graciosa'},
    'RDU': {'lat': 50.3543, 'lng': 5.4563, 'name': 'Durbuy'},
    'SPACE': {'lat': 0.0, 'lng': 0.0, 'name': 'Space (ISS)'},
    # Alias supplémentaires Flask
    'NCE': {'lat': 43.7102, 'lng': 7.2620, 'name': 'Nice'},
    'FLR': {'lat': 43.7696, 'lng': 11.2558, 'name': 'Florence'},
    'MIL': {'lat': 45.4642, 'lng': 9.1900, 'name': 'Milan'},
    'SF': {'lat': 37.7749, 'lng': -122.4194, 'name': 'San Francisco'},
    'SIN': {'lat': 1.3521, 'lng': 103.8198, 'name': 'Singapore'},
    'MAD': {'lat': 40.4168, 'lng': -3.7038, 'name': 'Madrid'},
    'PRG': {'lat': 50.0755, 'lng': 14.4378, 'name': 'Prague'},
    'WAR': {'lat': 52.2297, 'lng': 21.0122, 'name': 'Warsaw'},
    'SYD': {'lat': -33.8688, 'lng': 151.2093, 'name': 'Sydney'},
    'BHM': {'lat': 52.4862, 'lng': -1.8904, 'name': 'Birmingham'},
    'CF': {'lat': 44.6357, 'lng': -1.2479, 'name': 'Cap Ferret'},
    'CFT': {'lat': 44.6357, 'lng': -1.2479, 'name': 'Cap Ferret'},
    'CFRT': {'lat': 44.6357, 'lng': -1.2479, 'name': 'Cap Ferret'},
    'CAP': {'lat': 48.6815, 'lng': -2.3182, 'name': 'Cap Fréhel'},
    'ARN': {'lat': 44.6608, 'lng': -1.1680, 'name': 'Arcachon'},
    'ARC': {'lat': 44.6608, 'lng': -1.1680, 'name': 'Arcachon'},
    'RON': {'lat': 45.6222, 'lng': -1.0284, 'name': 'Royan'},
    'ROY': {'lat': 45.6222, 'lng': -1.0284, 'name': 'Royan'},
    'LROC': {'lat': 46.1603, 'lng': -1.1511, 'name': 'La Rochelle'},
    'LRC': {'lat': 46.1603, 'lng': -1.1511, 'name': 'La Rochelle'},
    'BRG': {'lat': 51.2093, 'lng': 3.2247, 'name': 'Bruges'},
    'BRUG': {'lat': 51.2093, 'lng': 3.2247, 'name': 'Bruges'},
    'LIS': {'lat': 38.7223, 'lng': -9.1393, 'name': 'Lisbonne'},
    'LX': {'lat': 38.7223, 'lng': -9.1393, 'name': 'Lisbonne'},
    'LSB': {'lat': 38.7223, 'lng': -9.1393, 'name': 'Lisbonne'},
    'GEN': {'lat': 44.4056, 'lng': 8.9463, 'name': 'Gênes'},
    'GNS': {'lat': 44.4056, 'lng': 8.9463, 'name': 'Gênes'},
    'NPL': {'lat': 40.8518, 'lng': 14.2681, 'name': 'Naples'},
    'NAP': {'lat': 40.8518, 'lng': 14.2681, 'name': 'Naples'},
    'VEN': {'lat': 45.4408, 'lng': 12.3155, 'name': 'Venise'},
    'VCE': {'lat': 45.4408, 'lng': 12.3155, 'name': 'Venise'},
    'TUN': {'lat': 36.8065, 'lng': 10.1815, 'name': 'Tunis'},
    'TN': {'lat': 36.8065, 'lng': 10.1815, 'name': 'Tunis'},
    'LEGE': {'lat': 44.6357, 'lng': -1.2479, 'name': 'Lège-Cap-Ferret'},
    'LGF': {'lat': 44.6357, 'lng': -1.2479, 'name': 'Lège-Cap-Ferret'},
}


def calculate_distance(lat1, lng1, lat2, lng2):
    """Calcule la distance en mètres entre deux points GPS"""
    R = 6371000
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    
    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c


# Rayon max de cohérence ville (en mètres)
# Adapté par taille de ville : grandes métropoles = rayon plus large
CITY_MAX_RADIUS = {
    # Grandes métropoles (rayon 40km)
    'PA': 40000, 'LDN': 40000, 'NY': 50000, 'LA': 60000, 'TK': 50000,
    'SP': 40000, 'BRL': 40000, 'ROM': 30000, 'BCN': 25000, 'BRC': 25000,
    # Villes moyennes (rayon 20km)
    'MRS': 20000, 'LYO': 20000, 'BDX': 20000, 'TLS': 20000, 'LIL': 20000,
    'AMS': 20000, 'BXL': 20000, 'MAN': 20000, 'MLB': 30000, 'MIA': 30000,
    'SD': 30000, 'HK': 25000,
    # Petites villes / villages (rayon 10km)
    'FTBL': 10000, 'VRS': 10000, 'CAPF': 10000, 'MEN': 10000, 'CON': 10000,
    'VLMO': 10000, 'CAZ': 10000, 'LCT': 10000, 'FRQ': 10000, 'ANZR': 10000,
    'GRU': 10000, 'NOO': 10000,
    # Îles / zones isolées (rayon 50km)
    'REUN': 50000, 'BT': 80000, 'GRTI': 20000,
}
DEFAULT_CITY_RADIUS = 25000  # 25km par défaut


def validate_city_coherence(lat, lng, city_code, verbose=False):
    """
    Vérifie que les coordonnées trouvées sont cohérentes avec la ville attendue.
    
    Retourne un dict:
    - valid: bool (coordonnées dans le rayon acceptable)
    - distance_to_center: float (distance en mètres au centre-ville)
    - max_radius: float (rayon max accepté pour cette ville)
    - city_name: str
    
    Si la ville est inconnue dans CITY_CENTERS, retourne valid=True (pas de check).
    """
    result = {
        'valid': True,
        'distance_to_center': None,
        'max_radius': None,
        'city_name': None,
        'warning': None,
    }
    
    if not city_code or city_code not in CITY_CENTERS:
        return result
    
    city = CITY_CENTERS[city_code]
    result['city_name'] = city['name']
    
    # Cas spécial: ISS / Space
    if city_code == 'SPACE':
        result['valid'] = True
        return result
    
    center_lat = city['lat']
    center_lng = city['lng']
    max_radius = CITY_MAX_RADIUS.get(city_code, DEFAULT_CITY_RADIUS)
    result['max_radius'] = max_radius
    
    distance = calculate_distance(lat, lng, center_lat, center_lng)
    result['distance_to_center'] = round(distance, 1)
    
    if distance > max_radius:
        result['valid'] = False
        result['warning'] = (
            f"GPS ({lat:.5f}, {lng:.5f}) à {distance/1000:.1f}km du centre de "
            f"{city['name']} (max: {max_radius/1000:.0f}km)"
        )
        if verbose:
            print(f"      ⚠️ INCOHÉRENCE VILLE: {result['warning']}")
    
    return result


def extract_gps_from_image_url(image_url, verbose=False):
    """
    Télécharge une image et extrait les coordonnées GPS des métadonnées EXIF.
    
    Returns:
        dict: {'found': bool, 'lat': float, 'lng': float, 'source': 'exif'}
    """
    result = {'found': False, 'lat': None, 'lng': None, 'source': 'exif', 'error': None}
    
    if not PIL_AVAILABLE:
        result['error'] = 'PIL non disponible'
        return result
    
    if not image_url:
        result['error'] = 'URL vide'
        return result
    
    try:
        if verbose:
            print(f"      [EXIF] Téléchargement: {image_url[:60]}...")
        
        # Télécharger l'image
        response = requests.get(image_url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            result['error'] = f'HTTP {response.status_code}'
            return result
        
        # Vérifier que c'est une image
        content_type = response.headers.get('Content-Type', '')
        if 'image' not in content_type.lower():
            result['error'] = f'Pas une image: {content_type}'
            return result
        
        # Ouvrir l'image
        img = Image.open(BytesIO(response.content))
        
        # Extraire les données EXIF
        exif_data = img._getexif()
        if not exif_data:
            result['error'] = 'Pas de données EXIF'
            return result
        
        # Chercher les données GPS
        gps_info = None
        for tag_id, value in exif_data.items():
            tag = TAGS.get(tag_id, tag_id)
            if tag == 'GPSInfo':
                gps_info = {}
                for gps_tag_id, gps_value in value.items():
                    gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
                    gps_info[gps_tag] = gps_value
                break
        
        if not gps_info:
            result['error'] = 'Pas de GPSInfo dans EXIF'
            return result
        
        # Extraire latitude et longitude
        def convert_to_degrees(value):
            """Convertit les coordonnées GPS EXIF en degrés décimaux"""
            if isinstance(value, tuple) and len(value) == 3:
                d, m, s = value
                # Gérer les ratios (fractions)
                if hasattr(d, 'numerator'):
                    d = d.numerator / d.denominator
                if hasattr(m, 'numerator'):
                    m = m.numerator / m.denominator
                if hasattr(s, 'numerator'):
                    s = s.numerator / s.denominator
                return d + (m / 60.0) + (s / 3600.0)
            return None
        
        lat = convert_to_degrees(gps_info.get('GPSLatitude'))
        lng = convert_to_degrees(gps_info.get('GPSLongitude'))
        
        if lat is None or lng is None:
            result['error'] = 'Coordonnées GPS incomplètes'
            return result
        
        # Appliquer les références (N/S, E/W)
        lat_ref = gps_info.get('GPSLatitudeRef', 'N')
        lng_ref = gps_info.get('GPSLongitudeRef', 'E')
        
        if lat_ref == 'S':
            lat = -lat
        if lng_ref == 'W':
            lng = -lng
        
        # Valider (pas à zéro)
        if abs(lat) < 0.01 and abs(lng) < 0.01:
            result['error'] = 'Coordonnées à zéro'
            return result
        
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            result['error'] = 'Coordonnées hors limites'
            return result
        
        result['found'] = True
        result['lat'] = lat
        result['lng'] = lng
        
        if verbose:
            print(f"      [EXIF] ✅ GPS trouvé: {lat:.6f}, {lng:.6f}")
        
    except Exception as e:
        result['error'] = str(e)
        if verbose:
            print(f"      [EXIF] ❌ Erreur: {e}")
    
    return result


# =============================================================================
# PATTERNS D'ADRESSES FRANÇAISES (enrichis v3)
# =============================================================================
# Supporte: Title Case, TOUT MAJUSCULES, minuscules
# Les plaques parisiennes sont en MAJUSCULES (blanc sur bleu/vert)

# Types de voies français (exhaustif)
FR_STREET_TYPES = [
    'rue', 'avenue', 'boulevard', 'place', 'quai', 'passage',
    'impasse', 'allée', 'cours', 'cité', 'square', 'villa',
    'chemin', 'sentier', 'galerie', 'parvis', 'esplanade',
    'pont', 'port', 'faubourg', 'route', 'ruelle', 'voie',
    'promenade', 'traverse', 'cour', 'résidence', 'hameau',
    'carrefour', 'rond-point', 'mail', 'montée',
]

# Set pour lookup rapide (en minuscules)
FR_STREET_TYPES_SET = set(FR_STREET_TYPES)

# Abréviations courantes
FR_STREET_ABBREVS_PATTERN = r'(?:r\.|av\.?|bd\.?|bl\.?|pl\.|imp\.|all\.|ch\.|fg\.?|rte\.?|prom\.?)'

# Pattern combiné des types de voies
_FR_TYPES_FULL = '|'.join(FR_STREET_TYPES)
_FR_TYPES_ALL = rf"(?:{_FR_TYPES_FULL}|{FR_STREET_ABBREVS_PATTERN})"

# Articles français (de la, du, des, de l', d')
_FR_ARTICLES = r"(?:de\s+la\s+|du\s+|des\s+|de\s+l['\u2019]?\s*|d['\u2019]\s*|de\s+)?"

# Numéro de rue optionnel: 12, 12 bis, 12-14, 12B
_FR_NUM = r"(?:\d{1,4}\s*(?:bis|ter|[A-Ba-b])?\s*[,\-]?\s*)?"

# Noms propres (3 variantes pour couvrir les différents formats d'écriture)
_FR_NAME_TITLE = r"[A-ZÀ-Ÿ][a-zà-ÿ\-']+(?:[\s\-][A-ZÀ-Ÿ][a-zà-ÿ\-']+)*"
_FR_NAME_UPPER = r"[A-ZÀ-Ÿ]{2,}(?:[\s\-][A-ZÀ-Ÿ]{2,})*"
_FR_NAME_MIXED = r"[A-ZÀ-Ÿa-zà-ÿ]{2,}(?:[\s\-][A-ZÀ-Ÿa-zà-ÿ]{2,})*"

FRENCH_ADDRESS_PATTERNS = [
    # Pattern MAJUSCULES plaques parisiennes: "RUE DE LA ROQUETTE", "BOULEVARD VOLTAIRE"
    rf"{_FR_NUM}(?:{_FR_TYPES_ALL})\s+{_FR_ARTICLES}({_FR_NAME_UPPER})",
    # Pattern Title Case: "Rue de la Roquette", "Boulevard Voltaire"
    rf"{_FR_NUM}(?:{_FR_TYPES_ALL})\s+{_FR_ARTICLES}({_FR_NAME_TITLE})",
    # Pattern mixte (OCR imparfait): "rue de la ROQuette"
    rf"{_FR_NUM}(?:{_FR_TYPES_ALL})\s+{_FR_ARTICLES}({_FR_NAME_MIXED})",
    # Arrondissement seul (utile pour contexte): "3e", "11ème", "XIe"
    r"\b(\d{1,2})\s*(?:e|ème|eme|er|ère)\s*(?:arr\.?|arrondissement)?\b",
    r"\b((?:I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX))\s*(?:e|ème)?\s*(?:arr\.?|arrondissement)\b",
]

# =============================================================================
# PATTERNS D'ADRESSES ANGLAISES (UK)
# =============================================================================
UK_STREET_TYPES_LIST = [
    'Street', 'St', 'Road', 'Rd', 'Lane', 'Ln', 'Avenue', 'Ave',
    'Place', 'Pl', 'Gardens', 'Gdns', 'Square', 'Sq', 'Terrace', 'Ter',
    'Court', 'Ct', 'Mews', 'Row', 'Way', 'Close', 'Drive', 'Dr',
    'Crescent', 'Cres', 'Grove', 'Hill', 'Walk', 'Yard', 'Passage',
    'Alley', 'Gate', 'Green', 'Park', 'Bridge', 'Wharf', 'Quay',
]
UK_STREET_TYPES_SET = {s.upper() for s in UK_STREET_TYPES_LIST}
_UK_TYPES = '|'.join(UK_STREET_TYPES_LIST)

UK_BUILDING_TYPES_LIST = [
    'House', 'Building', 'Tower', 'Hall', 'Centre', 'Center',
    'Theatre', 'Theater', 'Opera', 'Museum', 'Gallery', 'Hotel',
    'Station', 'Church', 'Cathedral', 'Palace', 'Castle', 'Abbey',
    'Market', 'Exchange', 'Bank', 'Library', 'College', 'School',
    'Hospital', 'Office', 'Arcade', 'Chambers', 'Lodge', 'Manor',
    'Villa', 'Mansion', 'Arms', 'Inn', 'Pub', 'Bar', 'Shop', 'Store', 'Studios?',
]
UK_BUILDING_TYPES_SET = {s.upper().rstrip('?') for s in UK_BUILDING_TYPES_LIST}
_UK_BUILDINGS = '|'.join(UK_BUILDING_TYPES_LIST)

UK_ADDRESS_PATTERNS = [
    # [Nom] [Type] [Code postal optionnel]
    rf"([A-Z][A-Za-z']+(?:\s+[A-Z][A-Za-z']+)*)\s+({_UK_TYPES})\.?\s*([A-Z]{{1,2}}\d{{1,2}}[A-Z]?\s*\d?[A-Z]{{0,2}})?",
    # Avec numéro devant
    rf"(\d+[A-Za-z]?)\s+([A-Z][A-Za-z']+(?:\s+[A-Z][A-Za-z']+)*)\s+({_UK_TYPES})\.?\s*([A-Z]{{1,2}}\d{{1,2}}[A-Z]?\s*\d?[A-Z]{{0,2}})?",
    # Bâtiments/lieux nommés
    rf"([A-Z][A-Za-z']+(?:\s+[A-Z][A-Za-z']+)*)\s+({_UK_BUILDINGS})",
]

# Patterns pour noms de lieux/enseignes (recherche plus large)
LANDMARK_PATTERNS = [
    # Noms propres en majuscules (enseignes, monuments)
    r"\b([A-Z]{2,}(?:\s+[A-Z]{2,})*)\b",
]

# Mapping des codes ville vers le pays/langue pour choisir les patterns
CITY_COUNTRIES = {
    # UK
    'LDN': 'uk', 'MAN': 'uk', 'BRM': 'uk', 'LPL': 'uk', 'EDI': 'uk', 'GLA': 'uk',
    # France
    'PA': 'fr', 'LYO': 'fr', 'MRS': 'fr', 'BDX': 'fr', 'NTE': 'fr', 'STR': 'fr',
    'TLS': 'fr', 'NCE': 'fr', 'REN': 'fr', 'VRS': 'fr', 'ORLN': 'fr', 'MLH': 'fr',
    # USA
    'NY': 'us', 'LA': 'us', 'SF': 'us', 'MIA': 'us', 'CHI': 'us', 'SD': 'us',
    # Autres
    'TYO': 'jp', 'HK': 'cn', 'BKK': 'th', 'ROM': 'it', 'AMS': 'nl', 'BCN': 'es',
    'MAD': 'es', 'BER': 'de', 'VIE': 'de', 'BRU': 'fr',  # Bruxelles = français
}


def get_address_patterns_for_city(city_code):
    """Retourne les patterns d'adresses appropriés pour une ville"""
    country = CITY_COUNTRIES.get(city_code, 'fr')  # Par défaut français
    
    if country == 'uk':
        return UK_ADDRESS_PATTERNS + FRENCH_ADDRESS_PATTERNS  # UK en priorité
    elif country == 'us':
        return UK_ADDRESS_PATTERNS + FRENCH_ADDRESS_PATTERNS  # US similaire à UK
    else:
        return FRENCH_ADDRESS_PATTERNS + UK_ADDRESS_PATTERNS  # Français en priorité


class ImageOCRAnalyzer:
    """
    Analyse une image via Tesseract OCR pour extraire du texte
    (plaques de rue, enseignes, etc.) et tenter de géolocaliser.
    
    Inclut le prétraitement d'image pour améliorer la détection.
    """
    
    def __init__(self, verbose=False):
        self.verbose = verbose
    
    def log(self, msg):
        if self.verbose:
            print(f"      [OCR] {msg}")
    
    def download_image(self, image_url):
        """Télécharge l'image et retourne un objet PIL Image"""
        try:
            response = requests.get(image_url, headers=HEADERS, timeout=15)
            if response.status_code != 200:
                return None
            
            return Image.open(BytesIO(response.content))
        except Exception as e:
            self.log(f"Erreur téléchargement: {e}")
            return None
    
    def preprocess_image(self, pil_image):
        """
        Applique différents prétraitements à l'image pour améliorer l'OCR.
        Retourne une liste d'images prétraitées (PIL).
        """
        variants = []
        
        # Image originale
        variants.append(('original', pil_image))
        
        if not CV2_AVAILABLE:
            return variants
        
        # Convertir PIL -> OpenCV
        cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        
        # 1. Niveaux de gris
        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
        variants.append(('grayscale', Image.fromarray(gray)))
        
        # 2. Augmentation du contraste (CLAHE)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        contrast = clahe.apply(gray)
        variants.append(('contrast', Image.fromarray(contrast)))
        
        # 3. Binarisation adaptative (bon pour les plaques de rue)
        binary_adaptive = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        variants.append(('binary_adaptive', Image.fromarray(binary_adaptive)))
        
        # 4. Binarisation Otsu (automatique)
        _, binary_otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(('binary_otsu', Image.fromarray(binary_otsu)))
        
        # 5. Binarisation inversée (texte clair sur fond sombre -> texte sombre sur fond clair)
        _, binary_inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        variants.append(('binary_inv', Image.fromarray(binary_inv)))
        
        # 6. Débruitage
        denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
        variants.append(('denoised', Image.fromarray(denoised)))
        
        # 7. Agrandissement x2 (aide pour les petits textes)
        h, w = gray.shape
        if max(h, w) < 1500:  # Seulement si l'image est petite
            enlarged = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
            variants.append(('enlarged', Image.fromarray(enlarged)))
        
        # 8. Sharpening (netteté)
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        sharpened = cv2.filter2D(gray, -1, kernel)
        variants.append(('sharpened', Image.fromarray(sharpened)))
        
        return variants
    
    def extract_text_from_image(self, image, lang='fra+eng'):
        """
        Extrait le texte de l'image via Tesseract OCR.
        Retourne le texte brut détecté.
        """
        if not TESSERACT_AVAILABLE:
            return ""
        
        try:
            # Configurer Tesseract
            # --psm 3 = Automatic page segmentation
            # -l = langue(s)
            custom_config = f'--oem 3 --psm 3 -l {lang}'
            
            text = pytesseract.image_to_string(image, config=custom_config)
            return text
        except Exception as e:
            self.log(f"Erreur OCR: {e}")
            return ""
    
    def extract_text_multi_config(self, image, lang='eng'):
        """
        Essaie plusieurs configurations OCR et combine les résultats.
        Retourne tous les textes uniques trouvés.
        """
        if not TESSERACT_AVAILABLE:
            return set()
        
        texts = set()
        
        # Différents PSM (Page Segmentation Mode) à essayer
        # On évite PSM 11/12 qui génèrent trop de bruit
        psm_modes = [
            (3, 'auto'),           # Fully automatic page segmentation
            (6, 'block'),          # Assume a single uniform block of text
            (7, 'single_line'),    # Treat the image as a single text line
        ]
        
        for psm, mode_name in psm_modes:
            try:
                config = f'--oem 3 --psm {psm} -l {lang}'
                text = pytesseract.image_to_string(image, config=config)
                if text and text.strip():
                    # Ajouter chaque ligne non vide
                    for line in text.strip().split('\n'):
                        # Nettoyer la ligne
                        line = line.strip()
                        # Enlever les caractères parasites courants de l'OCR
                        line = re.sub(r'[|_\[\]{}()<>\\/*#@$%^&+=~`]', ' ', line)
                        line = re.sub(r'\s+', ' ', line).strip()
                        # Enlever les : et ! isolés à la fin
                        line = re.sub(r'[:\!\.]+$', '', line).strip()
                        # Filtrer le bruit: ignorer les lignes avec trop de caractères spéciaux
                        if len(line) > 2 and self._is_valid_text(line):
                            texts.add(line)
            except Exception as e:
                pass  # Ignorer les erreurs silencieusement
        
        return texts
    
    def _is_valid_text(self, text):
        """Vérifie si le texte est valide (pas du bruit OCR)"""
        if len(text) < 3:
            return False
        
        # Nettoyer pour analyse
        clean = text.strip()
        
        # Compter les lettres et chiffres
        alphanumeric = sum(1 for c in clean if c.isalnum())
        letters = sum(1 for c in clean if c.isalpha())
        
        # Au moins 60% de caractères alphanumériques
        if len(clean) > 0 and alphanumeric / len(clean) < 0.6:
            return False
        
        # Au moins 2 lettres
        if letters < 2:
            return False
        
        # Pas trop de tirets ou espaces consécutifs
        if '---' in clean or '   ' in clean or '===' in clean or '———' in clean:
            return False
        
        # Pas de lignes avec uniquement des caractères répétés
        unique_chars = set(clean.replace(' ', '').lower())
        if len(unique_chars) < 3:
            return False
        
        # Ignorer les mots très courts avec caractères bizarres
        if len(clean) <= 4:
            # Pour les mots courts, être plus strict
            if not clean.replace(' ', '').isalpha():
                return False
            if clean.lower() in {'the', 'and', 'for', 'was', 'are', 'but', 'not', 'you', 'all', 'can'}:
                return False
        
        # Ignorer les séquences qui ressemblent à du bruit
        noise_patterns = [
            r'^[a-z\s]{1,3}$',           # Très court en minuscules
            r'^[—\-\s]+$',               # Juste des tirets
            r'^\W+$',                     # Juste des symboles
            r'^[aeiouy\s]+$',            # Juste des voyelles
            r'^[^a-zA-Z]*$',             # Pas de lettres
            r'^[a-z]\s[a-z]\s[a-z]',     # Lettres espacées (a i a)
            r'[—\-]{2,}',                 # Tirets multiples
        ]
        for pattern in noise_patterns:
            if re.match(pattern, clean, re.IGNORECASE):
                return False
        
        # Ignorer les mots avec beaucoup de 'i' et 'l' mélangés (bruit OCR typique)
        il_count = sum(1 for c in clean.lower() if c in 'il1|!')
        if len(clean) > 3 and il_count / len(clean) > 0.4:
            return False
        
        return True
    
    def _is_valid_street_name(self, address):
        """Vérifie si l'adresse contient un nom de rue valide (FR ou UK)"""
        # Rejeter si trop court
        if len(address) < 5:
            return False
        
        words = address.split()
        
        # Rejeter si trop de mots courts (bruit OCR typique)
        short_words = sum(1 for w in words if len(w) <= 2)
        if len(words) > 3 and short_words / len(words) > 0.5:
            return False
        
        # Vérifier pattern français
        fr_types_lower = '|'.join(FR_STREET_TYPES)
        fr_match = re.match(
            rf'^(\d+\s*(?:bis|ter)?\s*[,\-]?\s*)?({fr_types_lower}|{FR_STREET_ABBREVS_PATTERN})\s+(.+)$',
            address, re.IGNORECASE
        )
        if fr_match:
            name = fr_match.group(3)
            # Nettoyer les articles
            name = re.sub(r"^(?:de\s+la\s+|du\s+|des\s+|de\s+l['\u2019]?\s*|d['\u2019]?\s*|de\s+)",
                         '', name, flags=re.IGNORECASE).strip()
            if len(name) >= 3 and sum(1 for c in name if c.isalpha()) >= 3:
                if 'ii' not in name.lower() and not re.search(r'(.)\1{3,}', name):
                    return True
        
        # Vérifier pattern UK
        uk_types = '|'.join(UK_STREET_TYPES_LIST)
        uk_match = re.match(rf'^(.+?)\s+({uk_types})\.?\s*', address, re.IGNORECASE)
        if uk_match:
            name = uk_match.group(1).strip()
            if len(name) >= 3 and sum(1 for c in name if c.isalpha()) >= 3:
                if 'ii' not in name.lower():
                    return True
        
        # Vérifier pattern bâtiment UK
        uk_builds = '|'.join(UK_BUILDING_TYPES_LIST)
        build_match = re.match(rf'^(.+?)\s+({uk_builds})\s*', address, re.IGNORECASE)
        if build_match:
            name = build_match.group(1).strip()
            if len(name) >= 3:
                return True
        
        return False
    
    def extract_text_with_preprocessing(self, pil_image, lang='eng'):
        """
        Applique le prétraitement et essaie plusieurs configs OCR.
        Retourne le texte combiné de toutes les variantes.
        """
        all_texts = set()
        
        # Générer les variantes prétraitées
        variants = self.preprocess_image(pil_image)
        self.log(f"{len(variants)} variantes d'image générées")
        
        # Pour chaque variante, essayer plusieurs configs OCR
        for variant_name, variant_image in variants:
            texts = self.extract_text_multi_config(variant_image, lang)
            if texts:
                self.log(f"  {variant_name}: {len(texts)} texte(s)")
                all_texts.update(texts)
        
        return all_texts
    
    def find_addresses_in_text(self, text, city_name=None, city_code=None):
        """
        Cherche des patterns d'adresses dans le texte extrait.
        Retourne une liste d'adresses trouvées.
        """
        direct_addresses = []
        
        # Choisir les patterns selon la ville
        patterns = get_address_patterns_for_city(city_code) if city_code else FRENCH_ADDRESS_PATTERNS + UK_ADDRESS_PATTERNS
        
        # D'abord chercher ligne par ligne (évite de joindre du bruit)
        for line in text.split('\n'):
            line = line.strip()
            if len(line) < 5:
                continue
            
            # Nettoyer la ligne
            clean_line = line.replace('|', ' ').replace('_', ' ')
            clean_line = ' '.join(clean_line.split())
            
            for pattern in patterns:
                matches = re.finditer(pattern, clean_line, re.IGNORECASE)
                for match in matches:
                    full_match = match.group(0).strip()
                    full_match = ' '.join(full_match.split())
                    
                    # Valider le nom de rue (pas de bruit OCR)
                    if self._is_valid_street_name(full_match):
                        if not re.search(r'[A-Z]{1,2}\d[A-Z]?$', full_match):
                            full_match = re.sub(r'\s+[A-Za-z]{1,2}$', '', full_match)
                        if len(full_match) > 5 and full_match not in direct_addresses:
                            direct_addresses.append(full_match)
                            self.log(f"Adresse directe: {full_match}")
        
        # Toujours essayer la recombinaison des fragments
        recombined = self._recombine_fragments(text, city_code)
        
        # Combiner: recombinées d'abord (plus fiables si scoring élevé), puis directes
        addresses = []
        
        # Ajouter les recombinées en premier (elles ont un scoring)
        for addr in recombined:
            if addr not in addresses:
                addresses.append(addr)
        
        # Ajouter les directes ensuite
        for addr in direct_addresses:
            if addr not in addresses:
                addresses.append(addr)
        
        # Ajouter la ville si connue
        if addresses and city_name:
            addresses = [f"{addr}, {city_name}" for addr in addresses]
        
        return addresses
    
    def _recombine_fragments(self, text, city_code=None):
        """
        Essaie de recombiner des fragments de texte OCR en adresses.
        Supporte FR et UK.
        
        Exemples FR: "RUE", "DE LA", "ROQUETTE" → "RUE DE LA ROQUETTE"
        Exemples UK: "SPRING", "GARDENS", "SW1" → "SPRING GARDENS SW1"
        """
        candidates = []  # (score, address)
        country = CITY_COUNTRIES.get(city_code, 'fr')
        
        # Séparer en lignes puis en mots
        lines = [l.strip() for l in text.upper().split('\n') if l.strip()]
        all_words = []
        for line in lines:
            words = line.split()
            all_words.extend([w.strip() for w in words if len(w.strip()) > 1])
        
        # =====================================================================
        # RECOMBINAISON FRANÇAISE
        # =====================================================================
        if country in ('fr', 'it', 'es', 'nl', 'de'):
            candidates.extend(self._recombine_french(lines, all_words, city_code))
        
        # =====================================================================
        # RECOMBINAISON UK / US
        # =====================================================================
        if country in ('uk', 'us'):
            candidates.extend(self._recombine_uk(lines, all_words))
        
        # Si pays inconnu, essayer les deux
        if country not in ('fr', 'it', 'es', 'nl', 'de', 'uk', 'us'):
            candidates.extend(self._recombine_french(lines, all_words, city_code))
            candidates.extend(self._recombine_uk(lines, all_words))
        
        # Trier par score décroissant et dédupliquer
        candidates.sort(key=lambda x: -x[0])
        seen = set()
        unique = []
        for score, address in candidates:
            key = address.upper()
            if key not in seen and score >= 40:
                seen.add(key)
                unique.append((score, address))
                self.log(f"Candidat (score={score}): {address}")
        
        return [addr for score, addr in unique[:5]]
    
    def _recombine_french(self, lines, all_words, city_code=None):
        """Recombinaison spécifique FR"""
        candidates = []
        
        # Noms de rues/places connus à Paris (bonus scoring fort)
        KNOWN_FR_NAMES = {
            # Grandes artères parisiennes
            'RIVOLI', 'VOLTAIRE', 'REPUBLIQUE', 'RÉPUBLIQUE', 'BELLEVILLE',
            'ROQUETTE', 'OBERKAMPF', 'MÉNILMONTANT', 'MENILMONTANT',
            'CHARONNE', 'BASTILLE', 'TEMPLE', 'TURBIGO', 'RÉAUMUR', 'REAUMUR',
            'SÉBASTOPOL', 'SEBASTOPOL', 'MAGENTA', 'STRASBOURG',
            'HAUSSMANN', 'OPÉRA', 'OPERA', 'MADELEINE', 'CONCORDE',
            'CHAMPS', 'ÉLYSÉES', 'ELYSEES', 'MONTMARTRE', 'PIGALLE',
            'CLICHY', 'BATIGNOLLES', 'SAINT', 'SAINTE', 'FAUBOURG',
            'VAUGIRARD', 'GRENELLE', 'LECOURBE', 'CONVENTION',
            'DAGUERRE', 'ALÉSIA', 'ALESIA', 'TOLBIAC', 'GLACIÈRE', 'GLACIERE',
            'MOUFFETARD', 'MONGE', 'JUSSIEU', 'CARDINAL', 'LEMOINE',
            'POPINCOURT', 'FOLIE', 'MÉRICOURT', 'MERICOURT',
            'BUTTES', 'CHAUMONT', 'JOURDAIN', 'PYRÉNÉES', 'PYRENEES',
            'GAMBETTA', 'PÈRE', 'PERE', 'LACHAISE', 'MARAIS', 'FRANCS',
            'BOURGEOIS', 'ARCHIVES', 'BRETAGNE', 'TURENNE', 'BEAUMARCHAIS',
            'RICHARD', 'LENOIR', 'PARMENTIER', 'JEAN', 'PIERRE', 'TIMBAUD',
            # Noms propres courants
            'VICTOR', 'HUGO', 'JEAN', 'JAURÈS', 'JAURES', 'LÉON', 'LEON',
            'GAMBETTA', 'DANTON', 'VOLTAIRE', 'MOLIÈRE', 'MOLIERE',
            'PASTEUR', 'RASPAIL', 'DENFERT', 'ROCHEREAU',
            # Londres
            'OXFORD', 'BAKER', 'REGENT', 'BOND', 'FLEET', 'STRAND',
            'BRICK', 'CARNABY', 'SOHO', 'COVENT', 'PICCADILLY',
            'PORTOBELLO', 'CAMDEN', 'BRIXTON', 'SHOREDITCH',
        }
        
        # Trouver les types de voies dans le texte
        fr_types_upper = {t.upper() for t in FR_STREET_TYPES}
        found_types = []
        for i, line in enumerate(lines):
            for word in line.split():
                clean = word.strip('.,;:!?')
                if clean in fr_types_upper:
                    found_types.append((clean, i, line))
        
        if not found_types:
            return candidates
        
        # Pour chaque type de voie trouvé, chercher le nom qui suit
        for street_type, line_idx, full_line in found_types:
            # Stratégie 1: tout est sur la même ligne
            # Ex: "RUE DE LA ROQUETTE" ou "BOULEVARD VOLTAIRE"
            type_pos = full_line.find(street_type)
            after_type = full_line[type_pos + len(street_type):].strip()
            
            # Nettoyer les articles au début
            after_clean = re.sub(
                r"^(?:DE\s+LA\s+|DU\s+|DES\s+|DE\s+L['\u2019]?\s*|D['\u2019]?\s*|DE\s+)",
                '', after_type, flags=re.IGNORECASE
            ).strip()
            
            if after_clean and len(after_clean) >= 3:
                # Construire l'adresse complète
                address = f"{street_type} {after_type}".strip()
                # Chercher un numéro avant le type sur la même ligne
                before_type = full_line[:type_pos].strip()
                num_match = re.search(r'(\d{1,4})\s*$', before_type)
                if num_match:
                    address = f"{num_match.group(1)} {address}"
                
                score = self._score_french_address(address, after_clean, KNOWN_FR_NAMES)
                if score > 0:
                    candidates.append((score, address.title()))
            
            # Stratégie 2: nom sur la ligne suivante
            if line_idx + 1 < len(lines):
                next_line = lines[line_idx + 1].strip()
                # Ignorer si la ligne suivante est un autre type de voie
                if next_line.split()[0] if next_line else '' not in fr_types_upper:
                    next_clean = re.sub(
                        r"^(?:DE\s+LA\s+|DU\s+|DES\s+|DE\s+L['\u2019]?\s*|D['\u2019]?\s*|DE\s+)",
                        '', next_line, flags=re.IGNORECASE
                    ).strip()
                    if next_clean and len(next_clean) >= 3:
                        # Combiner type + articles + nom
                        combined = f"{street_type} {next_line}".strip()
                        score = self._score_french_address(combined, next_clean, KNOWN_FR_NAMES)
                        # Bonus pour adjacence de lignes
                        score += 10
                        if score > 0:
                            candidates.append((score, combined.title()))
        
        # Stratégie 3: chercher des noms connus isolés
        for word in all_words:
            clean = word.strip('.,;:!?')
            if clean in KNOWN_FR_NAMES and clean not in fr_types_upper:
                # Chercher un type de voie à proximité
                for street_type, _, _ in found_types:
                    address = f"{street_type} {clean}"
                    candidates.append((60, address.title()))
        
        return candidates
    
    def _score_french_address(self, address, name_part, known_names):
        """Score une adresse française candidate"""
        score = 0
        words = name_part.split()
        
        # Bonus si un mot est un nom connu
        for w in words:
            if w.strip('.,;:!?') in known_names:
                score += 50
                break
        
        # Bonus si le nom a une longueur raisonnable (3-40 chars)
        if 3 <= len(name_part) <= 40:
            score += 20
        
        # Bonus si plusieurs mots (plus spécifique)
        if len(words) >= 2:
            score += 10
        
        # Bonus voyelles présentes (pas du bruit consonantique)
        vowels = sum(1 for c in name_part if c in 'AEIOUYÀÂÉÈÊËÏÎÔÙÛÜ')
        if vowels >= 1:
            score += 15
        
        # Malus: caractères répétés ou patterns bizarres
        if re.search(r'(.)\1{2,}', name_part):
            score -= 30
        if len(set(name_part.replace(' ', ''))) < 4:
            score -= 30
        # Malus: trop de consonnes consécutives
        if re.search(r'[BCDFGHJKLMNPQRSTVWXZ]{4,}', name_part):
            score -= 20
        
        return score
    
    def _recombine_uk(self, lines, all_words):
        """Recombinaison spécifique UK (inchangée, refactorisée)"""
        candidates = []
        
        # Noms communs UK
        common_uk_names = {
            'SPRING', 'OXFORD', 'BAKER', 'ABBEY', 'KINGS', 'QUEENS',
            'VICTORIA', 'REGENT', 'BOND', 'FLEET', 'STRAND', 'SOHO',
            'BRICK', 'DEAN', 'GREEK', 'POLAND', 'CARNABY', 'COVENT',
            'TRAFALGAR', 'LEICESTER', 'PICCADILLY', 'CHELSEA', 'DANSEY',
            'ARBLAY', "D'ARBLAY", 'ILFORD', 'WARDOUR', 'BERWICK', 'FRITH',
            'WHITEHALL', 'DOWNING', 'PORTOBELLO', 'CAMDEN', 'BRIXTON',
        }
        uk_postcode_pattern = re.compile(r'^[A-Z]{1,2}\d{1,2}[A-Z]?$')
        
        # Extraire numéros par fréquence
        number_counts = {}
        for line in lines:
            for n in re.findall(r'\b(\d{1,3})\b', line):
                if 1 <= int(n) <= 999:
                    number_counts[n] = number_counts.get(n, 0) + 1
        sorted_numbers = sorted(number_counts.keys(),
                               key=lambda x: (-number_counts[x], -int(x)))
        
        # Trouver fragments de type rue
        street_fragments = []
        for line in lines:
            for st in UK_STREET_TYPES_SET:
                if re.search(rf'\b{st}\b', line):
                    m = re.search(rf'({st}\s*[A-Z]{{1,2}}\d{{1,2}}[A-Z]?)', line)
                    street_fragments.append((st, m.group(1) if m else st, 'street'))
        
        building_fragments = []
        for line in lines:
            for bt in UK_BUILDING_TYPES_SET:
                if re.search(rf'\b{bt}\b', line):
                    building_fragments.append((bt, bt, 'building'))
        
        # Noms potentiels
        potential_names = []
        for word in all_words:
            clean = re.sub(r'[^A-Z]', '', word)
            if len(clean) >= 4 and clean.isalpha():
                if clean not in UK_STREET_TYPES_SET and clean not in UK_BUILDING_TYPES_SET:
                    potential_names.append(clean)
        
        # Combiner
        for name in potential_names:
            for frag_type, fragment, kind in street_fragments:
                if not fragment.startswith(name):
                    address = f"{name} {fragment}"
                    score = self._score_address(name, fragment, common_uk_names, uk_postcode_pattern)
                    if score > 0:
                        candidates.append((score, address))
            
            for bt, fragment, kind in building_fragments:
                address = f"{name} {fragment}"
                score = self._score_address(name, fragment, common_uk_names, uk_postcode_pattern)
                if name in common_uk_names:
                    score += 20
                if score > 0:
                    for num in sorted_numbers:
                        freq_bonus = number_counts[num] * 5
                        candidates.append((score + 25 + freq_bonus, f"{num} {address}"))
                    candidates.append((score, address))
        
        return candidates
    
    def _score_address(self, name, fragment, common_names, postcode_pattern):
        """Calcule un score pour une adresse candidate"""
        score = 0
        
        # Bonus si le nom est un nom connu
        if name in common_names:
            score += 50
        
        # Bonus si le nom ressemble à un mot anglais (voyelles présentes)
        vowels = sum(1 for c in name if c in 'AEIOU')
        if vowels >= 1 and vowels <= len(name) - 2:
            score += 20
        
        # Bonus si le fragment inclut un code postal
        if re.search(r'[A-Z]{1,2}\d', fragment):
            score += 30
        
        # Malus si le nom contient des patterns bizarres
        if 'II' in name or len(set(name)) < 4:
            score -= 30
        
        # Malus si trop de consonnes consécutives
        if re.search(r'[BCDFGHJKLMNPQRSTVWXZ]{4,}', name):
            score -= 20
        
        return score
    
    def geocode_address(self, address, city_code=None):
        """
        Géocode une adresse via Nominatim (structuré puis free-form).
        Valide le résultat contre la ville attendue.
        
        Stratégie:
        1. Requête structurée (street=, city=, country=) — plus précise
        2. Si échec: requête free-form (q=) avec ville en suffixe
        3. Validation des coordonnées contre la ville attendue
        """
        city_name = None
        country_code = None
        if city_code:
            city_info = CITY_CENTERS.get(city_code)
            if city_info:
                city_name = city_info.get('name')
            country = CITY_COUNTRIES.get(city_code, 'fr')
            country_map = {
                'fr': 'fr', 'uk': 'gb', 'us': 'us', 'it': 'it', 'es': 'es',
                'de': 'de', 'nl': 'nl', 'jp': 'jp', 'cn': 'cn', 'th': 'th',
            }
            country_code = country_map.get(country)
        
        base_url = "https://nominatim.openstreetmap.org/search"
        headers = {'User-Agent': 'InvaderHunter/3.0'}
        
        # Stratégie 1: requête structurée
        if city_name:
            try:
                params = {
                    'street': address,
                    'city': city_name,
                    'format': 'json',
                    'limit': 3,
                    'addressdetails': 1,
                }
                if country_code:
                    params['countrycodes'] = country_code
                
                response = requests.get(base_url, params=params, headers=headers, timeout=10)
                if response.status_code == 200:
                    results = response.json()
                    geo = self._pick_best_nominatim_result(results, city_code)
                    if geo:
                        self.log(f"Geocode structuré: {geo['lat']:.5f}, {geo['lng']:.5f}")
                        return geo
            except Exception as e:
                self.log(f"Erreur geocode structuré: {e}")
        
        # Stratégie 2: requête free-form avec ville
        try:
            query = address
            if city_name and city_name.lower() not in address.lower():
                query = f"{address}, {city_name}"
            
            params = {
                'q': query,
                'format': 'json',
                'limit': 3,
                'addressdetails': 1,
            }
            if country_code:
                params['countrycodes'] = country_code
            
            response = requests.get(base_url, params=params, headers=headers, timeout=10)
            if response.status_code == 200:
                results = response.json()
                geo = self._pick_best_nominatim_result(results, city_code)
                if geo:
                    self.log(f"Geocode free-form: {geo['lat']:.5f}, {geo['lng']:.5f}")
                    return geo
        except Exception as e:
            self.log(f"Erreur geocode free-form: {e}")
        
        return None
    
    def _pick_best_nominatim_result(self, results, city_code=None):
        """
        Parmi les résultats Nominatim, choisit le meilleur.
        Priorise les résultats cohérents avec la ville attendue.
        """
        if not results:
            return None
        
        best = None
        best_distance = float('inf')
        
        for r in results:
            lat = float(r['lat'])
            lng = float(r['lon'])
            
            # Ignorer les coordonnées nulles
            if abs(lat) < 0.01 and abs(lng) < 0.01:
                continue
            
            candidate = {
                'lat': lat,
                'lng': lng,
                'display_name': r.get('display_name', ''),
                'type': r.get('type', ''),
                'importance': float(r.get('importance', 0)),
            }
            
            # Validation contre la ville
            if city_code and city_code in CITY_CENTERS:
                check = validate_city_coherence(lat, lng, city_code)
                if check['valid']:
                    dist = check['distance_to_center'] or float('inf')
                    if dist < best_distance:
                        best = candidate
                        best_distance = dist
                else:
                    self.log(f"Nominatim rejeté: {check['warning']}")
            else:
                # Pas de ville à valider, prendre le premier
                if best is None:
                    best = candidate
        
        return best
    
    def analyze(self, image_url, city_name=None, city_code=None):
        """
        Analyse complète: télécharge l'image, extrait le texte via OCR,
        cherche des adresses et géocode.
        
        Returns:
            dict: {'found': bool, 'lat': float, 'lng': float, 'address': str, 'source': 'ocr'}
        """
        result = {
            'found': False,
            'lat': None,
            'lng': None,
            'address': None,
            'source': 'ocr',
            'text_found': '',
            'texts_all': [],
            'error': None
        }
        
        if not TESSERACT_AVAILABLE:
            result['error'] = 'Tesseract non disponible'
            return result
        
        if not PIL_AVAILABLE:
            result['error'] = 'PIL non disponible'
            return result
        
        if not image_url:
            result['error'] = 'URL vide'
            return result
        
        # 1. Télécharger l'image
        self.log(f"Téléchargement: {image_url[:50]}...")
        image = self.download_image(image_url)
        if not image:
            result['error'] = 'Échec téléchargement'
            return result
        
        # 2. Extraire le texte via OCR avec prétraitement
        # Choisir la langue selon le pays
        country = CITY_COUNTRIES.get(city_code, 'fr') if city_code else 'fr'
        if country == 'uk' or country == 'us':
            lang = 'eng'  # Anglais en priorité
        else:
            lang = 'eng'  # On utilise eng qui marche mieux, les patterns gèrent le français
        
        self.log(f"Extraction OCR avec prétraitement (lang={lang})...")
        
        # Utiliser la nouvelle méthode avec prétraitement
        all_texts = self.extract_text_with_preprocessing(image, lang)
        
        # Convertir en texte pour l'affichage et le stockage
        text = '\n'.join(sorted(all_texts))
        result['text_found'] = text
        result['texts_all'] = list(all_texts)
        
        if not all_texts:
            result['error'] = 'Aucun texte détecté'
            return result
        
        self.log(f"Textes uniques extraits ({len(all_texts)}):")
        for line in sorted(all_texts):
            self.log(f"   │ {line}")
        
        # 3. Chercher des adresses dans tous les textes combinés
        addresses = self.find_addresses_in_text(text, city_name, city_code)
        
        if not addresses:
            result['error'] = 'Aucune adresse détectée dans le texte'
            return result
        
        # 4. Géocoder la première adresse trouvée
        for addr in addresses:
            self.log(f"Géocodage: {addr}")
            geo = self.geocode_address(addr, city_code=city_code)
            if geo:
                result['found'] = True
                result['lat'] = geo['lat']
                result['lng'] = geo['lng']
                result['address'] = addr
                self.log(f"✅ GPS trouvé: {geo['lat']:.6f}, {geo['lng']:.6f}")
                break
        
        if not result['found']:
            result['error'] = 'Géocodage échoué pour toutes les adresses'
        
        return result


class VisionAnalyzer:
    """
    Analyse d'image via Claude Vision API (Anthropic) — v2.
    
    Fonctionnalités:
    - Multi-images: image_lieu (vue large) + image_close (gros plan) pour croiser les indices
    - Prompts adaptés par ville (plaques parisiennes, postcodes UK, etc.)
    - Recherche web des commerces/landmarks identifiés par la Vision
    
    Nécessite: pip install anthropic
    Usage: --anthropic-key sk-ant-... (ou env ANTHROPIC_API_KEY)
    Coût: ~0.003-0.006€ par invader (1-2 images Sonnet)
    """
    
    VISION_MODEL = "claude-sonnet-4-5-20250929"
    
    # Prompts spécifiques par pays/ville
    CITY_HINTS = {
        'PA': {
            'context': "Paris, France",
            'hints': """Indices spécifiques à Paris:
- Les plaques de rue parisiennes sont BLANCHES sur fond BLEU (rues) ou VERT (boulevards/avenues)
- Elles indiquent souvent l'arrondissement en bas (ex: "3e Arr't", "11e")  
- Numérotation: les numéros pairs sont à droite en montant
- Cherche: plaques Vélib', bouches de métro RATP style Hector Guimard, colonnes Morris, fontaines Wallace
- Les pharmacies ont des croix vertes, les tabacs ont des losanges rouges
- Style haussmannien = pierre de taille, balcons filants aux 2e et 5e étages"""
        },
        'LDN': {
            'context': "Londres, UK",
            'hints': """Indices spécifiques à Londres:
- Les plaques de rue sont BLANCHES sur fond NOIR ou BLEU (selon le borough)
- Les postcodes UK sont visibles partout (ex: SW1, EC1, W1, E2)
- Cherche: cabines téléphoniques rouges, bus à impériale rouges, plaques rondes bleues (English Heritage)
- Briques rouges = typique Est londonien (Shoreditch, Brick Lane)
- Cherche les noms de pubs, off-licences, charity shops"""
        },
        'LYO': {
            'context': "Lyon, France",
            'hints': """Indices spécifiques à Lyon:
- Plaques de rue similaires à Paris (blanches sur bleu/vert)
- Cherche: traboules (passages couverts), murs peints, quais de Saône/Rhône
- Quartiers: Croix-Rousse (pentes, murs en pisé), Vieux Lyon (Renaissance), Confluence"""
        },
        'MRS': {
            'context': "Marseille, France",
            'hints': """Indices spécifiques à Marseille:
- Plaques de rue en céramique bleue et blanche typiques
- Cherche: Bonne Mère en arrière-plan, Vieux-Port, calanques
- Style: immeubles colorés, volets bleus"""
        },
        'TK': {
            'context': "Tokyo, Japon",
            'hints': """Indices spécifiques à Tokyo:
- Plaques de rue en japonais (kanji/hiragana) + romanisation
- Numérotation par bloc (chōme-ban-gō)
- Cherche: enseignes en katakana, konbini (7-Eleven, Lawson, FamilyMart)
- Style: fils électriques, distributeurs automatiques, architecture mixte"""
        },
        'BKK': {
            'context': "Bangkok, Thaïlande",
            'hints': """Indices spécifiques à Bangkok:
- Texte en thaï + translittération latine
- Soi (ruelles) numérotées depuis les routes principales
- Cherche: tuk-tuks, temples, fils électriques très denses, 7-Eleven omniprésents"""
        },
    }
    
    # Prompt par défaut pour les villes sans hints spécifiques
    DEFAULT_HINTS = """Indices généraux:
- Cherche les plaques de rue, panneaux de signalisation, numéros de bâtiments
- Identifie les enseignes commerciales, restaurants, pharmacies
- Note le style architectural, les monuments reconnaissables
- Cherche les codes postaux, noms de quartiers"""
    
    SYSTEM_PROMPT_TEMPLATE = """Tu es un expert en géolocalisation d'œuvres de street art, 
spécialisé dans les mosaïques Space Invaders de l'artiste Invader.

Contexte: L'invader se situe à {city_context}.

{city_hints}

Analyse les images fournies et identifie TOUS les indices de localisation visibles.
Si plusieurs images sont fournies, la première est une vue large (contexte) et la seconde un gros plan (détails).
Croise les indices des deux images.

Réponds UNIQUEMENT avec un JSON valide (pas de markdown, pas de ```):
{{
  "street_signs": ["texte exact de chaque plaque de rue visible"],
  "building_numbers": ["numéros de bâtiments visibles"],
  "shop_signs": ["noms d'enseignes/commerces visibles avec type si possible"],
  "landmarks": ["monuments ou bâtiments reconnaissables"],
  "district": "arrondissement ou quartier si identifiable",
  "postcode": "code postal si visible",
  "metro_bus": ["stations de métro/bus/tram visibles"],
  "architectural_style": "style architectural observé",
  "other_clues": ["tout autre indice de localisation"],
  "best_address_guess": "ta meilleure estimation d'adresse complète incluant la ville",
  "confidence": "HIGH/MEDIUM/LOW",
  "reasoning": "explication courte de ton raisonnement"
}}"""
    
    def __init__(self, api_key=None, verbose=False):
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY')
        self.verbose = verbose
        self.enabled = False
        self.client = None
        
        if self.api_key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key)
                self.enabled = True
                print("   🧠 Claude Vision activé (multi-images + recherche web)")
            except ImportError:
                print("   ⚠️ Claude Vision: 'pip install anthropic' requis")
            except Exception as e:
                print(f"   ⚠️ Claude Vision init: {e}")
    
    def log(self, msg):
        if self.verbose:
            print(f"      [VISION] {msg}")
    
    def _download_image_base64(self, image_url):
        """Télécharge l'image et retourne le base64 + media type"""
        try:
            response = requests.get(image_url, headers=HEADERS, timeout=15)
            if response.status_code != 200:
                self.log(f"HTTP {response.status_code} pour {image_url[:50]}")
                return None, None
            
            content_type = response.headers.get('content-type', 'image/jpeg')
            if 'png' in content_type:
                media_type = 'image/png'
            elif 'webp' in content_type:
                media_type = 'image/webp'
            elif 'gif' in content_type:
                media_type = 'image/gif'
            else:
                media_type = 'image/jpeg'
            
            import base64
            b64 = base64.standard_b64encode(response.content).decode('utf-8')
            
            if len(response.content) > 20 * 1024 * 1024:
                self.log("Image trop grande (>20MB)")
                return None, None
            
            self.log(f"Image: {len(response.content)//1024}KB, {media_type}")
            return b64, media_type
            
        except Exception as e:
            self.log(f"Erreur téléchargement: {e}")
            return None, None
    
    def _build_prompt(self, city_code=None, city_name=None):
        """Construit le system prompt adapté à la ville"""
        # Chercher les hints spécifiques à la ville
        city_info = self.CITY_HINTS.get(city_code, {})
        city_context = city_info.get('context', city_name or 'ville inconnue')
        city_hints = city_info.get('hints', self.DEFAULT_HINTS)
        
        return self.SYSTEM_PROMPT_TEMPLATE.format(
            city_context=city_context,
            city_hints=city_hints,
        )
    
    def _call_vision(self, images, city_code=None, city_name=None):
        """
        Envoie une ou plusieurs images à Claude Vision.
        
        Args:
            images: list of (b64, media_type, label) tuples
            city_code: code ville pour prompt adapté
            city_name: nom ville pour contexte
            
        Returns: dict (parsed JSON) or None
        """
        try:
            system_prompt = self._build_prompt(city_code, city_name)
            
            # Construire le contenu multi-images
            content = []
            for b64, media_type, label in images:
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64,
                    }
                })
                content.append({
                    "type": "text",
                    "text": f"[{label}]"
                })
            
            content.append({
                "type": "text",
                "text": "Analyse ces images et identifie tous les indices de localisation."
            })
            
            response = self.client.messages.create(
                model=self.VISION_MODEL,
                max_tokens=1200,
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": content
                }]
            )
            
            raw = response.content[0].text.strip()
            self.log(f"Réponse brute: {raw[:300]}...")
            
            # Parser le JSON
            raw = re.sub(r'^```json\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            
            return json.loads(raw)
            
        except json.JSONDecodeError as e:
            self.log(f"JSON invalide: {e}")
            # Extraction de secours
            addr_match = re.search(r'"best_address_guess"\s*:\s*"([^"]+)"', raw)
            if addr_match:
                return {'best_address_guess': addr_match.group(1), 'confidence': 'LOW'}
            return None
        except Exception as e:
            self.log(f"Erreur Vision API: {e}")
            return None
    
    def _search_landmark_address(self, name, city_name=None):
        """
        Recherche l'adresse d'un commerce/landmark via Nominatim.
        Ex: "Boulangerie Dupain" → "12 Rue de la Roquette, Paris"
        """
        try:
            query = name
            if city_name:
                query = f"{name}, {city_name}"
            
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                'q': query,
                'format': 'json',
                'limit': 3,
                'addressdetails': 1,
            }
            response = requests.get(url, params=params,
                                    headers={'User-Agent': 'InvaderHunter/3.0'},
                                    timeout=10)
            
            if response.status_code == 200:
                results = response.json()
                if results:
                    r = results[0]
                    lat = float(r['lat'])
                    lng = float(r['lon'])
                    display = r.get('display_name', '')
                    self.log(f"Landmark '{name}' → {lat:.5f}, {lng:.5f} ({display[:60]})")
                    return {
                        'lat': lat, 'lng': lng,
                        'display_name': display,
                        'source_name': name,
                    }
        except Exception as e:
            self.log(f"Erreur recherche landmark '{name}': {e}")
        
        return None
    
    def _search_landmarks_web(self, clues, city_name=None, city_code=None):
        """
        Recherche les coordonnées des commerces et landmarks identifiés par Vision.
        Retourne une liste de candidats GPS triés par pertinence.
        """
        candidates = []
        
        # 1. Chercher les enseignes/commerces
        for shop in (clues.get('shop_signs') or []):
            if len(shop) >= 4:  # Ignorer les noms trop courts
                self.log(f"Recherche enseigne: {shop}")
                result = self._search_landmark_address(shop, city_name)
                if result:
                    # Valider contre la ville
                    if city_code:
                        check = validate_city_coherence(result['lat'], result['lng'], city_code)
                        if check['valid']:
                            candidates.append({**result, 'type': 'shop', 'score': 70})
                        else:
                            self.log(f"  → hors ville, ignoré")
                    else:
                        candidates.append({**result, 'type': 'shop', 'score': 60})
                time.sleep(1)  # Rate limiting Nominatim
        
        # 2. Chercher les landmarks
        for landmark in (clues.get('landmarks') or []):
            if len(landmark) >= 4:
                self.log(f"Recherche landmark: {landmark}")
                result = self._search_landmark_address(landmark, city_name)
                if result:
                    if city_code:
                        check = validate_city_coherence(result['lat'], result['lng'], city_code)
                        if check['valid']:
                            candidates.append({**result, 'type': 'landmark', 'score': 80})
                        else:
                            self.log(f"  → hors ville, ignoré")
                    else:
                        candidates.append({**result, 'type': 'landmark', 'score': 70})
                time.sleep(1)
        
        # 3. Chercher les stations de métro/bus
        for station in (clues.get('metro_bus') or []):
            if len(station) >= 3:
                self.log(f"Recherche station: {station}")
                # Ajouter "station" pour disambiguation
                query = f"station {station}"
                result = self._search_landmark_address(query, city_name)
                if result:
                    if city_code:
                        check = validate_city_coherence(result['lat'], result['lng'], city_code)
                        if check['valid']:
                            candidates.append({**result, 'type': 'metro_bus', 'score': 65})
                        else:
                            self.log(f"  → hors ville, ignoré")
                    else:
                        candidates.append({**result, 'type': 'metro_bus', 'score': 55})
                time.sleep(1)
        
        candidates.sort(key=lambda x: -x['score'])
        return candidates
    
    def analyze(self, image_lieu_url, city_name=None, city_code=None, image_close_url=None):
        """
        Analyse complète via Claude Vision v2:
        1. Télécharge image_lieu (+ image_close si dispo)
        2. Envoie à Claude avec prompt adapté à la ville
        3. Géocode la meilleure adresse (Nominatim structuré)
        4. Recherche web des commerces/landmarks identifiés
        5. Valide contre la ville attendue
        
        Returns:
            dict: {'found': bool, 'lat': float, 'lng': float, 'address': str,
                   'source': 'vision', 'clues': dict, 'confidence': str}
        """
        result = {
            'found': False,
            'lat': None,
            'lng': None,
            'address': None,
            'source': 'vision',
            'clues': None,
            'confidence': None,
            'error': None,
        }
        
        if not self.enabled:
            result['error'] = 'Vision non activé (--anthropic-key requis)'
            return result
        
        # 1. Télécharger les images
        images = []
        
        self.log(f"Téléchargement image_lieu: {image_lieu_url[:60]}...")
        b64_lieu, mt_lieu = self._download_image_base64(image_lieu_url)
        if b64_lieu:
            images.append((b64_lieu, mt_lieu, "Vue large — contexte de la rue"))
        
        if image_close_url:
            self.log(f"Téléchargement image_close: {image_close_url[:60]}...")
            b64_close, mt_close = self._download_image_base64(image_close_url)
            if b64_close:
                images.append((b64_close, mt_close, "Gros plan — détails de la mosaïque et son environnement immédiat"))
        
        if not images:
            result['error'] = 'Impossible de télécharger les images'
            return result
        
        self.log(f"Envoi de {len(images)} image(s) à Claude Vision...")
        
        # 2. Analyser avec Claude Vision (prompt adapté à la ville)
        clues = self._call_vision(images, city_code=city_code, city_name=city_name)
        if not clues:
            result['error'] = 'Pas de réponse exploitable de Vision'
            return result
        
        result['clues'] = clues
        result['confidence'] = clues.get('confidence', 'LOW')
        
        # Afficher les indices trouvés
        if clues.get('street_signs'):
            self.log(f"🪧 Plaques: {clues['street_signs']}")
        if clues.get('shop_signs'):
            self.log(f"🏪 Enseignes: {clues['shop_signs']}")
        if clues.get('landmarks'):
            self.log(f"🏛️ Repères: {clues['landmarks']}")
        if clues.get('metro_bus'):
            self.log(f"🚇 Transports: {clues['metro_bus']}")
        if clues.get('district'):
            self.log(f"📍 Quartier: {clues['district']}")
        if clues.get('postcode'):
            self.log(f"📮 Code postal: {clues['postcode']}")
        
        # 3. Construire les adresses candidates à géocoder
        addresses_to_try = []
        
        # Priorité 1: best_address_guess de Claude
        if clues.get('best_address_guess'):
            addresses_to_try.append(clues['best_address_guess'])
        
        # Priorité 2: plaques de rue + numéros
        for sign in (clues.get('street_signs') or []):
            nums = clues.get('building_numbers') or ['']
            for num in nums[:1]:
                addr = f"{num} {sign}".strip() if num else sign
                if city_name and city_name.lower() not in addr.lower():
                    addr = f"{addr}, {city_name}"
                if addr not in addresses_to_try:
                    addresses_to_try.append(addr)
        
        if not addresses_to_try:
            # Pas d'adresse textuelle → fallback sur landmarks web uniquement
            self.log("Pas d'adresse dans les indices, recherche web des landmarks...")
        
        # 4. Géocoder les adresses candidates (Nominatim structuré)
        ocr = ImageOCRAnalyzer(verbose=self.verbose)
        
        for addr in addresses_to_try[:5]:
            self.log(f"Géocodage: {addr}")
            geo = ocr.geocode_address(addr, city_code=city_code)
            if geo:
                result['found'] = True
                result['lat'] = geo['lat']
                result['lng'] = geo['lng']
                result['address'] = addr
                self.log(f"✅ GPS via adresse: {geo['lat']:.6f}, {geo['lng']:.6f}")
                return result
        
        # 5. Recherche web des commerces/landmarks identifiés
        self.log("Recherche web des commerces et landmarks...")
        landmark_candidates = self._search_landmarks_web(clues, city_name, city_code)
        
        if landmark_candidates:
            best = landmark_candidates[0]
            result['found'] = True
            result['lat'] = best['lat']
            result['lng'] = best['lng']
            result['address'] = f"{best.get('source_name', '?')} ({best['display_name'][:80]})"
            self.log(f"✅ GPS via {best['type']}: {best['lat']:.6f}, {best['lng']:.6f}")
            return result
        
        result['error'] = 'Géocodage échoué pour tous les indices Vision'
        return result


class PnoteSearcher:
    """
    Recherche dans la base pnote.eu (fichier JSON local ou fetch URL).
    
    Supporte trois modes d'entrée:
    - URL directe: https://pnote.eu/projects/invaders/map/invaders.json?nocache=1
    - Fichier local format pnote.eu natif: {id, obf_lat, obf_lng, status, hint, instagramUrl}
    - Fichier local format master-like: {id, lat, lng, status, hint?, ...} (virgules décimales)
    
    Les coordonnées pnote ont un offset volontaire de ±10m.
    Confiance: MEDIUM (offset connu).
    """
    
    PNOTE_DEFAULT_URL = "https://pnote.eu/projects/invaders/map/invaders.json?nocache=1"
    
    def __init__(self, pnote_file=None, pnote_url=None, verbose=False):
        self.verbose = verbose
        self.data = {}  # id -> {lat, lng, status, hint}
        self.loaded = False
        if pnote_file:
            self.load_file(pnote_file)
        elif pnote_url:
            self.load_url(pnote_url)
    
    def log(self, msg):
        if self.verbose:
            print(f"      [PNOTE] {msg}")
    
    def _index_data(self, raw):
        """Indexe une liste d'invaders par ID"""
        for inv in raw:
            inv_id = inv.get('id', '').upper()
            if not inv_id:
                continue
            
            lat = lng = None
            
            # Format pnote.eu natif (obf_lat/obf_lng — floats)
            if 'obf_lat' in inv:
                try:
                    lat = float(inv['obf_lat'])
                    lng = float(inv['obf_lng'])
                except (ValueError, TypeError):
                    pass
            
            # Format master-like (lat/lng — strings avec virgules possibles)
            elif 'lat' in inv:
                try:
                    lat = float(str(inv['lat']).replace(',', '.'))
                    lng = float(str(inv['lng']).replace(',', '.'))
                except (ValueError, TypeError):
                    pass
            
            # Valider les coordonnées (pas à zéro, dans les bornes)
            if lat is not None and lng is not None:
                if abs(lat) < 0.01 and abs(lng) < 0.01:
                    lat = lng = None
                elif not (-90 <= lat <= 90 and -180 <= lng <= 180):
                    lat = lng = None
            
            self.data[inv_id] = {
                'lat': lat,
                'lng': lng,
                'status': inv.get('status'),
                'hint': inv.get('hint'),
            }
        
        with_coords = sum(1 for v in self.data.values() if v['lat'] is not None)
        with_hints = sum(1 for v in self.data.values() if v.get('hint'))
        self.loaded = True
        print(f"   📦 Pnote chargé: {len(self.data)} invaders, {with_coords} avec GPS, {with_hints} avec hints")
    
    def load_file(self, filepath):
        """Charge depuis un fichier JSON local"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            self._index_data(raw)
        except Exception as e:
            print(f"   ⚠️ Erreur chargement pnote (fichier): {e}")
            self.loaded = False
    
    def load_url(self, url):
        """Télécharge le JSON pnote depuis une URL"""
        try:
            print(f"   📡 Téléchargement pnote: {url[:60]}...")
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code != 200:
                print(f"   ⚠️ Pnote HTTP {resp.status_code}")
                self.loaded = False
                return
            raw = resp.json()
            self._index_data(raw)
        except Exception as e:
            print(f"   ⚠️ Erreur chargement pnote (URL): {e}")
            self.loaded = False
    
    def search(self, invader_id, city_name=None):
        """
        Cherche un invader dans la base pnote.
        Retourne un dict compatible avec le format des autres searchers.
        """
        result = {
            'found': False,
            'lat': None,
            'lng': None,
            'source': 'pnote',
            'hint': None,
            'status': None,
            'error': None,
        }
        
        if not self.loaded:
            result['error'] = 'Pnote non chargé'
            return result
        
        inv_id = invader_id.upper()
        entry = self.data.get(inv_id)
        
        if not entry:
            result['error'] = f'{inv_id} absent de pnote'
            self.log(f"❌ {inv_id} non trouvé")
            return result
        
        if entry['lat'] is not None and entry['lng'] is not None:
            result['found'] = True
            result['lat'] = entry['lat']
            result['lng'] = entry['lng']
            result['status'] = entry.get('status')
            result['hint'] = entry.get('hint')
            self.log(f"✅ {inv_id}: {entry['lat']:.6f}, {entry['lng']:.6f}")
            if entry.get('hint'):
                self.log(f"   Hint: {entry['hint']}")
        else:
            result['error'] = f'{inv_id} sans coordonnées dans pnote'
            self.log(f"⚠️ {inv_id} trouvé mais sans GPS")
            # On remonte quand même le hint s'il existe
            if entry.get('hint'):
                result['hint'] = entry['hint']
                self.log(f"   Hint disponible: {entry['hint']}")
        
        return result


class FlickrScraper:
    """
    Recherche de photos geotaggées sur Flickr par scraping HTML (sans API).
    
    Stratégie:
    1. Cherche par tag sur flickr.com/search/?tags={invader_id}
    2. Récupère les URLs des photos résultantes
    3. Sur chaque page photo, extrait les coordonnées GPS du modelExport JS
    
    Flickr embarque les données geo dans le JavaScript de la page (modelExport).
    Pattern: "location":{"latitude":48.xxx,"longitude":2.xxx}
    
    Utilise Playwright (partagé avec les autres searchers).
    Confiance: MEDIUM (coordonnées de la photo, pas forcément de l'invader exact).
    """
    
    SEARCH_URL = "https://www.flickr.com/search/?tags={tag}&view_all=1"
    
    def __init__(self, page=None, verbose=False):
        self.page = page
        self.verbose = verbose
        self.enabled = page is not None
    
    def log(self, msg):
        if self.verbose:
            print(f"      [FLICKR] {msg}")
    
    def _format_tags(self, invader_id):
        """Génère le tag Flickr (format officiel avec underscore uniquement)"""
        inv = invader_id.upper()
        # La communauté Flickr utilise le format officiel: PA_1531, LDN_151, etc.
        return [inv.lower()]  # → ['pa_1531']
    
    def _extract_photo_links(self):
        """Extrait les liens vers les photos depuis la page de résultats Flickr"""
        try:
            links = self.page.evaluate("""
                () => {
                    const results = [];
                    // Flickr search results: div.photo-list-photo-view with data
                    const photos = document.querySelectorAll('div.photo-list-photo-view a.overlay, a.photo-list-photo-view');
                    photos.forEach(a => {
                        const href = a.getAttribute('href');
                        if (href && href.includes('/photos/')) {
                            results.push('https://www.flickr.com' + href);
                        }
                    });
                    // Fallback: any link matching /photos/{user}/{id}/
                    if (results.length === 0) {
                        document.querySelectorAll('a[href*="/photos/"]').forEach(a => {
                            const href = a.getAttribute('href');
                            if (href && /\\/photos\\/[^/]+\\/\\d+\\//.test(href)) {
                                const full = href.startsWith('http') ? href : 'https://www.flickr.com' + href;
                                if (!results.includes(full)) results.push(full);
                            }
                        });
                    }
                    return results.slice(0, 10);  // Max 10 photos
                }
            """)
            return links
        except Exception as e:
            self.log(f"Erreur extraction liens: {e}")
            return []
    
    def _extract_geo_from_photo_page(self):
        """
        Extrait les coordonnées GPS depuis une page photo Flickr.
        Cherche dans:
        1. Le modelExport JS (pattern location.latitude/longitude)
        2. Les meta tags geo
        3. Les liens vers la carte (?fLat=...&fLon=...)
        """
        try:
            geo = self.page.evaluate("""
                () => {
                    const html = document.documentElement.innerHTML;
                    
                    // Strategy 1: modelExport location data
                    // Pattern: "location":{"latitude":48.xxx,"longitude":2.xxx}
                    const locMatch = html.match(/"location"\\s*:\\s*\\{[^}]*"latitude"\\s*:\\s*([\\d.-]+)[^}]*"longitude"\\s*:\\s*([\\d.-]+)/);
                    if (locMatch) {
                        const lat = parseFloat(locMatch[1]);
                        const lng = parseFloat(locMatch[2]);
                        if (Math.abs(lat) > 0.01 || Math.abs(lng) > 0.01) {
                            return {found: true, lat: lat, lng: lng, method: 'modelExport'};
                        }
                    }
                    
                    // Strategy 1b: reverse order (longitude first)
                    const locMatch2 = html.match(/"location"\\s*:\\s*\\{[^}]*"longitude"\\s*:\\s*([\\d.-]+)[^}]*"latitude"\\s*:\\s*([\\d.-]+)/);
                    if (locMatch2) {
                        const lng = parseFloat(locMatch2[1]);
                        const lat = parseFloat(locMatch2[2]);
                        if (Math.abs(lat) > 0.01 || Math.abs(lng) > 0.01) {
                            return {found: true, lat: lat, lng: lng, method: 'modelExport_rev'};
                        }
                    }
                    
                    // Strategy 2: map link with fLat/fLon
                    const mapMatch = html.match(/fLat=([\\d.-]+)&fLon=([\\d.-]+)/);
                    if (mapMatch) {
                        const lat = parseFloat(mapMatch[1]);
                        const lng = parseFloat(mapMatch[2]);
                        if (Math.abs(lat) > 0.01 || Math.abs(lng) > 0.01) {
                            return {found: true, lat: lat, lng: lng, method: 'mapLink'};
                        }
                    }
                    
                    // Strategy 3: geo meta tags
                    const geoLat = document.querySelector('meta[name="geo.position"]');
                    if (geoLat) {
                        const parts = geoLat.content.split(';');
                        if (parts.length === 2) {
                            const lat = parseFloat(parts[0]);
                            const lng = parseFloat(parts[1]);
                            if (Math.abs(lat) > 0.01 || Math.abs(lng) > 0.01) {
                                return {found: true, lat: lat, lng: lng, method: 'metaGeo'};
                            }
                        }
                    }
                    
                    // Strategy 4: data attributes on map elements
                    const mapEl = document.querySelector('[data-lat][data-lng], [data-latitude][data-longitude]');
                    if (mapEl) {
                        const lat = parseFloat(mapEl.dataset.lat || mapEl.dataset.latitude);
                        const lng = parseFloat(mapEl.dataset.lng || mapEl.dataset.longitude);
                        if (Math.abs(lat) > 0.01 || Math.abs(lng) > 0.01) {
                            return {found: true, lat: lat, lng: lng, method: 'dataAttr'};
                        }
                    }
                    
                    return {found: false};
                }
            """)
            return geo
        except Exception as e:
            self.log(f"Erreur extraction geo: {e}")
            return {'found': False}
    
    def _get_photo_owner(self):
        """Extrait le nom du photographe"""
        try:
            owner = self.page.evaluate("""
                () => {
                    const el = document.querySelector('.owner-name, a.owner-name');
                    return el ? el.textContent.trim() : null;
                }
            """)
            return owner
        except:
            return None
    
    def search(self, invader_id, city_name=None):
        """
        Cherche des photos geotaggées correspondant à cet invader sur Flickr.
        
        Stratégie:
        1. Recherche par tag exact (ex: pa_1531)
        2. Si pas de résultats: tag sans underscore (ex: pa1531)
        3. Pour chaque photo trouvée: extraire les coordonnées GPS
        4. Retourner la première photo avec des coordonnées valides
        """
        result = {
            'found': False,
            'lat': None,
            'lng': None,
            'source': 'flickr',
            'photo_url': None,
            'owner': None,
            'method': None,
            'error': None,
        }
        
        if not self.enabled:
            result['error'] = 'Flickr désactivé (pas de page Playwright)'
            return result
        
        tags = self._format_tags(invader_id)
        
        for tag in tags:
            search_url = self.SEARCH_URL.format(tag=tag)
            self.log(f"Recherche: {search_url}")
            
            try:
                self.page.goto(search_url, timeout=15000, wait_until='domcontentloaded')
                time.sleep(2)  # Attendre le rendu JS
                
                # Extraire les liens photo
                photo_links = self._extract_photo_links()
                self.log(f"{len(photo_links)} photos trouvées")
                
                if not photo_links:
                    continue
                
                # Visiter chaque photo pour chercher des coordonnées
                for i, photo_url in enumerate(photo_links[:5]):  # Max 5 photos
                    self.log(f"Photo {i+1}: {photo_url}")
                    
                    try:
                        self.page.goto(photo_url, timeout=15000, wait_until='domcontentloaded')
                        time.sleep(1.5)
                        
                        geo = self._extract_geo_from_photo_page()
                        
                        if geo.get('found'):
                            result['found'] = True
                            result['lat'] = geo['lat']
                            result['lng'] = geo['lng']
                            result['method'] = geo.get('method')
                            result['photo_url'] = photo_url
                            result['owner'] = self._get_photo_owner()
                            self.log(f"✅ GPS: {geo['lat']:.6f}, {geo['lng']:.6f} (via {geo.get('method')})")
                            return result
                    
                    except Exception as e:
                        self.log(f"Erreur page photo: {e}")
                        continue
                
            except Exception as e:
                self.log(f"Erreur recherche: {e}")
                continue
            
            time.sleep(1)  # Pause entre les tags
        
        result['error'] = 'Aucune photo geotaggée trouvée'
        self.log(f"❌ Rien trouvé pour {invader_id}")
        return result


class IlluminateArtSearcher:
    """Recherche sur illuminateartofficial.com via Google"""
    
    def __init__(self, page=None, verbose=False):
        self.page = page
        self.verbose = verbose
        self.base_url = "https://illuminateartofficial.com"
        self.consent_handled = False
        self.google_consent_handled = False
    
    def log(self, msg):
        if self.verbose:
            print(f"      [Illuminate] {msg}")
    
    def _handle_google_consent(self):
        """Gère le consentement Google"""
        if self.google_consent_handled:
            return
        
        try:
            time.sleep(2)
            button_texts = ["Tout accepter", "Accept all", "Alle akzeptieren", "Accetta tutto"]
            
            for text in button_texts:
                try:
                    btn = self.page.get_by_role("button", name=text)
                    if btn.is_visible():
                        btn.click()
                        self.log(f"✅ Consentement Google accepté")
                        self.google_consent_handled = True
                        time.sleep(1)
                        return
                except:
                    pass
            
            self.google_consent_handled = True
        except:
            self.google_consent_handled = True
    
    def _handle_consent(self):
        """Gère le consentement cookies sur illuminateartofficial.com"""
        if self.consent_handled:
            return
        
        try:
            time.sleep(2)
            button_texts = ["Accept", "Accept All", "I agree", "OK", "Accepter", "Tout accepter"]
            
            for text in button_texts:
                try:
                    btn = self.page.get_by_role("button", name=text)
                    if btn.is_visible():
                        btn.click()
                        self.consent_handled = True
                        time.sleep(1)
                        return
                except:
                    pass
            
            self.consent_handled = True
        except:
            self.consent_handled = True
    
    def _check_and_wait_for_captcha(self):
        """Détecte un CAPTCHA Google et attend la validation manuelle"""
        try:
            content = self.page.content().lower()
            url = self.page.url.lower()
            
            captcha_indicators = [
                'captcha' in content,
                'recaptcha' in content,
                'unusual traffic' in content,
                'trafic inhabituel' in content,
                'sorry/index' in url,
                'ipv4.google.com/sorry' in url,
                'www.google.com/sorry' in url,
                'are you a robot' in content,
                'êtes-vous un robot' in content,
            ]
            
            if any(captcha_indicators):
                self.log(f"⚠️ CAPTCHA détecté!")
                print(f"\n{'='*60}")
                print(f"⚠️  CAPTCHA GOOGLE DÉTECTÉ")
                print(f"   Résolvez le CAPTCHA dans le navigateur")
                print(f"   puis appuyez sur ENTRÉE pour continuer...")
                print(f"{'='*60}\n")
                
                input()
                
                self.log(f"✅ Reprise après CAPTCHA")
                time.sleep(2)
                return True
            
            return False
        except:
            return False
    
    def _format_invader_id(self, invader_id):
        """Convertit AMI_06 en ami-06 pour les URLs"""
        return invader_id.lower().replace('_', '-')
    
    def _scrape_google_results(self):
        """Scrape la page de résultats Google et retourne toutes les URLs trouvées"""
        results = []
        content = self.page.content()
        
        from urllib.parse import unquote
        
        # Pattern 1: URLs dans /url?q=
        redirect_pattern = r'/url\?q=([^&"]+)'
        matches = re.findall(redirect_pattern, content)
        for url in matches:
            decoded_url = unquote(url)
            if decoded_url.startswith('http') and decoded_url not in [r['url'] for r in results]:
                results.append({
                    'url': decoded_url,
                    'extraction_method': 'google_redirect',
                    'is_target': False
                })
        
        # Pattern 2: URLs directes
        direct_pattern = r'href="(https?://[^"]+)"'
        matches = re.findall(direct_pattern, content)
        for url in matches:
            if url not in [r['url'] for r in results]:
                if not any(x in url for x in ['google.com/search', 'google.fr/search', 'accounts.google']):
                    results.append({
                        'url': url,
                        'extraction_method': 'direct_href',
                        'is_target': False
                    })
        
        return results
    
    def _analyze_urls(self, urls, invader_id):
        """Analyse les URLs pour identifier celles qui correspondent au site cible"""
        formatted_id = self._format_invader_id(invader_id)
        target_urls = []
        
        for item in urls:
            url = item['url']
            url_lower = url.lower()
            
            # Filtrer: ne garder que https://illuminateartofficial.com/...
            if not url_lower.startswith('https://illuminateartofficial.com/'):
                continue
            
            item['is_target'] = True
            item['site'] = 'illuminateartofficial.com'
            
            # Accepter les articles (format /2025/06/10/...) ET les blogs (format /blogs/...)
            is_article = re.search(r'/\d{4}/\d{2}/\d{2}/', url_lower)
            is_blog = '/blogs/' in url_lower or '/blog/' in url_lower
            
            if is_article or is_blog:
                item['page_type'] = 'article' if is_article else 'blog'
                
                if formatted_id in url_lower or invader_id.lower() in url_lower:
                    item['id_match'] = True
                    item['priority'] = 1
                    target_urls.append(item)
                    self.log(f"   ✓ URL valide: {url[:60]}...")
                elif is_blog and ('invader' in url_lower):
                    item['id_match'] = False
                    item['priority'] = 2
                    target_urls.append(item)
                    self.log(f"   ✓ URL blog: {url[:60]}...")
            else:
                item['page_type'] = 'other'
                item['id_match'] = False
        
        target_urls.sort(key=lambda x: x.get('priority', 99))
        return target_urls
    
    def _extract_data_from_page(self, url, invader_id):
        """Visite une page IlluminateArt et extrait les données pour un invader spécifique"""
        data = {
            'url': url,
            'visited': False,
            'gps_found': False,
            'lat': None,
            'lng': None,
            'maps_url': None,
            'error': None
        }
        
        try:
            self.log(f"   → Visite: {url}")
            self.page.goto(url, timeout=20000)
            time.sleep(2)
            
            self._handle_consent()
            time.sleep(1)
            
            data['visited'] = True
            
            # Extraire préfixe et numéro pour le scroll
            match = re.match(r'([A-Z]+)[_-]?(\d+)', invader_id.upper())
            if match:
                prefix = match.group(1)
                current_num = int(match.group(2))
                
                # Scroller jusqu'à la section de l'invader pour déclencher le lazy loading
                self.log(f"   📜 Scroll vers {invader_id}...")
                scrolled = False
                
                # Méthode 1: Chercher le header h4 de l'invader et scroller
                try:
                    header_selector = f"h4:has-text('{prefix}_{current_num:02d}')"
                    header = self.page.locator(header_selector).first
                    if header.is_visible():
                        header.scroll_into_view_if_needed()
                        self.log(f"   📜 Scrollé vers header h4")
                        scrolled = True
                        time.sleep(2)  # Attendre le lazy loading
                except:
                    pass
                
                # Méthode 2: Scroll progressif seulement si header non trouvé
                if not scrolled:
                    try:
                        scroll_ratio = current_num / 20  # Approximation
                        total_height = self.page.evaluate("document.body.scrollHeight")
                        scroll_to = int(total_height * scroll_ratio)
                        self.page.evaluate(f"window.scrollTo(0, {scroll_to})")
                        self.log(f"   📜 Scroll approximatif à {scroll_ratio*100:.0f}%")
                        time.sleep(2)
                    except:
                        pass
            
            # Récupérer le contenu après scroll
            content = self.page.content()
            
            # DEBUG: Sauvegarder le HTML pour analyse
            debug_file = f"/tmp/illuminate_debug_{invader_id}.html"
            try:
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.log(f"   💾 HTML sauvé: {debug_file}")
            except:
                pass
            
            # Stratégie 1: Chercher une section spécifique à l'invader
            invader_section = self._find_invader_section(content, invader_id)
            
            if invader_section:
                self.log(f"   📍 Section trouvée pour {invader_id} ({len(invader_section)} chars)")
                
                # DEBUG: Chercher tous les @lat,lng dans la section
                all_coords = re.findall(r'@([-\d.]+),([-\d.]+)', invader_section)
                if all_coords:
                    self.log(f"   🔍 DEBUG: {len(all_coords)} coordonnées @ trouvées dans section")
                    for lat, lng in all_coords[:3]:
                        self.log(f"      @{lat},{lng}")
                else:
                    self.log(f"   🔍 DEBUG: Aucun @lat,lng dans la section")
                
                # DEBUG: Chercher tous les liens maps dans la section
                all_maps = re.findall(r'(https?://[^\s"<>]*maps[^\s"<>]*)', invader_section, re.IGNORECASE)
                if all_maps:
                    self.log(f"   🔍 DEBUG: {len(all_maps)} liens maps dans section")
                    for m in all_maps[:3]:
                        self.log(f"      {m[:80]}...")
                else:
                    self.log(f"   🔍 DEBUG: Aucun lien maps dans la section")
                
                # D'abord: Chercher les coordonnées @lat,lng directement dans la section
                coord_match = re.search(r'@([-\d.]+),([-\d.]+)', invader_section)
                if coord_match:
                    lat = float(coord_match.group(1))
                    lng = float(coord_match.group(2))
                    if -90 <= lat <= 90 and -180 <= lng <= 180:
                        data['gps_found'] = True
                        data['lat'] = lat
                        data['lng'] = lng
                        self.log(f"   📍 GPS (direct @): {lat:.6f}, {lng:.6f}")
                        return data
                
                # Ensuite: Chercher le lien Maps dans cette section
                maps_url = self._find_maps_link(invader_section)
                if maps_url:
                    data['maps_url'] = maps_url
                    self.log(f"   🗺️ Maps URL: {maps_url[:80]}...")
                    coords = self._extract_coords_from_maps_url(maps_url)
                    if coords:
                        data['gps_found'] = True
                        data['lat'] = coords['lat']
                        data['lng'] = coords['lng']
                        self.log(f"   📍 GPS: {coords['lat']:.6f}, {coords['lng']:.6f}")
                        return data
                
                coords = self._find_coords_in_text(invader_section)
                if coords:
                    data['gps_found'] = True
                    data['lat'] = coords['lat']
                    data['lng'] = coords['lng']
                    self.log(f"   📍 GPS (section): {coords['lat']:.6f}, {coords['lng']:.6f}")
                    return data
            else:
                self.log(f"   ⚠️ Section non trouvée pour {invader_id}")
            
            # NOTE: Le fallback "recherche globale" est désactivé car il retourne
            # le premier GPS de la page, pas celui de l'invader recherché.
            # Mieux vaut retourner "pas de GPS" que de retourner un GPS incorrect.
            self.log(f"   ⚠️ Pas de GPS trouvé pour {invader_id} dans sa section")
            
        except Exception as e:
            data['error'] = str(e)
            self.log(f"   ❌ Erreur: {e}")
        
        return data
    
    def _find_invader_section(self, content, invader_id):
        """Trouve la section HTML entre cet invader et le suivant"""
        match = re.match(r'([A-Z]+)[_-]?(\d+)', invader_id.upper())
        if not match:
            return None
        
        prefix = match.group(1)
        current_num = int(match.group(2))
        
        # Méthode 1: Chercher les headers h3/h4 qui contiennent l'ID
        header_pattern = rf'<h[34][^>]*>([^<]*{prefix}_\d+[^<]*)</h[34]>'
        headers = list(re.finditer(header_pattern, content, re.IGNORECASE))
        
        if headers:
            self.log(f"   📋 {len(headers)} headers h3/h4 trouvés")
            
            target_idx = -1
            for i, h in enumerate(headers):
                header_text = h.group(1)
                if f'{prefix}_{current_num:02d}' in header_text or f'{prefix}_{current_num}' in header_text:
                    target_idx = i
                    self.log(f"   🎯 Header #{i}: '{header_text}'")
                    break
            
            if target_idx != -1:
                start_pos = headers[target_idx].start()
                end_pos = headers[target_idx + 1].start() if target_idx + 1 < len(headers) else len(content)
                section = content[start_pos:end_pos]
                self.log(f"   📄 Section (h3/h4): {len(section)} chars")
                return section
        
        # Méthode 2: Chercher des mentions de l'invader avec contexte
        self.log(f"   🔍 Fallback: recherche par patterns alternatifs...")
        
        # Chercher >AMI_01< ou >AMI-01< ou "AMI_01" etc.
        mention_pattern = rf'[>"\s]{prefix}[_-]{current_num:02d}[<"\s]'
        mentions = list(re.finditer(mention_pattern, content, re.IGNORECASE))
        
        if not mentions:
            # Essayer sans le zéro devant
            mention_pattern = rf'[>"\s]{prefix}[_-]{current_num}[<"\s]'
            mentions = list(re.finditer(mention_pattern, content, re.IGNORECASE))
        
        if not mentions:
            self.log(f"   ⚠️ Aucune mention de {invader_id} trouvée")
            return None
        
        self.log(f"   📍 {len(mentions)} mentions trouvées")
        
        # Prendre la dernière mention (généralement la section de contenu, pas le menu)
        if len(mentions) > 1:
            start_pos = mentions[-1].start()
            self.log(f"   📍 Utilisation de la dernière mention (position {start_pos})")
        else:
            start_pos = mentions[0].start()
        
        # Chercher la fin: prochain invader
        next_num = current_num + 1
        next_pattern = rf'[>"\s]{prefix}[_-]0?{next_num}[<"\s]'
        next_match = re.search(next_pattern, content[start_pos + 50:], re.IGNORECASE)
        
        if next_match:
            end_pos = start_pos + 50 + next_match.start()
        else:
            end_pos = min(start_pos + 20000, len(content))
        
        start_pos = max(0, start_pos - 500)
        section = content[start_pos:end_pos]
        
        self.log(f"   📄 Section (fallback): {len(section)} chars")
        return section
    
    def _find_maps_link(self, html_section):
        """Trouve un lien Google Maps dans une section HTML"""
        maps_patterns = [
            # URLs directes avec coordonnées (format IlluminateArt)
            r'(https?://(?:www\.)?google\.[a-z.]+/maps/@[-\d.,/!:a-zA-Z?=&]+)',
            # href avec Maps
            r'href="(https?://(?:www\.)?google\.[a-z.]+/maps[^"]+)"',
            r'href="(https?://goo\.gl/maps/[^"]+)"',
            r'href="(https?://maps\.app\.goo\.gl/[^"]+)"',
            # Liens courts
            r'(https?://goo\.gl/maps/[^\s"<>]+)',
            r'(https?://maps\.app\.goo\.gl/[^\s"<>]+)',
        ]
        for pattern in maps_patterns:
            match = re.search(pattern, html_section)
            if match:
                return match.group(1)
        return None
    
    def _find_coords_in_text(self, text):
        """Trouve des coordonnées GPS dans du texte"""
        coord_patterns = [
            r'(\d{1,2}\.\d{4,})\s*[,/]\s*(\d{1,2}\.\d{4,})',
            r'GPS[:\s]*([-\d.]+)\s*,\s*([-\d.]+)',
            r'@(-?\d+\.\d+),(-?\d+\.\d+)',
        ]
        for pattern in coord_patterns:
            match = re.search(pattern, text)
            if match:
                lat = float(match.group(1))
                lng = float(match.group(2))
                if -90 <= lat <= 90 and -180 <= lng <= 180:
                    return {'lat': lat, 'lng': lng}
        return None
    
    def _find_all_maps_links_with_context(self, content, invader_id):
        """Trouve tous les liens Maps et vérifie s'ils sont proches de l'ID de l'invader"""
        results = []
        formatted_id = self._format_invader_id(invader_id)
        maps_pattern = r'(https?://(?:goo\.gl/maps|maps\.app\.goo\.gl|(?:www\.)?google\.[a-z.]+/maps)[^\s"<>]+)'
        
        for match in re.finditer(maps_pattern, content):
            maps_url = match.group(1)
            position = match.start()
            context_start = max(0, position - 1500)
            context = content[context_start:position].lower()
            
            invader_nearby = any(p.lower() in context for p in [invader_id, formatted_id])
            results.append({'url': maps_url, 'invader_nearby': invader_nearby, 'position': position})
        
        results.sort(key=lambda x: (0 if x['invader_nearby'] else 1, x['position']))
        return results
    
    def _extract_coords_from_maps_url(self, url):
        """Extrait les coordonnées depuis une URL Google Maps"""
        if 'goo.gl' in url or 'maps.app' in url:
            try:
                self.log(f"   ↪️ Redirection Maps...")
                self.page.goto(url, timeout=15000)
                time.sleep(3)
                url = self.page.url
                self.log(f"   URL finale: {url[:60]}...")
            except Exception as e:
                self.log(f"   ⚠️ Erreur redirection: {e}")
        
        patterns = [
            r'@(-?\d+\.\d+),(-?\d+\.\d+)',
            r'll=(-?\d+\.\d+),(-?\d+\.\d+)',
            r'q=(-?\d+\.\d+),(-?\d+\.\d+)',
            r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                lat = float(match.group(1))
                lng = float(match.group(2))
                if -90 <= lat <= 90 and -180 <= lng <= 180:
                    return {'lat': lat, 'lng': lng}
        
        return None
    
    def search(self, invader_id, city_name=None):
        """Recherche un invader sur illuminateartofficial.com via Google"""
        result = {
            'source': 'illuminateartofficial',
            'invader_id': invader_id,
            'found': False,
            'lat': None,
            'lng': None,
            'address': None,
            'url': None,
            # Détails pour le rapport
            'google_query': None,
            'all_urls_found': [],
            'target_urls': [],
            'pages_visited': [],
            'search_steps': []
        }
        
        try:
            formatted_id = self._format_invader_id(invader_id)
            
            # ÉTAPE 1: Recherche Google
            google_query = f"site:illuminateartofficial.com {invader_id}"
            google_url = f"https://www.google.com/search?q={quote(google_query)}"
            result['google_query'] = google_query
            result['search_steps'].append(f"1. Recherche Google: {google_query}")
            
            self.log(f"🔍 Google: {google_query}")
            self.page.goto(google_url, timeout=20000)
            time.sleep(2)
            
            # ÉTAPE 2: Consentement Google
            self._handle_google_consent()
            time.sleep(1)
            result['search_steps'].append("2. Consentement Google géré")
            
            # ÉTAPE 2b: Vérifier CAPTCHA
            if self._check_and_wait_for_captcha():
                result['search_steps'].append("2b. CAPTCHA résolu manuellement")
            
            # ÉTAPE 3: Scraper les résultats Google
            self.log(f"📄 Scraping des résultats Google...")
            all_urls = self._scrape_google_results()
            result['all_urls_found'] = all_urls
            result['search_steps'].append(f"3. URLs trouvées dans Google: {len(all_urls)}")
            
            for i, item in enumerate(all_urls[:10]):
                self.log(f"   [{i+1}] {item['url'][:80]}...")
            
            # ÉTAPE 4: Analyser les URLs
            self.log(f"🔎 Analyse des URLs...")
            target_urls = self._analyze_urls(all_urls, invader_id)
            result['target_urls'] = target_urls
            result['search_steps'].append(f"4. URLs IlluminateArt correspondantes: {len(target_urls)}")
            
            if not target_urls:
                self.log(f"❌ Aucun article IlluminateArt trouvé pour {invader_id}")
                result['search_steps'].append("5. ÉCHEC: Aucune URL cible trouvée")
                return result
            
            self.log(f"✅ {len(target_urls)} article(s) trouvé(s):")
            for item in target_urls:
                self.log(f"   • {item['url']}")
            
            # ÉTAPE 5: Visiter les pages et extraire les données
            self.log(f"📥 Extraction des données...")
            result['search_steps'].append(f"5. Visite des {len(target_urls)} page(s)")
            
            for item in target_urls:
                page_data = self._extract_data_from_page(item['url'], invader_id)
                result['pages_visited'].append(page_data)
                
                if page_data['gps_found']:
                    result['found'] = True
                    result['lat'] = page_data['lat']
                    result['lng'] = page_data['lng']
                    result['url'] = page_data['url']
                    result['maps_url'] = page_data.get('maps_url')
                    result['search_steps'].append(f"6. SUCCÈS: GPS trouvé sur {page_data['url']}")
                    break
            
            if not result['found']:
                result['search_steps'].append("6. ÉCHEC: Pas de GPS trouvé sur les pages visitées")
            
            return result
            
        except Exception as e:
            result['error'] = str(e)
            result['search_steps'].append(f"ERREUR: {e}")
            self.log(f"❌ Erreur: {e}")
            return result


class AroundUsSearcher:
    """Recherche sur aroundus.com via Google"""
    
    def __init__(self, page=None, verbose=False):
        self.page = page
        self.verbose = verbose
        self.base_url = "https://aroundus.com"
        self.google_consent_handled = False
    
    def log(self, msg):
        if self.verbose:
            print(f"      [AroundUs] {msg}")
    
    def _format_invader_id(self, invader_id):
        """Convertit AMI_06 en ami-06 pour AroundUs"""
        return invader_id.lower().replace('_', '-')
    
    def _handle_google_consent(self):
        """Gère le consentement Google"""
        if self.google_consent_handled:
            return
        
        try:
            time.sleep(2)
            button_texts = ["Tout accepter", "Accept all", "Alle akzeptieren", "Accetta tutto"]
            
            for text in button_texts:
                try:
                    btn = self.page.get_by_role("button", name=text)
                    if btn.is_visible():
                        btn.click()
                        self.log(f"✅ Consentement Google accepté")
                        self.google_consent_handled = True
                        time.sleep(1)
                        return
                except:
                    pass
            
            self.google_consent_handled = True
        except:
            self.google_consent_handled = True
    
    def _check_and_wait_for_captcha(self):
        """Détecte un CAPTCHA Google et attend la validation manuelle"""
        try:
            content = self.page.content().lower()
            url = self.page.url.lower()
            
            captcha_indicators = [
                'captcha' in content,
                'recaptcha' in content,
                'unusual traffic' in content,
                'trafic inhabituel' in content,
                'sorry/index' in url,
                'ipv4.google.com/sorry' in url,
                'www.google.com/sorry' in url,
                'are you a robot' in content,
                'êtes-vous un robot' in content,
            ]
            
            if any(captcha_indicators):
                self.log(f"⚠️ CAPTCHA détecté!")
                print(f"\n{'='*60}")
                print(f"⚠️  CAPTCHA GOOGLE DÉTECTÉ")
                print(f"   Résolvez le CAPTCHA dans le navigateur")
                print(f"   puis appuyez sur ENTRÉE pour continuer...")
                print(f"{'='*60}\n")
                
                input()
                
                self.log(f"✅ Reprise après CAPTCHA")
                time.sleep(2)
                return True
            
            return False
        except:
            return False
    
    def _scrape_google_results(self):
        """Scrape la page de résultats Google et retourne toutes les URLs trouvées"""
        results = []
        content = self.page.content()
        
        from urllib.parse import unquote
        
        # Pattern 1: URLs dans /url?q=
        redirect_pattern = r'/url\?q=([^&"]+)'
        matches = re.findall(redirect_pattern, content)
        for url in matches:
            decoded_url = unquote(url)
            if decoded_url.startswith('http') and decoded_url not in [r['url'] for r in results]:
                results.append({
                    'url': decoded_url,
                    'extraction_method': 'google_redirect',
                    'is_target': False
                })
        
        # Pattern 2: URLs directes
        direct_pattern = r'href="(https?://[^"]+)"'
        matches = re.findall(direct_pattern, content)
        for url in matches:
            if url not in [r['url'] for r in results]:
                if not any(x in url for x in ['google.com/search', 'google.fr/search', 'accounts.google']):
                    results.append({
                        'url': url,
                        'extraction_method': 'direct_href',
                        'is_target': False
                    })
        
        return results
    
    def _analyze_urls(self, urls, invader_id):
        """Analyse les URLs pour identifier celles qui correspondent au site cible"""
        formatted_id = self._format_invader_id(invader_id)
        target_urls = []
        
        for item in urls:
            url = item['url']
            url_lower = url.lower()
            
            # Filtrer: accepter https://aroundus.com OU https://xx.aroundus.com (xx = fr, en, de, es, it, nl, pl, pt)
            # Exclure les sous-domaines comme www.aroundus.com ou api.aroundus.com
            aroundus_match = re.match(r'https?://(?:([a-z]{2})\.)?aroundus\.com', url_lower)
            if aroundus_match:
                # Vérifier que ce n'est pas www. ou api. etc.
                if url_lower.startswith('https://www.') or url_lower.startswith('http://www.'):
                    continue
                if url_lower.startswith('https://api.') or url_lower.startswith('http://api.'):
                    continue
                    
                item['is_target'] = True
                item['site'] = 'aroundus.com'
                item['lang'] = aroundus_match.group(1) or 'en'  # 'en' par défaut si pas de préfixe
                
                # Vérifier si c'est une page d'invader (/p/)
                if '/p/' in url_lower:
                    item['page_type'] = 'invader_page'
                    
                    if formatted_id in url_lower or invader_id.lower() in url_lower:
                        item['id_match'] = True
                        target_urls.append(item)
                        self.log(f"   ✓ URL valide ({item['lang']}): {url[:60]}...")
                    else:
                        item['id_match'] = False
                else:
                    item['page_type'] = 'other'
                    item['id_match'] = False
        
        return target_urls
    
    def _extract_data_from_page(self, url):
        """Visite une page AroundUs et extrait les données"""
        data = {
            'url': url,
            'visited': False,
            'gps_found': False,
            'lat': None,
            'lng': None,
            'address': None,
            'inception': None,
            'creator': None,
            'error': None
        }
        
        try:
            self.log(f"   → Visite: {url}")
            self.page.goto(url, timeout=20000)
            
            # Attendre que la page soit bien chargée
            time.sleep(3)
            
            data['visited'] = True
            content = self.page.content()
            
            # Méthode 1: JSON-LD (format structuré, le plus fiable)
            json_ld_pattern = r'"geo"\s*:\s*\{\s*"@type"\s*:\s*"GeoCoordinates"\s*,\s*"latitude"\s*:\s*"?([-\d.]+)"?\s*,\s*"longitude"\s*:\s*"?([-\d.]+)"?'
            json_match = re.search(json_ld_pattern, content)
            if json_match:
                lat = float(json_match.group(1))
                lng = float(json_match.group(2))
                # Valider: dans les limites ET pas à zéro (AroundUs met parfois 0,0)
                if -90 <= lat <= 90 and -180 <= lng <= 180 and not (abs(lat) < 0.01 and abs(lng) < 0.01):
                    data['gps_found'] = True
                    data['lat'] = lat
                    data['lng'] = lng
                    self.log(f"   📍 GPS (JSON-LD): {lat:.6f}, {lng:.6f}")
                elif abs(lat) < 0.01 and abs(lng) < 0.01:
                    self.log(f"   ⚠️ GPS (JSON-LD) ignoré: coordonnées à zéro")
            
            # Méthode 2: Patterns HTML (multilingue)
            if not data['gps_found']:
                gps_patterns = [
                    # Anglais
                    r'<strong>GPS\s*coordinates?:</strong>\s*([-\d.]+)\s*,\s*([-\d.]+)',
                    r'GPS\s*coordinates?[:\s]*([-\d.]+)\s*,\s*([-\d.]+)',
                    # Français
                    r'<strong>Coordonn[ée]es\s*GPS\s*:</strong>\s*([-\d.]+)\s*,\s*([-\d.]+)',
                    r'Coordonn[ée]es\s*GPS\s*:\s*([-\d.]+)\s*,\s*([-\d.]+)',
                    # Néerlandais
                    r'<strong>GPS-co[öo]rdinaten:</strong>\s*([-\d.]+)\s*,\s*([-\d.]+)',
                    # Allemand
                    r'<strong>GPS-Koordinaten:</strong>\s*([-\d.]+)\s*,\s*([-\d.]+)',
                    # Espagnol/Portugais
                    r'<strong>Coordenadas\s*GPS:</strong>\s*([-\d.]+)\s*,\s*([-\d.]+)',
                    # Italien
                    r'<strong>Coordinate\s*GPS:</strong>\s*([-\d.]+)\s*,\s*([-\d.]+)',
                    # Polonais
                    r'<strong>Wsp[óo][łl]rz[ęe]dne\s*GPS:</strong>\s*([-\d.]+)\s*,\s*([-\d.]+)',
                ]
                
                for pattern in gps_patterns:
                    match = re.search(pattern, content, re.IGNORECASE)
                    if match:
                        lat = float(match.group(1))
                        lng = float(match.group(2))
                        # Valider: dans les limites ET pas à zéro
                        if -90 <= lat <= 90 and -180 <= lng <= 180 and not (abs(lat) < 0.01 and abs(lng) < 0.01):
                            data['gps_found'] = True
                            data['lat'] = lat
                            data['lng'] = lng
                            self.log(f"   📍 GPS (HTML): {lat:.6f}, {lng:.6f}")
                            break
                        elif abs(lat) < 0.01 and abs(lng) < 0.01:
                            self.log(f"   ⚠️ GPS (HTML) ignoré: coordonnées à zéro")
            
            # Extraire l'adresse (multilingue)
            addr_patterns = [
                r'<strong>Address:</strong>\s*([^<]+)',           # Anglais
                r'<strong>Adresse\s*:</strong>\s*([^<]+)',        # Français/Allemand
                r'<strong>Adres:</strong>\s*([^<]+)',             # Néerlandais/Polonais
                r'<strong>Direcci[óo]n:</strong>\s*([^<]+)',      # Espagnol
                r'<strong>Indirizzo:</strong>\s*([^<]+)',         # Italien
                r'<strong>Endere[çc]o:</strong>\s*([^<]+)',       # Portugais
            ]
            for pattern in addr_patterns:
                addr_match = re.search(pattern, content, re.IGNORECASE)
                if addr_match:
                    data['address'] = addr_match.group(1).strip()
                    self.log(f"   📫 Adresse: {data['address']}")
                    break
            
            # Extraire la date d'inception (multilingue)
            inception_patterns = [
                r'<strong>Inception:</strong>\s*([^<]+)',         # Anglais
                r'<strong>Cr[ée]ation\s*:</strong>\s*([^<]+)',    # Français
                r'<strong>Oprichting:</strong>\s*([^<]+)',        # Néerlandais
                r'<strong>Gr[üu]ndung:</strong>\s*([^<]+)',       # Allemand
                r'<strong>Creaci[óo]n:</strong>\s*([^<]+)',       # Espagnol
                r'<strong>Creazione:</strong>\s*([^<]+)',         # Italien
                r'<strong>Cria[çc][ãa]o:</strong>\s*([^<]+)',     # Portugais
            ]
            for pattern in inception_patterns:
                inception_match = re.search(pattern, content, re.IGNORECASE)
                if inception_match:
                    data['inception'] = inception_match.group(1).strip()
                    self.log(f"   📅 Inception: {data['inception']}")
                    break
            
            # Extraire le créateur (multilingue)
            creator_patterns = [
                r'<strong>Creator:</strong>\s*([^<]+)',           # Anglais
                r'<strong>Cr[ée]ateur:</strong>\s*([^<]+)',       # Français
                r'<strong>Maker:</strong>\s*([^<]+)',             # Néerlandais
                r'<strong>Sch[öo]pfer:</strong>\s*([^<]+)',       # Allemand
                r'<strong>Creador:</strong>\s*([^<]+)',           # Espagnol
                r'<strong>Creatore:</strong>\s*([^<]+)',          # Italien
                r'<strong>Criador:</strong>\s*([^<]+)',           # Portugais
            ]
            for pattern in creator_patterns:
                creator_match = re.search(pattern, content, re.IGNORECASE)
                if creator_match:
                    data['creator'] = creator_match.group(1).strip()
                    break
            
        except Exception as e:
            data['error'] = str(e)
            self.log(f"   ❌ Erreur: {e}")
        
        return data
    
    def search(self, invader_id, city_name=None):
        """Recherche un invader sur aroundus.com via Google"""
        result = {
            'source': 'aroundus',
            'invader_id': invader_id,
            'found': False,
            'lat': None,
            'lng': None,
            'address': None,
            'url': None,
            # Détails pour le rapport
            'google_query': None,
            'all_urls_found': [],
            'target_urls': [],
            'pages_visited': [],
            'search_steps': []
        }
        
        try:
            formatted_id = self._format_invader_id(invader_id)
            
            # ÉTAPE 1: Recherche Google
            google_query = f"site:aroundus.com {invader_id}"
            google_url = f"https://www.google.com/search?q={quote(google_query)}"
            result['google_query'] = google_query
            result['search_steps'].append(f"1. Recherche Google: {google_query}")
            
            self.log(f"🔍 Google: {google_query}")
            self.page.goto(google_url, timeout=20000)
            time.sleep(2)
            
            # ÉTAPE 2: Consentement Google
            self._handle_google_consent()
            time.sleep(1)
            result['search_steps'].append("2. Consentement Google géré")
            
            # ÉTAPE 2b: Vérifier CAPTCHA
            if self._check_and_wait_for_captcha():
                result['search_steps'].append("2b. CAPTCHA résolu manuellement")
            
            # ÉTAPE 3: Scraper les résultats Google
            self.log(f"📄 Scraping des résultats Google...")
            all_urls = self._scrape_google_results()
            result['all_urls_found'] = all_urls
            result['search_steps'].append(f"3. URLs trouvées dans Google: {len(all_urls)}")
            
            for i, item in enumerate(all_urls[:10]):
                self.log(f"   [{i+1}] {item['url'][:80]}...")
            
            # ÉTAPE 4: Analyser les URLs
            self.log(f"🔎 Analyse des URLs...")
            target_urls = self._analyze_urls(all_urls, invader_id)
            result['target_urls'] = target_urls
            result['search_steps'].append(f"4. URLs AroundUs correspondantes: {len(target_urls)}")
            
            if not target_urls:
                self.log(f"❌ Aucune page AroundUs trouvée pour {invader_id}")
                result['search_steps'].append("5. ÉCHEC: Aucune URL cible trouvée")
                return result
            
            self.log(f"✅ {len(target_urls)} URL(s) AroundUs trouvée(s):")
            for item in target_urls:
                self.log(f"   • {item['url']}")
            
            # ÉTAPE 5: Visiter les pages et extraire les données
            self.log(f"📥 Extraction des données...")
            result['search_steps'].append(f"5. Visite des {len(target_urls)} page(s)")
            
            for item in target_urls:
                page_data = self._extract_data_from_page(item['url'])
                result['pages_visited'].append(page_data)
                
                if page_data['gps_found']:
                    result['found'] = True
                    result['lat'] = page_data['lat']
                    result['lng'] = page_data['lng']
                    result['address'] = page_data.get('address')
                    result['url'] = page_data['url']
                    result['inception'] = page_data.get('inception')
                    result['search_steps'].append(f"6. SUCCÈS: GPS trouvé sur {page_data['url']}")
                    break
            
            if not result['found']:
                result['search_steps'].append("6. ÉCHEC: Pas de GPS trouvé sur les pages visitées")
            
            return result
            
        except Exception as e:
            result['error'] = str(e)
            result['search_steps'].append(f"ERREUR: {e}")
            self.log(f"❌ Erreur: {e}")
            return result


class InvaderLocationSearcher:
    """Recherche combinée sur plusieurs sources"""
    
    def __init__(self, visible=False, verbose=False, pnote_file=None, pnote_url=None, flickr=True, anthropic_key=None, no_browser=False):
        self.visible = visible
        self.verbose = verbose
        self.pnote_file = pnote_file
        self.pnote_url = pnote_url
        self.flickr_enabled = flickr and not no_browser
        self.anthropic_key = anthropic_key
        self.no_browser = no_browser
        self.playwright = None
        self.browser = None
        self.page = None
        self.illuminate = None
        self.aroundus = None
        self.ocr_analyzer = None
        self.pnote = None
        self.flickr = None
        self.vision = None
    
    def start(self):
        """Démarre les sources. En mode --no-browser, pas de Playwright."""
        
        if not self.no_browser:
            # Mode normal: lancer le navigateur
            from playwright.sync_api import sync_playwright
            
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(
                headless=not self.visible,
                args=['--disable-blink-features=AutomationControlled']
            )
            context = self.browser.new_context(
                viewport={'width': 1280, 'height': 900},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            )
            self.page = context.new_page()
            
            # Sources qui nécessitent le navigateur
            self.illuminate = IlluminateArtSearcher(self.page, self.verbose)
            self.aroundus = AroundUsSearcher(self.page, self.verbose)
            if self.flickr_enabled:
                self.flickr = FlickrScraper(self.page, self.verbose)
        else:
            print("   🤖 Mode sans navigateur (Pnote + EXIF + OCR + Vision)")
        
        # Sources sans navigateur (toujours initialisées)
        self.ocr_analyzer = ImageOCRAnalyzer(self.verbose)
        
        if self.pnote_file:
            self.pnote = PnoteSearcher(pnote_file=self.pnote_file, verbose=self.verbose)
        elif self.pnote_url:
            self.pnote = PnoteSearcher(pnote_url=self.pnote_url, verbose=self.verbose)
        
        if self.anthropic_key or os.environ.get('ANTHROPIC_API_KEY'):
            self.vision = VisionAnalyzer(api_key=self.anthropic_key, verbose=self.verbose)
    
    def stop(self):
        """Arrête le navigateur"""
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
    
    def reverse_geocode(self, lat, lng):
        """
        Convertit des coordonnées GPS en adresse via Nominatim (OpenStreetMap)
        Utilise requests en mode --no-browser, Playwright sinon
        Retourne l'adresse ou None si échec
        """
        try:
            url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lng}&format=json&addressdetails=1"
            
            if self.no_browser or not self.page:
                resp = requests.get(url, headers={'User-Agent': 'InvaderHunter/3.0'}, timeout=10)
                if resp.status_code != 200:
                    return None
                data = resp.json()
            else:
                response = self.page.request.get(url, headers={'User-Agent': 'InvaderHunter/1.0'})
                if not response.ok:
                    return None
                data = response.json()
            
            # Construire une adresse lisible
            address_parts = []
            addr = data.get('address', {})
            
            if addr.get('house_number'):
                address_parts.append(addr['house_number'])
            if addr.get('road'):
                address_parts.append(addr['road'])
            elif addr.get('pedestrian'):
                address_parts.append(addr['pedestrian'])
            
            city = addr.get('city') or addr.get('town') or addr.get('village') or addr.get('municipality')
            if city:
                address_parts.append(city)
            
            if addr.get('postcode'):
                address_parts.append(addr['postcode'])
            
            if address_parts:
                return ', '.join(address_parts)
            
            return data.get('display_name', '')[:100]
            
        except Exception as e:
            if self.verbose:
                print(f"      ⚠️ Reverse geocoding error: {e}")
        
        return None
    
    def check_coherence(self, aroundus_result, illuminate_result):
        """
        Vérifie la cohérence entre les résultats de 2 sources
        Retourne un dict avec le statut et les détails
        """
        coherence = {
            'status': 'unknown',
            'distance_m': None,
            'details': ''
        }
        
        # Les deux sources ont trouvé des coordonnées ?
        au_found = aroundus_result.get('found') and aroundus_result.get('lat') and aroundus_result.get('lng')
        il_found = illuminate_result.get('found') and illuminate_result.get('lat') and illuminate_result.get('lng')
        
        if au_found and il_found:
            # Calculer la distance entre les deux GPS
            distance = calculate_distance(
                aroundus_result['lat'], aroundus_result['lng'],
                illuminate_result['lat'], illuminate_result['lng']
            )
            coherence['distance_m'] = round(distance, 1)
            
            if distance < 50:
                coherence['status'] = 'excellent'
                coherence['details'] = f"GPS identiques à {distance:.0f}m près"
            elif distance < 200:
                coherence['status'] = 'good'
                coherence['details'] = f"GPS proches ({distance:.0f}m)"
            elif distance < 500:
                coherence['status'] = 'warning'
                coherence['details'] = f"GPS différents ({distance:.0f}m) - vérifier"
            else:
                coherence['status'] = 'conflict'
                coherence['details'] = f"GPS très différents ({distance:.0f}m) - conflit!"
        
        elif au_found and not il_found:
            coherence['status'] = 'single_source'
            coherence['details'] = "Seulement AroundUs"
        
        elif il_found and not au_found:
            coherence['status'] = 'single_source'
            coherence['details'] = "Seulement IlluminateArt"
        
        else:
            coherence['status'] = 'not_found'
            coherence['details'] = "Aucune source n'a trouvé de GPS"
        
        return coherence
    
    def search(self, invader_id, city_code=None):
        """
        Recherche un invader sur TOUTES les sources (v3)
        
        Pipeline:
        1. AroundUs (web scraping Google)
        2. IlluminateArt (web scraping Google)
        3. Cohérence entre sources web + validation ville
        4. [Fallback] Pnote.eu (lookup local, ±10m offset)
        5. [Fallback] Flickr (scraping, photos geotaggées)
        6. Meilleur résultat + reverse geocoding
        
        Chaque source est validée contre la ville attendue.
        Les coordonnées incohérentes sont rejetées avec un warning.
        """
        city_name = CITY_NAMES.get(city_code, city_code) if city_code else None
        
        results = {
            'invader_id': invader_id,
            'city': city_code,
            'found': False,
            'lat': None,
            'lng': None,
            'address': None,
            'address_geocoded': None,
            'source': None,
            'url': None,
            # Résultats par source
            'aroundus': None,
            'illuminate': None,
            'pnote': None,
            'flickr': None,
            # Cohérence
            'coherence': None,
            'city_validation': None,
            'rejected_sources': [],
            'sources_checked': []
        }
        
        def _check_city(lat, lng, source_name):
            """Valide les coordonnées contre la ville et retourne True si OK"""
            if not city_code:
                return True
            check = validate_city_coherence(lat, lng, city_code, verbose=self.verbose)
            if not check['valid']:
                print(f"   🚫 {source_name} REJETÉ: {check['warning']}")
                results['rejected_sources'].append({
                    'source': source_name,
                    'lat': lat, 'lng': lng,
                    'reason': check['warning'],
                    'distance_to_center': check['distance_to_center'],
                })
                return False
            return True
        
        # 1. Chercher sur AroundUs
        aroundus_result = {'found': False}
        aroundus_valid = False
        if not self.no_browser and self.aroundus:
            print(f"   🔍 AroundUs...", end='', flush=True)
            aroundus_result = self.aroundus.search(invader_id, city_name)
            results['sources_checked'].append({'source': 'aroundus', 'result': aroundus_result})
            results['aroundus'] = aroundus_result
            
            if aroundus_result['found']:
                print(f" ✅ GPS: {aroundus_result['lat']:.5f}, {aroundus_result['lng']:.5f}")
                aroundus_valid = _check_city(aroundus_result['lat'], aroundus_result['lng'], 'AroundUs')
            else:
                print(f" ❌")
            
            time.sleep(1)
        
        # 2. Chercher sur Illuminate Art (TOUJOURS, même si AroundUs a trouvé)
        illuminate_result = {'found': False}
        illuminate_valid = False
        if not self.no_browser and self.illuminate:
            print(f"   🔍 IlluminateArt...", end='', flush=True)
            illuminate_result = self.illuminate.search(invader_id, city_name)
            results['sources_checked'].append({'source': 'illuminateartofficial', 'result': illuminate_result})
            results['illuminate'] = illuminate_result
            
            if illuminate_result['found']:
                print(f" ✅ GPS: {illuminate_result['lat']:.5f}, {illuminate_result['lng']:.5f}")
                illuminate_valid = _check_city(illuminate_result['lat'], illuminate_result['lng'], 'IlluminateArt')
            else:
                print(f" ❌")
        
        # 3. Test de cohérence entre sources web (seulement si les deux sont valides)
        coherence = self.check_coherence(
            aroundus_result if aroundus_valid else {'found': False},
            illuminate_result if illuminate_valid else {'found': False}
        )
        results['coherence'] = coherence
        
        # 4. Choisir le meilleur résultat parmi les sources web
        best_source = None
        if aroundus_valid and illuminate_valid:
            if coherence['status'] in ['excellent', 'good']:
                best_source = 'aroundus'
            elif coherence['status'] == 'conflict':
                best_source = 'aroundus'
                print(f"   ⚠️  CONFLIT: {coherence['details']}")
            else:
                best_source = 'aroundus'
        elif aroundus_valid:
            best_source = 'aroundus'
        elif illuminate_valid:
            best_source = 'illuminate'
        
        # 5. Pnote (fallback en mode normal, source primaire en mode --no-browser)
        if not best_source and self.pnote and self.pnote.loaded:
            print(f"   🔍 Pnote.eu...", end='', flush=True)
            pnote_result = self.pnote.search(invader_id, city_name)
            results['sources_checked'].append({'source': 'pnote', 'result': pnote_result})
            results['pnote'] = pnote_result
            
            if pnote_result['found']:
                print(f" ✅ GPS: {pnote_result['lat']:.5f}, {pnote_result['lng']:.5f} (±10m)")
                if pnote_result.get('hint'):
                    print(f"      💡 Hint: {pnote_result['hint']}")
                if _check_city(pnote_result['lat'], pnote_result['lng'], 'Pnote'):
                    best_source = 'pnote'
                    coherence['status'] = 'single_source'
                    coherence['details'] = 'Seulement Pnote (±10m offset)'
            else:
                print(f" ❌")
                if pnote_result.get('hint'):
                    print(f"      💡 Hint disponible: {pnote_result['hint']}")
                    results['pnote_hint'] = pnote_result['hint']
        
        # 6. Fallback Flickr (si toujours rien de valide — nécessite navigateur)
        if not best_source and not self.no_browser and self.flickr and self.flickr.enabled:
            print(f"   🔍 Flickr...", end='', flush=True)
            flickr_result = self.flickr.search(invader_id, city_name)
            results['sources_checked'].append({'source': 'flickr', 'result': flickr_result})
            results['flickr'] = flickr_result
            
            if flickr_result['found']:
                method = flickr_result.get('method', '?')
                print(f" ✅ GPS: {flickr_result['lat']:.5f}, {flickr_result['lng']:.5f} (via {method})")
                if flickr_result.get('photo_url'):
                    print(f"      📷 {flickr_result['photo_url']}")
                if _check_city(flickr_result['lat'], flickr_result['lng'], 'Flickr'):
                    best_source = 'flickr'
                    coherence['status'] = 'single_source'
                    coherence['details'] = f"Seulement Flickr (via {method})"
            else:
                print(f" ❌")
            
            time.sleep(0.5)  # Rate limiting Flickr
        
        # 7. Remplir le résultat final
        if best_source == 'aroundus':
            results['found'] = True
            results['lat'] = aroundus_result['lat']
            results['lng'] = aroundus_result['lng']
            results['address'] = aroundus_result.get('address')
            results['source'] = 'aroundus'
            results['url'] = aroundus_result.get('url')
        elif best_source == 'illuminate':
            results['found'] = True
            results['lat'] = illuminate_result['lat']
            results['lng'] = illuminate_result['lng']
            results['address'] = illuminate_result.get('address')
            results['source'] = 'illuminateartofficial'
            results['url'] = illuminate_result.get('url')
        elif best_source == 'pnote':
            results['found'] = True
            results['lat'] = pnote_result['lat']
            results['lng'] = pnote_result['lng']
            results['source'] = 'pnote'
            if pnote_result.get('hint'):
                results['address'] = pnote_result['hint']
        elif best_source == 'flickr':
            results['found'] = True
            results['lat'] = flickr_result['lat']
            results['lng'] = flickr_result['lng']
            results['source'] = 'flickr'
            results['url'] = flickr_result.get('photo_url')
        
        # 8. Validation finale ville (pour le résultat retenu)
        if results['found'] and city_code:
            city_check = validate_city_coherence(results['lat'], results['lng'], city_code)
            results['city_validation'] = city_check
        
        # 9. Reverse geocoding si on a des coordonnées mais pas d'adresse
        if results['found'] and results['lat'] and results['lng'] and not results['address']:
            print(f"   🗺️  Reverse geocoding...", end='', flush=True)
            try:
                geocoded_address = self.reverse_geocode(results['lat'], results['lng'])
                if geocoded_address:
                    results['address_geocoded'] = geocoded_address
                    results['address'] = geocoded_address
                    print(f" ✅ {geocoded_address[:50]}...")
                else:
                    print(f" ⏭️ skipped")
            except Exception as e:
                print(f" ⏭️ skipped (network)")
                if self.verbose:
                    print(f"      ⚠️ {e}")
        
        # 10. Afficher le résumé
        if coherence['status'] != 'unknown':
            status_icons = {
                'excellent': '🟢',
                'good': '🟢',
                'warning': '🟡',
                'conflict': '🔴',
                'single_source': '🔵',
                'not_found': '⚪'
            }
            icon = status_icons.get(coherence['status'], '❓')
            print(f"   {icon} Cohérence: {coherence['details']}")
        
        if results.get('rejected_sources'):
            print(f"   🚫 {len(results['rejected_sources'])} source(s) rejetée(s) (hors ville)")
        
        return results


def load_invaders(filepath):
    """Charge le fichier JSON des invaders"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


# =============================================================================
# NOUVELLES FONCTIONS: Mode --from-missing et --merge
# =============================================================================

def interactive_google_lens(inv_id, image_url, city_name, searcher):
    """
    Mode interactif: affiche le lien Google Lens et attend l'adresse de l'utilisateur.
    
    Returns:
        dict: {'found': bool, 'lat': float, 'lng': float, 'address': str} ou None si skip
    """
    from urllib.parse import quote
    
    # Générer le lien Google Lens
    lens_url = f"https://lens.google.com/uploadbyurl?url={quote(image_url, safe='')}"
    
    print(f"\n   🔍 MODE INTERACTIF pour {inv_id}")
    print(f"   ┌─────────────────────────────────────────────────────────────")
    print(f"   │ 📷 Image: {image_url[:60]}...")
    print(f"   │ 🔗 Google Lens:")
    print(f"   │    {lens_url}")
    print(f"   └─────────────────────────────────────────────────────────────")
    print(f"   Entrez l'adresse trouvée (ou 'skip' pour passer, 'quit' pour arrêter):")
    
    try:
        user_input = input("   >>> ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n   ⏹️  Mode interactif interrompu")
        return None
    
    if not user_input or user_input.lower() == 'skip':
        print(f"   ⏭️  Skipped")
        return None
    
    if user_input.lower() == 'quit':
        print(f"   ⏹️  Arrêt du mode interactif")
        raise KeyboardInterrupt("User quit")
    
    # Ajouter la ville si pas déjà présente
    address = user_input
    if city_name and city_name.lower() not in address.lower():
        address = f"{user_input}, {city_name}"
    
    # Géocoder l'adresse
    print(f"   🗺️  Géocodage de: {address}...")
    
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': address,
            'format': 'json',
            'limit': 1
        }
        response = requests.get(url, params=params, headers={
            'User-Agent': 'InvaderHunter/2.0'
        }, timeout=10)
        
        if response.status_code == 200:
            results = response.json()
            if results:
                lat = float(results[0]['lat'])
                lng = float(results[0]['lon'])
                display_name = results[0].get('display_name', '')
                
                # Vérifier que les coordonnées ne sont pas nulles
                if abs(lat) < 0.01 and abs(lng) < 0.01:
                    print(f"   ❌ Coordonnées invalides (0,0)")
                    return None
                
                print(f"   ✅ Trouvé: {lat:.6f}, {lng:.6f}")
                print(f"      📍 {display_name[:60]}...")
                
                return {
                    'found': True,
                    'lat': lat,
                    'lng': lng,
                    'address': user_input,
                    'address_geocoded': display_name
                }
            else:
                print(f"   ❌ Adresse non trouvée par Nominatim")
                # Proposer de réessayer
                print(f"   Réessayer avec une autre adresse? (ou 'skip'):")
                retry = input("   >>> ").strip()
                if retry and retry.lower() != 'skip':
                    return interactive_google_lens(inv_id, image_url, city_name, searcher)
                return None
        else:
            print(f"   ❌ Erreur HTTP {response.status_code}")
            return None
            
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
        return None


def interactive_manual_address(inv_id, city_name):
    """
    Mode interactif sans image: demander une adresse à l'utilisateur.
    Si l'utilisateur ne saisit rien, retourne None (fallback au centre-ville).
    
    Returns:
        dict: {'found': bool, 'lat': float, 'lng': float, 'address': str} ou None si skip
    """
    print(f"\n   📝 SAISIE MANUELLE pour {inv_id}")
    print(f"   ┌─────────────────────────────────────────────────────────────")
    print(f"   │ 🏙️ Ville: {city_name}")
    print(f"   │ Pas d'image disponible pour Google Lens")
    print(f"   └─────────────────────────────────────────────────────────────")
    print(f"   Entrez l'adresse (ou Entrée pour centre-ville, 'skip', 'quit'):")
    
    try:
        user_input = input("   >>> ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n   ⏹️  Mode interactif interrompu")
        return None
    
    if not user_input or user_input.lower() == 'skip':
        print(f"   ⏭️  Fallback centre-ville")
        return None
    
    if user_input.lower() == 'quit':
        print(f"   ⏹️  Arrêt du mode interactif")
        raise KeyboardInterrupt("User quit")
    
    # Ajouter la ville si pas déjà présente
    address = user_input
    if city_name and city_name.lower() not in address.lower():
        address = f"{user_input}, {city_name}"
    
    # Géocoder l'adresse via Nominatim
    print(f"   🗺️  Géocodage de: {address}...")
    
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': address,
            'format': 'json',
            'limit': 1
        }
        response = requests.get(url, params=params, headers={
            'User-Agent': 'InvaderHunter/2.0'
        }, timeout=10)
        
        if response.status_code == 200:
            results = response.json()
            if results:
                lat = float(results[0]['lat'])
                lng = float(results[0]['lon'])
                display_name = results[0].get('display_name', '')
                
                if abs(lat) < 0.01 and abs(lng) < 0.01:
                    print(f"   ❌ Coordonnées invalides (0,0)")
                    return None
                
                print(f"   ✅ Trouvé: {lat:.6f}, {lng:.6f}")
                print(f"      📍 {display_name[:60]}...")
                
                return {
                    'found': True,
                    'lat': lat,
                    'lng': lng,
                    'address': user_input,
                    'address_geocoded': display_name
                }
            else:
                print(f"   ❌ Adresse non trouvée par Nominatim")
                print(f"   Réessayer avec une autre adresse? (ou 'skip'):")
                retry = input("   >>> ").strip()
                if retry and retry.lower() != 'skip':
                    return interactive_manual_address(inv_id, city_name)
                return None
        else:
            print(f"   ❌ Erreur HTTP {response.status_code}")
            return None
            
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
        return None


def process_missing_invaders(missing_file, output_file, searcher, city_filter=None, limit=None, pause=1.0, interactive=False):
    """
    Traite les invaders depuis invaders_missing_from_github.json
    et génère un fichier compatible avec invaders_updated.json
    
    Args:
        interactive: Si True, propose Google Lens pour les non trouvés
    """
    print(f"📂 Chargement de {missing_file}...")
    with open(missing_file, 'r', encoding='utf-8') as f:
        missing_invaders = json.load(f)
    print(f"   {len(missing_invaders)} invaders manquants chargés")
    
    # Filtrer par ville
    if city_filter:
        missing_invaders = [inv for inv in missing_invaders if inv.get('city', '').upper() == city_filter.upper()]
        print(f"   {len(missing_invaders)} invaders pour {city_filter}")
    
    # Limiter
    if limit:
        missing_invaders = missing_invaders[:limit]
        print(f"   Limité à {len(missing_invaders)} invaders")
    
    if not missing_invaders:
        print("❌ Aucun invader à traiter")
        return []
    
    print(f"\n🔍 Géolocalisation de {len(missing_invaders)} invaders...")
    if interactive:
        print("\n📌 MODE INTERACTIF activé")
        print("   Pour les invaders non trouvés automatiquement:")
        print("   1. Un lien Google Lens s'affichera")
        print("   2. Ouvrez-le dans un navigateur")
        print("   3. Entrez l'adresse trouvée (ex: '123 Oxford Street')")
        print("   4. Ou tapez 'skip' pour passer, 'quit' pour arrêter")
    print("=" * 60)
    
    # Stats
    stats = {'total': len(missing_invaders), 'found': 0, 'high': 0, 'medium': 0, 'low': 0, 'exif': 0, 'ocr': 0, 'vision': 0, 'interactive': 0, 'pnote': 0, 'flickr': 0}
    results = []
    
    for i, inv in enumerate(missing_invaders, 1):
        inv_name = inv.get('name', '')
        inv_id = inv_name.upper().replace('-', '_')
        city_code = inv.get('city', '')
        
        print(f"\n[{i}/{len(missing_invaders)}] {inv_id}")
        
        # Rechercher via le searcher existant
        search_result = searcher.search(inv_id, city_code)
        
        # Construire le résultat au format invaders_updated.json
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
        
        # Copier les champs existants
        for field in ['image_invader', 'image_lieu', 'landing_date', 'status_date']:
            if inv.get(field):
                new_inv[field] = inv[field]
        
        if search_result.get('found'):
            new_inv['lat'] = search_result['lat']
            new_inv['lng'] = search_result['lng']
            new_inv['address'] = search_result.get('address')
            new_inv['geo_source'] = search_result.get('source')
            new_inv['location_unknown'] = False
            new_inv['geo_search_exhausted'] = False  # Trouvé → reset du tag
            
            # Déterminer la confiance
            coherence = search_result.get('coherence') or {}
            if coherence.get('status') in ['excellent', 'good']:
                new_inv['geo_confidence'] = 'high'
                stats['high'] += 1
            elif coherence.get('status') in ['warning', 'conflict', 'single_source']:
                new_inv['geo_confidence'] = 'medium'
                stats['medium'] += 1
            else:
                new_inv['geo_confidence'] = 'medium'
                stats['medium'] += 1
            
            stats['found'] += 1
            
            # Tracker les sources v3
            src = search_result.get('source', '')
            if src == 'pnote':
                stats['pnote'] += 1
            elif src == 'flickr':
                stats['flickr'] += 1
        else:
            exif_result = None
            ocr_result = None
            image_lieu_url = inv.get('image_lieu')
            city_name = CITY_CENTERS.get(city_code, {}).get('name', city_code)
            
            if image_lieu_url:
                print(f"   🖼️  Tentative EXIF sur image_lieu...")
                exif_result = extract_gps_from_image_url(image_lieu_url, verbose=searcher.verbose)
                
                if exif_result.get('found'):
                    new_inv['lat'] = exif_result['lat']
                    new_inv['lng'] = exif_result['lng']
                    new_inv['geo_source'] = 'exif_image_lieu'
                    new_inv['geo_confidence'] = 'medium'
                    new_inv['location_unknown'] = False
                    new_inv['geo_search_exhausted'] = False
                    stats['found'] += 1
                    stats['medium'] += 1
                    stats['exif'] += 1
                    print(f"   ✅ EXIF: {exif_result['lat']:.6f}, {exif_result['lng']:.6f}")
                else:
                    if searcher.verbose:
                        print(f"      [EXIF] {exif_result.get('error', 'Non trouvé')}")
                    
                    # Fallback 2: OCR Tesseract (analyse visuelle de l'image)
                    if searcher.ocr_analyzer and TESSERACT_AVAILABLE:
                        print(f"   🔍 Tentative OCR sur image_lieu...")
                        ocr_result = searcher.ocr_analyzer.analyze(image_lieu_url, city_name, city_code)
                        
                        # Afficher les textes extraits
                        texts_all = ocr_result.get('texts_all', [])
                        if texts_all:
                            print(f"      📝 Textes extraits ({len(texts_all)} uniques):")
                            for line in sorted(texts_all)[:15]:  # Max 15 lignes
                                print(f"         │ {line}")
                            if len(texts_all) > 15:
                                print(f"         │ ... (+{len(texts_all) - 15} autres)")
                        
                        if ocr_result.get('found'):
                            new_inv['lat'] = ocr_result['lat']
                            new_inv['lng'] = ocr_result['lng']
                            new_inv['address'] = ocr_result.get('address')
                            new_inv['geo_source'] = 'ocr'
                            new_inv['geo_confidence'] = 'medium'
                            new_inv['location_unknown'] = False
                            new_inv['geo_search_exhausted'] = False
                            stats['found'] += 1
                            stats['medium'] += 1
                            stats['ocr'] += 1
                            print(f"   ✅ OCR: {ocr_result['lat']:.6f}, {ocr_result['lng']:.6f}")
                            if ocr_result.get('address'):
                                print(f"      📍 {ocr_result['address']}")
                        else:
                            print(f"      ❌ {ocr_result.get('error', 'Non trouvé')}")
            
            # Fallback Claude Vision (si image dispo et OCR n'a pas trouvé)
            found_via_image = (exif_result and exif_result.get('found')) or (ocr_result and ocr_result.get('found'))
            vision_result = None
            if not found_via_image and image_lieu_url and searcher.vision and searcher.vision.enabled:
                image_close_url = inv.get('image_invader')  # Gros plan mosaïque
                n_images = "2 images" if image_close_url else "1 image"
                print(f"   🧠 Claude Vision ({n_images})...", end='', flush=True)
                vision_result = searcher.vision.analyze(
                    image_lieu_url, city_name, city_code,
                    image_close_url=image_close_url
                )
                
                if vision_result.get('found'):
                    # Valider contre la ville
                    if city_code:
                        check = validate_city_coherence(vision_result['lat'], vision_result['lng'], city_code)
                        if not check['valid']:
                            print(f" 🚫 REJETÉ ({check['warning']})")
                            vision_result['found'] = False
                    
                    if vision_result.get('found'):
                        new_inv['lat'] = vision_result['lat']
                        new_inv['lng'] = vision_result['lng']
                        new_inv['address'] = vision_result.get('address')
                        new_inv['geo_source'] = 'vision'
                        new_inv['geo_confidence'] = 'medium' if vision_result.get('confidence') in ('HIGH', 'MEDIUM') else 'low'
                        new_inv['location_unknown'] = False
                        new_inv['geo_search_exhausted'] = False
                        stats['found'] += 1
                        stats['medium'] += 1
                        stats['vision'] += 1
                        print(f" ✅ {vision_result['lat']:.6f}, {vision_result['lng']:.6f}")
                        if vision_result.get('address'):
                            print(f"      📍 {vision_result['address']}")
                        confidence = vision_result.get('confidence', '?')
                        print(f"      🎯 Confiance: {confidence}")
                        found_via_image = True
                else:
                    print(f" ❌ {vision_result.get('error', 'Non trouvé')}")
            
            # Fallback interactif: proposer Google Lens si mode interactif activé
            found_via_fallback = found_via_image
            if not found_via_fallback and interactive:
                if image_lieu_url:
                    interactive_result = interactive_google_lens(
                        inv_id, image_lieu_url, city_name, searcher
                    )
                else:
                    # Pas d'image: proposer la saisie manuelle d'adresse
                    interactive_result = interactive_manual_address(inv_id, city_name)
                if interactive_result and interactive_result.get('found'):
                    new_inv['lat'] = interactive_result['lat']
                    new_inv['lng'] = interactive_result['lng']
                    new_inv['address'] = interactive_result.get('address')
                    new_inv['geo_source'] = 'interactive'
                    new_inv['geo_confidence'] = 'medium'
                    new_inv['location_unknown'] = False
                    new_inv['geo_search_exhausted'] = False
                    stats['found'] += 1
                    stats['medium'] += 1
                    stats['interactive'] += 1
                    found_via_fallback = True
            
            # Fallback 3: centre-ville
            if not found_via_fallback:
                if city_code in CITY_CENTERS:
                    new_inv['lat'] = CITY_CENTERS[city_code]['lat']
                    new_inv['lng'] = CITY_CENTERS[city_code]['lng']
                    new_inv['geo_source'] = 'city_center'
                    new_inv['geo_confidence'] = 'low'
                    new_inv['geo_search_exhausted'] = True
                    new_inv['geo_search_date'] = datetime.now().isoformat()
                    print(f"   ⚠️ Fallback: centre de {CITY_CENTERS[city_code]['name']}")
                    print(f"      🏷️ Marqué geo_search_exhausted (sera ignoré au prochain run)")
                else:
                    new_inv['lat'] = 0
                    new_inv['lng'] = 0
                    new_inv['geo_source'] = 'unknown'
                    new_inv['geo_search_exhausted'] = True
                    new_inv['geo_search_date'] = datetime.now().isoformat()
                    print(f"   ⚠️ Ville inconnue: {city_code}")
                
                stats['low'] += 1
        
        results.append(new_inv)
        time.sleep(pause)
    
    # Statistiques
    print("\n" + "=" * 60)
    print("📊 STATISTIQUES")
    print("=" * 60)
    print(f"   Total:   {stats['total']}")
    print(f"   Trouvés: {stats['found']} ({100*stats['found']/max(1,stats['total']):.1f}%)")
    print(f"   🟢 HIGH:   {stats['high']}")
    medium_details = []
    if stats['pnote'] > 0:
        medium_details.append(f"{stats['pnote']} Pnote")
    if stats['flickr'] > 0:
        medium_details.append(f"{stats['flickr']} Flickr")
    if stats['exif'] > 0:
        medium_details.append(f"{stats['exif']} EXIF")
    if stats['ocr'] > 0:
        medium_details.append(f"{stats['ocr']} OCR")
    if stats['vision'] > 0:
        medium_details.append(f"{stats['vision']} Vision")
    if stats['interactive'] > 0:
        medium_details.append(f"{stats['interactive']} Interactive")
    medium_suffix = f" (dont {', '.join(medium_details)})" if medium_details else ""
    print(f"   🟡 MEDIUM: {stats['medium']}{medium_suffix}")
    print(f"   🔴 LOW:    {stats['low']}")
    
    # Sauvegarder JSON
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n📄 Résultats: {output_file}")
    
    # Rapport texte
    txt_output = output_file.replace('.json', '.txt')
    with open(txt_output, 'w', encoding='utf-8') as f:
        f.write("GÉOLOCALISATION DES INVADERS MANQUANTS\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Total: {stats['total']}\n")
        f.write(f"Trouvés: {stats['found']}\n")
        f.write(f"HIGH: {stats['high']}, MEDIUM: {stats['medium']}")
        medium_details = []
        if stats['pnote'] > 0:
            medium_details.append(f"{stats['pnote']} Pnote")
        if stats['flickr'] > 0:
            medium_details.append(f"{stats['flickr']} Flickr")
        if stats['exif'] > 0:
            medium_details.append(f"{stats['exif']} EXIF")
        if stats['ocr'] > 0:
            medium_details.append(f"{stats['ocr']} OCR")
        if stats['vision'] > 0:
            medium_details.append(f"{stats['vision']} Vision")
        if medium_details:
            f.write(f" (dont {', '.join(medium_details)})")
        f.write(f", LOW: {stats['low']}\n\n")
        
        for inv in results:
            conf_icon = {'high': '🟢', 'medium': '🟡', 'low': '🔴'}.get(inv['geo_confidence'], '❓')
            f.write(f"{inv['id']} {conf_icon} ({inv['geo_confidence'].upper()})\n")
            if inv['lat'] and inv['lng']:
                f.write(f"   GPS: {inv['lat']:.6f}, {inv['lng']:.6f}\n")
            f.write(f"   Source: {inv.get('geo_source', '?')}\n")
            if inv.get('address'):
                f.write(f"   Adresse: {inv['address']}\n")
            if inv['lat'] and inv['lng']:
                f.write(f"   Maps: https://www.google.com/maps?q={inv['lat']},{inv['lng']}\n")
            if inv.get('location_unknown'):
                f.write(f"   ⚠️ Localisation approximative\n")
            f.write("\n")
    
    print(f"📄 Rapport: {txt_output}")
    
    return results


def merge_with_updated(geolocated_file, updated_file=None, backup=False, dry_run=False, verbose=False):
    """
    Fusionne les invaders géolocalisés avec invaders_master.json
    """
    if updated_file is None:
        updated_file = _p(MASTER_FILE)
    
    print("=" * 60)
    print(f"🔗 FUSION AVEC {os.path.basename(updated_file)}")
    print("=" * 60)
    
    # Vérifier les fichiers
    if not os.path.exists(geolocated_file):
        print(f"❌ Fichier non trouvé: {geolocated_file}")
        return
    
    if not os.path.exists(updated_file):
        print(f"❌ Fichier non trouvé: {updated_file}")
        return
    
    # Charger
    print(f"\n📂 Chargement de {updated_file}...")
    with open(updated_file, 'r', encoding='utf-8') as f:
        updated_db = json.load(f)
    print(f"   {len(updated_db)} invaders existants")
    
    print(f"📂 Chargement de {geolocated_file}...")
    with open(geolocated_file, 'r', encoding='utf-8') as f:
        geolocated = json.load(f)
    print(f"   {len(geolocated)} invaders géolocalisés")
    
    # Index des existants
    existing_ids = {}
    for i, inv in enumerate(updated_db):
        inv_id = inv.get('id', inv.get('name', '')).upper().replace('-', '_')
        existing_ids[inv_id] = i
    
    # Fusionner
    added = 0
    updated = 0
    confidence_order = {'high': 3, 'medium': 2, 'low': 1, 'very_low': 0}
    
    for geo_inv in geolocated:
        geo_id = geo_inv.get('id', '').upper().replace('-', '_')
        
        if geo_id in existing_ids:
            # Mettre à jour si meilleure confiance
            idx = existing_ids[geo_id]
            old_inv = updated_db[idx]
            
            old_conf = old_inv.get('geo_confidence', 'low')
            new_conf = geo_inv.get('geo_confidence', 'low')
            
            if confidence_order.get(new_conf, 0) >= confidence_order.get(old_conf, 0):
                updated_db[idx]['lat'] = geo_inv['lat']
                updated_db[idx]['lng'] = geo_inv['lng']
                updated_db[idx]['geo_source'] = geo_inv.get('geo_source')
                updated_db[idx]['geo_confidence'] = new_conf
                updated_db[idx]['location_unknown'] = geo_inv.get('location_unknown', False)
                updated_db[idx]['geo_search_exhausted'] = geo_inv.get('geo_search_exhausted', False)
                if geo_inv.get('geo_search_date'):
                    updated_db[idx]['geo_search_date'] = geo_inv['geo_search_date']
                if geo_inv.get('address'):
                    updated_db[idx]['address'] = geo_inv['address']
                updated_db[idx]['preserved'] = True
                updated_db[idx]['preserved_date'] = datetime.now().isoformat()
                updated += 1
                if verbose:
                    print(f"   🔄 {geo_id}: {old_conf} → {new_conf}")
        else:
            # Ajouter
            geo_inv['preserved'] = True
            geo_inv['preserved_date'] = datetime.now().isoformat()
            updated_db.append(geo_inv)
            added += 1
            if verbose:
                print(f"   ➕ {geo_id}")
    
    # Backup
    if backup and not dry_run:
        backup_file = f"{updated_file}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(updated_db, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Backup: {backup_file}")
    
    # Sauvegarder
    if not dry_run:
        with open(updated_file, 'w', encoding='utf-8') as f:
            json.dump(updated_db, f, indent=2, ensure_ascii=False)
        print(f"\n✅ {updated_file} mis à jour:")
    else:
        print(f"\n🔍 Mode dry-run - pas de sauvegarde:")
    
    print(f"   ➕ {added} invaders ajoutés")
    print(f"   🔄 {updated} invaders mis à jour")
    print(f"   📊 Total: {len(updated_db)} invaders")


def main():
    parser = argparse.ArgumentParser(
        description='Recherche de localisation via sources spécialisées',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument('invaders_file', nargs='?', help='Fichier JSON des invaders (mode classique, défaut: data/invaders_master.json)')
    parser.add_argument('--from-missing', dest='missing_file', help='Fichier invaders_missing_from_github.json (défaut: data/)')
    parser.add_argument('--from-master', action='store_true', help='Géolocaliser les invaders du master sans coordonnées ou au centre-ville')
    parser.add_argument('--merge', dest='merge_file', help='Fusionner ce fichier avec invaders_master.json')
    parser.add_argument('--city', '-c', help='Filtrer par code ville (ex: AMI)')
    parser.add_argument('--limit', '-l', type=int, help='Nombre max d\'invaders')
    parser.add_argument('--verbose', '-v', action='store_true', help='Mode verbeux')
    parser.add_argument('--visible', action='store_true', help='Afficher le navigateur')
    parser.add_argument('--output', '-o', default=None, help='Fichier de sortie (défaut: data/invaders_geolocated.json)')
    parser.add_argument('--only-missing', action='store_true', help='Seulement les invaders sans coordonnées')
    parser.add_argument('--pause', type=float, default=1.0, help='Pause entre requêtes')
    parser.add_argument('--interactive', '-i', action='store_true', help='Mode interactif pour les non trouvés (Google Lens)')
    parser.add_argument('--backup', action='store_true', help='Créer un backup avant merge')
    parser.add_argument('--dry-run', action='store_true', help='Simuler sans sauvegarder')
    # Sources v3
    parser.add_argument('--pnote-file', dest='pnote_file', help='Fichier JSON pnote.eu local (fallback GPS ±10m)')
    parser.add_argument('--pnote-url', dest='pnote_url', nargs='?',
                        const=PnoteSearcher.PNOTE_DEFAULT_URL,
                        default=None,
                        help='Télécharger pnote.eu depuis URL (défaut: pnote.eu/projects/invaders/map/invaders.json)')
    parser.add_argument('--no-flickr', dest='no_flickr', action='store_true',
                        help='Désactiver la recherche Flickr (scraping)')
    parser.add_argument('--anthropic-key', dest='anthropic_key', default=None,
                        help='Clé API Anthropic pour Claude Vision (ou env ANTHROPIC_API_KEY)')
    parser.add_argument('--id', dest='invader_id', default=None,
                        help='Chercher un seul invader par son code (ex: PA_1531, LDN_42)')
    parser.add_argument('--retry-failed', dest='retry_failed', action='store_true',
                        help='Relancer la recherche des invaders marqués geo_search_exhausted')
    parser.add_argument('--no-browser', dest='no_browser', action='store_true',
                        help='Mode sans navigateur: Pnote + EXIF + OCR + Vision uniquement (idéal CI/CD)')
    
    args = parser.parse_args()
    
    # --id implique --from-master et --retry-failed
    if args.invader_id:
        args.from_master = True
        args.retry_failed = True  # Forcer la recherche même si déjà échoué
    
    # --no-browser implique --no-flickr et désactive --interactive
    if args.no_browser:
        args.no_flickr = True
        args.interactive = False
    
    # =========================================================================
    # Mode --merge: fusionner avec invaders_updated.json
    # =========================================================================
    if args.merge_file:
        merge_with_updated(
            geolocated_file=args.merge_file,
            backup=args.backup,
            dry_run=args.dry_run,
            verbose=args.verbose
        )
        return
    
    # =========================================================================
    # Mode --from-master: géolocaliser les invaders mal localisés du master
    # =========================================================================
    if args.from_master:
        if not MASTER_FILE.exists():
            print(f"❌ Fichier master non trouvé: {MASTER_FILE}")
            return
        
        print(f"📂 Chargement du master: {MASTER_FILE.name}...")
        with open(_p(MASTER_FILE), 'r', encoding='utf-8') as f:
            master_db = json.load(f)
        print(f"   {len(master_db)} invaders chargés")
        
        # Centres des villes connus (utilise le dictionnaire global CITY_CENTERS)
        city_centers_coords = {code: (info['lat'], info['lng']) for code, info in CITY_CENTERS.items()}
        
        def is_poorly_located(inv):
            """Détermine si un invader a besoin d'être re-géolocalisé."""
            lat = inv.get('lat')
            lng = inv.get('lng')
            
            # Pas de coordonnées
            if lat is None or lng is None:
                return True, 'no_coords'
            if lat == '' or lng == '':
                return True, 'no_coords'
            
            try:
                lat, lng = float(lat), float(lng)
            except (ValueError, TypeError):
                return True, 'invalid_coords'
            
            # Coordonnées à zéro
            if lat == 0 and lng == 0:
                return True, 'zero_coords'
            if abs(lat) < 0.001 and abs(lng) < 0.001:
                return True, 'near_zero'
            
            # Marqué explicitement comme inconnu
            if inv.get('location_unknown') is True:
                # Mais si déjà cherché et échoué → skip (sauf --retry-failed)
                if inv.get('geo_search_exhausted') and not args.retry_failed:
                    return False, 'search_exhausted_skip'
                return True, 'location_unknown'
            
            # Source = city_center
            if inv.get('geo_source') == 'city_center':
                # Déjà cherché et échoué → skip (sauf --retry-failed)
                if inv.get('geo_search_exhausted') and not args.retry_failed:
                    return False, 'search_exhausted_skip'
                return True, 'city_center_tag'
            
            # Confiance très basse
            if inv.get('geo_confidence') == 'very_low':
                if inv.get('geo_search_exhausted') and not args.retry_failed:
                    return False, 'search_exhausted_skip'
                return True, 'very_low_confidence'
            
            # Coordonnées = centre-ville connu
            city = inv.get('city', '').upper()
            if city in city_centers_coords:
                c_lat, c_lng = city_centers_coords[city]
                if round(lat, 4) == round(c_lat, 4) and round(lng, 4) == round(c_lng, 4):
                    if inv.get('geo_search_exhausted') and not args.retry_failed:
                        return False, 'search_exhausted_skip'
                    return True, 'at_city_center'
            
            return False, None
        
        # Filtrer par ville
        candidates = master_db
        if args.city:
            candidates = [inv for inv in candidates if inv.get('city', '').upper() == args.city.upper()]
            print(f"   {len(candidates)} invaders pour {args.city}")
        
        # Filtrer par ID spécifique (--id PA_1531)
        if args.invader_id:
            target_id = args.invader_id.upper().replace('-', '_')
            candidates = [inv for inv in candidates 
                         if inv.get('id', inv.get('name', '')).upper().replace('-', '_') == target_id]
            if not candidates:
                print(f"❌ Invader '{args.invader_id}' non trouvé dans le master")
                return
            print(f"   🎯 Cible unique: {target_id}")
        
        # Identifier les mal localisés
        poorly_located = []
        reasons_count = {}
        exhausted_skip_count = 0
        for inv in candidates:
            needs_geo, reason = is_poorly_located(inv)
            if needs_geo:
                poorly_located.append(inv)
                reasons_count[reason] = reasons_count.get(reason, 0) + 1
            elif reason == 'search_exhausted_skip':
                exhausted_skip_count += 1
        
        print(f"\n📊 {len(poorly_located)} invaders à re-géolocaliser sur {len(candidates)}:")
        for reason, count in sorted(reasons_count.items(), key=lambda x: -x[1]):
            labels = {
                'no_coords': '📭 Pas de coordonnées',
                'invalid_coords': '❌ Coordonnées invalides',
                'zero_coords': '0️⃣ Coordonnées à zéro',
                'near_zero': '0️⃣ Coordonnées proches de zéro',
                'location_unknown': '❓ Marqué location_unknown',
                'city_center_tag': '🏙️ Source = city_center',
                'very_low_confidence': '🔴 Confiance very_low',
                'at_city_center': '📍 Au centre-ville exact',
            }
            print(f"   {labels.get(reason, reason)}: {count}")
        if exhausted_skip_count > 0:
            print(f"   ⏭️  Ignorés (recherche déjà échouée): {exhausted_skip_count}")
            if not args.retry_failed:
                print(f"      💡 Utilisez --retry-failed pour relancer ces recherches")
        
        if not poorly_located:
            # Si --id est passé, forcer la recherche même si les coords sont OK
            if args.invader_id and candidates:
                poorly_located = candidates
                print(f"   🎯 Recherche forcée pour {args.invader_id}")
            else:
                print("✅ Tous les invaders ont des coordonnées valides!")
                return
        
        # Limiter
        if args.limit:
            poorly_located = poorly_located[:args.limit]
            print(f"   Limité à {len(poorly_located)} invaders")
        
        # Convertir au format attendu par process_missing_invaders
        tmp_file = _p(DATA_DIR / '_tmp_poorly_located.json')
        missing_format = []
        for inv in poorly_located:
            missing_format.append({
                'name': inv.get('id', inv.get('name', '')),
                'city': inv.get('city', ''),
                'status': inv.get('status', 'OK'),
                'points': inv.get('points', 0),
                'image_invader': inv.get('image_invader'),
                'image_lieu': inv.get('image_lieu'),
                'landing_date': inv.get('landing_date'),
                'status_date': inv.get('status_date'),
            })
        
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(missing_format, f, indent=2, ensure_ascii=False)
        
        # Lancer le searcher
        searcher = InvaderLocationSearcher(visible=args.visible, verbose=args.verbose, pnote_file=args.pnote_file, pnote_url=args.pnote_url, flickr=not args.no_flickr, anthropic_key=args.anthropic_key, no_browser=args.no_browser)
        try:
            searcher.start()
            print("🌐 Navigateur démarré" if not getattr(searcher, "no_browser", False) else "🤖 Sources HTTP démarrées")
            
            output_file = args.output if args.output else _p(DATA_DIR / 'invaders_relocalized.json')
            
            process_missing_invaders(
                missing_file=tmp_file,
                output_file=output_file,
                searcher=searcher,
                city_filter=None,  # Déjà filtré
                limit=None,        # Déjà limité
                pause=args.pause,
                interactive=args.interactive
            )
            
            print(f"\n📋 Pour fusionner avec le master:")
            print(f"   python geolocate_missing.py --merge {output_file} --backup")
        finally:
            searcher.stop()
            # Nettoyer le fichier temporaire
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
            print("\n🌐 Navigateur fermé" if not getattr(searcher, "no_browser", False) else "\n🤖 Sources HTTP arrêtées")
        return
    
    # =========================================================================
    # Mode --from-missing: géolocaliser les invaders manquants
    # =========================================================================
    if args.missing_file:
        missing_path = args.missing_file
        if not os.path.exists(missing_path):
            print(f"❌ Fichier non trouvé: {missing_path}")
            return
        
        # Démarrer le searcher
        searcher = InvaderLocationSearcher(visible=args.visible, verbose=args.verbose, pnote_file=args.pnote_file, pnote_url=args.pnote_url, flickr=not args.no_flickr, anthropic_key=args.anthropic_key, no_browser=args.no_browser)
        try:
            searcher.start()
            print("🌐 Navigateur démarré" if not getattr(searcher, "no_browser", False) else "🤖 Sources HTTP démarrées")
            
            output_file = args.output if args.output else _p(DATA_DIR / 'invaders_geolocated.json')
            
            process_missing_invaders(
                missing_file=missing_path,
                output_file=output_file,
                searcher=searcher,
                city_filter=args.city,
                limit=args.limit,
                pause=args.pause,
                interactive=args.interactive
            )
            
            print(f"\n📋 Pour fusionner avec le master:")
            print(f"   python geolocate_missing.py --merge {output_file} --backup")
        finally:
            searcher.stop()
            print("\n🌐 Navigateur fermé" if not getattr(searcher, "no_browser", False) else "\n🤖 Sources HTTP arrêtées")
        return
    
    # =========================================================================
    # Mode classique: fichier invaders existant
    # =========================================================================
    invaders_file = args.invaders_file or _p(MASTER_FILE)
    if not os.path.exists(invaders_file):
        parser.print_help()
        print(f"\n❌ Fichier non trouvé: {invaders_file}")
        print("   Spécifiez un fichier ou utilisez --from-missing ou --merge")
        return
    
    
    # Charger les invaders
    print(f"📂 Chargement de {invaders_file}...")
    invaders = load_invaders(invaders_file)
    print(f"   {len(invaders)} invaders chargés")
    
    # Filtrer par ville
    if args.city:
        invaders = [inv for inv in invaders if inv.get('city', '').upper() == args.city.upper()]
        print(f"   {len(invaders)} invaders pour {args.city}")
    
    # Filtrer ceux sans coordonnées
    if args.only_missing:
        def has_coords(inv):
            try:
                lat = float(str(inv.get('lat', '')).replace(',', '.'))
                lng = float(str(inv.get('lng', '')).replace(',', '.'))
                return lat != 0 and lng != 0
            except:
                return False
        
        invaders = [inv for inv in invaders if not has_coords(inv)]
        print(f"   {len(invaders)} invaders sans coordonnées")
    
    # Limiter
    if args.limit:
        invaders = invaders[:args.limit]
        print(f"   Limité à {len(invaders)} invaders")
    
    if not invaders:
        print("❌ Aucun invader à traiter")
        return
    
    print(f"\n🔍 Recherche pour {len(invaders)} invaders...")
    print("=" * 60)
    
    # Statistiques
    stats = {
        'total': len(invaders),
        'searched': 0,
        'found': 0,
        'found_aroundus': 0,
        'found_illuminate': 0,
        'found_both': 0,
        'found_pnote': 0,
        'found_flickr': 0,
        'has_existing': 0,
        'matches': 0,
        'differs': 0,
        'new_coords': 0,
        'distances': [],
        # Cohérence entre sources
        'coherence': {
            'excellent': 0,
            'good': 0,
            'warning': 0,
            'conflict': 0,
            'single_source': 0,
            'not_found': 0
        }
    }
    
    results = []
    
    # Initialiser le searcher
    searcher = InvaderLocationSearcher(visible=args.visible, verbose=args.verbose, pnote_file=args.pnote_file, pnote_url=args.pnote_url, flickr=not args.no_flickr, anthropic_key=args.anthropic_key, no_browser=args.no_browser)
    
    try:
        searcher.start()
        print("🌐 Navigateur démarré" if not getattr(searcher, "no_browser", False) else "🤖 Sources HTTP démarrées")
        
        for i, inv in enumerate(invaders, 1):
            inv_id = inv.get('id', '')
            city_code = inv.get('city', '')
            
            # Coordonnées existantes
            existing_lat = None
            existing_lng = None
            try:
                existing_lat = float(str(inv.get('lat', '')).replace(',', '.'))
                existing_lng = float(str(inv.get('lng', '')).replace(',', '.'))
                if existing_lat == 0 or existing_lng == 0:
                    existing_lat = None
                    existing_lng = None
            except:
                pass
            
            has_existing = existing_lat is not None
            if has_existing:
                stats['has_existing'] += 1
            
            print(f"\n[{i}/{len(invaders)}] {inv_id}")
            
            # Rechercher
            search_result = searcher.search(inv_id, city_code)
            stats['searched'] += 1
            
            result = {
                'id': inv_id,
                'city': city_code,
                'existing_lat': existing_lat,
                'existing_lng': existing_lng,
                **search_result
            }
            
            if search_result['found']:
                stats['found'] += 1
                
                # Compter par source
                aroundus_found = (search_result.get('aroundus') or {}).get('found', False)
                illuminate_found = (search_result.get('illuminate') or {}).get('found', False)
                
                if aroundus_found:
                    stats['found_aroundus'] += 1
                if illuminate_found:
                    stats['found_illuminate'] += 1
                if aroundus_found and illuminate_found:
                    stats['found_both'] += 1
                
                # Sources v3
                if search_result.get('source') == 'pnote':
                    stats['found_pnote'] += 1
                elif search_result.get('source') == 'flickr':
                    stats['found_flickr'] += 1
                
                # Cohérence
                coherence = search_result.get('coherence') or {}
                coherence_status = coherence.get('status', 'unknown')
                if coherence_status in stats['coherence']:
                    stats['coherence'][coherence_status] += 1
                
                # Comparer avec existant
                if has_existing:
                    distance = calculate_distance(
                        existing_lat, existing_lng,
                        search_result['lat'], search_result['lng']
                    )
                    result['distance_to_existing'] = distance
                    stats['distances'].append(distance)
                    
                    if distance < 100:
                        stats['matches'] += 1
                        print(f"   ✅ Distance: {distance:.0f}m - MATCH")
                    else:
                        stats['differs'] += 1
                        print(f"   ⚠️ Distance: {distance:.0f}m - DIFFÉRENT")
                else:
                    stats['new_coords'] += 1
                    print(f"   🆕 Nouvelles coordonnées!")
            else:
                # Pas trouvé - compter quand même la cohérence
                coherence = search_result.get('coherence') or {}
                coherence_status = coherence.get('status', 'not_found')
                if coherence_status in stats['coherence']:
                    stats['coherence'][coherence_status] += 1
            
            results.append(result)
            
            time.sleep(args.pause)
    
    finally:
        searcher.stop()
        print("\n🌐 Navigateur fermé" if not getattr(searcher, "no_browser", False) else "\n🤖 Sources HTTP arrêtées")
    
    # Statistiques
    print("\n" + "=" * 60)
    print("📊 STATISTIQUES")
    print("=" * 60)
    
    print(f"\n📁 Analyse:")
    print(f"   Total invaders:        {stats['total']}")
    print(f"   Recherchés:            {stats['searched']}")
    
    print(f"\n📍 Résultats:")
    print(f"   GPS trouvés:           {stats['found']} ({100*stats['found']/max(1,stats['searched']):.1f}%)")
    print(f"   - via AroundUs:        {stats['found_aroundus']}")
    print(f"   - via IlluminateArt:   {stats['found_illuminate']}")
    print(f"   - Les deux sources:    {stats['found_both']}")
    print(f"   - via Pnote.eu:       {stats['found_pnote']}")
    print(f"   - via Flickr:          {stats['found_flickr']}")
    
    print(f"\n🔗 Cohérence entre sources:")
    print(f"   🟢 Excellent (<50m):   {stats['coherence']['excellent']}")
    print(f"   🟢 Good (<200m):       {stats['coherence']['good']}")
    print(f"   🟡 Warning (<500m):    {stats['coherence']['warning']}")
    print(f"   🔴 Conflit (>500m):    {stats['coherence']['conflict']}")
    print(f"   🔵 Source unique:      {stats['coherence']['single_source']}")
    print(f"   ⚪ Non trouvé:         {stats['coherence']['not_found']}")
    
    print(f"\n📍 Comparaison avec existant:")
    print(f"   Avec coords existantes: {stats['has_existing']}")
    print(f"   - Match (<100m):       {stats['matches']}")
    print(f"   - Différent (>100m):   {stats['differs']}")
    print(f"   - Nouvelles coords:    {stats['new_coords']}")
    
    if stats['distances']:
        print(f"\n📏 Distances:")
        print(f"   Min:                   {min(stats['distances']):.0f}m")
        print(f"   Max:                   {max(stats['distances']):.0f}m")
        print(f"   Moyenne:               {sum(stats['distances'])/len(stats['distances']):.0f}m")
    
    # Sauvegarder
    output_path = args.output if args.output else _p(DATA_DIR / 'location_search_results.json')
    output_data = {
        'stats': {k: v for k, v in stats.items() if k != 'distances'},
        'distances': [round(d, 2) for d in stats['distances']],
        'results': results
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n📄 Résultats: {output_path}")
    
    # Rapport texte
    txt_output = output_path.replace('.json', '.txt')
    with open(txt_output, 'w', encoding='utf-8') as f:
        f.write("RECHERCHE LOCALISATION - Sources Spécialisées\n")
        f.write("=" * 60 + "\n\n")
        
        f.write("Sources:\n")
        f.write("  - aroundus.com\n")
        f.write("  - illuminateartofficial.com\n")
        f.write("  - pnote.eu (fallback)\n")
        f.write("  - flickr.com (fallback)\n\n")
        
        f.write(f"STATISTIQUES\n")
        f.write(f"-" * 40 + "\n")
        f.write(f"Total recherchés:     {stats['searched']}\n")
        f.write(f"GPS trouvés:          {stats['found']}\n")
        f.write(f"- AroundUs:           {stats['found_aroundus']}\n")
        f.write(f"- IlluminateArt:      {stats['found_illuminate']}\n")
        f.write(f"- Les deux:           {stats['found_both']}\n")
        f.write(f"- Pnote.eu:           {stats['found_pnote']}\n")
        f.write(f"- Flickr:             {stats['found_flickr']}\n")
        f.write(f"Nouvelles coords:     {stats['new_coords']}\n\n")
        
        f.write(f"COHERENCE ENTRE SOURCES\n")
        f.write(f"-" * 40 + "\n")
        f.write(f"Excellent (<50m):     {stats['coherence']['excellent']}\n")
        f.write(f"Good (<200m):         {stats['coherence']['good']}\n")
        f.write(f"Warning (<500m):      {stats['coherence']['warning']}\n")
        f.write(f"Conflit (>500m):      {stats['coherence']['conflict']}\n")
        f.write(f"Source unique:        {stats['coherence']['single_source']}\n\n")
        
        # Liste des invaders trouvés
        found_results = [r for r in results if r.get('found')]
        if found_results:
            f.write(f"\n📍 {len(found_results)} INVADERS AVEC GPS:\n")
            f.write("-" * 40 + "\n\n")
            
            for r in found_results:
                coherence = r.get('coherence', {})
                coherence_icon = {'excellent': '🟢', 'good': '🟢', 'warning': '🟡', 'conflict': '🔴', 'single_source': '🔵'}.get(coherence.get('status', ''), '❓')
                
                f.write(f"{r['id']} {coherence_icon} (source: {r.get('source', '?')})\n")
                f.write(f"   GPS: {r['lat']:.6f}, {r['lng']:.6f}\n")
                
                # Adresses
                if r.get('address'):
                    f.write(f"   Adresse (source): {r['address']}\n")
                if r.get('address_geocoded') and r.get('address_geocoded') != r.get('address'):
                    f.write(f"   Adresse (geocoded): {r['address_geocoded']}\n")
                
                # Détails des deux sources
                aroundus = r.get('aroundus', {})
                illuminate = r.get('illuminate', {})
                
                if aroundus.get('found') and illuminate.get('found'):
                    f.write(f"   AroundUs:    {aroundus['lat']:.6f}, {aroundus['lng']:.6f}\n")
                    f.write(f"   Illuminate:  {illuminate['lat']:.6f}, {illuminate['lng']:.6f}\n")
                    f.write(f"   Cohérence:   {coherence.get('details', '?')}\n")
                
                # Comparaison avec existant
                if r.get('existing_lat'):
                    f.write(f"   Existant:    {r['existing_lat']:.6f}, {r['existing_lng']:.6f}\n")
                    f.write(f"   Distance:    {r.get('distance_to_existing', 0):.0f}m\n")
                else:
                    f.write(f"   🆕 Nouvelles coordonnées!\n")
                    
                f.write(f"   Maps: https://www.google.com/maps?q={r['lat']},{r['lng']}\n")
                if r.get('url'):
                    f.write(f"   Source: {r['url']}\n")
                f.write("\n")
        
        # Liste des conflits
        conflicts = [r for r in results if (r.get('coherence') or {}).get('status') == 'conflict']
        if conflicts:
            f.write(f"\n⚠️ {len(conflicts)} CONFLITS À VÉRIFIER:\n")
            f.write("-" * 40 + "\n\n")
            for r in conflicts:
                aroundus = r.get('aroundus', {})
                illuminate = r.get('illuminate', {})
                f.write(f"{r['id']}:\n")
                f.write(f"   AroundUs:   {aroundus.get('lat', 0):.6f}, {aroundus.get('lng', 0):.6f}\n")
                f.write(f"   Illuminate: {illuminate.get('lat', 0):.6f}, {illuminate.get('lng', 0):.6f}\n")
                f.write(f"   Distance:   {(r.get('coherence') or {}).get('distance_m', 0):.0f}m\n\n")
    
    print(f"📄 Rapport: {txt_output}")
    
    print("\n" + "=" * 60)
    if stats['found'] > 0:
        print(f"🎉 {stats['found']} invaders localisés!")
        if stats['new_coords'] > 0:
            print(f"   🆕 Dont {stats['new_coords']} avec NOUVELLES coordonnées!")
    else:
        print("😔 Aucune localisation trouvée")
    print("=" * 60)


if __name__ == '__main__':
    main()
