# 🛸 Space Invaders Database

Base de données personnelle des Space Invaders de l'artiste [Invader](https://www.space-invaders.com/), maintenue et enrichie par scraping et géolocalisation.

## 📊 Statistiques

| Métrique | Valeur |
|----------|--------|
| Total invaders | 4 371 |
| Villes/Territoires | 88 |
| Géolocalisés | 4 254 (97,3%) |
| OK | 2 422 |
| Endommagés | 429 |
| Détruits | 1 472 |
| Cachés | 24 |
| Inconnus | 24 |

## 📁 Structure

```
data/
├── invaders_master.json        # Base complète (source de vérité)
├── invaders_changelog.json     # Historique des changements détectés
└── metadata.json               # Stats, version, sources

scripts/
├── update_from_spotter.py      # Script 1 : scraping invader-spotter.art
├── geolocate_missing.py        # Script 2 : géolocalisation des nouveaux
├── push_update.sh              # Script 3 : commit & push automatique
└── requirements.txt

.github/workflows/
└── weekly_update.yml           # GitHub Action : MAJ automatique hebdo
```

## 🔄 Workflow de mise à jour

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  invaders_master │────▶│ update_from_     │────▶│ invaders_master │
│  .json (avant)  │     │ spotter.py       │     │ .json (enrichi) │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                        ┌──────────────────┐              │
                        │ geolocate_       │◀─────────────┘
                        │ missing.py       │
                        └───────┬──────────┘
                                │
                        ┌───────▼──────────┐
                        │ invaders_master   │
                        │ .json (complet)  │
                        └───────┬──────────┘
                                │
                        ┌───────▼──────────┐
                        │ git commit & push│
                        └──────────────────┘
```

### Mise à jour manuelle

```bash
# 1. Cloner le repo
git clone https://github.com/jojosh1er/space-invaders-db.git
cd space-invaders-db

# 2. Installer les dépendances
pip install -r scripts/requirements.txt
playwright install chromium

# 3. Scraper les statuts depuis invader-spotter.art
python scripts/update_from_spotter.py

# 4. Géolocaliser les invaders sans coordonnées
python scripts/geolocate_missing.py

# 5. Commit & push
bash scripts/push_update.sh
```

### Mise à jour d'une seule ville

```bash
python scripts/update_from_spotter.py --city PA --verbose
```

### Mise à jour automatique (GitHub Action)

Une GitHub Action tourne chaque dimanche à 6h UTC. Elle :
1. Scrape les statuts depuis invader-spotter.art
2. Met à jour `invaders_master.json`
3. Commit & push les changements

## 📋 Structure d'un invader

```json
{
  "id": "PA_1234",
  "lat": "48.8566",
  "lng": "2.3522",
  "points": "50",
  "status": "OK",
  "city": "PA",
  "landing_date": "15/03/2020",
  "status_date": "décembre 2025",
  "status_source": "report",
  "image_invader": "https://www.invader-spotter.art/grosplan/PA/PA_1234-grosplan.png",
  "image_lieu": "https://www.invader-spotter.art/photos/PA/PA_1234-mars2020.jpg",
  "previous_status": "",
  "previous_status_date": "",
  "hint": "",
  "address": "",
  "geo_source": "google",
  "geo_confidence": "high"
}
```

### Statuts possibles

| Statut | Description |
|--------|-------------|
| `OK` | Visible et flashable |
| `a little damaged` | Légèrement abîmé |
| `damaged` | Endommagé (manque des carreaux) |
| `hidden` | Caché temporairement (travaux, végétation...) |
| `destroyed` | Détruit définitivement |
| `unknown` | Statut inconnu |

## 📡 Sources de données

| Source | Usage | Accès |
|--------|-------|-------|
| [goguelnikov/SpaceInvaders](https://github.com/goguelnikov/SpaceInvaders) | Base initiale (coords, points) | GitHub public |
| [invader-spotter.art](https://www.invader-spotter.art) | Statuts à jour, images, dates | Scraping Playwright |
| Google Search | Géolocalisation des nouveaux | API / scraping |

## 🎯 Utilisation dans l'app Flask

L'application de chasse pointe directement sur le raw du master :

```python
INVADERS_DB_URL = "https://raw.githubusercontent.com/jojosh1er/space-invaders-db/main/data/invaders_master.json"
```

## 📝 Licence

Usage personnel. Les données Invader appartiennent à l'artiste Invader. Les images proviennent d'invader-spotter.art.
