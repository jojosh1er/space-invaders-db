# Guide opératoire — Instagram Enricher (local)

## Vue d'ensemble

L'enrichissement Instagram se fait **uniquement en local** (ton Mac).  
GitHub Actions ne fait que lire le résultat (`data/instagram_cache.json`).

```
TON MAC                              GITHUB ACTIONS
──────────────────────────────────   ──────────────────────────────
instagram_context_enricher.py   →   geolocate_missing.py
  scrape Instagram                    lit instagram_cache.json
  → instagram_cache.json              comme source prioritaire
  → git push                          (0 appel Instagram)
```

---

## Prérequis

### Dépendances Python
```bash
pip3.11 install instagrapi anthropic python-dotenv requests rapidfuzz
```

### Fichier secrets
```bash
mkdir -p ~/.invader_secrets
# Créer/éditer ~/.invader_secrets/.env avec :
ANTHROPIC_API_KEY=sk-ant-...
IG_SESSION_ID=ton_sessionid_instagram  # voir ci-dessous
```

### Obtenir le sessionid Instagram
1. Ouvrir Chrome → [instagram.com](https://www.instagram.com) → se connecter
2. `Cmd+Option+I` → onglet **Application** → **Cookies** → `https://www.instagram.com`
3. Copier la valeur du cookie **`sessionid`**
4. Coller dans `~/.invader_secrets/.env` : `IG_SESSION_ID=valeur_copiée`

> ⚠️ Le sessionid expire (~90 jours ou à la déconnexion). À renouveler en cas d'erreur `login_required`.

---

## Workflow type

### 1. Vérifier le login
```bash
cd ~/Desktop/space-invaders-db/scripts
python3.11 instagram_context_enricher.py --login-test
# Résultat attendu : ✅ Connecté comme @ton_username
```

### 2. Enrichir les nouveaux invaders mal localisés
```bash
# Dry-run d'abord : voir combien d'invaders sont candidats
python3.11 instagram_context_enricher.py --batch-missing --dry-run -v

# Run réel (prévoir ~4 min/invader avec le throttle)
python3.11 instagram_context_enricher.py --batch-missing -v
```

### 3. Enrichir une ville spécifique
```bash
# Par exemple HK ou BGK
python3.11 instagram_context_enricher.py --batch-missing --city HK -v
```

### 4. Tester un invader précis (avec Vision)
```bash
python3.11 instagram_context_enricher.py \
  --invader PA_1228 \
  --official-image https://www.invader-spotter.art/photos/PA/PA_1228-septembre2016.jpg
```

### 5. Relancer les invaders low/medium confidence
Relance les invaders déjà traités mais avec une localisation fragile,  
si leur cache Instagram a plus de 30 jours (nouveaux posts possibles).
```bash
# Dry-run
python3.11 instagram_context_enricher.py --retry-low-confidence --dry-run -v

# Run réel
python3.11 instagram_context_enricher.py --retry-low-confidence -v

# Relance plus agressive (cache > 7 jours)
python3.11 instagram_context_enricher.py --retry-low-confidence --min-cache-age-days 7
```

### 6. Vider le cache d'un invader (forcer re-scrape)
```bash
python3.11 instagram_context_enricher.py --clear PA_1228
```

---

## Passe de géocodage local (après enrichment Instagram)

Après `--batch-missing`, certains invaders ont une adresse dans `geo_hint`  
mais pas encore de coordonnées GPS précises (Vision GitHub a trouvé `vision_district`,  
Instagram a affiné en `instagram_vision` avec une rue textuelle).  

Lance une passe locale pour géocoder ces `geo_hint` :

```bash
cd ~/Desktop/space-invaders-db/scripts

# Voir combien d'invaders ont un geo_hint à géocoder
python3 -c "
import json
db = json.load(open('../data/invaders_master.json'))
pending = [inv for inv in db 
           if inv.get('geo_hint') 
           and inv.get('geo_source') in ('instagram_vision', 'instagram_geotag')
           and inv.get('geo_confidence') in ('medium', 'low')
           and not inv.get('geo_search_exhausted')]
print(f'{len(pending)} invaders avec geo_hint à géocoder')
for inv in pending[:10]:
    print(f'  {inv["id"]:12s} {inv.get("geo_hint","")[:60]}')
"

# Géocoder via geolocate_missing
# Le filtre --from-master capte automatiquement instagram_vision/geotag + geo_hint + confidence=medium/low
python3 geolocate_missing.py --from-master --no-browser --verbose

# Fusionner les résultats
if [ -f ../data/invaders_relocalized.json ]; then
  python3 geolocate_missing.py --merge ../data/invaders_relocalized.json
fi
```
> Cette passe utilise Nominatim + fuzzy Overpass pour convertir  
> le `geo_hint` textuel en coordonnées GPS précises dans le master.

---

## Après le run : commit & push

```bash
cd ~/Desktop/space-invaders-db

git add data/invaders_master.json \
        data/instagram_cache.json

git commit -m "feat(instagram): enrichissement $(date +%Y-%m-%d)

$(python3 -c "
import json
cache = json.load(open('data/instagram_cache.json'))
enriched = sum(1 for v in cache.values() if v.get('corroborated_street') or v.get('best_address'))
print(f'{len(cache)} invaders traités, {enriched} avec adresse corroborée')
")"

git push
```

GitHub Actions détectera le push et relancera `geolocate_missing.py`  
qui lira automatiquement `instagram_cache.json` comme **source 0**.

---

## Cadence recommandée

| Action | Fréquence | Durée estimée |
|---|---|---|
| `--login-test` | À chaque session | < 5s |
| `--batch-missing` | Après chaque run GitHub Actions | 5-60 min selon nb candidats |
| `--retry-low-confidence` | 1×/mois | 1-4h (67 invaders max) |
| Renouveler `IG_SESSION_ID` | Tous les ~90 jours | 2 min |

---

## Filtres candidats Instagram

Un invader est candidat `--batch-missing` si :
- `geo_source` ∈ `city_center`, `vision_district`, `unknown` ou absent
- `location_unknown = true`
- `instagram_vision_pending = true` (géotag posé, Vision pas encore faite)

Un invader est candidat `--retry-low-confidence` si :
- `geo_source` ∈ `vision`, `instagram_geotag`, `instagram_vision`, `city_center`…
- `geo_confidence` ∈ `low`, `medium`
- Cache Instagram absent ou âgé de plus de `--min-cache-age-days` jours

---

## Ce que produit le script

### `data/instagram_cache.json`
```json
{
  "PA_1228": {
    "fetched_at": "2026-05-02T11:30:00",
    "posts_count": 5,
    "corroborated_street": "RUE WATTEAU",
    "best_address": "Rue Watteau, 75013 Paris",
    "confidence": "HIGH",
    "granularity": "STREET",
    "direct_geotag": null
  },
  "BGK_46": {
    "fetched_at": "2026-05-02T14:15:00",
    "posts_count": 5,
    "corroborated_street": null,
    "best_address": "Charan Sanitwong / Bang Phlat, Bangkok",
    "confidence": "MEDIUM",
    "granularity": "BLOCK",
    "direct_geotag": {"lat": 13.75222, "lng": 100.49389, "name": "Bangkok"}
  }
}
```

### `data/invaders_master.json` (champs mis à jour)
| Champ | Valeur possible | Signification |
|---|---|---|
| `geo_source` | `instagram_geotag` | Coordonnées du géotag Instagram |
| `geo_source` | `instagram_vision` | Adresse Vision corroborée par Instagram |
| `geo_confidence` | `high` / `medium` | Confiance de la localisation |
| `geo_hint` | `"Rue Watteau, 75013"` | Adresse textuelle pour debug |
| `instagram_vision_pending` | `true` | Géotag posé, Vision encore à faire |

---

## Dépannage

### `login_required` au login-test
→ Le sessionid a expiré. Recopier un nouveau depuis Chrome DevTools.

### `CSRF token missing` sur la recherche hashtag
→ Instagram n'a pas servi le cookie. Le script retry 3× automatiquement.  
Si ça persiste : attendre 30 min et relancer.

### `unsupported format string passed to NoneType`
→ Un géotag Instagram a un nom de lieu mais sans coordonnées GPS.  
Déjà corrigé dans la version courante.

### Instagram suspect d'utilisation automatisée
→ Stopper le script, attendre 2h minimum, puis relancer.  
Le throttle aléatoire (25-55s) minimise ce risque.

### Vision échoue (`credit balance too low`)
→ Recharger les crédits sur [console.anthropic.com](https://console.anthropic.com) → Plans & Billing.
