# 🛸 Space Invaders DB — Guide Complet d'Utilisation

## Vue d'ensemble

Le projet comprend 6 fichiers principaux, organisés en 3 couches :

```
┌─────────────────────────────────────────────────────────┐
│  COUCHE PRÉSENTATION                                    │
│  flask_app_V12.py    → API web (PythonAnywhere)         │
├─────────────────────────────────────────────────────────┤
│  COUCHE AUTOMATISATION                                  │
│  weekly_update.yml   → GitHub Actions (CI/CD)           │
│  send_notifications.py → Emails post-update             │
├─────────────────────────────────────────────────────────┤
│  COUCHE TRAITEMENT                                      │
│  geolocate_missing.py → Géolocalisation multi-sources   │
│  vision_ml_harvest.py → Collecte ML + évaluation        │
│  scoring_reliability.py → Scoring tier (legacy, intégré)│
└─────────────────────────────────────────────────────────┘
```

---

## 1. Installation

### Prérequis système

```bash
# Python 3.10+ requis
python3 --version

# Tesseract OCR (optionnel, pour l'analyse d'images)
sudo apt-get install tesseract-ocr tesseract-ocr-fra

# Playwright (optionnel, pour le scraping navigateur)
playwright install chromium
playwright install-deps
```

### Dépendances Python

```bash
# Dépendances essentielles
pip3 install requests Pillow pytesseract anthropic

# Google Lens (optionnel, expérimental)
pip3 install git+https://github.com/krishna2206/google-lens-python.git

# Pour le harvest ML
pip3 install anthropic

# Pour le scoring ML (optionnel, si utilisation du modèle pickle)
pip3 install scikit-learn numpy

# Pour l'app Flask
pip3 install flask

# Pour les notifications email
# Aucune dépendance externe (stdlib uniquement)
```

### Clés API nécessaires

| Clé | Variable d'environnement | Utilisée par | Obligatoire |
|-----|--------------------------|--------------|-------------|
| Anthropic (Claude) | `ANTHROPIC_API_KEY` | geolocate_missing, vision_ml_harvest | Pour Vision uniquement |
| GitHub PAT | `PAT_TOKEN` ou `GITHUB_TOKEN` | weekly_update.yml | Pour le scraping issues |
| SMTP Gmail | `SMTP_USERNAME` / `SMTP_PASSWORD` | send_notifications.py | Pour les emails |

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Structure de fichiers attendue

```
space-invaders-db/
├── data/
│   ├── invaders_master.json          # Base principale
│   ├── invaders_missing_from_github.json  # Invaders sans page GitHub
│   ├── invaders_changelog.json       # Historique des changements
│   └── metadata.json                 # Stats globales
├── scripts/
│   ├── geolocate_missing.py          # Géolocalisation
│   ├── vision_ml_harvest.py          # Collecte ML
│   ├── scoring_reliability.py        # Scoring (legacy)
│   ├── send_notifications.py         # Notifications
│   ├── update_from_spotter.py        # Scraping (non documenté ici)
│   └── requirements.txt
├── .github/workflows/
│   └── weekly_update.yml             # CI/CD
└── flask_app_V12.py                  # API web
```

---

## 2. geolocate_missing.py — Géolocalisation Multi-Sources

**Le script principal.** Cherche les coordonnées GPS des invaders via une cascade de sources : Pnote → EXIF → OCR Tesseract → Google Lens → Claude Vision.

### Modes d'exécution

#### Mode 1 : Depuis le master (production)

Géolocalise les invaders sans coordonnées ou avec coordonnées imprécises (centre-ville).

```bash
# Tous les invaders manquants
python3 geolocate_missing.py --from-master --pnote-url --no-browser

# Une ville spécifique
python3 geolocate_missing.py --from-master --city AMI --pnote-url --no-browser

# Limiter le nombre
python3 geolocate_missing.py --from-master --city PA --limit 10 --pnote-url --no-browser

# Mode verbeux (debug)
python3 geolocate_missing.py --from-master --city PA --limit 5 --pnote-url --no-browser -v
```

