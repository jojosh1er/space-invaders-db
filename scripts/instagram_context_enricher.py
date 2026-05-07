#!/usr/bin/env python3
"""
Instagram Context Enricher — Prototype Étape 2
================================================
Enrichit le géocodage d'un Invader en récupérant des photos contextuelles
postées par la communauté chasseur sur Instagram, puis en les passant à
Claude Vision en multi-image pour corroboration croisée.

Pipeline pour un Invader_id (ex. PA_1228):
  1. Charge credentials depuis ~/.invader_secrets/.env
  2. Login Instagram via instagrapi (session pickle pour éviter re-login)
  3. Throttling agressif (1 req/30s) pour limiter risque de ban
  4. Recherche hashtag #PA_1228
  5. Télécharge top 5 posts (photos + légende + géotag si présent)
  6. Cache disque: ~/.cache/invader_instagram/PA_1228/
  7. Appel Claude Vision multi-image avec prompt de corroboration:
       "Voici l'image officielle + N photos contextuelles. Identifie
        plaques de rue, enseignes, panneaux métro visibles. Corrobore
        entre images avant de proposer une adresse."
  8. Retourne dict enrichi avec:
       - adresse proposée (avec confiance recalibrée)
       - géotags instagram s'ils existent (signal direct)
       - nombre de sources corroborantes

Usage:
    # Test login (crée session.pkl la 1re fois)
    python instagram_context_enricher.py --login-test

    # Test sur un Invader
    python instagram_context_enricher.py --invader PA_1228 \
        --official-image path/to/invader_official.jpg

    # Vider cache d'un Invader pour re-scraper
    python instagram_context_enricher.py --clear PA_1228
"""

import os
import sys
import json
import time
import random
import pickle
import shutil
import argparse
import base64
import requests
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired, ChallengeRequired
except ImportError:
    print("⚠️  pip install python-dotenv instagrapi anthropic requis")
    raise

try:
    import anthropic
except ImportError:
    anthropic = None  # Vision step facultatif pour tests de scraping seul

# ─── Config ────────────────────────────────────────────────────────────────

SECRETS_PATH = Path.home() / ".invader_secrets" / ".env"
SESSION_PATH = Path.home() / ".invader_secrets" / "ig_session.pkl"
CACHE_ROOT = Path.home() / ".cache" / "invader_instagram"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)

# Throttle : plages aléatoires pour éviter la détection de pattern régulier.
# Instagram détecte les délais fixes (30s, 30s, 30s…) comme signature de bot.
THROTTLE_MIN = 25           # secondes minimum entre requêtes Instagram
THROTTLE_MAX = 55           # secondes maximum (moyenne ~40s)
MAX_POSTS_PER_INVADER = 5   # Limite téléchargements
LAST_REQUEST_TIME = [0.0]   # liste mutable = "variable globale throttle"

# Chemin master JSON (cherché relativement au script, puis dans data/)
MASTER_CANDIDATES = [
    Path(__file__).parent.parent / "data" / "invaders_master.json",
    Path(__file__).parent / "data" / "invaders_master.json",
    Path(__file__).parent / "invaders_master.json",
]

# geo_source qui signifient "mal localisé, candidat Instagram"
RETRY_LOW_CONFIDENCE_SOURCES = frozenset({
    'vision', 'instagram_geotag', 'instagram_vision',
    'ocr', 'city_center', 'vision_district', 'community_issue',
})
RETRY_LOW_CONFIDENCE_LEVELS = frozenset({'low', 'medium'})

NEEDS_INSTAGRAM_SOURCES = frozenset({
    'city_center', 'vision_district', None, 'unknown', ''
})

