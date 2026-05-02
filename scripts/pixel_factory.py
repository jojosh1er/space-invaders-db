#!/usr/bin/env python3
"""
InvaDex Pixel Factory
=====================
Télécharge les images des Invaders et génère un JSON de sprites pixelisés.

Usage:
  python pixel_factory.py

Prérequis:
  pip install Pillow requests

Paramètres ajustables ci-dessous (GRID_SIZE, SAT_BOOST, BRIGHT_BOOST)
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

try:
    from PIL import Image, ImageEnhance
except ImportError:
    print("❌ Pillow requis: pip install Pillow")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("❌ requests requis: pip install requests")
    sys.exit(1)

# ============================================================
# PARAMÈTRES À AJUSTER
# ============================================================
GRID_SIZE = 10          # Résolution pixel: 6=ultra blocky, 8=arcade, 10=détaillé, 12=fin
SAT_BOOST = 1.6         # Boost saturation (1.0=normal, 1.5=vif, 2.0=néon)
BRIGHT_BOOST = 1.15     # Boost luminosité (1.0=normal, 1.2=clair)
MAX_WORKERS = 15        # Téléchargements parallèles
OUTPUT_FILE = "invadex-pixels.json"
CACHE_DIR = ".pixel_cache"  # Cache les images téléchargées

IMG_PREFIX = "https://www.invader-spotter.art/grosplan/PA/"

# ============================================================
# DATA - Les 1559 Invaders de Paris
# ============================================================
# Format: [id, lat, lng, pts, status, year, imgFile]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MASTER_JSON = os.path.join(SCRIPT_DIR, "invaders_master.json")

def load_invaders():
    """Charge les données depuis invaders_master.json"""
    if not os.path.exists(MASTER_JSON):
        # Cherche aussi dans le dossier courant
        alt = "invaders_master.json"
        if os.path.exists(alt):
            path = alt
        else:
            print(f"❌ Fichier introuvable: {MASTER_JSON}")
            print(f"   Place invaders_master.json dans le même dossier que ce script.")
            sys.exit(1)
    else:
        path = MASTER_JSON
    
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Filtre Paris uniquement
    pa = [d for d in data if d.get("city") == "PA"]
    print(f"📦 {len(pa)} Invaders Paris chargés depuis {path}")
    return pa


def download_image(url, cache_path):
    """Télécharge une image avec cache local."""
    if os.path.exists(cache_path):
        return Image.open(cache_path)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    
    img = Image.open(BytesIO(resp.content))
    
    # Cache
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    img.save(cache_path, "PNG")
    
    return img


def pixelate_image(img, grid_size, sat_boost, bright_boost):
    """Pixelise une image en grille NxN avec boost couleurs."""
    # Convertir en RGB si nécessaire
    if img.mode == "RGBA":
        # Fond noir pour les zones transparentes
        bg = Image.new("RGB", img.size, (0, 0, 0))
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    
    # Boost saturation
    if sat_boost != 1.0:
        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(sat_boost)
    
    # Boost luminosité
    if bright_boost != 1.0:
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(bright_boost)
    
    # Redimensionner à la grille (nearest neighbor pour garder le côté pixel)
    # Garder l'aspect ratio
    aspect = img.width / img.height
    if aspect >= 1:
        new_w = grid_size
        new_h = max(1, round(grid_size / aspect))
    else:
        new_h = grid_size
        new_w = max(1, round(grid_size * aspect))
    
    img_small = img.resize((new_w, new_h), Image.Resampling.NEAREST)
    
    # Créer la grille finale (centrée)
    pixels = []
    offset_x = (grid_size - new_w) // 2
    offset_y = (grid_size - new_h) // 2
    
    for y in range(grid_size):
        for x in range(grid_size):
            src_x = x - offset_x
            src_y = y - offset_y
            if 0 <= src_x < new_w and 0 <= src_y < new_h:
                r, g, b = img_small.getpixel((src_x, src_y))
                # Skip near-black pixels (background)
                if r < 8 and g < 8 and b < 8:
                    pixels.append(None)
                else:
                    hex_color = f"{r:02x}{g:02x}{b:02x}"
                    pixels.append(hex_color)
            else:
                pixels.append(None)
    
    return pixels


def process_single(entry, grid_size, sat_boost, bright_boost, cache_dir):
    """Traite un seul Invader."""
    inv_id = entry["id"]
    img_file = entry.get("image_invader", "")
    
    if not img_file:
        return inv_id, None, "no image URL"
    
    # Nom du cache
    cache_name = img_file.split("/")[-1] if "/" in img_file else f"{inv_id}.png"
    cache_path = os.path.join(cache_dir, cache_name)
    
    try:
        img = download_image(img_file, cache_path)
        pixels = pixelate_image(img, grid_size, sat_boost, bright_boost)
        return inv_id, pixels, None
    except Exception as e:
        return inv_id, None, str(e)


def main():
    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║   🎮 InvaDex PIXEL FACTORY 🎮       ║")
    print("  ╚══════════════════════════════════════╝")
    print()
    print(f"  Résolution:  {GRID_SIZE}×{GRID_SIZE} pixels")
    print(f"  Saturation:  ×{SAT_BOOST}")
    print(f"  Luminosité:  ×{BRIGHT_BOOST}")
    print(f"  Workers:     {MAX_WORKERS}")
    print(f"  Cache:       {CACHE_DIR}/")
    print()
    
    invaders = load_invaders()
    total = len(invaders)
    
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    all_pixels = {}
    errors = []
    done = 0
    start_time = time.time()
    
    print(f"🚀 Traitement de {total} Invaders...")
    print()
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_single, entry, GRID_SIZE, SAT_BOOST, BRIGHT_BOOST, CACHE_DIR): entry
            for entry in invaders
        }
        
        for future in as_completed(futures):
            inv_id, pixels, error = future.result()
            done += 1
            
            if pixels:
                all_pixels[inv_id] = pixels
            else:
                errors.append((inv_id, error))
            
            # Progress bar
            pct = done / total * 100
            bar_len = 40
            filled = int(bar_len * done / total)
            bar = "█" * filled + "░" * (bar_len - filled)
            elapsed = time.time() - start_time
            eta = (elapsed / done * (total - done)) if done > 0 else 0
            
            sys.stdout.write(f"\r  [{bar}] {pct:5.1f}% | {done}/{total} | ⚡{len(all_pixels)} OK | ❌{len(errors)} err | ETA {eta:.0f}s")
            sys.stdout.flush()
    
    print()
    print()
    
    # Build output
    output = {
        "version": 1,
        "gridSize": GRID_SIZE,
        "saturation": SAT_BOOST,
        "brightness": BRIGHT_BOOST,
        "count": len(all_pixels),
        "errors": len(errors),
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "pixels": all_pixels,
    }
    
    # Save
    output_path = os.path.join(SCRIPT_DIR, OUTPUT_FILE)
    with open(output_path, "w") as f:
        json.dump(output, f, separators=(",", ":"))
    
    file_size = os.path.getsize(output_path)
    elapsed = time.time() - start_time
    
    print(f"  ✅ Terminé en {elapsed:.1f}s")
    print(f"  📊 Sprites générés: {len(all_pixels)}/{total}")
    print(f"  ❌ Erreurs: {len(errors)}")
    print(f"  💾 Fichier: {output_path} ({file_size/1024:.0f} KB)")
    print()
    
    if errors:
        print(f"  ⚠️  Premiers erreurs:")
        for inv_id, err in errors[:10]:
            print(f"     {inv_id}: {err}")
        if len(errors) > 10:
            print(f"     ... et {len(errors)-10} autres")
        print()
    
    print(f"  👉 Renvoie le fichier '{OUTPUT_FILE}' dans Claude pour intégrer à l'InvaDex!")
    print()


if __name__ == "__main__":
    main()
