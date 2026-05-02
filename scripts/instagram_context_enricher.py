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

THROTTLE_SEC = 30           # 1 requête / 30s (conservateur)
MAX_POSTS_PER_INVADER = 5   # Limite téléchargements
LAST_REQUEST_TIME = [0.0]   # liste mutable = "variable globale throttle"

load_dotenv(SECRETS_PATH)


def throttle():
    """Garantit un délai minimum entre requêtes Instagram."""
    elapsed = time.time() - LAST_REQUEST_TIME[0]
    if elapsed < THROTTLE_SEC:
        wait = THROTTLE_SEC - elapsed
        print(f"  ⏳ throttle: attente {wait:.0f}s")
        time.sleep(wait)
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
    cl.delay_range = [3, 7]

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
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "X-IG-App-ID": "936619743392459",   # Instagram Web App ID (stable)
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://www.instagram.com/explore/tags/{hashtag}/",
        "Origin": "https://www.instagram.com",
    })

    # Récupérer csrftoken via une requête HEAD sur la page du hashtag
    try:
        head = session.get(
            f"https://www.instagram.com/explore/tags/{hashtag}/",
            timeout=15,
        )
        csrf = session.cookies.get("csrftoken", "")
        if csrf:
            session.headers["X-CSRFToken"] = csrf
    except Exception:
        pass

    # API sections — requiert POST (pas GET) avec body form-encoded
    medias = []
    for tab in ("top", "recent"):
        if len(medias) >= limit:
            break
        try:
            time.sleep(2)
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
    """Retourne (media_type, base64) pour Claude API."""
    suffix = Path(path).suffix.lower()
    mt = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
    }.get(suffix, "image/jpeg")
    with open(path, "rb") as f:
        return mt, base64.standard_b64encode(f.read()).decode()


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


def analyze_with_vision(invader_id: str, official_image: str, posts: list):
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
            geotags_block.append(f"[{i}] {g['name']} ({g['lat']:.5f}, {g['lng']:.5f})")

    # User message : contexte Instagram + instruction de corroboration
    user_text = INSTAGRAM_CORROBORATION_USER.format(
        n_context=len(posts),
        invader_id=invader_id,
        captions="\n".join(captions_block) or "(aucune légende exploitable)",
        geotags="\n".join(geotags_block) or "(aucun géotag)",
    )
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

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--login-test", action="store_true", help="Teste login only")
    p.add_argument("--invader", help="ID Invader (ex: PA_1228)")
    p.add_argument("--official-image", help="Chemin image officielle FlashInvaders")
    p.add_argument("--clear", help="Vide le cache pour cet ID")
    p.add_argument("--no-vision", action="store_true", help="Skip appel Vision")
    args = p.parse_args()

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

    if args.no_vision or not args.official_image:
        print("\n⏭️  Skip Vision (pas d'image officielle ou --no-vision)")
        return

    if not posts:
        print("\n❌ Aucun post — pas d'enrichissement possible")
        return

    print("\n🧠 Analyse Claude Vision multi-image…")
    result = analyze_with_vision(args.invader, args.official_image, posts)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
