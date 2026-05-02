#!/usr/bin/env python3
"""
Rigorous Vision Prompt — Prototype Étape 1.5
==============================================
Remplace le prompt Vision mono-étape actuel (qui demande directement une
adresse + niveau de confiance) par un pipeline en 2 étapes forcées :

  ÉTAPE A — EXTRACTION DES PREUVES (pas d'inférence)
    Vision doit ENUMÉRER les éléments visuels effectivement lisibles :
      - plaques de rue (texte exact)
      - numéros de rue
      - enseignes commerciales (texte exact)
      - panneaux métro/bus (nom de station)
      - autres indices (graffitis nommés, arrêts de bus, monuments)
    Si aucun élément lisible → liste vide, pas d'invention.

  ÉTAPE B — INFÉRENCE AU PLUS FIN NIVEAU SUPPORTÉ PAR LES PREUVES
    Granularité obligatoirement décroissante :
      EXACT_ADDRESS   : plaque de rue + numéro visibles et cohérents
      STREET          : plaque de rue visible, pas de numéro
      BLOCK           : ≥2 enseignes commerciales identifiables (non chaînes)
      ARRONDISSEMENT  : indices contextuels parisiens sans nom de rue
      PARIS_ONLY      : juste "ça ressemble à Paris"
      UNKNOWN         : pas assez d'indices

RÈGLE D'ABSTENTION :
  Si Vision ne peut pas justifier l'adresse proposée par AU MOINS un élément
  extrait à l'étape A, elle DOIT redescendre d'un cran (STREET → BLOCK etc.)
  plutôt que d'inventer.

Usage standalone (test avec une image) :
    python rigorous_vision_prompt.py --image path/to/invader.jpg
    python rigorous_vision_prompt.py --image path/to/invader.jpg --compare

Intégration dans harvester :
    from rigorous_vision_prompt import rigorous_vision_analyze
    result = rigorous_vision_analyze(client, image_path)
    # result = {
    #   "evidence": {...},
    #   "granularity": "STREET",
    #   "address": "Rue de Turenne, 75003 Paris",
    #   "confidence": "HIGH",
    #   "abstained": False,
    #   "reasoning": "..."
    # }
"""

import os
import sys
import json
import base64
import argparse
import hashlib
import urllib.request
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("⚠️  pip install anthropic requis")
    raise


# ─── Cache images distantes ────────────────────────────────────────────────

IMG_CACHE = Path.home() / ".cache" / "invader_images"
IMG_CACHE.mkdir(parents=True, exist_ok=True)


def download_image(url: str) -> str:
    """Télécharge l'URL dans le cache et retourne le chemin local."""
    h = hashlib.sha1(url.encode()).hexdigest()[:16]
    suffix = Path(url.split("?")[0]).suffix or ".jpg"
    cached = IMG_CACHE / f"{h}{suffix}"
    if cached.exists():
        return str(cached)
    print(f"  ⬇️  Téléchargement : {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        cached.write_bytes(resp.read())
    return str(cached)


# ─── Résolution Invader ID → chemin image ──────────────────────────────────

SCRIPT_DIR = Path(__file__).parent.resolve()

MASTER_FALLBACKS = [
    SCRIPT_DIR / "data" / "invaders_master.json",
    SCRIPT_DIR / "invaders_master.json",
    SCRIPT_DIR.parent / "data" / "invaders_master.json",
    Path.home() / "Desktop" / "space-invaders-db" / "data" / "invaders_master.json",
    Path.home() / "data" / "invaders_master.json",
]


def find_master_json():
    for p in MASTER_FALLBACKS:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"invaders_master.json introuvable. Testé : {[str(p) for p in MASTER_FALLBACKS]}"
    )


def resolve_image_path(invader_id: str):
    """
    Depuis un ID (ex 'PA_1228'), retourne (image_path_local, city).
    Cherche les clés usuelles : image_lieu, image_path, image_local_path, image_url.
    Si seulement une URL est dispo, tente de deviner le chemin local équivalent.
    """
    master = find_master_json()
    with open(master) as f:
        data = json.load(f)

    # data peut être {"PA_1228": {...}} ou [{"id": "PA_1228", ...}]
    if isinstance(data, dict):
        entry = data.get(invader_id)
    else:
        entry = next((e for e in data if e.get("id") == invader_id or
                      e.get("invader_id") == invader_id), None)
    if not entry:
        raise KeyError(f"Invader {invader_id} introuvable dans {master}")

    # Essaie plusieurs clés
    candidates = []
    for key in ("image_lieu", "image_path", "image_local_path", "local_image",
                "image_file", "image"):
        v = entry.get(key)
        if v:
            candidates.append(v)

    master_dir = master.parent
    repo_root = master_dir.parent  # data/ -> repo

    for c in candidates:
        # Cas URL distante
        if isinstance(c, str) and c.startswith(("http://", "https://")):
            local = download_image(c)
            return local, entry.get("city", "Paris")

        # Cas chemin local
        p = Path(c)
        if p.is_absolute() and p.exists():
            return str(p), entry.get("city", "Paris")
        for base in (master_dir, repo_root, SCRIPT_DIR, SCRIPT_DIR.parent):
            candidate = (base / c).resolve()
            if candidate.exists():
                return str(candidate), entry.get("city", "Paris")

    raise FileNotFoundError(
        f"Image pour {invader_id} introuvable. Clés testées : {candidates or '(aucune)'}"
    )