#### Mode 2 : Un seul invader

```bash
python3 geolocate_missing.py --id PA_1531 --pnote-url --no-browser -v
```

#### Mode 3 : Backtest (comparaison avec vérité terrain)

```bash
python3 geolocate_missing.py --backtest PA_142,NY_100,TK_30 --pnote-url --no-browser -v
```

#### Mode 4 : Interactif (saisie manuelle)

Quand toutes les sources automatiques échouent, le mode `-i` propose un fallback humain :
- Si l'image existe → Google Lens interactif (tu choisis parmi les résultats)
- Si pas d'image → saisie manuelle d'adresse (géocodée via Nominatim)

```bash
# Interactif sur une ville
python3 geolocate_missing.py --from-master --city BTA -i --pnote-url --no-browser

# Interactif sur un seul invader
python3 geolocate_missing.py --id BTA_16 -i --pnote-url --no-browser -v
```

Exemple de session :

```
   📝 SAISIE MANUELLE pour BTA_16
   ┌─────────────────────────────────────────────────────────────
   │ 🏙️ Ville: Bastia
   │ Pas d'image disponible pour Google Lens
   └─────────────────────────────────────────────────────────────
   Entrez l'adresse (ou Entrée pour centre-ville, 'skip', 'quit'):
   >>> 3 Boulevard Paoli, 20200 Bastia
   🗺️  Géocodage de: 3 Boulevard Paoli, 20200 Bastia...
   ✅ Trouvé: 42.697845, 9.450725
      📍 Boulevard Paoli, Bastia, Haute-Corse, France...
```

Commandes dans le prompt interactif :

| Commande | Action |
|----------|--------|
| `adresse libre` | Géocode via Nominatim (ajoute la ville automatiquement) |
| `Entrée` (vide) | Fallback centre-ville |
| `skip` | Passer cet invader |
| `quit` | Arrêter le mode interactif |

Si Nominatim ne trouve pas l'adresse, il propose de réessayer avec une autre formulation.
Le résultat est stocké avec `geo_source: "interactive"` et `geo_confidence: "medium"`.

#### Mode 5 : Relancer les échecs précédents

```bash
python3 geolocate_missing.py --from-master --retry-failed --pnote-url --no-browser
```

#### Mode 6 : Adresse directe (sans cascade)

Géocode une adresse manuellement et met à jour le master, sans passer par Pnote/EXIF/OCR/Vision :

```bash
# Géocoder et sauvegarder directement
python3 geolocate_missing.py --id PA_1556 --address "12 Rue de la Roquette, 75011 Paris"

# Avec backup du master
python3 geolocate_missing.py --id PA_1556 --address "12 Rue de la Roquette, 75011 Paris" --backup

# Dry-run (vérifier sans sauvegarder)
python3 geolocate_missing.py --id PA_1556 --address "12 Rue de la Roquette, 75011" --dry-run
```

Exemple de sortie :

```
📝 GÉOCODAGE MANUEL — PA_1556
   Adresse: 12 Rue de la Roquette, 75011 Paris
============================================================
   ✅ Coordonnées: 48.854321, 2.372456
   📍 Rue de la Roquette, Paris 11e, Île-de-France, France...
   📊 Ancien: 48.856614, 2.352222 (city_center) → Δ 1.53km

   ✅ PA_1556 mis à jour dans data/invaders_master.json
      geo_source: manual | geo_confidence: medium
```

Le résultat est stocké avec `geo_source: "manual"` et `geo_confidence: "medium"`.

#### Mode 7 : Fusion des résultats

```bash
# Après une géolocalisation, fusionner dans le master
python3 geolocate_missing.py --merge data/invaders_geolocated.json --backup
```

### Options complètes

