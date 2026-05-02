#!/usr/bin/env python3
"""
🔬 Backtest A/B — Claude Vision : Sonnet 4.5 vs Opus 4.7
=========================================================

Compare les deux modèles sur les mêmes images d'invaders avec coords connues.
Mesure la précision GPS (distance à la vérité terrain) pour chaque modèle.

Usage:
    # Test sur les cas d'échec connus (liste par défaut)
    python vision_ab_test.py --master ../data/invaders_master.json

    # IDs personnalisés
    python vision_ab_test.py --master ../data/invaders_master.json \\
        --ids PA_142,PA_567,BGK_07,TK_30,ROM_30,MPL_10

    # Réduire à 1 shot pour économiser (moins fiable, plus rapide)
    python vision_ab_test.py --master ../data/invaders_master.json --shots 1

    # Tester seulement Opus (skip Sonnet)
    python vision_ab_test.py --master ../data/invaders_master.json --only-opus

    # Verbose + output JSON
    python vision_ab_test.py --master ../data/invaders_master.json -v \\
        --output results/ab_test_$(date +%Y%m%d).json

Options:
    --master FILE     Chemin vers invaders_master.json (requis)
    --ids LIST        IDs séparés par virgules (défaut: liste prédéfinie)
    --shots N         Nombre de shots Vision par modèle (défaut: 3, min: 1)
    --only-sonnet     Tester uniquement Sonnet 4.5
    --only-opus       Tester uniquement Opus 4.7
    --output FILE     Sauvegarder résultats JSON
    --anthropic-key   Clé API (ou env ANTHROPIC_API_KEY)
    -v, --verbose     Logs détaillés

Coût estimé (3 shots × 2 modèles × N invaders):
    6 appels/invader × ~0.004€/appel Sonnet + ~0.008€/appel Opus
    Exemple 10 invaders ≈ 0.10€
"""

import argparse
import json
import math
import os
import sys
import time
import importlib.util
from pathlib import Path
from datetime import datetime

# ─── Chargement dynamique de VisionAnalyzer depuis geolocate_missing.py ────

def load_vision_analyzer(script_path: str):
    """
    Charge VisionAnalyzer et ImageOCRAnalyzer depuis geolocate_missing.py
    sans exécuter le main().
    """
    spec = importlib.util.spec_from_file_location("geolocate_missing", script_path)
    mod = importlib.util.module_from_spec(spec)
    # Patch sys.modules pour éviter double-import si le script s'importe lui-même
    sys.modules["geolocate_missing"] = mod
    spec.loader.exec_module(mod)
    return mod.VisionAnalyzer, mod.ImageOCRAnalyzer, mod.CITY_CENTERS, mod.CITY_NAMES


# ─── Vérité terrain : IDs par défaut avec ground truth overrides ────────────
# Ces coords sont les vraies positions (issues de pnote/aroundus lors du 1er backtest).
# Si l'invader a déjà des bonnes coords dans le master, pas besoin de override.

GROUND_TRUTH_OVERRIDE = {
    # Cas d'échec du backtest précédent — overrides manuels si nécessaire
    # Format: 'ID': (lat, lng)
    # Ex: 'PA_142': (48.8601, 2.3477),
}

# Liste d'IDs par défaut (échecs + contrôles positifs du backtest précédent)
DEFAULT_IDS = [
    # Échecs notables
    'PA_142',    # Paris   — 3.13km off (ZONE)
    'PA_567',    # Paris   — 6.19km off (ZONE)
    'BGK_07',    # Bangkok — 5.65km off (ZONE)
    'TK_30',     # Tokyo   — 27.46km off (FAR)
    'HK_20',     # HK      — 4.66km off (ZONE)
    'NY_100',    # NY      — 3.84km off (ZONE)
    # Contrôles positifs (bons résultats — doivent rester bons)
    'MPL_10',    # Montpellier — 0.01km (EXCELLENT)
    'ROM_30',    # Rome        — 0.08km (EXCELLENT)
    'LDN_50',    # Londres     — 0.26km (GOOD)
    'MARS_30',   # Marseille   — 0.69km (OK)
]

# ─── Helpers ────────────────────────────────────────────────────────────────

def haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(min(1.0, math.sqrt(a)))


def classify(dist_km: float) -> str:
    if dist_km < 0.1:   return "🎯 EXCELLENT"
    if dist_km < 0.5:   return "✅ BON"
    if dist_km < 1.0:   return "🟡 OK"
    if dist_km < 3.0:   return "🟠 APPROX"
    if dist_km < 10.0:  return "🔶 ZONE"
    return "❌ LOIN"


def city_code_from_id(invader_id: str) -> str:
    """'PA_142' → 'PA', 'BGK_07' → 'BGK'"""
    return invader_id.rsplit('_', 1)[0]


def load_master(path: str) -> dict:
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    # Supporte liste ou dict {id: obj}
    if isinstance(data, list):
        return {inv['id']: inv for inv in data if 'id' in inv}
    return data


# ─── Coeur du test ──────────────────────────────────────────────────────────

def run_ab_test(args):
    # 1. Localiser geolocate_missing.py
    script_candidates = [
        Path(args.master).parent.parent / "geolocate_missing.py",
        Path(args.master).parent / "geolocate_missing.py",
        Path(__file__).parent / "geolocate_missing.py",
        Path.cwd() / "geolocate_missing.py",
    ]
    geolocate_path = None
    for c in script_candidates:
        if c.exists():
            geolocate_path = str(c)
            break
    if not geolocate_path:
        print("❌ geolocate_missing.py introuvable. Utilisez --geolocate-path si non standard.")
        sys.exit(1)

    print(f"📂 geolocate_missing.py : {geolocate_path}")
    VisionAnalyzer, ImageOCRAnalyzer, CITY_CENTERS, CITY_NAMES = load_vision_analyzer(geolocate_path)

    # Patch Nominatim rate-limit : 1 req/s max — sans sleep, les réponses sont silencieusement
    # ignorées après le 2e appel consécutif. Le pipeline enchaîne ~10 requêtes par invader.
    _orig_geocode = ImageOCRAnalyzer.geocode_address
    def _geocode_throttled(self, address, city_code=None):
        time.sleep(1.2)   # légèrement au-dessus du minimum Nominatim (1.0s)
        return _orig_geocode(self, address, city_code=city_code)
    ImageOCRAnalyzer.geocode_address = _geocode_throttled
    print("   \u23f1\ufe0f  Nominatim throttle activé (1.2s entre requêtes)")

    # 2. Charger le master
    master = load_master(args.master)
    print(f"📦 Master chargé : {len(master)} invaders")

    # 3. Préparer les IDs à tester
    ids_to_test = [i.strip() for i in args.ids.split(',')] if args.ids else DEFAULT_IDS
    ids_to_test = [i for i in ids_to_test if i]
    print(f"🧪 IDs à tester : {', '.join(ids_to_test)}\n")

    # 4. Modèles à comparer
    models = {}
    if not args.only_opus:
        models['sonnet'] = {
            'label': 'Sonnet 4.5',
            'model_id': 'claude-sonnet-4-5-20250929',
        }
    if not args.only_sonnet:
        models['opus'] = {
            'label': 'Opus 4.7',
            'model_id': 'claude-opus-4-7',
        }

    if not models:
        print("❌ --only-sonnet et --only-opus sont mutuellement exclusifs.")
        sys.exit(1)

    api_key = args.anthropic_key or os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("❌ Clé API Anthropic manquante. --anthropic-key ou ANTHROPIC_API_KEY")
        sys.exit(1)

    # Modèles qui ne supportent PAS temperature (deprecated Opus 4.7+)
    NO_TEMPERATURE_PREFIXES = ('claude-opus-4-7', 'claude-opus-4-8', 'claude-opus-5')

    def _make_no_temp_call_vision(va_instance):
        """Retourne un _call_vision patché sans temperature."""
        import types, re as _re, json as _json

        def _call_vision_no_temp(self, images, city_code=None, city_name=None):
            try:
                system_prompt = self._build_prompt(city_code, city_name)
                content = []
                for b64, media_type, label in images:
                    content.append({"type": "image",
                                    "source": {"type": "base64",
                                               "media_type": media_type, "data": b64}})
                    content.append({"type": "text", "text": f"[{label}]"})
                content.append({"type": "text",
                                "text": "Analyse ces images et identifie tous les indices de localisation."})
                response = self.client.messages.create(
                    model=self.VISION_MODEL,
                    max_tokens=1200,
                    system=system_prompt,
                    messages=[{"role": "user", "content": content}]
                )
                raw = response.content[0].text.strip()
                self.log(f"Réponse brute: {raw[:300]}...")
                raw = _re.sub(r'^```json\s*', '', raw)
                raw = _re.sub(r'\s*```$', '', raw)
                return _json.loads(raw)
            except _json.JSONDecodeError as e:
                self.log(f"JSON invalide: {e}")
                m = _re.search(r'"best_address_guess"\s*:\s*"([^"]+)"', raw)
                return {'best_address_guess': m.group(1), 'confidence': 'LOW'} if m else None
            except Exception as e:
                self.log(f"Erreur Vision API: {e}")
                return None

        return types.MethodType(_call_vision_no_temp, va_instance)

    # Créer un VisionAnalyzer par modèle
    analyzers = {}
    for key, cfg in models.items():
        va = VisionAnalyzer(api_key=api_key, verbose=args.verbose, n_shots=args.shots)
        va.VISION_MODEL = cfg['model_id']
        needs_patch = any(va.VISION_MODEL.startswith(p) for p in NO_TEMPERATURE_PREFIXES)
        if needs_patch:
            va._call_vision = _make_no_temp_call_vision(va)
            print(f"   🤖 {cfg['label']} ({cfg['model_id']}) — {args.shots} shot(s)  [temperature désactivé]")
        else:
            print(f"   🤖 {cfg['label']} ({cfg['model_id']}) — {args.shots} shot(s)")
        analyzers[key] = (cfg['label'], va)
    print()

    # 5. Boucle de test
    results = []
    skipped = []

    for inv_id in ids_to_test:
        inv = master.get(inv_id)
        if not inv:
            print(f"⚠️  {inv_id} absent du master — ignoré")
            skipped.append(inv_id)
            continue

        city_code = city_code_from_id(inv_id)
        city_name = CITY_NAMES.get(city_code) or CITY_CENTERS.get(city_code, {}).get('name', city_code)

        image_lieu = inv.get('image_lieu') or inv.get('image_invader')
        image_close = inv.get('image_close')

        if not image_lieu:
            print(f"⚠️  {inv_id} sans image_lieu — ignoré")
            skipped.append(inv_id)
            continue

        # Vérité terrain
        if inv_id in GROUND_TRUTH_OVERRIDE:
            gt_lat, gt_lng = GROUND_TRUTH_OVERRIDE[inv_id]
            gt_source = 'override_manuel'
        else:
            gt_lat = inv.get('lat') or inv.get('latitude')
            gt_lng = inv.get('lng') or inv.get('longitude')
            gt_source = inv.get('geo_source', 'master')

        # Le master stocke parfois les coords comme strings
        try:
            gt_lat = float(gt_lat) if gt_lat is not None else None
            gt_lng = float(gt_lng) if gt_lng is not None else None
        except (ValueError, TypeError):
            gt_lat, gt_lng = None, None

        if gt_lat is None or gt_lng is None:
            print(f"⚠️  {inv_id} sans coords de référence — ignoré")
            skipped.append(inv_id)
            continue

        print(f"\n{'─'*60}")
        print(f"🗺  {inv_id}  ({city_name})  — vérité: {gt_lat:.4f}, {gt_lng:.4f}  [{gt_source}]")
        print(f"   Image: {str(image_lieu)[:70]}...")

        row = {
            'id': inv_id,
            'city': city_code,
            'city_name': city_name,
            'gt_lat': gt_lat,
            'gt_lng': gt_lng,
            'gt_source': gt_source,
            'image_lieu': image_lieu,
            'models': {},
        }

        for key, (label, va) in analyzers.items():
            print(f"\n   ▶ {label}...")
            t0 = time.time()
            try:
                res = va.analyze(
                    image_lieu_url=image_lieu,
                    city_name=city_name,
                    city_code=city_code,
                    image_close_url=image_close,
                )
            except Exception as e:
                print(f"   ❌ Exception: {e}")
                res = {'found': False, 'error': str(e)}

            elapsed = time.time() - t0

            found = res.get('found', False)
            pred_lat = res.get('lat')
            pred_lng = res.get('lng')
            address = res.get('address', '')
            confidence = res.get('confidence', '?')
            source = res.get('source', '?')

            if found and pred_lat and pred_lng:
                dist_km = haversine_km(gt_lat, gt_lng, pred_lat, pred_lng)
                quality = classify(dist_km)
                print(f"   ✅ {quality}  dist={dist_km:.2f}km  conf={confidence}")
                print(f"      Adresse: {address}")
                print(f"      Coords:  {pred_lat:.4f}, {pred_lng:.4f}  [{elapsed:.1f}s]")
            else:
                dist_km = None
                quality = "❓ NON TROUVÉ"
                print(f"   ❌ Pas de résultat  [{elapsed:.1f}s]")
                if res.get('error'):
                    print(f"      Erreur: {res['error']}")

            row['models'][key] = {
                'label': label,
                'found': found,
                'dist_km': round(dist_km, 3) if dist_km is not None else None,
                'quality': quality,
                'confidence': confidence,
                'source': source,
                'address': address,
                'pred_lat': pred_lat,
                'pred_lng': pred_lng,
                'elapsed_s': round(elapsed, 1),
                'error': res.get('error'),
            }

            # Pause poli entre modèles
            time.sleep(2)

        results.append(row)

    # 6. Rapport récapitulatif
    print(f"\n\n{'='*80}")
    print("📊  RAPPORT A/B — SONNET 4.5 vs OPUS 4.7")
    print(f"{'='*80}\n")

    model_keys = list(analyzers.keys())
    labels = {k: v[0] for k, v in analyzers.items()}

    # En-tête
    header = f"{'ID':12s} {'Ville':6s}"
    for k in model_keys:
        lbl = labels[k][:12]
        header += f"  {lbl:>12s}  {'km':>6s}  {'Qualité':13s}"
    print(header)
    print("─" * len(header))

    # Stats par modèle
    model_stats = {k: {'found': 0, 'dist_sum': 0.0, 'dists': [], 'by_quality': {}} for k in model_keys}

    for row in results:
        line = f"{row['id']:12s} {row['city']:6s}"
        for k in model_keys:
            m = row['models'].get(k, {})
            d = m.get('dist_km')
            q = m.get('quality', '?')
            conf = m.get('confidence', '?')[:1]
            if d is not None:
                line += f"  {conf:>12s}  {d:>6.2f}  {q:13s}"
                model_stats[k]['found'] += 1
                model_stats[k]['dist_sum'] += d
                model_stats[k]['dists'].append(d)
                model_stats[k]['by_quality'][q] = model_stats[k]['by_quality'].get(q, 0) + 1
            else:
                line += f"  {'NON TROUVÉ':>12s}  {'---':>6s}  {'❓':13s}"
        print(line)

    # Stats globales
    print(f"\n{'─'*80}")
    print("📈  STATISTIQUES COMPARÉES\n")
    total = len(results)

    quality_order = ["🎯 EXCELLENT", "✅ BON", "🟡 OK", "🟠 APPROX", "🔶 ZONE", "❌ LOIN"]

    for k in model_keys:
        s = model_stats[k]
        n = s['found']
        dists = sorted(s['dists'])
        avg = s['dist_sum'] / n if n else 0
        median = dists[len(dists)//2] if dists else 0
        best = min(dists) if dists else 0
        worst = max(dists) if dists else 0
        precise = sum(1 for d in dists if d < 1.0)

        print(f"  {labels[k]}:")
        print(f"    Trouvés:       {n}/{total}")
        print(f"    Précision <1km: {precise}/{n} ({100*precise//n if n else 0}%)")
        print(f"    Distance moy:  {avg:.2f} km")
        print(f"    Distance méd:  {median:.2f} km")
        print(f"    Meilleure:     {best:.2f} km")
        print(f"    Pire:          {worst:.2f} km")

        if s['by_quality']:
            breakdown = "  ".join(f"{q}: {c}" for q, c in
                                  sorted(s['by_quality'].items(),
                                         key=lambda x: quality_order.index(x[0])
                                         if x[0] in quality_order else 99))
            print(f"    Qualités:      {breakdown}")
        print()

    # Delta Opus - Sonnet
    if 'sonnet' in model_stats and 'opus' in model_stats:
        common = [r for r in results
                  if r['models'].get('sonnet', {}).get('dist_km') is not None
                  and r['models'].get('opus', {}).get('dist_km') is not None]
        if common:
            print(f"  🔄 Delta Opus vs Sonnet (sur {len(common)} invaders comparables):")
            improvements = []
            regressions = []
            for r in common:
                d_s = r['models']['sonnet']['dist_km']
                d_o = r['models']['opus']['dist_km']
                delta = d_s - d_o   # positif = Opus meilleur
                if delta > 0.1:
                    improvements.append((r['id'], delta, d_s, d_o))
                elif delta < -0.1:
                    regressions.append((r['id'], -delta, d_s, d_o))

            if improvements:
                print(f"    ✅ Opus meilleur sur {len(improvements)} invader(s):")
                for inv_id, gain, ds, do in sorted(improvements, key=lambda x: -x[1]):
                    print(f"       {inv_id:12s}  Sonnet={ds:.2f}km → Opus={do:.2f}km  (-{gain:.2f}km)")
            if regressions:
                print(f"    ⚠️  Opus moins bon sur {len(regressions)} invader(s):")
                for inv_id, loss, ds, do in sorted(regressions, key=lambda x: -x[1]):
                    print(f"       {inv_id:12s}  Sonnet={ds:.2f}km → Opus={do:.2f}km  (+{loss:.2f}km)")
            neutral = len(common) - len(improvements) - len(regressions)
            if neutral:
                print(f"    ➡️  Résultats équivalents: {neutral} invader(s)")

            avg_delta = sum(
                r['models']['sonnet']['dist_km'] - r['models']['opus']['dist_km']
                for r in common
            ) / len(common)
            print(f"\n    📏 Gain moyen Opus: {avg_delta:+.2f}km "
                  f"({'Opus meilleur' if avg_delta > 0 else 'Sonnet meilleur'})")

    if skipped:
        print(f"\n⚠️  Ignorés: {', '.join(skipped)}")

    # 7. Export JSON
    if args.output:
        output_data = {
            'run_date': datetime.now().isoformat(),
            'models_tested': {k: {'label': v[0], 'model_id': models[k]['model_id']}
                              for k, v in analyzers.items()},
            'shots_per_model': args.shots,
            'total_tested': total,
            'skipped': skipped,
            'results': results,
            'stats': {k: {
                'found': model_stats[k]['found'],
                'avg_dist_km': round(model_stats[k]['dist_sum'] / model_stats[k]['found'], 3)
                               if model_stats[k]['found'] else None,
                'by_quality': model_stats[k]['by_quality'],
            } for k in model_keys},
        }
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n💾 Résultats sauvegardés : {args.output}")

    print(f"\n{'='*80}")


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Backtest A/B Vision : Sonnet 4.5 vs Opus 4.7",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--master', required=True,
                        help="Chemin vers invaders_master.json")
    parser.add_argument('--geolocate-path', dest='geolocate_path', default=None,
                        help="Chemin explicite vers geolocate_missing.py si non détecté")
    parser.add_argument('--ids', default=None,
                        help="IDs séparés par virgules (défaut: liste prédéfinie)")
    parser.add_argument('--shots', type=int, default=3,
                        help="Shots Vision par modèle (défaut: 3)")
    parser.add_argument('--only-sonnet', action='store_true',
                        help="Tester uniquement Sonnet 4.5")
    parser.add_argument('--only-opus', action='store_true',
                        help="Tester uniquement Opus 4.7")
    parser.add_argument('--anthropic-key', dest='anthropic_key', default=None,
                        help="Clé API Anthropic (ou env ANTHROPIC_API_KEY)")
    parser.add_argument('--output', '-o', default=None,
                        help="Fichier de sortie JSON")
    parser.add_argument('--verbose', '-v', action='store_true',
                        help="Logs détaillés")
    args = parser.parse_args()

    run_ab_test(args)


if __name__ == '__main__':
    main()