# ─── Prompt structuré avec abstention ──────────────────────────────────────

RIGOROUS_SYSTEM_PROMPT = """Tu es un géolocaliseur forensique. Ta mission est \
d'identifier où se trouve une mosaïque Space Invader à partir d'une photo, en \
suivant STRICTEMENT une procédure en 2 étapes.

═══ ÉTAPE A — EXTRACTION DES PREUVES OBSERVABLES ═══

Tu ne fais QUE lister ce que tes yeux voient effectivement sur l'image. \
Tu n'infères rien. Tu n'imagines rien. Tu ne complètes rien.

Catégories :
  1. street_plates      : plaques de rue bleues (Paris) ou autres. Texte EXACT \
                          lu sur la plaque. Si tu n'es pas sûr d'une lettre, \
                          marque-la [?]. Si aucune plaque n'est lisible → [].
  2. street_numbers     : numéros de rue (façades, au-dessus de portes). \
                          Texte EXACT.
  3. shop_signs         : enseignes commerciales (devantures, auvents). Texte \
                          EXACT. Distingue chaînes (Monoprix, Franprix...) et \
                          commerces indépendants.
  4. metro_bus_signs    : panneaux RATP/métro/bus. Nom de station EXACT.
  5. other_landmarks    : autres éléments textuels ou monumentaux clairement \
                          identifiables (église nommée, cinéma, etc.).
  6. architectural_clues: style haussmannien / moderne / brique / pavés / type \
                          de trottoir. Purement descriptif, pas une preuve \
                          d'adresse.

RÈGLE ABSOLUE : si aucun texte n'est lisible sur l'image, toutes les listes \
sauf architectural_clues doivent être VIDES. Ne JAMAIS supposer qu'une plaque \
de rue dit X parce que le quartier ressemble à X.

═══ ÉTAPE B — INFÉRENCE AU PLUS FIN NIVEAU JUSTIFIABLE ═══

À partir UNIQUEMENT des preuves de l'étape A, choisis la granularité \
maximale justifiable, en suivant l'échelle :

  EXACT_ADDRESS    : street_plates ET street_numbers visibles et cohérents.
                     → "12 Rue du Temple, 75003 Paris"
  STREET           : street_plates visible (même sans numéro).
                     → "Rue du Temple, 75003 Paris"
  BLOCK            : ≥2 shop_signs non-chaînes identifiables via recherche \
                     OU 1 metro_bus_signs, OU 1 landmark nommé.
                     → "Environs de [station/enseigne], 75003 Paris"
  ARRONDISSEMENT   : architectural_clues parisiens + 1 indice faible \
                     (chaîne, style de plaque, etc.).
                     → "75003 Paris"
  PARIS_ONLY       : style manifestement parisien, aucun indice de quartier.
                     → "Paris"
  UNKNOWN          : insuffisant pour situer même Paris.
                     → null

RÈGLE D'ABSTENTION CRITIQUE :
Si tu hésites entre deux niveaux, choisis TOUJOURS le moins précis. Une adresse \
inventée à 3 km de la réalité est BEAUCOUP plus nuisible qu'une granularité \
ARRONDISSEMENT correcte. Le système qui t'utilise sait gérer l'incertitude ; il \
ne sait PAS corriger tes hallucinations.

Le champ "confidence" reflète ta certitude à la granularité choisie :
  HIGH   : preuves textuelles directes et non ambiguës.
  MEDIUM : preuves indirectes mais cohérentes (enseigne + style urbain).
  LOW    : inférence par recoupement fragile.

═══ FORMAT DE SORTIE ═══

Réponds UNIQUEMENT en JSON strict, sans préambule, sans markdown :

{
  "evidence": {
    "street_plates": [],
    "street_numbers": [],
    "shop_signs": [],
    "metro_bus_signs": [],
    "other_landmarks": [],
    "architectural_clues": []
  },
  "granularity": "EXACT_ADDRESS|STREET|BLOCK|ARRONDISSEMENT|PARIS_ONLY|UNKNOWN",
  "address": "<adresse au niveau de granularité choisi, ou null si UNKNOWN>",
  "confidence": "HIGH|MEDIUM|LOW",
  "reasoning": "<2-3 phrases expliquant quelles preuves justifient la granularité choisie>",
  "abstained_from_higher": "<si tu as choisi un niveau moins précis qu'une lecture naïve suggérerait, explique pourquoi ; sinon null>"
}"""