load_dotenv(SECRETS_PATH)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance en km entre deux points GPS (formule de Haversine)."""
    import math
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(min(1.0, math.sqrt(a)))


def throttle():
    """
    Pause aléatoire entre requêtes Instagram.
    Délai variable (THROTTLE_MIN..THROTTLE_MAX) + micro-jitter (<2s)
    pour éviter la détection de pattern régulier par Instagram.
    """
    elapsed = time.time() - LAST_REQUEST_TIME[0]
    # Délai cible : aléatoire dans la plage + jitter sous-seconde
    target = random.uniform(THROTTLE_MIN, THROTTLE_MAX) + random.random() * 1.8
    wait = max(0.0, target - elapsed)
    if wait > 0.5:
        print(f"  ⏳ pause {wait:.0f}s…")
        # Découper en petits sleeps pour permettre Ctrl+C
        deadline = time.time() + wait
        while time.time() < deadline:
            time.sleep(min(5.0, deadline - time.time()))
    LAST_REQUEST_TIME[0] = time.time()


# ─── Session Instagram ─────────────────────────────────────────────────────

def get_client() -> Client:
    """
    Retourne un client instagrapi authentifié.
    Priorité : IG_SESSION_ID (cookie navigateur) > session.pkl > username/password.

    IG_SESSION_ID est la méthode recommandée : copier la valeur du cookie
    sessionid depuis Chrome DevTools → Application → Cookies → instagram.com.
    """
    cl = Client()
    cl.delay_range = [4, 12]  # délai interne instagrapi (aléatoire)

    # ── Priorité 1 : sessionid cookie (contourne blacklist IP) ────────────
    session_id = os.getenv("IG_SESSION_ID")
    if session_id:
        # Décoder l'URL encoding si nécessaire (%3A → :)
        from urllib.parse import unquote
        session_id = unquote(session_id)
        try:
            cl.login_by_sessionid(session_id)
            # Validation légère via l'API web (compatible sessionid navigateur)
            # get_timeline_feed() appelle l'API mobile privée → incompatible
            user_id = cl.user_id_from_username("instagram")  # compte public
            print(f"  🔐 Connecté via sessionid cookie (user_id={cl.user_id})")
            with open(SESSION_PATH, "wb") as f:
                pickle.dump(cl.get_settings(), f)
            os.chmod(SESSION_PATH, 0o600)
            return cl
        except Exception as e:
            print(f"  ⚠️  sessionid invalide ou expiré ({e})")
            print("     → Recopie un sessionid frais depuis Chrome DevTools")
            raise

    # ── Priorité 2 : session pickle sauvegardée ────────────────────────────
    if SESSION_PATH.exists():
        try:
            with open(SESSION_PATH, "rb") as f:
                cl.set_settings(pickle.load(f))
            cl.user_id_from_username("instagram")  # validation légère
            print("  🔐 Session Instagram réutilisée (pickle)")
            return cl
        except (LoginRequired, Exception) as e:
            print(f"  ⚠️  Session pickle invalide ({e}), supprimée")
            SESSION_PATH.unlink(missing_ok=True)

    # ── Priorité 3 : username / password (risque blacklist IP) ────────────
    username = os.getenv("IG_USERNAME")
    password = os.getenv("IG_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            f"Aucune méthode d'auth disponible.\n"
            f"Ajoute IG_SESSION_ID dans {SECRETS_PATH}\n"
            f"(copie le cookie sessionid depuis Chrome DevTools)"
        )
    try:
        cl.login(username, password)
    except ChallengeRequired:
        print("  ❌ Challenge Instagram détecté — résous-le dans l'app puis relance")
        raise

    with open(SESSION_PATH, "wb") as f:
        pickle.dump(cl.get_settings(), f)
    os.chmod(SESSION_PATH, 0o600)
    print("  🔐 Nouvelle session Instagram créée (username/password)")
    return cl


# ─── Scraping hashtag ──────────────────────────────────────────────────────

def _web_search_hashtag(session_id: str, hashtag: str, limit: int):
    """
    Recherche les posts d'un hashtag via l'API web Instagram (sessionid cookie).
    Contourne les restrictions de l'API mobile privée utilisée par instagrapi.
    Retourne liste de dicts bruts Instagram.
    """
    import urllib.parse

    session = requests.Session()
    session_id_clean = urllib.parse.unquote(session_id)

    # Cookies web Instagram
    session.cookies.set("sessionid", session_id_clean, domain=".instagram.com")

    # Headers simulant Chrome sur Mac
    _USER_AGENTS = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    ]
    session.headers.update({
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "*/*",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "X-IG-App-ID": "936619743392459",   # Instagram Web App ID (stable)
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://www.instagram.com/explore/tags/{hashtag}/",
        "Origin": "https://www.instagram.com",
    })

    # Récupérer csrftoken depuis la page d'accueil Instagram.
    # Instagram ne le retourne pas systématiquement au premier appel — on retry
    # jusqu'à CSRF_RETRIES fois avec un délai croissant.
    CSRF_RETRIES = 3
    CSRF_RETRY_URLS = [
        "https://www.instagram.com/",
        "https://www.instagram.com/explore/",
        f"https://www.instagram.com/explore/tags/{hashtag}/",
    ]
    csrf = ""
    for attempt in range(CSRF_RETRIES):
        try:
            url = CSRF_RETRY_URLS[attempt % len(CSRF_RETRY_URLS)]
            if attempt > 0:
                wait = random.uniform(8, 20) * attempt
                print(f"  🔄 CSRF retry {attempt}/{CSRF_RETRIES-1} ({wait:.0f}s)…")
                time.sleep(wait)
            resp = session.get(url, timeout=15, allow_redirects=True)
            csrf = session.cookies.get("csrftoken", "")
            if not csrf:
                for h in resp.headers.get("set-cookie", "").split(";"):
                    if "csrftoken=" in h:
                        csrf = h.split("csrftoken=")[-1].strip()
                        break
            if csrf:
                session.headers["X-CSRFToken"] = csrf
                prefix = f" (attempt {attempt+1})" if attempt > 0 else ""
                print(f"  🔑 csrftoken: {csrf[:12]}…{prefix}")
                break
        except Exception as e:
            print(f"  ⚠️  CSRF fetch échoué (attempt {attempt+1}): {e}")
    if not csrf:
        print("  ⚠️  csrftoken introuvable après {CSRF_RETRIES} tentatives — les POST risquent d'échouer")

    # API sections — requiert POST (pas GET) avec body form-encoded
    medias = []
    for tab in ("top", "recent"):
        if len(medias) >= limit:
            break
        try:
            time.sleep(random.uniform(1.5, 4.0))
            resp = session.post(
                f"https://i.instagram.com/api/v1/tags/{hashtag}/sections/",
                data={
                    "tab": tab,
                    "page": 1,
                    "count": limit * 2,
                    "include_persistent": "0",
                    "surface": "grid",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=20,
            )
            print(f"  ℹ️  API sections {tab}: HTTP {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                for section in data.get("sections", []):
                    for layout_content in section.get("layout_content", {}).get("medias", []):
                        m = layout_content.get("media", {})
                        if m:
                            medias.append(m)
                            if len(medias) >= limit * 2:
                                break
            elif resp.status_code in (400, 401, 403):
                print(f"     Réponse: {resp.text[:200]}")
        except Exception as e:
            print(f"  ⚠️  API sections {tab} échouée: {e}")

    return medias[:limit * 2]


def _download_image_url(url: str, dest_path: Path) -> bool:
    """Télécharge une image depuis une URL Instagram vers dest_path."""
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if resp.status_code == 200:
            dest_path.write_bytes(resp.content)
            return True
    except Exception as e:
        print(f"  ⚠️  Download échoué ({url[:60]}…): {e}")
    return False


def fetch_invader_posts(cl: Client, invader_id: str, limit: int = MAX_POSTS_PER_INVADER):
    """
    Recherche #PA_1228 via l'API web Instagram (sessionid cookie).
    Retourne liste de dicts: {media_id, caption, image_path, geotag, likes}
    """
    cache_dir = CACHE_ROOT / invader_id
    cache_meta = cache_dir / "posts.json"

    if cache_meta.exists():
        print(f"  💾 Cache hit: {invader_id}")
        with open(cache_meta) as f:
            return json.load(f)

    cache_dir.mkdir(parents=True, exist_ok=True)

    session_id = os.getenv("IG_SESSION_ID", "")
    hashtag = invader_id  # ex: PA_1228

    throttle()
    print(f"  🔎 Recherche #{hashtag} (API web)…")
    raw_medias = _web_search_hashtag(session_id, hashtag, limit)

    if not raw_medias:
        print(f"  ❌ Aucun post trouvé pour #{hashtag}")
        return []

    posts = []
    for m in raw_medias:
        if len(posts) >= limit:
            break

        # Seulement images fixes (media_type=1), pas reels (2) ni carrousel (8)
        if m.get("media_type") not in (1, 8):
            continue

        # URL image : image_versions2 > candidates (plus grande résolution)
        candidates = (
            m.get("image_versions2", {}).get("candidates", [])
            or (m.get("carousel_media", [{}])[0]
                 .get("image_versions2", {}).get("candidates", []))
        )
        if not candidates:
            continue
        img_url = candidates[0]["url"]  # première = meilleure résolution

        media_id = m.get("pk") or m.get("id", "")
        img_path = cache_dir / f"{media_id}.jpg"

        throttle()
        if not _download_image_url(img_url, img_path):
            continue

        # Géotag
        geotag = None
        loc = m.get("location")
        if loc:
            geotag = {
                "name": loc.get("name", ""),
                "lat": loc.get("lat"),
                "lng": loc.get("lng"),
                "address": loc.get("address"),
            }

        user = (m.get("user") or {}).get("username", "?")
        caption_node = (m.get("caption") or {})
        caption = (caption_node.get("text", "") if isinstance(caption_node, dict)
                   else str(caption_node))[:500]

        posts.append({
            "media_id": str(media_id),
            "caption": caption,
            "image_path": str(img_path),
            "geotag": geotag,
            "likes": m.get("like_count", 0),
            "user": user,
            "taken_at": m.get("taken_at"),
        })

    with open(cache_meta, "w") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)
    print(f"  ✅ {len(posts)} posts téléchargés et cachés")
    return posts


# ─── Claude Vision multi-image ─────────────────────────────────────────────

# Prompt rigoureux importé depuis rigorous_vision_prompt.py
# (2 étapes : extraction des preuves + inférence au plus fin niveau justifiable)
try:
    from rigorous_vision_prompt import RIGOROUS_SYSTEM_PROMPT
    _RIGOROUS_AVAILABLE = True
except ImportError:
    _RIGOROUS_AVAILABLE = False

# Prompt de corroboration multi-images — s'appuie sur RIGOROUS_SYSTEM_PROMPT
# comme system prompt et ajoute le contexte Instagram en user message.
INSTAGRAM_CORROBORATION_USER = """Tu reçois :
1. L'image officielle de la mosaïque #{invader_id} (source FlashInvaders)
2. {n_context} photo(s) contextuelle(s) postée(s) par la communauté chasseur \
   sur Instagram (hashtag #{invader_id})

Légendes Instagram (indice textuel, avec méfiance) :
{captions}

Géotags Instagram disponibles (signal fort si présents) :
{geotags}

CONSIGNES SUPPLÉMENTAIRES POUR LA CORROBORATION :
- Applique la procédure habituelle en 2 étapes (extraction preuves → inférence).
- Corrobore entre les images : un indice est plus fiable s'il apparaît sur \
  ≥2 photos. Note-le dans street_plates / shop_signs / other_landmarks.
- Si les photos Instagram ne montrent que la mosaïque en gros plan sans \
  contexte de rue, indique-le dans reasoning et baisse la granularité.
- Si un géotag Instagram est disponible, mentionne-le dans other_landmarks \
  et remonte la confiance d'un cran si cohérent avec les indices visuels.

Applique la procédure en 2 étapes et réponds en JSON strict."""


def img_to_b64(path: str) -> tuple[str, str]:
    """
    Retourne (media_type, base64) pour Claude API.
    Détecte le vrai format depuis les magic bytes plutôt que l'extension
    (les images Instagram sont souvent WebP renommées en .jpg).
    """
    with open(path, "rb") as f:
        raw = f.read()

    # Détection par magic bytes
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        mt = "image/webp"
    elif raw[:8] == b"\x89PNG\r\n\x1a\n":
        mt = "image/png"
    elif raw[:3] in (b"\xff\xd8\xff",):
        mt = "image/jpeg"
    elif raw[:4] in (b"GIF8",):
        mt = "image/gif"
    else:
        # Fallback sur l'extension
        suffix = Path(path).suffix.lower()
        mt = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/jpeg")

    return mt, base64.standard_b64encode(raw).decode()


def download_official_image(url_or_path: str, cache_dir: Path) -> str:
    """
    Retourne un chemin local vers l'image officielle.
    Si c'est une URL, télécharge dans cache_dir. Sinon retourne tel quel.
    """
    if url_or_path.startswith(("http://", "https://")):
        import hashlib
        h = hashlib.sha1(url_or_path.encode()).hexdigest()[:12]
        suffix = Path(url_or_path.split("?")[0]).suffix or ".jpg"
        dest = cache_dir / f"official_{h}{suffix}"
        if not dest.exists():
            print(f"  ⬇️  Téléchargement image officielle…")
            resp = requests.get(url_or_path,
                                headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
        return str(dest)
    return url_or_path


def analyze_with_vision(invader_id: str, official_image: str, posts: list, city_name: str = "Paris"):
    """Appel Claude multi-image avec corroboration croisée."""
    if anthropic is None:
        print("  ⚠️  anthropic package non installé — skip Vision")
        return None

    client = anthropic.Anthropic()

    # Résoudre l'image officielle (URL ou chemin local)
    cache_dir = CACHE_ROOT / invader_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    official_image = download_official_image(official_image, cache_dir)

    content = []
    # Image 1 : officielle
    mt, b64 = img_to_b64(official_image)
    content.append({"type": "text", "text": "Image officielle :"})
    content.append({
        "type": "image",
        "source": {"type": "base64", "media_type": mt, "data": b64},
    })

    # Images contextuelles
    captions_block = []
    geotags_block = []
    for i, p in enumerate(posts, 1):
        mt, b64 = img_to_b64(p["image_path"])
        content.append({"type": "text", "text": f"Photo contextuelle {i} (par @{p['user']}):"})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": mt, "data": b64},
        })
        if p["caption"]:
            captions_block.append(f"[{i}] {p['caption']}")
        if p["geotag"]:
            g = p["geotag"]
            if g.get('lat') is not None and g.get('lng') is not None:
                geotags_block.append(f"[{i}] {g['name']} ({float(g['lat']):.5f}, {float(g['lng']):.5f})")
            elif g.get('name'):
                geotags_block.append(f"[{i}] {g['name']} (coordonnées indisponibles)")

    # User message : contexte Instagram + instruction de corroboration
    user_text = INSTAGRAM_CORROBORATION_USER.format(
        n_context=len(posts),
        invader_id=invader_id,
        captions="\n".join(captions_block) or "(aucune légende exploitable)",
        geotags="\n".join(geotags_block) or "(aucun géotag)",
    )
    # Ajouter le contexte ville en tête du message
    user_text = (
        f"Contexte : cet invader se situe à {city_name}.\n"
        f"Adapte ta granularité à cette ville (pas à Paris).\n\n"
    ) + user_text
    content.append({"type": "text", "text": user_text})

    # System prompt : rigoureux si dispo, fallback minimaliste sinon
    system_prompt = (
        RIGOROUS_SYSTEM_PROMPT
        if _RIGOROUS_AVAILABLE
        else "Tu es un expert en géolocalisation. Réponds en JSON strict."
    )

    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1500,
        system=system_prompt,
        messages=[{"role": "user", "content": content}],
    )
    text = resp.content[0].text.strip()
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        parsed = json.loads(text[start:end])
        # Normalise le format rigoureux vers le format attendu par le reste du pipeline
        # Le prompt rigoureux retourne: evidence, granularity, address, confidence, reasoning
        # On garde tout + on ajoute les clés compatibles enricher
        parsed.setdefault("corroborated_indices",
            parsed.get("evidence", {}).get("street_plates", []) +
            parsed.get("evidence", {}).get("shop_signs", []) +
            parsed.get("evidence", {}).get("other_landmarks", [])
        )
        parsed.setdefault("used_geotag", bool(geotags_block))
        parsed["abstained"] = bool(parsed.get("abstained_from_higher"))
        return parsed
    except Exception:
        return {"raw": text, "parse_error": True}


# ─── CLI ───────────────────────────────────────────────────────────────────


# ─── Helpers master JSON ───────────────────────────────────────────────────

def find_master_json() -> Path:
    for p in MASTER_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"invaders_master.json introuvable. Testé : {[str(p) for p in MASTER_CANDIDATES]}"
    )


def load_master() -> list:
    with open(find_master_json(), encoding='utf-8') as f:
        data = json.load(f)
    return data if isinstance(data, list) else list(data.values())


def save_master(data: list, path: Path = None):
    if path is None:
        path = find_master_json()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))


def needs_retry(inv: dict, min_cache_age_days: int = 30) -> bool:
    """
    Retourne True si l'invader mérite un retry Instagram :
      - A déjà une localisation mais confiance low/medium
      - Son cache Instagram est absent ou plus vieux que min_cache_age_days
    """
    if inv.get('geo_source') not in RETRY_LOW_CONFIDENCE_SOURCES:
        return False
    if inv.get('geo_confidence') not in RETRY_LOW_CONFIDENCE_LEVELS:
        return False
    # Vérifier l'âge du cache
    cache_meta = CACHE_ROOT / inv['id'] / "posts.json"
    if not cache_meta.exists():
        return True
    try:
        age = (datetime.now().timestamp() - cache_meta.stat().st_mtime) / 86400
        return age >= min_cache_age_days
    except Exception:
        return True


def needs_instagram(inv: dict) -> bool:
    """
    Retourne True si l'invader mérite un passage Instagram.
    Deux cas :
      1. Mal localisé (city_center, vision_district, etc.)
      2. Géotag Instagram posé mais Vision pas encore faite
         (instagram_vision_pending=True)
    """
    return (
        inv.get('geo_source') in NEEDS_INSTAGRAM_SOURCES
        or inv.get('location_unknown') is True
        or inv.get('instagram_vision_pending') is True
    )


# ─── Mode batch ────────────────────────────────────────────────────────────

def run_batch(args):
    """
    --batch-missing : enrichit tous les invaders mal localisés.

    Pipeline par invader :
      1. Vérifie le filtre needs_instagram()
      2. Skips si déjà en cache Instagram (posts.json présent)
      3. Scrape Instagram → cache local
      4. Si posts trouvés + image_lieu dispo → appel Vision
      5. Écrit le résultat dans instagram_cache.json
      6. Si adresse corroborée → met à jour invaders_master.json

    Utilise --dry-run pour simuler sans modifier le master.
    Utilise --city CODE pour limiter à une ville.
    Utilise --limit N pour limiter le nombre d'invaders traités.
    """
    master = load_master()
    master_path = find_master_json()

    # Charger ou initialiser instagram_cache.json
    cache_json_path = master_path.parent / "instagram_cache.json"
    if cache_json_path.exists():
        with open(cache_json_path, encoding='utf-8') as f:
            ig_cache = json.load(f)
    else:
        ig_cache = {}

    # Filtrer les candidats
    if getattr(args, 'retry_low_confidence', False):
        min_age = getattr(args, 'min_cache_age_days', 30)
        candidates = [inv for inv in master if needs_retry(inv, min_age)]
        mode_label = f"retry low/medium confidence (cache >{min_age}j)"
    else:
        candidates = [inv for inv in master if needs_instagram(inv)]
        mode_label = "batch missing"

    if args.city:
        candidates = [inv for inv in candidates if inv.get('city') == args.city]
    if args.limit:
        candidates = candidates[:args.limit]

    print(f"\n📋 Mode : {mode_label}")
    print(f"📋 Candidats Instagram : {len(candidates)} invaders")
    if args.city:
        print(f"   (filtrés sur ville : {args.city})")
    if args.dry_run:
        print("   🔍 Mode dry-run — aucune modification")
    print()

    # En mode retry : purger le cache Instagram pour forcer re-scrape
    if getattr(args, 'retry_low_confidence', False) and not args.dry_run:
        purged = 0
        for inv in candidates:
            cache_meta = CACHE_ROOT / inv['id'] / "posts.json"
            if cache_meta.exists():
                cache_meta.unlink()
                purged += 1
        if purged:
            print(f"   🗑️  Cache purgé pour {purged} invaders → re-scrape Instagram")
    elif getattr(args, 'retry_low_confidence', False) and args.dry_run:
        print("   🔍 [dry-run] cache non purgé")

    cl = get_client()

    stats = {'total': len(candidates), 'skipped_cache': 0, 'no_posts': 0,
             'vision_ok': 0, 'updated_master': 0, 'errors': 0}

    # Index master par id pour mise à jour rapide
    master_index = {inv['id']: i for i, inv in enumerate(master)}

    # Construire city_centers depuis les flashinvaders du master (±median par ville)
    # Utilisé pour valider la cohérence géographique des géotags Instagram
    from collections import defaultdict
    import statistics
    _city_lats = defaultdict(list)
    _city_lngs = defaultdict(list)
    for inv in master:
        if inv.get('geo_source') == 'flashinvaders' and inv.get('lat') and inv.get('lng'):
            try:
                _city_lats[inv['city']].append(float(inv['lat']))
                _city_lngs[inv['city']].append(float(inv['lng']))
            except (ValueError, TypeError):
                pass
    city_centers_local = {
        city: (statistics.median(_city_lats[city]), statistics.median(_city_lngs[city]))
        for city in _city_lats if len(_city_lats[city]) >= 3
    }

    for inv in candidates:
        inv_id = inv['id']
        print(f"\n── {inv_id} ({inv.get('city','?')}) "
              f"[geo_source={inv.get('geo_source','None')}] ──")

        # Skip si déjà dans instagram_cache avec adresse corroborée
        if inv_id in ig_cache and ig_cache[inv_id].get('corroborated_street'):
            print(f"  💾 Déjà enrichi (cache) : {ig_cache[inv_id]['corroborated_street']}")
            stats['skipped_cache'] += 1
            continue

        # Scrape Instagram
        try:
            posts = fetch_invader_posts(cl, inv_id)
        except Exception as e:
            print(f"  ❌ Erreur scraping : {e}")
            stats['errors'] += 1
            continue

        if not posts:
            print(f"  📭 Aucun post Instagram trouvé")
            ig_cache[inv_id] = {
                'fetched_at': datetime.now().isoformat(),
                'posts_count': 0,
                'corroborated_street': None,
            }
            stats['no_posts'] += 1
            continue

        print(f"  📦 {len(posts)} posts — géotags : "
              f"{sum(1 for p in posts if p.get('geotag'))}")

        # Géotag direct disponible → signal fort, pas besoin de Vision
        direct_geotag = next(
            (p['geotag'] for p in posts
             if p.get('geotag') and p['geotag'].get('lat')),
            None
        )
        if direct_geotag and direct_geotag['lat']:
            gt_lat = direct_geotag.get('lat')
            gt_lng = direct_geotag.get('lng')
            coords_str = (f"{float(gt_lat):.5f}, {float(gt_lng):.5f}"
                          if gt_lat is not None and gt_lng is not None else "coords N/A")
            print(f"  📍 Géotag direct : {direct_geotag.get('name','?')} ({coords_str})")

        # Vision sur les photos Instagram (même si géotag présent)
        # Le géotag donne la zone, Vision affine jusqu'à la rue
        vision_result = None
        image_lieu = inv.get('image_lieu')
        if image_lieu and not args.no_vision:
            try:
                # Enrichir city_name avec le géotag si disponible
                city_ctx = inv.get('city', 'unknown')
                if direct_geotag and direct_geotag.get('name'):
                    city_ctx = f"{city_ctx} ({direct_geotag['name']})"
                vision_result = analyze_with_vision(inv_id, image_lieu, posts,
                    city_name=city_ctx)
                stats['vision_ok'] += 1
            except Exception as e:
                print(f"  ⚠️  Vision échouée : {e}")
                vision_result = None  # Pas de pending — Vision n'a pas tourné

        # Construire l'entrée cache
        entry = {
            'fetched_at': datetime.now().isoformat(),
            'posts_count': len(posts),
            'corroborated_street': None,
            'best_address': None,
            'confidence': None,
            'granularity': None,
            'direct_geotag': direct_geotag,
        }

        if vision_result and not vision_result.get('parse_error'):
            addr = vision_result.get('address')
            conf = vision_result.get('confidence')
            gran = vision_result.get('granularity')
            plates = (vision_result.get('evidence') or {}).get('street_plates', [])

            entry['best_address'] = addr
            entry['confidence'] = conf
            entry['granularity'] = gran
            entry['corroborated_street'] = plates[0] if plates else None

            print(f"  🧠 Vision → {gran} | {addr} | conf={conf}")
            if entry['corroborated_street']:
                print(f"  🪧  Plaque corroborée : {entry['corroborated_street']}")

        ig_cache[inv_id] = entry

        # Mettre à jour le master
        idx = master_index.get(inv_id)

        # Priorité 1 : géotag Instagram direct (coords précises du chasseur)
        # Importer CITY_MAX_RADIUS depuis geolocate_missing si dispo
        try:
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location("_geo", str(find_master_json().parent.parent / "scripts" / "geolocate_missing.py"))
            if _spec is None:
                raise ImportError
            _geo_mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_geo_mod)
            _city_max_radius = getattr(_geo_mod, 'CITY_MAX_RADIUS', {})
            _default_radius = getattr(_geo_mod, 'DEFAULT_CITY_RADIUS', 25000)
        except Exception:
            # Fallback si geolocate_missing non trouvé
            _city_max_radius = {
                'PA': 20000, 'LA': 30000, 'NY': 30000, 'LDN': 25000,
                'BT': 80000, 'GRTI': 80000, 'REUN': 50000,
                'FTBL': 10000, 'VRS': 10000,
            }
            _default_radius = 25000

        def _geotag_coherent(gt, city):
            """
            Vérifie que le géotag est dans le rayon attendu pour la ville.
            Utilise CITY_MAX_RADIUS de geolocate_missing (par ville) avec fallback 25km.
            """
            if not gt or not gt.get('lat') or not gt.get('lng'):
                return False
            gt_lat, gt_lng = float(gt['lat']), float(gt['lng'])
            if abs(gt_lat) < 0.001 and abs(gt_lng) < 0.001:
                return False
            center = city_centers_local.get(city)
            if not center:
                return True  # Ville sans flashinvaders de référence → on accepte
            dist_km = haversine_km(gt_lat, gt_lng, center[0], center[1])
            max_km = _city_max_radius.get(city, _default_radius) / 1000
            if dist_km > max_km:
                print(f"  ⚠️  Géotag rejeté : {dist_km:.0f}km du centre de {city} "
                      f"(max={max_km:.0f}km, lieu='{gt.get('name', '?')}')")
                return False
            return True

        geotag_usable = _geotag_coherent(direct_geotag, inv.get('city', ''))
        if geotag_usable and idx is not None:
            if not args.dry_run:
                master[idx]['lat'] = round(float(direct_geotag['lat']), 7)
                master[idx]['lng'] = round(float(direct_geotag['lng']), 7)
                master[idx]['geo_source'] = 'instagram_geotag'
                master[idx]['geo_confidence'] = 'medium'
                master[idx]['location_unknown'] = False
                master[idx]['geo_hint'] = direct_geotag.get('name', '')
                master[idx]['instagram_vision_pending'] = True  # Vision à faire
                stats['updated_master'] += 1
                _dlat = direct_geotag.get('lat')
                _dlng = direct_geotag.get('lng')
                _coords = (f"{float(_dlat):.5f}, {float(_dlng):.5f}"
                           if _dlat is not None and _dlng is not None else "N/A")
                print(f"  ✅ Master mis à jour → geo_source=instagram_geotag ({_coords}) [Vision pending]")
            else:
                _dlat = direct_geotag.get('lat')
                _dlng = direct_geotag.get('lng')
                _coords = (f"{float(_dlat):.5f}, {float(_dlng):.5f}"
                           if _dlat is not None and _dlng is not None else "N/A")
                print(f"  🔍 [dry-run] géotag direct → ({_coords})")

        # Priorité 2 : adresse Vision corroborée (plus précise que géotag si STREET+)
        # Vision tourne même si géotag présent — les deux se complètent :
        # géotag = zone probable, Vision = rue exacte dans cette zone
        if vision_result and not vision_result.get('parse_error') and idx is not None:
            gran = vision_result.get('granularity', '')
            conf = vision_result.get('confidence', '')
            addr = vision_result.get('address')
            # Accepter STREET+ avec HIGH/MEDIUM, ou BLOCK avec HIGH
            # Niveau 1 : STREET+ → override coords + geo_hint
            street_override = (
                gran in ('EXACT_ADDRESS', 'STREET') and conf in ('HIGH', 'MEDIUM')
            )
            # Niveau 2 : BLOCK HIGH/MED → upgrade confiance géotag + geo_hint
            block_corroborate = (
                gran == 'BLOCK' and conf in ('HIGH', 'MEDIUM')
            )
            # Niveau 3 : tout résultat non-null → au moins geo_hint
            hint_only = (
                addr and gran not in ('UNKNOWN', None)
                and not street_override and not block_corroborate
            )

            if street_override:
                if not args.dry_run:
                    master[idx]['geo_hint'] = addr
                    master[idx]['geo_source'] = 'instagram_vision'
                    master[idx]['geo_confidence'] = conf.lower()
                    master[idx]['location_unknown'] = False
                    master[idx].pop('instagram_vision_pending', None)
                    stats['updated_master'] += 1
                    print(f"  ✅ instagram_vision ({gran}) "
                          f"{'[écrase géotag]' if geotag_usable else ''}")
                else:
                    print(f"  🔍 [dry-run] STREET+ {gran}/{conf} → {addr}")

            elif block_corroborate:
                if not args.dry_run:
                    master[idx]['geo_hint'] = addr
                    master[idx].pop('instagram_vision_pending', None)
                    # Si Vision corrobore le géotag → upgrade confiance
                    if geotag_usable:
                        master[idx]['geo_confidence'] = 'high'
                        print(f"  ✅ BLOCK corrobore géotag → confiance upgradée HIGH")
                    else:
                        print(f"  ✅ BLOCK sans géotag → geo_hint posé")
                    stats['updated_master'] += 1
                else:
                    upgrade = "→ confiance HIGH" if geotag_usable else ""
                    print(f"  🔍 [dry-run] BLOCK {conf} {upgrade} → {addr}")

            elif hint_only:
                if not args.dry_run:
                    master[idx]['geo_hint'] = addr
                    master[idx].pop('instagram_vision_pending', None)
                    print(f"  ℹ️  geo_hint posé ({gran}/{conf}) → {addr}")
                else:
                    print(f"  🔍 [dry-run] hint seulement ({gran}/{conf}) → {addr}")

            elif not args.dry_run:
                master[idx].pop('instagram_vision_pending', None)
                print(f"  ℹ️  Vision {gran}/{conf} — aucune mise à jour")

        # Sauvegarder le cache Instagram après chaque invader
        if not args.dry_run:
            with open(cache_json_path, 'w', encoding='utf-8') as f:
                json.dump(ig_cache, f, indent=2, ensure_ascii=False)

    # Sauvegarder le master mis à jour
    if not args.dry_run and stats['updated_master'] > 0:
        save_master(master, master_path)
        print(f"\n💾 Master sauvegardé ({stats['updated_master']} modifications)")

    # Rapport final
    print(f"\n{'='*60}")
    print(f"📊 RAPPORT BATCH")
    print(f"{'='*60}")
    print(f"  Total candidats    : {stats['total']}")
    print(f"  Skippés (cache)    : {stats['skipped_cache']}")
    print(f"  Aucun post         : {stats['no_posts']}")
    print(f"  Vision OK          : {stats['vision_ok']}")
    print(f"  Master mis à jour  : {stats['updated_master']}")
    print(f"  Erreurs            : {stats['errors']}")
    if not args.dry_run:
        print(f"\n  📁 Cache Instagram : {cache_json_path}")

def main():
    p = argparse.ArgumentParser(
        description="Instagram Context Enricher — enrichissement géolocalisation Invaders"
    )
    p.add_argument("--login-test", action="store_true", help="Teste le login Instagram")
    p.add_argument("--invader", help="ID Invader unique (ex: PA_1228)")
    p.add_argument("--official-image", help="Image officielle (chemin local ou URL)")
    p.add_argument("--clear", help="Vide le cache Instagram pour cet ID")
    p.add_argument("--no-vision", action="store_true", help="Skip appel Claude Vision")
    # Mode batch
    p.add_argument("--batch-missing", action="store_true",
                   help="Enrichit tous les invaders mal localisés depuis invaders_master.json")
    p.add_argument("--city", help="Filtrer sur une ville (ex: PA, BGK, HK) — batch uniquement")
    p.add_argument("--limit", type=int, default=None,
                   help="Nombre max d'invaders à traiter — batch uniquement")
    p.add_argument("--dry-run", action="store_true",
                   help="Simule sans modifier master ni cache — batch uniquement")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Logs détaillés")
    p.add_argument("--retry-low-confidence", action="store_true",
                   help="Relance Instagram sur les invaders geo_confidence=low/medium")
    p.add_argument("--min-cache-age-days", type=int, default=30, dest="min_cache_age_days",
                   help="Age minimum du cache Instagram pour re-scraper (défaut: 30j)")
    args = p.parse_args()

    if args.batch_missing or args.retry_low_confidence:
        run_batch(args)
        return

    if args.clear:
        target = CACHE_ROOT / args.clear
        if target.exists():
            shutil.rmtree(target)
            print(f"✅ Cache vidé: {target}")
        return

    if args.login_test:
        cl = get_client()
        me = cl.account_info()
        print(f"✅ Connecté comme @{me.username}")
        return

    if not args.invader:
        p.print_help()
        return

    cl = get_client()
    posts = fetch_invader_posts(cl, args.invader)
    print(f"\n📦 {len(posts)} posts récupérés pour {args.invader}")
    for i, post in enumerate(posts, 1):
        geo = post.get("geotag")
        geo_str = f" @ {geo['name']}" if geo else ""
        print(f"  [{i}] @{post['user']} ({post['likes']} likes){geo_str}")
        print(f"      → {post['image_path']}")

    if args.no_vision:
        print("\n⏭️  Skip Vision (--no-vision)")
        return

    # Résoudre l'image officielle : --official-image ou fallback master JSON
    official_image = args.official_image
    if not official_image:
        try:
            master = load_master()
            inv = next((x for x in master if x.get('id') == args.invader), None)
            if inv:
                official_image = inv.get('image_lieu') or inv.get('image_invader')
                if official_image:
                    print(f"\n📖 image_lieu depuis master : {official_image[:70]}…")
        except Exception as e:
            print(f"\n⚠️  Impossible de lire le master : {e}")

    if not official_image:
        print("\n⏭️  Skip Vision (pas d'image — utilise --official-image)")
        return


    if not posts:
        print("\n❌ Aucun post — pas d'enrichissement possible")
        return

    print("\n🧠 Analyse Claude Vision multi-image…")
    result = analyze_with_vision(args.invader, official_image, posts)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # Mise à jour master si résultat utilisable
    if result and not result.get('parse_error'):
        _gran = result.get('granularity', '')
        _conf = result.get('confidence', '')
        _addr = result.get('address')
        _usable = (
            _gran in ('EXACT_ADDRESS', 'STREET', 'BLOCK')
            and _conf in ('HIGH', 'MEDIUM')
            and _addr
        )
        if _usable:
            try:
                _master = load_master()
                _master_path = find_master_json()
                _idx = next((i for i, x in enumerate(_master)
                             if x.get('id') == args.invader), None)
                if _idx is not None:
                    _master[_idx]['geo_hint'] = _addr
                    _master[_idx]['geo_source'] = 'instagram_vision'
                    _master[_idx]['geo_confidence'] = _conf.lower()
                    _master[_idx]['location_unknown'] = False
                    _master[_idx].pop('instagram_vision_pending', None)
                    # Géocoder l'adresse pour obtenir les coords GPS
                    _geo = None
                    try:
                        import importlib.util as _ilu2, pathlib as _pl2
                        _geo_path = _pl2.Path(__file__).parent / 'geolocate_missing.py'
                        if _geo_path.exists():
                            _spec2 = _ilu2.spec_from_file_location('_gm2', _geo_path)
                            _mod2 = _ilu2.module_from_spec(_spec2)
                            _spec2.loader.exec_module(_mod2)
                            _ocr = _mod2.ImageOCRAnalyzer(verbose=False)
                            city_code = args.invader.rsplit('_', 1)[0]
                            _geo = _ocr.geocode_address(_addr, city_code=city_code)
                    except Exception as _ge:
                        print(f'  ⚠️  Géocodage échoué : {_ge}')

                    if _geo and _geo.get('lat'):
                        _master[_idx]['lat'] = _geo['lat']
                        _master[_idx]['lng'] = _geo['lng']
                        _master[_idx]['address'] = _addr
                        _master[_idx]['geo_source'] = 'instagram_vision'
                        print(f'\n✅ Master mis à jour → {_gran}/{_conf}')
                        print(f'   📍 {_addr}')
                        print(f'   🌐 {_geo["lat"]:.6f}, {_geo["lng"]:.6f}')
                    else:
                        # Pas de coords → abaisser confiance pour que geolocate_missing
                        # --from-master reprenne cet invader (filtre instagram_hint_pending)
                        _master[_idx]['geo_confidence'] = 'medium'
                        print(f'\n✅ Master mis à jour → geo_hint posé (géocodage à faire)')
                        print(f'   📍 {_addr}')
                        print(f'   ⚠️  Coords GPS non disponibles — lance geolocate_missing --from-master')
                    # Mettre à jour instagram_cache.json pour que
                    # geolocate_missing puisse utiliser le résultat comme source 0
                    try:
                        _cache_path = _master_path.parent / 'instagram_cache.json'
                        _ig_cache = {}
                        if _cache_path.exists():
                            with open(_cache_path, encoding='utf-8') as _cf:
                                _ig_cache = json.load(_cf)
                        _ig_cache[args.invader] = {
                            'fetched_at': datetime.now().isoformat(),
                            'posts_count': len(posts),
                            'best_address': _addr,
                            'confidence': _conf,
                            'granularity': _gran,
                            'corroborated_street': (
                                result.get('evidence', {}).get('street_plates', [None])[0]
                                if result.get('evidence', {}).get('street_plates') else None
                            ),
                            'direct_geotag': None,
                        }
                        with open(_cache_path, 'w', encoding='utf-8') as _cf:
                            json.dump(_ig_cache, _cf, indent=2, ensure_ascii=False)
                        print(f'   📁 instagram_cache.json mis à jour')
                    except Exception as _ce:
                        print(f'   ⚠️  Cache Instagram non mis à jour : {_ce}')
                    save_master(_master, _master_path)
                else:
                    print(f'\n⚠️  {args.invader} non trouvé dans le master')
            except Exception as e:
                print(f'\n⚠️  Mise à jour master échouée : {e}')
        else:
            print(f'\n⏭️  Master non mis à jour ({_gran}/{_conf} insuffisant)')


if __name__ == "__main__":
    main()