| Option | Court | Défaut | Description |
|--------|-------|--------|-------------|
| `--from-master` | | | Géolocaliser depuis invaders_master.json |
| `--from-missing` | | | Géolocaliser depuis invaders_missing_from_github.json |
| `--merge FILE` | | | Fusionner un fichier de résultats dans le master |
| `--city CODE` | `-c` | toutes | Filtrer par ville (ex: PA, NY, LDN, TK) |
| `--limit N` | `-l` | illimité | Nombre max d'invaders à traiter |
| `--id CODE` | | | Un seul invader (ex: PA_1531) |
| `--verbose` | `-v` | off | Logs détaillés |
| `--output FILE` | `-o` | data/invaders_geolocated.json | Fichier de sortie |
| `--pnote-url` | | off | Télécharger les données pnote.eu (GPS ±10m) |
| `--pnote-file FILE` | | | Fichier pnote.eu local |
| `--no-browser` | | off | Sans navigateur (Pnote+EXIF+OCR+Lens+Vision) |
| `--no-flickr` | | off | Désactiver Flickr |
| `--no-lens` | | off | Désactiver Google Lens |
| `--anthropic-key KEY` | | env `ANTHROPIC_API_KEY` | Clé API Claude |
| `--vision-shots N` | | 3 | Nombre d'appels Vision par image (consensus) |
| `--retry-failed` | | off | Relancer les invaders marqués "exhausted" |
| `--backtest IDS` | | | Mode comparaison (IDs séparés par virgules) |
| `--address ADDR` | | | Géocoder directement une adresse (requiert --id) |
| `--interactive` | `-i` | off | Mode interactif : Google Lens manuel ou saisie d'adresse pour les non trouvés |
| `--visible` | | off | Afficher le navigateur (debug) |
| `--backup` | | off | Backup avant fusion |
| `--dry-run` | | off | Simuler sans sauvegarder |
| `--pause SEC` | | 1.0 | Pause entre requêtes |

### Cascade de sources (ordre de priorité)

```
1. Pnote.eu         → GPS exact (±10m), source communautaire
2. EXIF image_lieu   → GPS embarqué dans la photo (rare)
3. OCR Tesseract     → Lecture de texte dans l'image (plaques de rue)
4. Google Lens       → Reconnaissance visuelle + localisation
5. Claude Vision     → Analyse IA multi-shot (3 appels, consensus)
   ├─ Géocode adresse → Nominatim (OSM)
   ├─ Cross-validation quartier
   ├─ Raffinement intersection (midpoint 2 rues)
   └─ Tier scoring (HIGH/MEDIUM/LOW)
6. Interactif (-i)   → Google Lens manuel ou saisie d'adresse
7. Fallback district → Centroïde du quartier identifié
```

### Sortie

Le script produit `data/invaders_geolocated.json` avec pour chaque invader :

```json
{
  "id": "PA_1531",
  "lat": 48.8566,
  "lng": 2.3522,
  "geo_source": "vision",
  "geo_confidence": "high",
  "geo_tier_reason": "signs=2,dist=0.8km",
  "address": "15 Rue François Miron, 75004 Paris",
  "geo_hint": "intersection: Rue de Rivoli, 75004 Paris"
}
```

Valeurs possibles de `geo_source` :

| Source | Description | Confiance typique |
|--------|-------------|-------------------|
| `pnote` | GPS pnote.eu communautaire | high |
| `exif_image_lieu` | EXIF embarqué dans la photo | medium |
| `ocr` | Texte lu par Tesseract | medium |
| `google_lens` | Reconnaissance visuelle Google | medium |
| `vision` | Claude Vision (adresse géocodée) | high/medium/low (tier) |
| `vision_district` | Claude Vision (fallback quartier) | low |
| `interactive` | Saisie manuelle humaine (mode -i) | medium |
| `manual` | Adresse directe via --address | medium |
| `city_center` | Centroïde de la ville (fallback) | low |

### Tiers de confiance (ML-derived)