# ─── Helpers ────────────────────────────────────────────────────────────────

def img_to_b64(path: str):
    suffix = Path(path).suffix.lower()
    mt = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
    }.get(suffix, "image/jpeg")
    with open(path, "rb") as f:
        return mt, base64.standard_b64encode(f.read()).decode()


def rigorous_vision_analyze(client, image_path: str, city_hint: str = "Paris"):
    """
    Analyse une image d'Invader avec le prompt structuré.
    Retourne dict parsé ou dict avec 'parse_error' si JSON invalide.
    """
    mt, b64 = img_to_b64(image_path)

    user_msg = (
        f"Image d'une mosaïque Space Invader, probablement à {city_hint}. "
        f"Applique la procédure en 2 étapes et réponds en JSON strict."
    )

    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1500,
        system=RIGOROUS_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": mt, "data": b64}},
                {"type": "text", "text": user_msg},
            ],
        }],
    )
    text = resp.content[0].text.strip()

    # Parsing robuste
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        parsed = json.loads(text[start:end])
        # Normalise abstained flag
        parsed["abstained"] = bool(parsed.get("abstained_from_higher"))
        return parsed
    except Exception as e:
        return {"parse_error": str(e), "raw": text}


# ─── Prompt naïf pour comparaison A/B ──────────────────────────────────────

NAIVE_SYSTEM_PROMPT = """Tu es un expert en géolocalisation. Identifie \
l'adresse précise de cette mosaïque Space Invader à Paris. Réponds en JSON :
{"address": "...", "confidence": "HIGH|MEDIUM|LOW"}"""


def naive_vision_analyze(client, image_path: str):
    """Prompt de référence style harvest actuel, pour A/B test."""
    mt, b64 = img_to_b64(image_path)
    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=500,
        system=NAIVE_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": mt, "data": b64}},
                {"type": "text", "text": "Quelle est l'adresse ?"},
            ],
        }],
    )
    text = resp.content[0].text.strip()
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        return json.loads(text[start:end])
    except Exception:
        return {"raw": text}


# ─── CLI ───────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--invader", help="ID Invader (résout l'image via invaders_master.json)")
    p.add_argument("--image", help="Chemin direct vers l'image (ou URL)")
    p.add_argument("--batch", help="Fichier texte avec un ID Invader par ligne")
    p.add_argument("--compare", action="store_true",
                   help="Compare prompt rigoureux vs prompt naïf")
    p.add_argument("--city", default="Paris")
    args = p.parse_args()

    if not (args.invader or args.image or args.batch):
        p.error("Précisez --invader, --image ou --batch")

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY manquante")
        sys.exit(1)

    client = anthropic.Anthropic()

    # Mode batch : fichier avec plusieurs IDs
    if args.batch:
        ids = [l.strip() for l in open(args.batch) if l.strip() and not l.startswith("#")]
        results = []
        for iid in ids:
            try:
                img_path, city = resolve_image_path(iid)
                r = rigorous_vision_analyze(client, img_path, city)
                r["invader_id"] = iid
                results.append(r)
                print(f"[{iid}] granularité={r.get('granularity')} "
                      f"address={r.get('address')} conf={r.get('confidence')} "
                      f"abstained={r.get('abstained')}")
            except Exception as e:
                print(f"[{iid}] ❌ {e}")
        out = Path("rigorous_batch_results.json")
        out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        print(f"\n✅ {len(results)} résultats → {out}")
        return

    # Mode single
    if args.invader:
        img_path, city = resolve_image_path(args.invader)
        print(f"📁 Image résolue : {img_path}")
    else:
        if args.image.startswith(("http://", "https://")):
            img_path = download_image(args.image)
        else:
            img_path = args.image
        city = args.city

    print("═" * 60)
    print("🧠 PROMPT RIGOUREUX (Étape 1.5)")
    print("═" * 60)
    result = rigorous_vision_analyze(client, img_path, city)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if args.compare:
        print("\n" + "═" * 60)
        print("📏 PROMPT NAÏF (baseline actuel)")
        print("═" * 60)
        naive = naive_vision_analyze(client, img_path)
        print(json.dumps(naive, indent=2, ensure_ascii=False))

        print("\n" + "═" * 60)
        print("📊 DIFF")
        print("═" * 60)
        print(f"Naïf      : {naive.get('address', '?')} (conf={naive.get('confidence', '?')})")
        print(f"Rigoureux : {result.get('address', '?')} "
              f"(granularité={result.get('granularity', '?')}, "
              f"conf={result.get('confidence', '?')}, "
              f"abstained={result.get('abstained', False)})")


if __name__ == "__main__":
    main()