| Tier | Règle | Précision <1km | Erreur moyenne |
|------|-------|---------------|----------------|
| 🟢 HIGH | `street_signs ≥ 1` AND `distance_center < 3km` | 81% | 0.76 km |
| 🟡 MEDIUM | `confidence=HIGH` OR `has_postcode` OR `has_number` OR `signs ≥ 1` | 53% | 3.11 km |
| 🔴 LOW | Tout le reste | 37% | 3.29 km |

---

## 3. vision_ml_harvest.py — Collecte ML & Évaluation

**Script de benchmark.** Appelle Claude Vision sur un échantillon stratifié d'invaders dont on connaît la position exacte, pour mesurer la qualité du géocodage et entraîner le scoring.

### Commandes

```bash
# Harvest complet (200 samples, ~50 min, ~$2)
python3 vision_ml_harvest.py --n 200 -o features_full_v2.csv

# Test rapide (30 samples Paris, ~8 min)
python3 vision_ml_harvest.py --n 30 --cities PA -o features_test.csv

# Villes spécifiques
python3 vision_ml_harvest.py --n 50 --cities PA,NY,LDN -o features_3cities.csv

# Reprendre un harvest interrompu
python3 vision_ml_harvest.py --n 200 --resume features_partial.csv -o features_full.csv

# Seed différent (autre échantillon)
python3 vision_ml_harvest.py --n 200 --seed 123 -o features_seed123.csv

# Stats seules (pas de Vision, juste analyse du CSV)
python3 vision_ml_harvest.py --stats features_full_v2.csv
```

### Options complètes

| Option | Court | Défaut | Description |
|--------|-------|--------|-------------|
| `--n N` | | 200 | Nombre d'invaders à échantillonner |
| `--output FILE` | `-o` | vision_ml_features.csv | Fichier CSV de sortie |
| `--cities CODES` | | toutes | Villes à inclure (ex: PA,NY,LDN) |
| `--master FILE` | | data/invaders_master.json | Fichier master source |
| `--anthropic-key KEY` | | env `ANTHROPIC_API_KEY` | Clé API Claude |
| `--resume FILE` | | | Reprendre depuis un CSV partiel |
| `--stats FILE` | | | Afficher stats d'un CSV existant |
| `--seed N` | | 42 | Graine aléatoire (reproductibilité) |
| `--verbose` | `-v` | off | Logs détaillés |

### Sortie CSV

Chaque ligne = 1 invader avec ~35 features :

```
invader_id, city_code, points, gt_lat, gt_lng, gt_source,
confidence, n_street_signs, n_shop_signs, n_landmarks, n_building_numbers,
n_metro_bus, n_other_clues, n_total_clues, has_district, has_postcode,
has_address, reasoning_length, address_length, address_has_number,
address_has_business, address_n_business, signs_total_business,
geo_success, geo_lat, geo_lng, distance_to_center_km, distance_to_district_km,
district_geocodes, city_coherent, error_km, error_class,
best_address_guess, district, street_signs, shop_signs, landmarks
```

### Classes d'erreur

| Classe | Seuil | Signification |
|--------|-------|---------------|
| EXCELLENT | < 100m | Localisation exacte |
| GOOD | 100m – 500m | Bonne approximation |
| OK | 500m – 1km | Acceptable |
| APPROX | 1 – 3 km | Approximatif |
| ZONE | 3 – 10 km | Zone large |
| FAR | > 10 km | Très imprécis |
| NO_GEO | — | Géocodage échoué |

### Dépendance

Ce script importe `geolocate_missing.py` — les deux fichiers doivent être dans le même répertoire.

---

## 4. scoring_reliability.py — Scoring Tier (Legacy)

**Note :** Ce module est désormais intégré directement dans `geolocate_missing.py` via la méthode `_classify_vision_tier()`. Le fichier standalone est conservé pour compatibilité avec un éventuel modèle pickle.

### Utilisation standalone (si modèle pickle disponible)

```python
from scoring_reliability import predict_reliability

features = {
    'n_street_signs': '2',
    'confidence': 'HIGH',
    'distance_to_center_km': '1.5',
    # ... autres features
}
result = predict_reliability(features, model_path='geocoding_reliability_model.pkl')
# → {'tier': 'TRUSTED', 'proba': 0.82}
```

En pratique, le scoring par règles simples (3 tiers) dans `_classify_vision_tier()` est aussi performant que le modèle ML sur 169 samples.

---

## 5. weekly_update.yml — Workflow GitHub Actions

### Déclenchement

- **Automatique** : chaque dimanche à 6h UTC (`cron: '0 6 * * 0'`)
- **Manuel** : via l'onglet Actions de GitHub (workflow_dispatch)

### Paramètres manuels

| Paramètre | Type | Défaut | Description |
|-----------|------|--------|-------------|
| `city` | texte | (vide = toutes) | Ville spécifique à scraper |
| `verbose` | boolean | false | Mode verbeux |
| `skip_geolocate` | boolean | false | Passer l'étape géolocalisation |

### Pipeline (6 étapes)

```
┌──────────────────────────────────────────────────────────┐
│ 1. 📥 Checkout                                           │
│    git clone du repo                                     │
├──────────────────────────────────────────────────────────┤
│ 2. 🐍 Setup Python 3.11                                  │
│    + pip install requirements.txt                        │
│    + playwright install chromium                          │
│    + apt install tesseract-ocr tesseract-ocr-fra         │
├──────────────────────────────────────────────────────────┤
│ 3. 🔍 Scrape & process issues                            │
│    python scripts/update_from_spotter.py --headless      │
│    → Met à jour invaders_master.json depuis les issues   │
│    → Détecte nouveaux invaders / changements de statut   │
├──────────────────────────────────────────────────────────┤
│ 4. 🆕 Détecter les nouveaux invaders                     │
│    → Compte ceux avec geo_source=city_center             │
│    → Skip étape 5 si aucun nouveau                       │
├──────────────────────────────────────────────────────────┤
│ 5. 📍 Géolocaliser (si nouveaux trouvés)                 │
│    python scripts/geolocate_missing.py                   │
│      --from-master --pnote-url --no-browser              │
│    puis: --merge data/invaders_geolocated.json           │
│    ⚠️ Requiert ANTHROPIC_API_KEY dans les secrets        │
├──────────────────────────────────────────────────────────┤
│ 6. 📤 Commit & Push                                      │
│    git commit -m "🔄 Auto-update DATE - N invaders"      │
│    + Génère rapport markdown (GITHUB_STEP_SUMMARY)       │
│    + Génère rapport texte (/tmp/email_body.txt)          │
├──────────────────────────────────────────────────────────┤
│ 7. 📧 Notifications email                                │
│    python scripts/send_notifications.py                  │
│    ⚠️ Requiert SMTP_USERNAME, SMTP_PASSWORD, EMAIL_CONFIG│
│    S'exécute toujours (succès ou échec)                  │
└──────────────────────────────────────────────────────────┘
```

### Secrets GitHub requis

| Secret | Description |
|--------|-------------|
| `PAT_TOKEN` | GitHub Personal Access Token (scraping issues) |
| `ANTHROPIC_API_KEY` | Clé API Claude pour Vision |
| `SMTP_USERNAME` | Email Gmail expéditeur |
| `SMTP_PASSWORD` | App Password Gmail |
| `EMAIL_CONFIG` | JSON des destinataires (voir section 6) |

### Timeout

Le workflow a un timeout de **150 minutes** (2h30). Le scraping prend ~10 min, la géolocalisation ~1-2h selon le nombre de nouveaux invaders.

---

## 6. send_notifications.py — Emails Post-Update

**Envoi d'emails personnalisés** après chaque run du workflow. S'exécute toujours (même en cas d'échec du job).

### Configuration

Le secret `EMAIL_CONFIG` contient un JSON avec la liste des destinataires :

```json
[
  {
    "name": "Jocelyn",
    "email": "jocelyn@example.com",
    "detail_level": "full",
    "cities": ["PA", "LDN", "NY"]
  },
  {
    "name": "Alice",
    "email": "alice@example.com",
    "detail_level": "summary"
  },
  {
    "name": "Bot",
    "email": "alerts@example.com",
    "detail_level": "minimal"
  }
]
```

### Niveaux de détail

| Niveau | Contenu |
|--------|---------|
| `full` | Rapport complet + détail des changements + liens Google Maps pour chaque invader géolocalisé |
| `summary` | Stats résumées + liste des changements + résumé géolocalisation (localisés / non localisés avec hints) |
| `minimal` | Une ligne : "N changements, statut OK/FAIL" |

### Contenu géolocalisation dans les emails

Les niveaux `summary` et `full` incluent automatiquement le rapport de géolocalisation des nouveaux invaders :

```
📍 Géolocalisation : 2 localisés / 4 nouveaux

  Localisés :
    🟡 FRQ_01 (pnote, MEDIUM) — 5 Rue Louis Andrieux, Forcalquier
    🟡 VLMO_01 (pnote, MEDIUM) — Route de Crève-Cœur, Valmorel
  Non localisés :
    🔴 PA_1556 — 💡 TAPISSIER | quartier: 11e
    🔴 NY_198
```

Le niveau `full` ajoute en plus les liens Google Maps cliquables pour chaque invader localisé.

### Variables d'environnement (injectées par le workflow)

```
SMTP_USERNAME, SMTP_PASSWORD, EMAIL_CONFIG,
HAS_CHANGES, CHANGE_COUNT, TOTAL_INVADERS, TOTAL_CITIES,
JOB_STATUS, RUN_URL, REPO_NAME
```

### Exécution manuelle (test)

```bash
export SMTP_USERNAME="user@gmail.com"
export SMTP_PASSWORD="xxxx xxxx xxxx xxxx"
export EMAIL_CONFIG='[{"name":"Test","email":"test@test.com","detail_level":"minimal"}]'
export JOB_STATUS="success"
export HAS_CHANGES="true"
export CHANGE_COUNT="5"
export TOTAL_INVADERS="1850"
export TOTAL_CITIES="87"
export RUN_URL="https://github.com/..."
export REPO_NAME="space-invaders-db"

python3 send_notifications.py
```

---

## 7. flask_app_V12.py — API Web

**API REST** hébergée sur PythonAnywhere. Sert les données du repo GitHub en temps réel avec cache 1h.

### Déploiement PythonAnywhere

1. Créer un compte sur pythonanywhere.com
2. Web → Add new web app → Flask → Python 3.10
3. Upload `flask_app_V12.py` comme `flask_app.py`
4. Configurer le chemin WSGI
5. Reload

### Exécution locale

```bash
python3 flask_app_V12.py
# → http://localhost:5000
```

### Endpoints principaux

| Endpoint | Description |
|----------|-------------|
| `/api/invaders` | Liste complète des invaders |
| `/api/invaders/<id>` | Un invader par ID |
| `/api/cities` | Liste des villes avec stats |
| `/api/stats` | Statistiques globales |

---

## 8. Workflows Typiques

### A) Mise à jour hebdomadaire (automatique)

```
Dimanche 6h UTC → weekly_update.yml se déclenche
  → Scrape les issues GitHub (nouveaux invaders, changements de statut)
  → Géolocalise les nouveaux (Pnote → EXIF → OCR → Lens → Vision)
  → Commit + Push
  → Email aux abonnés
```

Rien à faire — tout est automatique.

### B) Géolocaliser manuellement une ville

```bash
# 1. S'assurer que ANTHROPIC_API_KEY est set
export ANTHROPIC_API_KEY="sk-ant-..."

# 2. Lancer la géolocalisation
python3 geolocate_missing.py --from-master --city BTA --pnote-url --no-browser -v

# 3. Vérifier les résultats
cat data/invaders_geolocated.json | python3 -m json.tool | head -50

# 4. Fusionner dans le master (avec backup)
python3 geolocate_missing.py --merge data/invaders_geolocated.json --backup

# 5. Commit & push
git add data/ && git commit -m "📍 Géolocalisation BTA" && git push
```

### C) Évaluer la qualité du géocodage Vision

```bash
# 1. Lancer un harvest de 200 samples
python3 vision_ml_harvest.py --n 200 -o features_eval.csv

# 2. Afficher les stats
python3 vision_ml_harvest.py --stats features_eval.csv

# 3. Analyser en détail (Python interactif)
python3 -c "
import csv
from statistics import mean, median
from collections import Counter

with open('features_eval.csv') as f:
    rows = list(csv.DictReader(f))
geo = [r for r in rows if r['error_class'] != 'NO_GEO']
print(f'Géocodés: {len(geo)}/{len(rows)}')
print(f'Mean: {mean(float(r[\"error_km\"]) for r in geo):.2f}km')
print(f'Median: {median(float(r[\"error_km\"]) for r in geo):.2f}km')
print(Counter(r['error_class'] for r in rows))
"
```

### D) Tester un seul invader (debug)

```bash
python3 geolocate_missing.py --id PA_39 --pnote-url --no-browser -v
```

### E) Backtest — comparer la géoloc avec la vérité terrain

```bash
python3 geolocate_missing.py --backtest PA_142,NY_100,TK_30,LDN_01 --pnote-url --no-browser -v
```

### F) Déclencher le workflow manuellement

Sur GitHub : Actions → "🛸 Weekly Invaders Update" → Run workflow

Options :
- `city` : laisser vide ou entrer un code (ex: `PA`)
- `verbose` : cocher pour le debug
- `skip_geolocate` : cocher pour ne faire que le scraping sans géoloc

---

## 9. Coûts & Performance

| Opération | Durée | Coût API | Notes |
|-----------|-------|----------|-------|
| Harvest 200 samples | ~50 min | ~$2 | 3 shots × 200 appels Claude |
| Harvest 30 samples | ~8 min | ~$0.30 | Test rapide |
| Géoloc 1 invader | ~15s | ~$0.01 | 3 shots Vision |
| Workflow complet | ~2h | ~$1-5 | Dépend du nombre de nouveaux |
| Pnote download | ~5s | gratuit | Cache local |
| OCR Tesseract | ~2s/image | gratuit | Local |

### Limites

- **Nominatim** : 1 requête/seconde (respecté par le script via `--pause 1.0`)
- **Claude Vision** : rate limits standard de l'API Anthropic
- **GitHub Actions** : 150 min timeout, 2000 min/mois sur free tier
- **PythonAnywhere** : cache 1h sur les données

---

## 10. Résumé des Commandes

```bash
# ══ GÉOLOCALISATION ══
python3 geolocate_missing.py --from-master --pnote-url --no-browser          # Tous
python3 geolocate_missing.py --from-master --city PA --limit 10 --no-browser  # Paris, 10 max
python3 geolocate_missing.py --id PA_1531 --pnote-url --no-browser -v         # Debug 1 invader
python3 geolocate_missing.py --id PA_1556 --address "12 Rue X, 75011 Paris"   # Adresse directe
python3 geolocate_missing.py --from-master --city BTA -i --no-browser          # Interactif (saisie manuelle)
python3 geolocate_missing.py --backtest PA_142,NY_100 --no-browser -v          # Backtest
python3 geolocate_missing.py --merge data/invaders_geolocated.json --backup   # Fusion

# ══ HARVEST ML ══
python3 vision_ml_harvest.py --n 200 -o features.csv                          # Full harvest
python3 vision_ml_harvest.py --n 30 --cities PA -o test.csv                   # Test Paris
python3 vision_ml_harvest.py --stats features.csv                              # Stats seules
python3 vision_ml_harvest.py --n 200 --resume partial.csv -o full.csv         # Reprendre

# ══ FLASK (local) ══
python3 flask_app_V12.py                                                       # Port 5000

# ══ NOTIFICATIONS (test) ══
python3 send_notifications.py                                                  # Avec env vars
```
