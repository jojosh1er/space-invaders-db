"""
Total Invaders Search - Powered by Jojosh1er
Version Flask pour hébergement PythonAnywhere

Instructions:
1. Crée un compte sur pythonanywhere.com
2. Va dans "Web" > "Add new web app" > Flask > Python 3.10
3. Upload ce fichier comme "flask_app.py"
4. Dans le fichier WSGI, modifie le chemin vers ce fichier
5. Reload et c'est en ligne !
"""

from flask import Flask, jsonify, request, Response
import urllib.request
import json
import time

app = Flask(__name__)

INVADERS_DB_URL = "https://raw.githubusercontent.com/jojosh1er/space-invaders-db/main/data/invaders_master.json"
FLASH_API_URL = "https://api.space-invaders.com/flashinvaders_v3_pas_trop_predictif/api/gallery"

invaders_cache = None
cities_cache = None
cache_timestamp = 0
CACHE_TTL = 3600  # 1 heure en secondes

def fetch_url(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'TotalInvaders/2.0'})
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.read().decode('utf-8-sig')
    except Exception as e:
        print(f"Erreur: {e}")
        return None

def load_database(force_refresh=False):
    global invaders_cache, cities_cache, cache_timestamp
    
    # Cache valide et pas de refresh forcé → on garde
    if not force_refresh and invaders_cache is not None and (time.time() - cache_timestamp) < CACHE_TTL:
        return True
    
    import os
    data = None
    
    # Charger depuis GitHub (source de vérité)
    data = fetch_url(INVADERS_DB_URL)
    if data:
        print(f"Chargé depuis GitHub: {INVADERS_DB_URL.split('/')[-1]}")
    
    # Fallback: fichier local (si GitHub indisponible)
    if not data:
        local_file = os.path.join(os.path.dirname(__file__), 'invaders_master.json')
        if os.path.exists(local_file):
            try:
                with open(local_file, 'r', encoding='utf-8-sig') as f:
                    data = f.read()
                print(f"Fallback fichier local: {local_file}")
            except:
                pass
    
    # Si GitHub down et cache existant → garder l'ancien cache
    if not data and invaders_cache is not None:
        print("GitHub indisponible, cache existant conservé")
        cache_timestamp = time.time()  # Reset le TTL pour ne pas re-tenter en boucle
        return True
    
    if not data:
        return False
    
    raw_data = json.loads(data)
    invaders_cache, cities_cache = {}, {}
    
    for item in raw_data:
        if not isinstance(item, dict):
            continue
        city = item.get('city', '')
        lat, lng = item.get('lat'), item.get('lng')
        if not city or not lat or not lng:
            continue
        
        try:
            lat_f = float(str(lat).replace(',', '.'))
            lng_f = float(str(lng).replace(',', '.'))
            if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
                continue
            
            if city not in invaders_cache:
                invaders_cache[city] = []
                cities_cache[city] = {'count': 0, 'lat': 0, 'lng': 0}
            
            invaders_cache[city].append({
                'name': item.get('id', item.get('name', '?')),
                'lat': lat_f, 'lng': lng_f,
                'points': int(item.get('points', 10)),
                'status': item.get('status', 'OK'),
                'hint': item.get('hint', ''),
                'image_invader': item.get('image_invader'),
                'image_lieu': item.get('image_lieu'),
                'location_unknown': item.get('location_unknown', False),
                # Champs v4
                'landing_date': item.get('landing_date'),
                'status_date': item.get('status_date'),
                'status_source': item.get('status_source'),
                'previous_status': item.get('previous_status'),
                'previous_status_date': item.get('previous_status_date'),
                # Champs géolocalisation
                'geo_source': item.get('geo_source'),
                'geo_confidence': item.get('geo_confidence'),
                'geo_hint': item.get('geo_hint'),
                'missing_from_github': item.get('missing_from_github', False),
                'address': item.get('address'),
            })
            cities_cache[city]['count'] += 1
            cities_cache[city]['lat'] += lat_f
            cities_cache[city]['lng'] += lng_f
        except:
            continue
    
    for c in cities_cache:
        n = cities_cache[c]['count']
        cities_cache[c]['lat'] /= n
        cities_cache[c]['lng'] /= n
    
    cache_timestamp = time.time()
    print(f"Cache mis à jour: {len(invaders_cache)} villes, TTL={CACHE_TTL}s")
    return True

CITY_NAMES = {
    'PA':'Paris','LY':'Lyon','MARS':'Marseille','MPL':'Montpellier','TLS':'Toulouse',
    'NA':'Nantes','LIL':'Lille','GRN':'Grenoble','RN':'Rennes','CLR':'Clermont-Ferrand',
    'AIX':'Aix-en-Provence','AVI':'Avignon','DIJ':'Dijon','NIM':'Nîmes','PAU':'Pau',
    'VRS':'Versailles','FTBL':'Fontainebleau','CAZ':"Côte d'Azur",'REUN':'La Réunion',
    'BTA':'Bastia','MEN':'Menton','STR':'Strasbourg','BDX':'Bordeaux','NCE':'Nice',
    'NY':'New York','LA':'Los Angeles','SD':'San Diego','MIA':'Miami','SF':'San Francisco',
    'LDN':'London','MAN':'Manchester','NCL':'Newcastle','BHM':'Birmingham',
    'TK':'Tokyo','HK':'Hong Kong','BGK':'Bangkok','SIN':'Singapore',
    'BRC':'Barcelona','BRL':'Berlin','AMS':'Amsterdam','RTD':'Rotterdam','ROM':'Rome',
    'WN':'Vienna','BXL':'Brussels','GNV':'Geneva','LSN':'Lausanne','BSL':'Basel','BRN':'Bern',
    'RA':'Ravenna','VRN':'Verona','FLR':'Florence','MIL':'Milan','MAD':'Madrid',
    'KLN':'Cologne','MUN':'Munich','FKF':'Frankfurt','PRG':'Prague','WAR':'Warsaw',
    'MLB':'Melbourne','SYD':'Sydney','IST':'Istanbul','SP':'São Paulo',
    'BAB':'Biarritz-Bayonne','DJBA':'Djerba','POTI':'Potosi','LJU':'Ljubljana',
    'MLGA':'Malaga','PRT':'Perth','DJN':'Daejeon','KAT':'Kathmandu','RBA':'Rabat',
    'MTB':'Montauban','CAP':'Cap Fréhel','NOO':'Noordwijk','LCT':'La Ciotat','LBR':'Lubéron','PRP':'Perpignan','RDU':'Redu','MBSA':'Mombasa',
    'ANZR':'Anzère','FAO':'Faro','FRQ':'Forcalquier','MRAK':'Marrakesh',
    'CCU':'Cancun','GRU':'Grude','VLMO':'Valmorel','VSB':'Visby','ANVR':'Antwerpen',
    'CON':'Contis','ELT':'Eilat','HALM':'Halmstad','CHAR':'Charleroi',
    # Villes ajoutées
    'ORLN':'Orléans',
    'BBO':'Bilbao',
    'AMI':'Amiens',
    'CAPF':'Cap-Ferret','CF':'Cap-Ferret','CFT':'Cap-Ferret','CFRT':'Cap-Ferret',
    'ARN':'Arcachon','ARC':'Arcachon',
    'RON':'Royan','ROY':'Royan',
    'LROC':'La Rochelle','LRC':'La Rochelle',
    'BRG':'Bruges','BRUG':'Bruges',
    'LIS':'Lisbonne','LX':'Lisbonne','LSB':'Lisbonne',
    'GEN':'Gênes','GNS':'Gênes',
    'NPL':'Naples','NAP':'Naples',
    'VEN':'Venise','VCE':'Venise',
    'MAR':'Maroc','MRC':'Maroc',
    'TUN':'Tunis','TN':'Tunis',
    'LEGE':'Lège-Cap-Ferret','LGF':'Lège-Cap-Ferret'
    
}

@app.route('/api/cities')
def api_cities():
    if not load_database():
        return jsonify({'cities': []})
    cities = [{'code':c,'name':CITY_NAMES.get(c,c),'count':cities_cache[c]['count'],
               'lat':cities_cache[c]['lat'],'lng':cities_cache[c]['lng']} 
              for c in sorted(cities_cache, key=lambda x: cities_cache[x]['count'], reverse=True)]
    return jsonify({'cities': cities})

@app.route('/api/invaders')
def api_invaders():
    if not load_database():
        return jsonify({'invaders': []})
    city = request.args.get('city', 'PA').upper()
    invaders = invaders_cache.get(city, [])
    info = cities_cache.get(city, {'lat': 48.8566, 'lng': 2.3522})
    return jsonify({'city': city, 'invaders': invaders, 'center': {'lat': info['lat'], 'lng': info['lng']}})

@app.route('/api/proxy-image')
def proxy_image():
    """Proxy pour télécharger les images d'invader-spotter.art (contourne CORS)"""
    url = request.args.get('url', '')
    
    # Vérification de sécurité
    if not url:
        return Response('Missing URL parameter', status=400)
    
    allowed_domains = ['invader-spotter.art', 'www.invader-spotter.art']
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.netloc not in allowed_domains:
        return Response(f'Domain not allowed: {parsed.netloc}', status=400)
    
    try:
        import ssl
        import urllib.request
        
        # Créer un contexte SSL qui accepte tout (pour éviter les erreurs de certificat)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://www.invader-spotter.art/'
        })
        
        with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
            content = response.read()
            content_type = response.headers.get('Content-Type', 'image/jpeg')
            
            # Créer la réponse avec les bons headers
            resp = Response(content, mimetype=content_type)
            resp.headers['Cache-Control'] = 'public, max-age=86400'
            return resp
            
    except urllib.error.HTTPError as e:
        print(f"Proxy HTTPError for {url}: {e.code} {e.reason}")
        return Response(f'HTTP Error: {e.code}', status=e.code)
    except urllib.error.URLError as e:
        print(f"Proxy URLError for {url}: {e.reason}")
        return Response(f'URL Error: {e.reason}', status=502)
    except Exception as e:
        print(f"Proxy error for {url}: {type(e).__name__}: {e}")
        return Response(f'Error: {type(e).__name__}: {e}', status=500)

@app.route('/')
def index():
    return Response(HTML_PAGE, mimetype='text/html')

HTML_PAGE = '''<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <title>Total Invaders Search</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js" defer></script>
    <style>
        :root{--sat:env(safe-area-inset-top);--sab:env(safe-area-inset-bottom);--primary:#00ff88;--danger:#ff6b6b;--dark:#1a1a2e}
        *{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
        html,body{height:100%;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:var(--dark)}
        
        /* Mode sombre */
        .dark-mode .leaflet-tile{filter:invert(1) hue-rotate(180deg) brightness(0.9) contrast(0.9)}
        .dark-mode .leaflet-container{background:#1a1a2e}
        
        .app{display:flex;flex-direction:column;height:100%;padding-top:var(--sat)}
        .header{background:linear-gradient(135deg,var(--dark) 0%,#16213e 100%);padding:10px 12px;display:flex;flex-direction:column;gap:8px;align-items:center}
        .brand-title{font-size:16px;font-weight:700;color:var(--primary);text-shadow:0 0 10px rgba(0,255,136,0.5)}
        .brand-subtitle{font-size:11px;color:#aaa}
        .brand-subtitle span{color:#ffd93d;font-weight:600}
        .header-actions{display:flex;gap:8px;align-items:center;width:100%}
        .header-actions select{flex:1;padding:12px 10px;border:none;border-radius:10px;background:rgba(255,255,255,.12);color:#fff;font-size:15px}
        .hbtn{width:44px;height:44px;border:none;border-radius:12px;background:rgba(255,255,255,.12);color:#fff;font-size:20px}
        
        .stats{background:var(--dark);padding:6px 8px;display:flex;justify-content:space-around;color:#fff;font-size:11px;border-bottom:1px solid rgba(255,255,255,.1);flex-wrap:wrap}
        .stat{text-align:center;min-width:40px}
        .stat-val{font-weight:700;font-size:15px}
        .stat-hunt .stat-val{color:var(--danger)}
        .stat-flash .stat-val{color:var(--primary)}
        .stat-damaged .stat-val{color:#f59f00}
        .stat-hidden .stat-val{color:#9775fa}
        .stat-destroyed .stat-val{color:#868e96}
        .stat-findispo .stat-val{color:#607d8b}
        .stat-route .stat-val{color:#ffd93d}
        .stat-label{font-size:10px;color:#888;margin-top:2px}
        
        #map{flex:1;z-index:1}
        
        .bottombar{background:var(--dark);padding:8px 12px;padding-bottom:calc(8px + var(--sab));display:flex;gap:6px;border-top:1px solid rgba(255,255,255,.1);flex-wrap:wrap}
        .bbtn{flex:1;min-width:60px;padding:12px 8px;border:none;border-radius:12px;font-size:12px;font-weight:600;display:flex;flex-direction:column;align-items:center;gap:4px}
        .bbtn .ico{font-size:22px}
        .bbtn.primary{background:var(--primary);color:var(--dark)}
        .bbtn.secondary{background:rgba(255,255,255,.1);color:#fff}
        
        .panel{position:fixed;left:10px;right:10px;background:#fff;border-radius:20px;z-index:2000;box-shadow:0 -4px 30px rgba(0,0,0,.3);max-height:70vh;overflow:hidden;display:flex;flex-direction:column}
        .panel.bottom{bottom:80px;bottom:calc(80px + var(--sab))}
        .panel.top{top:calc(60px + var(--sat))}
        .panel.hidden{transform:translateY(20px);opacity:0;pointer-events:none}
        .panel-head{padding:16px;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center}
        .panel-head h3{font-size:17px}
        .panel-close{width:32px;height:32px;border:none;border-radius:50%;background:#f0f0f0;font-size:20px}
        .panel-body{padding:16px;overflow-y:auto;flex:1}
        
        .uid-input{width:100%;padding:16px;border:2px solid #eee;border-radius:14px;font-size:16px;margin-bottom:12px}
        .uid-input:focus{border-color:var(--primary);outline:none}
        .uid-btn{width:100%;padding:16px;border:none;border-radius:14px;background:var(--primary);color:var(--dark);font-size:16px;font-weight:600}
        .uid-help{margin-top:16px;padding:14px;background:#f8f9fa;border-radius:12px;font-size:13px;color:#666;line-height:1.6}
        
        .filter-row{display:flex;justify-content:space-between;align-items:center;padding:14px 0;border-bottom:1px solid #f0f0f0}
        .filter-row:last-child{border:none}
        .filter-label{font-size:15px}
        .toggle{width:52px;height:32px;background:#e0e0e0;border-radius:16px;position:relative;cursor:pointer}
        .toggle.on{background:var(--primary)}
        .toggle::after{content:'';position:absolute;width:28px;height:28px;background:#fff;border-radius:50%;top:2px;left:2px;transition:transform .3s}
        .toggle.on::after{transform:translateX(20px)}
        
        .route-item{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid #f0f0f0}
        .route-num{width:28px;height:28px;background:var(--dark);color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:600}
        .route-info{flex:1}
        .route-name{font-weight:500;font-size:15px}
        .route-pts{color:#888;font-size:13px}
        .route-del{width:36px;height:36px;border:none;border-radius:50%;background:#fee;color:var(--danger);font-size:18px}
        .route-total{padding:16px 0;text-align:center;font-size:20px;font-weight:700;color:var(--primary)}
        .route-actions{display:flex;gap:8px}
        .route-actions button{flex:1;padding:14px;border:none;border-radius:12px;font-size:14px;font-weight:600}
        .btn-gmaps{background:#4285f4;color:#fff}
        .btn-apple{background:#333;color:#fff}
        .btn-clear{background:#fee;color:var(--danger)}
        
        .search-select{width:100%;padding:16px;border:2px solid #eee;border-radius:12px;font-size:16px;background:#fff}
        .search-info{margin-top:12px;padding:12px;background:#f0f8ff;border-radius:10px;font-size:13px;color:#666;text-align:center}
        
        .pos-alert{position:fixed;top:calc(120px + var(--sat));left:10px;right:10px;background:#fff3cd;color:#856404;padding:14px 16px;border-radius:12px;z-index:1500;display:flex;align-items:center;gap:10px;box-shadow:0 4px 15px rgba(0,0,0,.15)}
        .pos-alert.error{background:#f8d7da;color:#721c24}
        .pos-alert.success{background:#d4edda;color:#155724}
        .pos-alert.hidden{display:none}
        
        /* Boutons flottants sur la carte - position plus basse pour ne pas masquer les stats */
        .legend-btn{position:absolute;bottom:calc(120px + var(--sab));left:10px;width:44px;height:44px;border:none;border-radius:50%;background:#fff;box-shadow:0 2px 10px rgba(0,0,0,.2);font-size:20px;z-index:500;cursor:pointer}
        .legend-panel{position:absolute;bottom:calc(170px + var(--sab));left:10px;background:#fff;border-radius:14px;padding:12px 16px;box-shadow:0 2px 15px rgba(0,0,0,.15);z-index:500;font-size:13px}
        .legend-panel.hidden{display:none}
        .leg-item{display:flex;align-items:center;gap:10px;padding:6px 0}
        .leg-dot{width:16px;height:16px;border-radius:4px}
        
        .leaflet-popup-content-wrapper{border-radius:14px;box-shadow:0 4px 20px rgba(0,0,0,.15)}
        .leaflet-popup-content{margin:10px 12px;min-width:180px}
        .pop-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:4px}
        .pop-name{font-size:16px;font-weight:600}
        .pop-name.hunt{color:#ff6b6b}
        .pop-name.flashed{color:#00aa55}
        .pop-name.damaged{color:#f59f00}
        .pop-name.hidden{color:#9775fa}
        .pop-name.destroyed{color:#868e96}
        .pop-badge{padding:3px 8px;border-radius:20px;font-size:10px;font-weight:600}
        .pop-badge.hunt{background:#fee;color:#c00}
        .pop-badge.flashed{background:#efe;color:#080}
        .pop-badge.damaged{background:#fff8e1;color:#f57c00}
        .pop-badge.hidden{background:#f3e5f5;color:#7b1fa2}
        .pop-badge.destroyed{background:#eee;color:#666}
        .pop-status{font-size:11px;color:#666;margin-bottom:4px;font-style:italic}
        .pop-status-change{font-size:11px;color:#e65100;margin-bottom:6px;padding:6px 8px;background:#fff3e0;border-radius:6px;border-left:3px solid #ff9800}
        .pop-status-prev{font-size:10px;color:#999;margin-left:4px}
        .pop-info{font-size:10px;color:#888;margin-bottom:4px;display:flex;flex-direction:column;gap:1px}
        .pop-info span{display:flex;align-items:center;gap:4px}
        .pop-pts{font-size:22px;font-weight:700;color:#ff6b6b;margin:4px 0}
        .pop-hint{color:#666;font-size:12px;margin-bottom:8px;padding:6px;background:#f8f9fa;border-radius:6px}
        .pop-photos{display:flex;justify-content:center;gap:8px;margin:6px 0}
        .pop-photos a{display:flex;align-items:center;justify-content:center;width:36px;height:36px;background:#f0f0f0;border-radius:10px;text-decoration:none;font-size:16px;transition:all .2s}
        .pop-photos a:hover{background:#667eea;transform:scale(1.1)}
        .pop-preview{width:100%;max-height:80px;object-fit:cover;border-radius:8px;margin-bottom:6px;cursor:pointer}
        .pop-preview:hover{opacity:.9}
        .pop-actions{display:flex;gap:6px}
        .pop-actions button{flex:1;padding:10px;border:none;border-radius:10px;font-size:13px;font-weight:600}
        
        .filter-section-title{font-size:11px;font-weight:600;color:#888;text-transform:uppercase;margin-bottom:8px;letter-spacing:.5px}
        .points-filter{display:flex;gap:6px;flex-wrap:wrap}
        .pts-btn{padding:8px 12px;border:2px solid #ddd;border-radius:8px;background:#fff;font-weight:600;font-size:13px;cursor:pointer;transition:all .2s}
        .pts-btn.on{border-color:#ff6b6b;background:#fff5f5;color:#ff6b6b}
        .pts-quick{padding:6px 12px;border:none;border-radius:6px;background:#f0f0f0;font-size:12px;cursor:pointer;margin:0 4px}
        .pts-quick:hover{background:#ddd}
        .pop-go{background:#4285f4;color:#fff}
        .pop-add{background:#ffd93d;color:#1a1a2e}
        
        .loading{position:fixed;inset:0;background:rgba(0,0,0,.85);display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:9999;color:#fff;gap:20px}
        .loading.hidden{display:none}
        .spinner{width:50px;height:50px;border:4px solid rgba(255,255,255,.2);border-top-color:var(--primary);border-radius:50%;animation:spin 1s linear infinite}
        @keyframes spin{to{transform:rotate(360deg)}}
        
        .gen-modal{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:3000;display:none;align-items:center;justify-content:center;padding:20px}
        .gen-modal.show{display:flex}
        .gen-content{background:#fff;border-radius:20px;max-width:400px;width:100%;max-height:85vh;overflow-y:auto}
        .gen-header{padding:16px;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center}
        .gen-header h3{margin:0;font-size:18px}
        .gen-close{background:none;border:none;font-size:24px;cursor:pointer}
        .gen-body{padding:16px}
        .gen-section{margin-bottom:20px}
        .gen-section h4{margin:0 0 10px;font-size:13px;color:#666;text-transform:uppercase}
        .gen-tabs{display:flex;gap:8px}
        .gen-tab{flex:1;padding:10px;border:2px solid #ddd;border-radius:8px;background:#fff;cursor:pointer;font-size:13px;text-align:center}
        .gen-tab.active{border-color:#ff6b6b;background:#fff5f5;color:#ff6b6b}
        .gen-options{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}
        .gen-opt{padding:12px;border:2px solid #eee;border-radius:10px;background:#fff;cursor:pointer;text-align:center}
        .gen-opt .val{font-size:18px;font-weight:700}
        .gen-opt .unit{font-size:11px;color:#888}
        .gen-opt.selected{border-color:#ff6b6b;background:#fff5f5}
        .gen-opt.selected .val{color:#ff6b6b}
        .gen-filters{display:flex;gap:8px;flex-wrap:wrap}
        .gen-filter{padding:8px 14px;border:1px solid #ddd;border-radius:20px;font-size:12px;cursor:pointer;background:#fff}
        .gen-filter.active{background:#ff6b6b;color:#fff;border-color:#ff6b6b}
        .gen-preview{padding:16px;background:linear-gradient(135deg,#e8f5e9,#f1f8e9);border-radius:14px;margin:16px 0}
        .gen-preview-title{text-align:center;font-weight:600;color:#2e7d32;margin-bottom:12px;font-size:14px}
        .gen-preview-stats{display:flex;justify-content:space-around;text-align:center}
        .gen-preview-stat .num{font-size:22px;font-weight:700;color:#ff6b6b}
        .gen-preview-stat .label{font-size:10px;color:#888}
        .gen-mode-tabs{display:flex;gap:8px;margin-bottom:8px}
        .gen-mode-tab{flex:1;padding:12px 8px;background:#f8f9fa;border:2px solid #e9ecef;border-radius:12px;text-align:center;cursor:pointer;font-size:13px;font-weight:600;color:#666;transition:all .2s}
        .gen-mode-tab:hover{border-color:#4dabf7;background:#e7f5ff}
        .gen-mode-tab.active{background:#ff6b6b;color:#fff;border-color:#ff6b6b}
        .gen-mode-tab .icon{display:block;font-size:20px;margin-bottom:4px}
        .gen-section.hidden{display:none}
        .gen-btn{width:100%;padding:14px;border:none;border-radius:12px;font-size:15px;font-weight:600;background:linear-gradient(135deg,#ff6b6b,#ee5a5a);color:#fff;cursor:pointer}
        .gen-btn:disabled{background:#ccc;cursor:not-allowed}
        
        /* Boutons outils parcours */
        .route-tools{display:flex;gap:6px;margin:10px 0;flex-wrap:wrap}
        .route-tool{padding:8px 12px;border:none;border-radius:8px;font-size:12px;cursor:pointer;display:flex;align-items:center;gap:4px}
        .route-tool.tsp{background:#e3f2fd;color:#1565c0}
        .route-tool.circuit{background:#f3e5f5;color:#7b1fa2}
        .route-tool.circuit.active{background:#7b1fa2;color:#fff}
        .route-tool.gpx{background:#e8f5e9;color:#2e7d32}
        .route-tool.nearby{background:#fff3e0;color:#e65100}
        
        /* Highlight invaders proches */
        .nearby-highlight{animation:pulse-nearby 1s ease-in-out infinite}
        @keyframes pulse-nearby{0%,100%{transform:scale(1);filter:drop-shadow(0 0 4px #ff6b6b)}50%{transform:scale(1.2);filter:drop-shadow(0 0 8px #ff6b6b)}}
        
        /* Popup actions supplémentaires */
        .pop-extra{display:flex;gap:4px;margin-top:6px;flex-wrap:wrap}
        .pop-extra button{flex:1;min-width:60px;padding:6px 4px;border:1px solid #ddd;border-radius:6px;background:#fff;font-size:10px;cursor:pointer}
        .pop-extra button:hover{background:#f5f5f5}
        .pop-note{margin-top:8px;padding:8px;background:#fffde7;border-radius:8px;font-size:12px;color:#f57f17;border-left:3px solid #ffc107}
        .pop-geo-hint{margin-top:4px;padding:6px 8px;background:#e3f2fd;border-radius:6px;font-size:10px;color:#1565c0;border-left:3px solid #42a5f5;line-height:1.4;word-break:break-word}
        .pop-geo-hint .hint-label{font-weight:600;color:#0d47a1}
        .pop-geo-confidence{display:inline-flex;align-items:center;gap:3px;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600}
        .pop-geo-confidence.high{background:#e8f5e9;color:#2e7d32}
        .pop-geo-confidence.medium{background:#fff8e1;color:#f57f17}
        .pop-geo-confidence.low{background:#fff3e0;color:#e65100}
        .pop-geo-confidence.very_low{background:#ffebee;color:#c62828}
        .pop-user-status{margin-top:6px;padding:6px 8px;background:#ffebee;border-radius:6px;font-size:11px;color:#c62828}
        
        /* Modal image plein écran */
        .img-modal{position:fixed;inset:0;background:rgba(0,0,0,.95);z-index:9999;display:none;align-items:center;justify-content:center;flex-direction:column}
        .img-modal.show{display:flex}
        .img-modal img{max-width:100%;max-height:calc(100vh - 80px);object-fit:contain}
        .img-modal-close{position:absolute;top:calc(20px + var(--sat));right:20px;width:44px;height:44px;border:none;border-radius:50%;background:rgba(255,255,255,.2);color:#fff;font-size:24px;cursor:pointer;display:flex;align-items:center;justify-content:center}
        .img-modal-close:hover{background:rgba(255,255,255,.3)}
        .img-modal-title{position:absolute;bottom:calc(20px + var(--sab));left:0;right:0;text-align:center;color:#fff;font-size:14px;font-weight:600}
        .img-modal-loading{color:#fff;font-size:16px}
        
        /* Modal signalement/note */
        .report-modal{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:4000;display:none;align-items:center;justify-content:center;padding:20px}
        .report-modal.show{display:flex}
        .report-content{background:#fff;border-radius:16px;max-width:340px;width:100%;padding:20px;max-height:85vh;overflow-y:auto}
        .report-title{font-size:18px;font-weight:700;margin-bottom:16px;display:flex;align-items:center;gap:8px}
        .report-options{display:flex;flex-direction:column;gap:8px}
        .report-opt{padding:12px;border:2px solid #eee;border-radius:10px;background:#fff;cursor:pointer;text-align:left;font-size:14px}
        .report-opt:hover{border-color:#ff6b6b;background:#fff5f5}
        .report-opt.selected{border-color:#ff6b6b;background:#fff5f5}
        .report-textarea{width:100%;padding:12px;border:2px solid #eee;border-radius:10px;font-size:14px;resize:none;margin-top:12px}
        .report-textarea:focus{outline:none;border-color:#667eea}
        .report-actions{display:flex;gap:8px;margin-top:16px}
        .report-actions button{flex:1;padding:12px;border:none;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer}
        .report-cancel{background:#f5f5f5;color:#666}
        .report-save{background:#ff6b6b;color:#fff}
        
        /* Indicateur offline */
        .offline-indicator{position:fixed;top:calc(70px + var(--sat));left:50%;transform:translateX(-50%);background:linear-gradient(135deg,#ff9800,#f57c00);color:#fff;padding:8px 20px;border-radius:25px;font-size:13px;font-weight:700;z-index:9000;display:none;align-items:center;gap:8px;box-shadow:0 4px 15px rgba(255,152,0,.4);animation:slideDown .3s ease}
        .offline-indicator.show{display:flex}
        .offline-dot{width:10px;height:10px;background:#fff;border-radius:50%;animation:blink 1s infinite}
        @keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
        @keyframes slideDown{from{transform:translateX(-50%) translateY(-20px);opacity:0}to{transform:translateX(-50%) translateY(0);opacity:1}}
        
        /* Stats détaillées */
        .stats-panel{padding:16px}
        .stats-city{margin-bottom:20px}
        .stats-city-name{font-size:18px;font-weight:700;margin-bottom:8px}
        .stats-progress{height:8px;background:#eee;border-radius:4px;overflow:hidden;margin-bottom:8px}
        .stats-progress-bar{height:100%;background:linear-gradient(90deg,#00aa55,#4caf50);transition:width .3s}
        .stats-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
        .stats-item{padding:10px;background:#f8f9fa;border-radius:8px;text-align:center}
        .stats-item-val{font-size:20px;font-weight:700}
        .stats-item-label{font-size:11px;color:#888}
        
        /* Replay journées */
        .replay-day{display:flex;align-items:center;gap:10px;padding:10px;background:#f8f9fa;border-radius:8px;margin-bottom:6px;cursor:pointer;transition:all .2s}
        .replay-day:hover{background:#e3f2fd}
        .replay-day.active{background:#bbdefb;border:2px solid #2196f3}
        .replay-day-date{font-weight:600;font-size:13px;min-width:90px}
        .replay-day-count{font-size:12px;color:#666}
        .replay-day-pts{font-size:11px;color:#00aa55;font-weight:600}
        .replay-day-btn{margin-left:auto;padding:6px 12px;border:none;border-radius:6px;background:#667eea;color:#fff;font-size:11px;cursor:pointer}
        
        /* Toggle mode sombre - à côté du bouton légende */
        .dark-toggle{position:absolute;bottom:calc(120px + var(--sab));left:62px;width:44px;height:44px;border:none;border-radius:50%;background:#fff;box-shadow:0 2px 10px rgba(0,0,0,.2);font-size:20px;z-index:500;cursor:pointer}
        .dark-toggle.active{background:#1a1a2e;color:#ffd93d}
        
        /* Radar Mode */
        .radar-active{background:linear-gradient(135deg,#00c853,#00aa55)!important;animation:radar-glow 2s infinite}
        @keyframes radar-glow{0%,100%{box-shadow:0 0 0 0 rgba(0,200,83,.4)}50%{box-shadow:0 0 0 10px rgba(0,200,83,0)}}
        .radar-indicator{position:fixed;top:calc(70px + var(--sat));left:50%;transform:translateX(-50%);background:linear-gradient(135deg,#00c853,#00aa55);color:#fff;padding:10px 20px;border-radius:25px;font-size:13px;font-weight:700;z-index:1500;display:none;align-items:center;gap:10px;box-shadow:0 4px 15px rgba(0,200,83,.4)}
        .radar-indicator.show{display:flex}
        .radar-pulse{width:12px;height:12px;background:#fff;border-radius:50%;animation:blink 1s infinite}
        .radar-distance{position:fixed;top:calc(110px + var(--sat));left:50%;transform:translateX(-50%);background:rgba(0,0,0,.8);color:#fff;padding:8px 16px;border-radius:20px;font-size:16px;font-weight:700;z-index:1500;display:none}
        .radar-distance.show{display:block}
        .radar-arrow{position:fixed;top:50%;left:50%;width:80px;height:80px;transform:translate(-50%,-50%);z-index:1400;display:none;pointer-events:none;filter:drop-shadow(0 2px 8px rgba(0,0,0,.4))}
        .radar-arrow.show{display:block}
        .radar-arrow svg{width:100%;height:100%;transition:transform .3s ease-out}
        .radar-alert{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:linear-gradient(135deg,#ff6b6b,#ee5a5a);color:#fff;padding:20px 30px;border-radius:20px;font-size:18px;font-weight:700;z-index:2000;display:none;flex-direction:column;align-items:center;gap:8px;box-shadow:0 8px 30px rgba(255,107,107,.5);animation:alert-pop .3s ease}
        .radar-alert.show{display:flex}
        .radar-alert-icon{font-size:40px}
        .radar-alert-sub{font-size:14px;opacity:.9}
        @keyframes alert-pop{0%{transform:translate(-50%,-50%) scale(.8);opacity:0}100%{transform:translate(-50%,-50%) scale(1);opacity:1}}
        
        /* Clusters */
        .cluster-marker{cursor:pointer;transition:transform .2s}
        .cluster-marker:hover{transform:scale(1.1)}
        
        /* Chart period buttons */
        .chart-period-btn{padding:6px 12px;border:1px solid #ddd;border-radius:6px;background:#fff;font-size:11px;cursor:pointer;transition:all .2s}
        .chart-period-btn:hover{border-color:#667eea}
        .chart-period-btn.active{background:#667eea;color:#fff;border-color:#667eea}
        .chart-mode-btn{padding:6px 10px;border:1px solid #ddd;border-radius:6px;background:#fff;font-size:11px;cursor:pointer;transition:all .2s}
        .chart-mode-btn:hover{border-color:#00aa55}
        .chart-mode-btn.active{background:#00aa55;color:#fff;border-color:#00aa55}
        
        /* Mode paysage - réduire header et toolbar */
        @media (orientation:landscape) and (max-height:500px){
            .header{padding:4px 10px;flex-direction:row;gap:10px}
            .brand-title{font-size:14px}
            .brand-subtitle{display:none}
            .header-actions{width:auto;flex:1}
            .header-actions select{padding:8px 10px;font-size:13px}
            .hbtn{width:36px;height:36px;font-size:16px;border-radius:8px}
            .stats{padding:3px 8px}
            .stat-val{font-size:13px}
            .stat-label{display:none}
            .bottombar{padding:4px 8px;padding-bottom:calc(4px + var(--sab))}
            .bbtn{padding:6px 6px;font-size:10px;border-radius:8px}
            .bbtn .ico{font-size:18px}
            .panel{max-height:60vh}
            /* Légende et dark toggle en mode paysage - à droite de la carte */
            .legend-btn{bottom:auto;top:10px;right:60px;left:auto;width:36px;height:36px;font-size:16px}
            .legend-panel{bottom:auto;top:50px;right:10px;left:auto;font-size:11px;padding:8px 12px}
            .leg-item{padding:3px 0}
            .leg-dot{width:12px;height:12px}
            .dark-toggle{bottom:auto;top:10px;right:10px;left:auto;width:36px;height:36px;font-size:16px}
        }
        /* Mode portrait petit écran - barre du bas sur 2 lignes */
        @media (max-width:430px) and (orientation:portrait){
            .bottombar{gap:4px;padding:6px 8px;padding-bottom:calc(6px + var(--sab))}
            .bbtn{flex:1 1 calc(25% - 4px);min-width:0;padding:8px 4px;font-size:10px;border-radius:8px}
            .bbtn .ico{font-size:18px}
        }
    </style>
</head>
<body>
<div class="app">
    <div class="header">
        <div class="brand-title">👾 Total Invaders Search</div>
        <div class="brand-subtitle">Powered by <span>Jojosh1er</span></div>
        <div class="header-actions">
            <select id="citySelect" onchange="changeCity()"></select>
            <button class="hbtn" onclick="showUid()">🔑</button>
            <button class="hbtn" onclick="showHelp()">❓</button>
        </div>
    </div>
    
    <div class="stats">
        <div class="stat stat-hunt"><div class="stat-val" id="sHunt">-</div><div class="stat-label">CHASSE</div></div>
        <div class="stat stat-flash"><div class="stat-val" id="sFlash">-</div><div class="stat-label">FLASHÉ</div></div>
        <div class="stat" style="background:#e8f5e9"><div class="stat-val" id="sRestored" style="color:#2e7d32">-</div><div class="stat-label" style="color:#388e3c">RESTAURÉ</div></div>
        <div class="stat stat-damaged"><div class="stat-val" id="sDamaged">-</div><div class="stat-label">ABÎMÉ</div></div>
        <div class="stat stat-hidden"><div class="stat-val" id="sHidden">-</div><div class="stat-label">CACHÉ</div></div>
        <div class="stat stat-destroyed"><div class="stat-val" id="sDestroyed">-</div><div class="stat-label">DÉTRUIT</div></div>
        <div class="stat stat-findispo"><div class="stat-val" id="sFlashedIndispo">-</div><div class="stat-label">F+RIP</div></div>
        <div class="stat stat-route"><div class="stat-val" id="sRoute">0</div><div class="stat-label">ROUTE</div></div>
    </div>
    
    <div id="map"></div>
    
    <button class="legend-btn" onclick="toggleLegend()">🎨</button>
    <div class="legend-panel hidden" id="legendPanel">
        <div class="leg-item"><div class="leg-dot" style="background:#ff6b6b"></div>À chasser</div>
        <div class="leg-item"><div class="leg-dot" style="background:#00aa55"></div>Flashé</div>
        <div class="leg-item"><div class="leg-dot" style="background:#f59f00"></div>Abîmé</div>
        <div class="leg-item"><div class="leg-dot" style="background:#9775fa"></div>Caché</div>
        <div class="leg-item"><div class="leg-dot" style="background:#868e96"></div>Détruit</div>
        <div class="leg-item"><div class="leg-dot" style="background:#9c27b0"></div>Flashé+caché</div>
        <div class="leg-item"><div class="leg-dot" style="background:#607d8b"></div>Flashé+détruit</div>
        <div class="leg-item"><div class="leg-dot" style="background:#17a2b8"></div>Position inconnue</div>
        <div class="leg-item"><div class="leg-dot" style="background:#ffd93d"></div>Mon parcours</div>
    </div>
    
    <button class="dark-toggle" id="darkToggle" onclick="toggleDarkMode()">🌙</button>
    
    <div class="offline-indicator" id="offlineIndicator"><span class="offline-dot"></span>Mode hors-ligne</div>
    
    <div class="radar-indicator" id="radarIndicator"><span class="radar-pulse"></span><span id="radarStatus">Radar actif</span></div>
    <div class="radar-arrow" id="radarArrow">
        <svg viewBox="0 0 100 100"><polygon points="50,15 65,85 50,70 35,85" fill="#ff6b6b"/></svg>
    </div>
    <div class="radar-distance" id="radarDistance">--m</div>
    <div class="radar-alert" id="radarAlert"><span class="radar-alert-icon">👾</span><span id="radarAlertName">--</span><span class="radar-alert-sub">à moins de 50m!</span></div>
    
    <div class="pos-alert hidden" id="posAlert"><span id="posIcon"></span><span id="posMsg"></span></div>
    
    <div class="bottombar">
        <button class="bbtn primary" onclick="centerOnMe()"><span class="ico">📍</span>Position</button>
        <button class="bbtn secondary" id="radarBtn" onclick="toggleRadar()"><span class="ico">📡</span>Radar</button>
        <button class="bbtn secondary" onclick="showSearch()"><span class="ico">🔍</span>Chercher</button>
        <button class="bbtn secondary" onclick="showRoute()"><span class="ico">🗺️</span>Parcours</button>
        <button class="bbtn secondary" onclick="showStats()"><span class="ico">📊</span>Stats</button>
        <button class="bbtn secondary" onclick="openNewInvaderReport()"><span class="ico">➕</span>Nouveau</button>
        <button class="bbtn secondary" onclick="showFilters()"><span class="ico">⚙️</span>Filtres</button>
    </div>
</div>

<div class="loading hidden" id="loading"><div class="spinner"></div><div id="loadingText">Chargement...</div></div>

<!-- Modal Signalement/Note -->
<div class="report-modal" id="reportModal" onclick="if(event.target===this)closeReportModal()">
    <div class="report-content">
        <div class="report-title" id="reportTitle">📝 Signaler</div>
        <div id="reportBody">
            <!-- Contenu dynamique -->
        </div>
        <div class="report-actions">
            <button class="report-cancel" onclick="closeReportModal()">Annuler</button>
            <button class="report-save" onclick="saveReport()">Enregistrer</button>
        </div>
    </div>
</div>

<div class="panel top hidden" id="uidPanel">
    <div class="panel-head"><h3>🔑 Mon compte FlashInvaders</h3><button class="panel-close" onclick="hidePanel('uidPanel')">✕</button></div>
    <div class="panel-body">
        <input class="uid-input" id="uidInput" placeholder="Ton UID FlashInvaders">
        <button class="uid-btn" onclick="loadFlashed()">Charger mes flashés</button>
        <div class="uid-help">Ton UID se trouve dans les requêtes réseau de l'app FlashInvaders. Utilise mitmproxy ou les outils développeur pour l'intercepter.</div>
    </div>
</div>

<div class="panel bottom hidden" id="filterPanel">
    <div class="panel-head"><h3>⚙️ Filtres</h3><button class="panel-close" onclick="hidePanel('filterPanel')">✕</button></div>
    <div class="panel-body">
        <div class="filter-section-title">Par statut</div>
        <div class="filter-row"><span class="filter-label">🔴 À chasser</span><div class="toggle on" id="tHunt" onclick="toggleFilter('tHunt')"></div></div>
        <div class="filter-row"><span class="filter-label">♻️ Restaurés</span><div class="toggle" id="tRestored" onclick="toggleFilter('tRestored')"></div></div>
        <div class="filter-row"><span class="filter-label">✅ Flashés</span><div class="toggle" id="tFlash" onclick="toggleFilter('tFlash')"></div></div>
        <div class="filter-row"><span class="filter-label">🟡 Abîmés</span><div class="toggle on" id="tDamaged" onclick="toggleFilter('tDamaged')"></div></div>
        <div class="filter-row"><span class="filter-label">🟣 Cachés</span><div class="toggle" id="tHidden" onclick="toggleFilter('tHidden')"></div></div>
        <div class="filter-row"><span class="filter-label">⚫ Détruits</span><div class="toggle" id="tDestroyed" onclick="toggleFilter('tDestroyed')"></div></div>
        <div class="filter-row"><span class="filter-label">💀 Flashés indispo</span><div class="toggle" id="tFlashedIndispo" onclick="toggleFilter('tFlashedIndispo')"></div></div>
        
        <div class="filter-section-title" style="margin-top:16px">Par position</div>
        <div class="filter-row"><span class="filter-label">🔵 Position inconnue</span><div class="toggle on" id="tUnknownLoc" onclick="toggleFilter('tUnknownLoc')"></div></div>
        <div style="font-size:11px;color:#888;margin-top:4px;padding-left:4px">Affiche les invaders dont la localisation est approximative</div>
        
        <div class="filter-section-title" style="margin-top:16px">Par points</div>
        <div class="points-filter">
            <button class="pts-btn on" id="pts10" onclick="togglePtsFilter('pts10')">10</button>
            <button class="pts-btn on" id="pts20" onclick="togglePtsFilter('pts20')">20</button>
            <button class="pts-btn on" id="pts30" onclick="togglePtsFilter('pts30')">30</button>
            <button class="pts-btn on" id="pts40" onclick="togglePtsFilter('pts40')">40</button>
            <button class="pts-btn on" id="pts50" onclick="togglePtsFilter('pts50')">50</button>
            <button class="pts-btn on" id="pts100" onclick="togglePtsFilter('pts100')">100</button>
        </div>
        <div style="text-align:center;margin-top:8px">
            <button class="pts-quick" onclick="ptsOnly(50,100)">🎯 50+ pts</button>
            <button class="pts-quick" onclick="ptsAll()">Tous</button>
        </div>
        
        <div class="filter-section-title" style="margin-top:16px">Raccourcis</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="pts-quick" onclick="filterUnknownOnly()" style="background:#e3f2fd;color:#1565c0">📍 Position inconnue seule</button>
            <button class="pts-quick" onclick="filterReset()">🔄 Réinitialiser</button>
        </div>
    </div>
</div>

<div class="panel bottom hidden" id="routePanel">
    <div class="panel-head"><h3>🗺️ Mon parcours</h3><button class="panel-close" onclick="hidePanel('routePanel')">✕</button></div>
    <div class="panel-body">
        <div id="startPointInfo" style="display:none;padding:10px 12px;background:#e3f2fd;border-radius:10px;margin-bottom:12px;font-size:13px;color:#1565c0">
            📍 <b>Départ:</b> <span id="startPointText">Ma position</span>
            <button onclick="clearStartPoint()" style="float:right;background:none;border:none;color:#c00;font-size:16px;cursor:pointer" title="Supprimer le point de départ">✕</button>
        </div>
        <div id="noStartHint" style="padding:10px 12px;background:#fff3e0;border-radius:10px;margin-bottom:12px;font-size:13px;color:#e65100">
            💡 <b>Astuce:</b> Clic long sur la carte pour définir un point de départ
        </div>
        
        <!-- Outils de parcours -->
        <div class="route-tools">
            <button class="route-tool nearby" onclick="findNearby()">📍 10 proches</button>
            <button class="route-tool nearby" onclick="addNearbyToRoute()" title="Ajouter les 10 proches au parcours">➕ Ajouter</button>
            <button class="route-tool tsp" onclick="optimizeRoute()">🔀 Optimiser</button>
            <button class="route-tool circuit" id="circuitToggle" onclick="toggleCircuit()">🔄 Circuit</button>
            <button class="route-tool gpx" onclick="exportGPX()">💾 GPX</button>
        </div>
        
        <div id="routeList"></div>
        <div class="route-total" id="routeTotal">0 points</div>
        <div id="routeDistance" style="font-size:12px;color:#666;text-align:center;margin-bottom:8px"></div>
        <div class="route-actions">
            <button class="btn-gmaps" onclick="openGMaps()">Google</button>
            <button class="btn-apple" onclick="openApple()">Apple</button>
            <button class="btn-clear" onclick="clearRoute()">Vider</button>
        </div>
        <button style="width:100%;margin-top:16px;padding:14px;border:none;border-radius:12px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;font-size:15px;font-weight:600;cursor:pointer" onclick="showRouteGenerator()">🚶 Générer un parcours automatique</button>
    </div>
</div>

<div class="panel top hidden" id="searchPanel">
    <div class="panel-head"><h3>🔍 Rechercher</h3><button class="panel-close" onclick="hidePanel('searchPanel')">✕</button></div>
    <div class="panel-body">
        <select class="search-select" id="invaderSelect" onchange="goToInvader()"><option value="">-- Choisis un invader --</option></select>
        <div class="search-info" id="searchInfo">Sélectionne une ville</div>
    </div>
</div>

<div class="panel top hidden" id="helpPanel" style="max-height:85vh">
    <div class="panel-head"><h3>❓ Guide complet</h3><button class="panel-close" onclick="hidePanel('helpPanel')">✕</button></div>
    <div class="panel-body" style="font-size:13px;line-height:1.5">
        
        <!-- Navigation rapide -->
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid #eee">
            <a href="#help-start" style="padding:6px 10px;background:#e3f2fd;border-radius:6px;color:#1565c0;text-decoration:none;font-size:11px">🚀 Démarrage</a>
            <a href="#help-buttons" style="padding:6px 10px;background:#e8f5e9;border-radius:6px;color:#2e7d32;text-decoration:none;font-size:11px">🎮 Boutons</a>
            <a href="#help-map" style="padding:6px 10px;background:#fff3e0;border-radius:6px;color:#e65100;text-decoration:none;font-size:11px">🗺️ Carte</a>
            <a href="#help-report" style="padding:6px 10px;background:#fce4ec;border-radius:6px;color:#c2185b;text-decoration:none;font-size:11px">📢 Signaler</a>
            <a href="#help-offline" style="padding:6px 10px;background:#f3e5f5;border-radius:6px;color:#7b1fa2;text-decoration:none;font-size:11px">📴 Hors-ligne</a>
        </div>
        
        <!-- SECTION: Démarrage rapide -->
        <div id="help-start" style="margin-bottom:20px">
            <h4 style="margin:0 0 10px;color:#1a1a2e;display:flex;align-items:center;gap:8px">
                <span style="background:#e3f2fd;padding:4px 8px;border-radius:6px">🚀</span> Démarrage rapide
            </h4>
            <div style="background:#f8f9fa;padding:12px;border-radius:10px">
                <p style="margin:0 0 8px"><b>1.</b> Sélectionne une <b>ville</b> dans le menu déroulant en haut</p>
                <p style="margin:0 0 8px"><b>2.</b> Clique sur <b>📍 Position</b> pour te localiser sur la carte</p>
                <p style="margin:0 0 8px"><b>3.</b> Entre ton <b>UID FlashInvaders</b> (🔑) pour voir tes invaders flashés en vert</p>
                <p style="margin:0"><b>4.</b> Clique sur un invader pour voir ses infos et l'ajouter à ton parcours</p>
            </div>
        </div>
        
        <!-- SECTION: Boutons principaux -->
        <div id="help-buttons" style="margin-bottom:20px">
            <h4 style="margin:0 0 10px;color:#1a1a2e;display:flex;align-items:center;gap:8px">
                <span style="background:#e8f5e9;padding:4px 8px;border-radius:6px">🎮</span> Boutons principaux
            </h4>
            <div style="display:grid;gap:8px">
                <div style="background:#f8f9fa;padding:10px;border-radius:8px;display:flex;gap:10px">
                    <span style="font-size:20px">📍</span>
                    <div><b>Position</b><br><span style="color:#666;font-size:12px">Te géolocalise sur la carte. Maintiens appuyé pour activer le suivi GPS continu.</span></div>
                </div>
                <div style="background:#f8f9fa;padding:10px;border-radius:8px;display:flex;gap:10px">
                    <span style="font-size:20px">🔍</span>
                    <div><b>Chercher</b><br><span style="color:#666;font-size:12px">Recherche un invader par son nom (ex: PA_1234). Affiche la liste triée par catégorie.</span></div>
                </div>
                <div style="background:#f8f9fa;padding:10px;border-radius:8px;display:flex;gap:10px">
                    <span style="font-size:20px">🗺️</span>
                    <div><b>Parcours</b><br><span style="color:#666;font-size:12px">Gère ton itinéraire de chasse. Ajoute jusqu'à 20 invaders et exporte vers Google Maps ou Apple Plans.</span></div>
                </div>
                <div style="background:#f8f9fa;padding:10px;border-radius:8px;display:flex;gap:10px">
                    <span style="font-size:20px">📊</span>
                    <div><b>Stats</b><br><span style="color:#666;font-size:12px">Statistiques, replay des journées de chasse, heatmap des zones à explorer, mode hors-ligne.</span></div>
                </div>
                <div style="background:#f8f9fa;padding:10px;border-radius:8px;display:flex;gap:10px">
                    <span style="font-size:20px">⚙️</span>
                    <div><b>Filtres</b><br><span style="color:#666;font-size:12px">Affiche/masque les invaders par statut (flashés, détruits...) ou par points.</span></div>
                </div>
            </div>
        </div>
        
        <!-- SECTION: Boutons header -->
        <div style="margin-bottom:20px">
            <h4 style="margin:0 0 10px;color:#1a1a2e">🔝 Boutons du haut</h4>
            <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px">
                <div style="background:#f8f9fa;padding:8px;border-radius:8px;text-align:center">
                    <span style="font-size:18px">🔑</span><br><span style="font-size:11px">Compte FlashInvaders</span>
                </div>
                <div style="background:#f8f9fa;padding:8px;border-radius:8px;text-align:center">
                    <span style="font-size:18px">🎨</span><br><span style="font-size:11px">Légende couleurs</span>
                </div>
                <div style="background:#f8f9fa;padding:8px;border-radius:8px;text-align:center">
                    <span style="font-size:18px">🌙</span><br><span style="font-size:11px">Mode sombre</span>
                </div>
                <div style="background:#f8f9fa;padding:8px;border-radius:8px;text-align:center">
                    <span style="font-size:18px">❓</span><br><span style="font-size:11px">Cette aide</span>
                </div>
            </div>
        </div>
        
        <!-- SECTION: Carte et marqueurs -->
        <div id="help-map" style="margin-bottom:20px">
            <h4 style="margin:0 0 10px;color:#1a1a2e;display:flex;align-items:center;gap:8px">
                <span style="background:#fff3e0;padding:4px 8px;border-radius:6px">🗺️</span> Carte et marqueurs
            </h4>
            <div style="background:#f8f9fa;padding:12px;border-radius:10px;margin-bottom:10px">
                <p style="margin:0 0 8px"><b>Taille des marqueurs</b> = points de l'invader (plus gros = plus de points)</p>
                <p style="margin:0 0 8px"><b>Contour jaune</b> = invader dans ton parcours actuel</p>
                <p style="margin:0 0 8px"><b>Animation pulsante</b> = invaders proches de toi (fonction "Proximité")</p>
                <p style="margin:0"><b>Clic sur marqueur</b> = ouvre la popup avec infos et actions</p>
            </div>
            <h5 style="margin:10px 0 8px;font-size:13px">🎨 Couleurs des marqueurs</h5>
            <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:6px">
                <div style="display:flex;align-items:center;gap:6px"><span style="color:#ff6b6b;font-size:18px">●</span><span>À chasser</span></div>
                <div style="display:flex;align-items:center;gap:6px"><span style="color:#00aa55;font-size:18px">●</span><span>Flashé</span></div>
                <div style="display:flex;align-items:center;gap:6px"><span style="color:#f59f00;font-size:18px">●</span><span>Abîmé</span></div>
                <div style="display:flex;align-items:center;gap:6px"><span style="color:#9775fa;font-size:18px">●</span><span>Caché</span></div>
                <div style="display:flex;align-items:center;gap:6px"><span style="color:#868e96;font-size:18px">●</span><span>Détruit</span></div>
                <div style="display:flex;align-items:center;gap:6px"><span style="color:#17a2b8;font-size:18px">●</span><span>Position inconnue</span></div>
                <div style="display:flex;align-items:center;gap:6px"><span style="color:#ffd93d;font-size:18px">●</span><span>Dans le parcours</span></div>
            </div>
        </div>
        
        <!-- SECTION: Popup invader -->
        <div style="margin-bottom:20px">
            <h4 style="margin:0 0 10px;color:#1a1a2e">💬 Popup d'un invader</h4>
            <div style="background:#f8f9fa;padding:12px;border-radius:10px">
                <p style="margin:0 0 6px"><b>🎨 / 📍</b> - Photos de la mosaïque et du lieu</p>
                <p style="margin:0 0 6px"><b>➕ / ➖</b> - Ajouter/retirer du parcours</p>
                <p style="margin:0 0 6px"><b>⚠️ Signaler</b> - Signaler un changement de statut (local)</p>
                <p style="margin:0 0 6px"><b>📝 Note</b> - Ajouter une note personnelle (locale)</p>
                <p style="margin:0"><b>🐙 GitHub</b> - Signaler officiellement (statut + position GPS)</p>
            </div>
        </div>
        
        <!-- SECTION: Signaler -->
        <div id="help-report" style="margin-bottom:20px">
            <h4 style="margin:0 0 10px;color:#1a1a2e;display:flex;align-items:center;gap:8px">
                <span style="background:#fce4ec;padding:4px 8px;border-radius:6px">📢</span> Signaler un invader
            </h4>
            <div style="background:#fff5f5;padding:12px;border-radius:10px;border:1px solid #ffcdd2">
                <p style="margin:0 0 8px"><b>⚠️ Signaler (local)</b></p>
                <p style="margin:0 0 12px;font-size:12px;color:#666">Change le statut visuellement sur ton appareil uniquement. Pratique pour noter un invader détruit sans connexion.</p>
                
                <p style="margin:0 0 8px"><b>🐙 GitHub (officiel)</b></p>
                <p style="margin:0 0 8px;font-size:12px;color:#666">Crée une issue GitHub pour signaler officiellement :</p>
                <ul style="margin:0 0 8px 16px;padding:0;font-size:12px;color:#666">
                    <li><b>Changement de statut</b> - L'invader est détruit, abîmé...</li>
                    <li><b>Position GPS</b> - Capture ta position actuelle si tu es devant l'invader !</li>
                    <li><b>Photos</b> - URL d'une image de l'invader ou du lieu</li>
                </ul>
                
                <p style="margin:0 0 8px"><b>➕ Nouvel invader</b></p>
                <p style="margin:0 0 8px;font-size:12px;color:#666">Tu as trouvé un invader qui n'est pas dans la base ? Utilise le bouton <b>➕ Nouveau</b> dans la barre du bas pour le signaler avec son code, sa position GPS et des photos.</p>
                
                <p style="margin:0;font-size:11px;color:#888">💡 Les positions approximatives (cyan) ont besoin de tes signalements GPS !</p>
            </div>
        </div>
        
        <!-- SECTION: Parcours -->
        <div style="margin-bottom:20px">
            <h4 style="margin:0 0 10px;color:#1a1a2e">🛣️ Créer un parcours</h4>
            <div style="background:#f8f9fa;padding:12px;border-radius:10px">
                <p style="margin:0 0 8px"><b>1.</b> Clique sur des invaders et utilise <b>➕</b> pour les ajouter (max 20)</p>
                <p style="margin:0 0 8px"><b>2.</b> Ouvre <b>🗺️ Parcours</b> pour voir la liste et réorganiser</p>
                <p style="margin:0 0 8px"><b>3.</b> Utilise <b>🚀 Générer parcours auto</b> pour optimiser l'ordre</p>
                <p style="margin:0 0 8px"><b>4.</b> Exporte vers <b>Google Maps</b> ou <b>Apple Plans</b></p>
                <p style="margin:0;font-size:12px;color:#666">💡 Le parcours reste affiché même si tu changes de ville</p>
            </div>
        </div>
        
        <!-- SECTION: Générateur automatique -->
        <div style="margin-bottom:20px">
            <h4 style="margin:0 0 10px;color:#1a1a2e">🚀 Générateur de parcours</h4>
            <div style="background:#e8f5e9;padding:12px;border-radius:10px">
                <p style="margin:0 0 8px"><b>Point de départ</b> : Ta position, le centre ville, ou un point personnalisé (clic long sur la carte)</p>
                <p style="margin:0 0 8px"><b>Filtres</b> : Par points minimum, par arrondissement (Paris)</p>
                <p style="margin:0 0 8px"><b>Algorithme</b> : Nearest Neighbor ou Circuit fermé</p>
                <p style="margin:0;font-size:12px;color:#666">💡 L'algorithme optimise l'ordre pour minimiser la distance totale</p>
            </div>
        </div>
        
        <!-- SECTION: Mode hors-ligne -->
        <div id="help-offline" style="margin-bottom:20px">
            <h4 style="margin:0 0 10px;color:#1a1a2e;display:flex;align-items:center;gap:8px">
                <span style="background:#f3e5f5;padding:4px 8px;border-radius:6px">📴</span> Mode hors-ligne
            </h4>
            <div style="background:#f8f9fa;padding:12px;border-radius:10px">
                <p style="margin:0 0 8px"><b>📥 Télécharger</b> (dans Stats) : Sauvegarde les données de la ville pour une utilisation sans connexion</p>
                <p style="margin:0 0 8px"><b>🖼️ Images</b> : Les photos vues sont mises en cache automatiquement</p>
                <p style="margin:0;font-size:12px;color:#666">💡 La barre orange en haut indique le mode hors-ligne</p>
            </div>
        </div>
        
        <!-- SECTION: Proximité -->
        <div style="margin-bottom:20px">
            <h4 style="margin:0 0 10px;color:#1a1a2e">📍 Fonction Proximité</h4>
            <div style="background:#e3f2fd;padding:12px;border-radius:10px">
                <p style="margin:0 0 8px">Après avoir cliqué sur <b>📍 Position</b>, clique sur <b>🎯 Top 10 proches</b></p>
                <p style="margin:0 0 8px">Affiche les 10 invaders les plus proches avec leur distance</p>
                <p style="margin:0 0 8px">Les marqueurs pulsent en rouge pour les repérer facilement</p>
                <p style="margin:0"><b>➕ Ajouter au parcours</b> : Ajoute les 10 d'un coup à ton itinéraire</p>
            </div>
        </div>
        
        <!-- SECTION: UID FlashInvaders -->
        <div style="margin-bottom:20px">
            <h4 style="margin:0 0 10px;color:#1a1a2e">🔑 Trouver son UID FlashInvaders</h4>
            <div style="background:#fff8e1;padding:12px;border-radius:10px">
                <p style="margin:0 0 10px;font-weight:600">L'UID permet de synchroniser tes invaders flashés avec l'app.</p>
                
                <!-- Méthode mitmproxy -->
                <div style="background:#e3f2fd;padding:12px;border-radius:8px;margin-bottom:12px;border-left:4px solid #1976d2">
                    <p style="margin:0 0 8px;font-weight:600;color:#1565c0">🔧 Méthode recommandée : mitmproxy</p>
                    <p style="margin:0 0 8px;font-size:12px;color:#666">Intercepte le trafic réseau de l'app pour capturer ton UID automatiquement.</p>
                    
                    <details style="margin-top:8px">
                        <summary style="cursor:pointer;font-weight:600;color:#1565c0;font-size:13px">📖 Guide complet mitmproxy</summary>
                        <div style="margin-top:10px;font-size:12px;color:#444;line-height:1.6">
                            
                            <p style="margin:8px 0;font-weight:600">1️⃣ Installation de mitmproxy</p>
                            <div style="background:#263238;color:#aed581;padding:8px;border-radius:4px;font-family:monospace;font-size:11px;overflow-x:auto">
                                # macOS<br>
                                brew install mitmproxy<br><br>
                                # Windows (avec pip)<br>
                                pip install mitmproxy<br><br>
                                # Linux (Debian/Ubuntu)<br>
                                sudo apt install mitmproxy
                            </div>
                            
                            <p style="margin:12px 0 8px;font-weight:600">2️⃣ Lancer mitmproxy</p>
                            <div style="background:#263238;color:#aed581;padding:8px;border-radius:4px;font-family:monospace;font-size:11px">
                                mitmweb
                            </div>
                            <p style="margin:4px 0;color:#666">Ouvre automatiquement l'interface web sur <code>http://localhost:8081</code></p>
                            <p style="margin:4px 0;color:#666">Le proxy écoute sur le port <code>8080</code></p>
                            
                            <p style="margin:12px 0 8px;font-weight:600">3️⃣ Configurer le proxy sur ton téléphone</p>
                            
                            <div style="background:#fff;padding:8px;border-radius:6px;margin-bottom:8px">
                                <p style="margin:0 0 4px;font-weight:600;color:#e65100">📱 iPhone :</p>
                                <ol style="margin:0 0 0 16px;padding:0;font-size:11px;color:#666">
                                    <li>Réglages → Wi-Fi → (i) sur ton réseau</li>
                                    <li>Configurer le proxy → Manuel</li>
                                    <li>Serveur : <b>IP de ton PC</b> (ex: 192.168.1.xx)</li>
                                    <li>Port : <b>8080</b></li>
                                </ol>
                            </div>
                            
                            <div style="background:#fff;padding:8px;border-radius:6px;margin-bottom:8px">
                                <p style="margin:0 0 4px;font-weight:600;color:#43a047">🤖 Android :</p>
                                <ol style="margin:0 0 0 16px;padding:0;font-size:11px;color:#666">
                                    <li>Paramètres → Wi-Fi → Appui long sur ton réseau</li>
                                    <li>Modifier le réseau → Options avancées</li>
                                    <li>Proxy : Manuel</li>
                                    <li>Nom d'hôte : <b>IP de ton PC</b></li>
                                    <li>Port : <b>8080</b></li>
                                </ol>
                            </div>
                            
                            <p style="margin:12px 0 8px;font-weight:600">4️⃣ Installer le certificat SSL</p>
                            <p style="margin:0 0 8px;color:#666">Sur ton téléphone, ouvre <code>http://mitm.it</code> et installe le certificat pour ton OS.</p>
                            
                            <div style="background:#fff;padding:8px;border-radius:6px;margin-bottom:8px">
                                <p style="margin:0 0 4px;font-weight:600;color:#e65100">📱 iPhone :</p>
                                <ol style="margin:0 0 0 16px;padding:0;font-size:11px;color:#666">
                                    <li>Télécharge le profil iOS</li>
                                    <li>Réglages → Général → VPN et gestion de l'appareil → Installer</li>
                                    <li>Réglages → Général → Informations → Réglages des certificats</li>
                                    <li>Active "mitmproxy" dans les certificats racine</li>
                                </ol>
                            </div>
                            
                            <div style="background:#fff;padding:8px;border-radius:6px;margin-bottom:8px">
                                <p style="margin:0 0 4px;font-weight:600;color:#43a047">🤖 Android :</p>
                                <ol style="margin:0 0 0 16px;padding:0;font-size:11px;color:#666">
                                    <li>Télécharge le certificat Android</li>
                                    <li>Paramètres → Sécurité → Installer depuis stockage</li>
                                    <li>Sélectionne le certificat téléchargé</li>
                                </ol>
                            </div>
                            
                            <p style="margin:12px 0 8px;font-weight:600">5️⃣ Capturer l'UID</p>
                            <ol style="margin:0 0 0 16px;padding:0;font-size:11px;color:#666">
                                <li>Ouvre l'app <b>FlashInvaders</b> sur ton téléphone</li>
                                <li>Navigue dans l'app (profil, carte, etc.)</li>
                                <li>Dans mitmweb, filtre par <code>flashinvaders</code></li>
                                <li>Cherche une requête vers <code>api.flashinvaders.com</code></li>
                                <li>Dans les headers ou le body, cherche <code>uid=</code> ou <code>"uid":</code></li>
                            </ol>
                            
                            <div style="background:#fff3e0;padding:8px;border-radius:6px;margin-top:10px">
                                <p style="margin:0 0 4px;font-weight:600;color:#e65100">💡 Astuce :</p>
                                <p style="margin:0;font-size:11px;color:#666">L'UID apparaît souvent dans les requêtes GET comme paramètre : <code>?uid=abc123def456...</code></p>
                            </div>
                            
                            <p style="margin:12px 0 8px;font-weight:600">6️⃣ Nettoyer après</p>
                            <ul style="margin:0 0 0 16px;padding:0;font-size:11px;color:#666">
                                <li>Désactive le proxy sur ton téléphone (Proxy → Désactivé)</li>
                                <li>Optionnel : supprime le certificat mitmproxy</li>
                            </ul>
                        </div>
                    </details>
                </div>
                
                <!-- Méthode simple (si visible dans l'app) -->
                <details style="margin-bottom:10px">
                    <summary style="cursor:pointer;font-weight:600;color:#666;font-size:13px">📱 Méthode alternative : dans l'app (si disponible)</summary>
                    <div style="margin-top:8px;padding:10px;background:#fff;border-radius:8px">
                        <p style="margin:0 0 6px;font-size:12px;color:#666">Sur certaines versions, l'UID est visible dans les paramètres :</p>
                        <ol style="margin:0 0 0 16px;padding:0;font-size:12px;color:#666">
                            <li>Ouvre FlashInvaders</li>
                            <li>Va dans Paramètres (⚙️)</li>
                            <li>Cherche "Mon compte" ou "UID"</li>
                            <li>Copie la chaîne de 32 caractères</li>
                        </ol>
                    </div>
                </details>
                
                <div style="background:#ffebee;padding:8px;border-radius:6px;font-size:11px">
                    <p style="margin:0 0 4px;color:#c62828"><b>⚠️ Important :</b></p>
                    <p style="margin:0;color:#666">• L'UID est personnel et confidentiel</p>
                    <p style="margin:0;color:#666">• Il donne accès à tout ton historique de flashs</p>
                    <p style="margin:0;color:#666">• Ne le partage jamais publiquement</p>
                </div>
                
                <div style="margin-top:10px;font-size:12px;color:#666">
                    <b>Format de l'UID :</b> <code style="background:#f5f5f5;padding:2px 6px;border-radius:4px">a1b2c3d4e5f6...</code> (32 caractères alphanumériques)
                </div>
            </div>
        </div>
        
        <!-- SECTION: Raccourcis -->
        <div style="margin-bottom:20px">
            <h4 style="margin:0 0 10px;color:#1a1a2e">⌨️ Astuces</h4>
            <div style="background:#f8f9fa;padding:12px;border-radius:10px">
                <p style="margin:0 0 6px"><b>Clic long sur carte</b> → Définir point de départ personnalisé</p>
                <p style="margin:0 0 6px"><b>Double-clic</b> → Zoom avant</p>
                <p style="margin:0 0 6px"><b>Clic photo</b> → Agrandir l'image</p>
                <p style="margin:0"><b>Swipe popup</b> → Fermer</p>
            </div>
        </div>
        
        <!-- SECTION: Sites utiles -->
        <div style="margin-bottom:20px">
            <h4 style="margin:0 0 10px;color:#1a1a2e">🔗 Sites utiles</h4>
            <a href="https://www.invader-spotter.art/" target="_blank" style="display:block;padding:10px;background:#f8f9fa;border-radius:8px;margin-bottom:6px;color:#333;text-decoration:none">
                <b>🎯 Invader Spotter</b> - <span style="font-size:12px;color:#666">Photos et statuts à jour</span>
            </a>
            <a href="https://invadersaroundtheworld.fandom.com/fr/wiki/" target="_blank" style="display:block;padding:10px;background:#f8f9fa;border-radius:8px;margin-bottom:6px;color:#333;text-decoration:none">
                <b>📚 Wiki Fandom</b> - <span style="font-size:12px;color:#666">Wiki communautaire</span>
            </a>
            <a href="https://www.space-invaders.com/world/" target="_blank" style="display:block;padding:10px;background:#f8f9fa;border-radius:8px;margin-bottom:6px;color:#333;text-decoration:none">
                <b>🌍 Site officiel</b> - <span style="font-size:12px;color:#666">Le site de l'artiste</span>
            </a>
            <a href="https://pnote.eu/projects/invaders/" target="_blank" style="display:block;padding:10px;background:#f8f9fa;border-radius:8px;margin-bottom:6px;color:#333;text-decoration:none">
                <b>🗺️ Space Invader Map</b> - <span style="font-size:12px;color:#666">Autre carte communautaire</span>
            </a>
            <a href="https://streetartcities.com/" target="_blank" style="display:block;padding:10px;background:#f8f9fa;border-radius:8px;margin-bottom:6px;color:#333;text-decoration:none">
                <b>🏙️ Street Art Cities</b> - <span style="font-size:12px;color:#666">Carte mondiale du street art</span>
            </a>
            <a href="https://www.flickr.com/search/?text=space%20invader%20street%20art" target="_blank" style="display:block;padding:10px;background:#f8f9fa;border-radius:8px;margin-bottom:6px;color:#333;text-decoration:none">
                <b>📷 Flickr</b> - <span style="font-size:12px;color:#666">Photos de la communauté (avec géoloc)</span>
            </a>
            <a href="https://illuminateartofficial.com/" target="_blank" style="display:block;padding:10px;background:#f8f9fa;border-radius:8px;color:#333;text-decoration:none">
                <b>💡 Illuminate Art</b> - <span style="font-size:12px;color:#666">Art urbain et installations</span>
            </a>
        </div>
        
        <!-- SECTION: À propos -->
        <div style="text-align:center;padding-top:12px;border-top:1px solid #eee">
            <p style="margin:0 0 4px;font-size:14px;font-weight:600;color:#1a1a2e">Total Invaders Search</p>
            <p style="margin:0 0 4px;font-size:12px;color:#666">Powered by Jojosh1er 🚀</p>
            <p style="margin:0;font-size:11px;color:#888">Données : space-invaders-db + Invader Spotter + FlashInvaders</p>
        </div>
    </div>
</div>

<!-- Panneau Stats & Historique -->
<div class="panel bottom hidden" id="statsPanel">
    <div class="panel-head"><h3>📊 Statistiques</h3><button class="panel-close" onclick="hidePanel('statsPanel')">✕</button></div>
    <div class="panel-body stats-panel">
        <div class="stats-city">
            <div class="stats-city-name" id="statsCityName">Paris</div>
            <div class="stats-progress"><div class="stats-progress-bar" id="statsProgressBar" style="width:0%"></div></div>
            <div style="font-size:12px;color:#666;margin-bottom:12px"><span id="statsFlashedCount">0</span> / <span id="statsTotalCount">0</span> flashés (<span id="statsPercent">0</span>%)</div>
            
            <div class="stats-grid">
                <div class="stats-item"><div class="stats-item-val" id="statsPoints" style="color:#00aa55">0</div><div class="stats-item-label">✅ Pts gagnés</div></div>
                <div class="stats-item"><div class="stats-item-val" id="statsRemaining" style="color:#ff6b6b">0</div><div class="stats-item-label">🎯 À chasser</div></div>
                <div class="stats-item"><div class="stats-item-val" id="statsRemainingPts" style="color:#2196F3">0</div><div class="stats-item-label">💰 Pts chassables</div></div>
                <div class="stats-item"><div class="stats-item-val" id="statsDestroyed" style="color:#868e96">0</div><div class="stats-item-label">💀 Détruits</div></div>
            </div>
            <div style="font-size:11px;color:#888;margin-top:8px;text-align:center">💀 = points perdus définitivement</div>
        </div>
        
        <div id="zoneProgress" style="margin-top:20px;display:none">
            <h4 style="margin:0 0 10px;font-size:14px;color:#666">🏛️ Progression par zone</h4>
            <div id="zoneProgressList" style="display:grid;grid-template-columns:repeat(2,1fr);gap:6px;max-height:250px;overflow-y:auto"></div>
        </div>
        
        <div id="progressChart" style="margin-top:20px;display:none">
            <h4 style="margin:0 0 10px;font-size:14px;color:#666">📈 Progression dans le temps</h4>
            <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;align-items:center">
                <button onclick="setChartPeriod('all')" class="chart-period-btn active" data-period="all">Tout</button>
                <button onclick="setChartPeriod('year')" class="chart-period-btn" data-period="year">1 an</button>
                <button onclick="setChartPeriod('month')" class="chart-period-btn" data-period="month">1 mois</button>
                <span style="margin-left:auto;font-size:11px;color:#888">Afficher:</span>
                <button onclick="setChartMode('count')" class="chart-mode-btn active" data-mode="count">👾 Invaders</button>
                <button onclick="setChartMode('points')" class="chart-mode-btn" data-mode="points">💰 Points</button>
            </div>
            <div style="height:200px;position:relative">
                <canvas id="flashedChart"></canvas>
            </div>
            <div id="chartStats" style="margin-top:10px;font-size:11px;color:#666;display:flex;gap:15px;flex-wrap:wrap"></div>
        </div>
        
        <div style="margin-top:20px">
            <h4 style="margin:0 0 10px;font-size:14px;color:#666">📅 Replay des journées de chasse</h4>
            <div style="font-size:11px;color:#888;margin-bottom:8px">Revisualisez vos chasses passées sur la carte</div>
            <div id="replayDaysList" style="max-height:350px;overflow-y:auto">
                <div style="color:#888;font-size:12px;padding:10px;text-align:center">Charge tes flashés pour voir le replay</div>
            </div>
            <div id="replayControls" style="display:none;margin-top:10px;padding:10px;background:#e8f5e9;border-radius:8px">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                    <span id="replayInfo" style="font-size:12px;font-weight:600;color:#2e7d32"></span>
                    <button onclick="clearReplay()" style="padding:4px 10px;border:none;border-radius:6px;background:#fff;font-size:11px;cursor:pointer">✕ Fermer</button>
                </div>
                <div id="replayStats" style="font-size:11px;color:#666"></div>
            </div>
        </div>
        
        <div style="margin-top:20px">
            <h4 style="margin:0 0 10px;font-size:14px;color:#666">🗺️ Heatmap zones non explorées</h4>
            <button onclick="toggleHeatmap()" id="heatmapBtn" style="padding:10px 20px;border:none;border-radius:8px;background:#e3f2fd;color:#1565c0;font-size:13px;cursor:pointer">🔥 Afficher la heatmap</button>
        </div>
        
        <div style="margin-top:20px">
            <h4 style="margin:0 0 10px;font-size:14px;color:#666">📱 Mode hors-ligne</h4>
            <div id="cacheStatus" style="padding:10px;background:#f5f5f5;border-radius:8px;margin-bottom:10px;font-size:12px">
                <div id="cacheInfo">Chargement...</div>
            </div>
            
            <!-- Barre de progression -->
            <div id="cacheProgress" style="display:none;margin-bottom:12px">
                <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:4px">
                    <span id="cacheProgressText">Téléchargement...</span>
                    <span id="cacheProgressPercent">0%</span>
                </div>
                <div style="height:6px;background:#eee;border-radius:3px;overflow:hidden">
                    <div id="cacheProgressBar" style="height:100%;background:linear-gradient(90deg,#ff9800,#ff5722);width:0%;transition:width .3s"></div>
                </div>
            </div>
            
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">
                <button onclick="cacheForOffline()" id="cacheBtn" style="padding:10px 16px;border:none;border-radius:8px;background:#fff3e0;color:#e65100;font-size:13px;cursor:pointer">💾 Données</button>
                <button onclick="cacheImages()" id="cacheImgBtn" style="padding:10px 16px;border:none;border-radius:8px;background:#e3f2fd;color:#1565c0;font-size:13px;cursor:pointer">🖼️ Images</button>
                <button onclick="cacheTiles()" id="cacheTilesBtn" style="padding:10px 16px;border:none;border-radius:8px;background:#e8f5e9;color:#2e7d32;font-size:13px;cursor:pointer">🗺️ Carte</button>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
                <button onclick="cacheAll()" style="padding:10px 16px;border:none;border-radius:8px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;font-size:13px;cursor:pointer;font-weight:600">⬇️ Tout télécharger</button>
                <button onclick="clearCache()" style="padding:10px 16px;border:none;border-radius:8px;background:#ffebee;color:#c62828;font-size:13px;cursor:pointer">🗑️ Vider</button>
                <button onclick="resetDB()" style="padding:10px 16px;border:none;border-radius:8px;background:#ff5722;color:#fff;font-size:13px;cursor:pointer">🔄 Reset DB</button>
            </div>
            <div id="connectionStatus" style="margin-top:10px;padding:8px 12px;border-radius:8px;font-size:12px;font-weight:600"></div>
        </div>
    </div>
</div>

<!-- Modal image plein écran -->
<div class="img-modal" id="imgModal" onclick="if(event.target===this)closeImgModal()">
    <button class="img-modal-close" onclick="closeImgModal()">×</button>
    <div id="imgModalContent"><span class="img-modal-loading">Chargement...</span></div>
    <div class="img-modal-title" id="imgModalTitle"></div>
</div>

<div class="gen-modal" id="genModal" onclick="if(event.target===this)closeGenModal()">
    <div class="gen-content">
        <div class="gen-header"><h3>🚶 Générateur de parcours</h3><button class="gen-close" onclick="closeGenModal()">×</button></div>
        <div class="gen-body">
            
            <!-- Choix du mode (toujours visible) -->
            <div class="gen-section">
                <h4>Je veux planifier par...</h4>
                <div class="gen-mode-tabs">
                    <div class="gen-mode-tab active" data-mode="count" onclick="selectGenMode('count')">
                        <span class="icon">🎯</span> Nombre
                    </div>
                    <div class="gen-mode-tab" data-mode="duration" onclick="selectGenMode('duration')">
                        <span class="icon">⏱️</span> Durée
                    </div>
                    <div class="gen-mode-tab" data-mode="distance" onclick="selectGenMode('distance')">
                        <span class="icon">📏</span> Distance
                    </div>
                </div>
            </div>
            
            <!-- Options dynamiques selon le mode -->
            <div class="gen-section" id="genCountOpts">
                <h4>Combien d'invaders ?</h4>
                <div class="gen-options">
                    <div class="gen-opt" onclick="selectOpt(this,3)"><div class="val">3</div></div>
                    <div class="gen-opt" onclick="selectOpt(this,5)"><div class="val">5</div></div>
                    <div class="gen-opt selected" onclick="selectOpt(this,8)"><div class="val">8</div></div>
                    <div class="gen-opt" onclick="selectOpt(this,10)"><div class="val">10</div></div>
                    <div class="gen-opt" onclick="selectOpt(this,15)"><div class="val">15</div></div>
                    <div class="gen-opt" onclick="selectOpt(this,20)"><div class="val">20</div></div>
                </div>
            </div>
            
            <div class="gen-section hidden" id="genDurationOpts">
                <h4>Combien de temps ?</h4>
                <div class="gen-options">
                    <div class="gen-opt" onclick="selectOpt(this,30)"><div class="val">30 min</div></div>
                    <div class="gen-opt selected" onclick="selectOpt(this,60)"><div class="val">1h</div></div>
                    <div class="gen-opt" onclick="selectOpt(this,90)"><div class="val">1h30</div></div>
                    <div class="gen-opt" onclick="selectOpt(this,120)"><div class="val">2h</div></div>
                    <div class="gen-opt" onclick="selectOpt(this,180)"><div class="val">3h</div></div>
                    <div class="gen-opt" onclick="selectOpt(this,240)"><div class="val">4h</div></div>
                </div>
            </div>
            
            <div class="gen-section hidden" id="genDistanceOpts">
                <h4>Quelle distance max ?</h4>
                <div class="gen-options">
                    <div class="gen-opt" onclick="selectOpt(this,1)"><div class="val">1 km</div></div>
                    <div class="gen-opt selected" onclick="selectOpt(this,2)"><div class="val">2 km</div></div>
                    <div class="gen-opt" onclick="selectOpt(this,3)"><div class="val">3 km</div></div>
                    <div class="gen-opt" onclick="selectOpt(this,5)"><div class="val">5 km</div></div>
                    <div class="gen-opt" onclick="selectOpt(this,8)"><div class="val">8 km</div></div>
                    <div class="gen-opt" onclick="selectOpt(this,10)"><div class="val">10 km</div></div>
                </div>
            </div>
        
            <div class="gen-section">
                <h4>Inclure les statuts</h4>
                <div class="gen-filters">
                    <div class="gen-filter active" data-status="hunt" onclick="toggleGenFilter(this)">🔴 À chasser</div>
                    <div class="gen-filter" data-status="damaged" onclick="toggleGenFilter(this)">🟡 Abîmés</div>
                    <div class="gen-filter" data-status="restored" onclick="toggleGenFilter(this)">♻️ Restaurés</div>
                </div>
            </div>
            
            <div class="gen-preview">
                <div class="gen-preview-title">📊 Estimation</div>
                <div class="gen-preview-stats">
                    <div class="gen-preview-stat"><div class="num" id="previewCount">-</div><div class="label">Invaders</div></div>
                    <div class="gen-preview-stat"><div class="num" id="previewDist">-</div><div class="label">km</div></div>
                    <div class="gen-preview-stat"><div class="num" id="previewTime">-</div><div class="label">min</div></div>
                    <div class="gen-preview-stat"><div class="num" id="previewPts">-</div><div class="label">pts</div></div>
                </div>
            </div>
            
            <button class="gen-btn" id="genBtn" onclick="generateRoute()">🗺️ Générer le parcours</button>
        </div>
    </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
let map,markers=[],invaders=[],flashed=new Set(),flashedData=[],route=[],cityCenter=null,cityName='Paris';
let customStart=null,customStartMarker=null;
let heatmapLayer=null,circuitMode=false,darkMode=false;
let radarMode=false,radarWatchId=null,lastAlertedInvader=null,alertCooldown={};
let clusterMarkers=[],clusterMode=false;
const RADAR_ALERT_DIST=50,RADAR_COOLDOWN=300000,CLUSTER_ZOOM=14;
const COL={hunt:'#ff6b6b',flashed:'#00aa55',damaged:'#f59f00',hidden:'#9775fa',destroyed:'#868e96',flashedHidden:'#9c27b0',flashedDead:'#607d8b',route:'#ffd93d',unknown:'#17a2b8'};

// Zones de clustering
const ZONES={
    Paris:{
        '1er':{lat:48.8606,lng:2.3376},'2e':{lat:48.8687,lng:2.3414},'3e':{lat:48.8636,lng:2.3617},
        '4e':{lat:48.8548,lng:2.3575},'5e':{lat:48.8462,lng:2.3490},'6e':{lat:48.8499,lng:2.3323},
        '7e':{lat:48.8566,lng:2.3150},'8e':{lat:48.8744,lng:2.3106},'9e':{lat:48.8767,lng:2.3378},
        '10e':{lat:48.8758,lng:2.3619},'11e':{lat:48.8592,lng:2.3789},'12e':{lat:48.8406,lng:2.3875},
        '13e':{lat:48.8322,lng:2.3561},'14e':{lat:48.8286,lng:2.3253},'15e':{lat:48.8421,lng:2.2922},
        '16e':{lat:48.8590,lng:2.2686},'17e':{lat:48.8867,lng:2.3044},'18e':{lat:48.8925,lng:2.3444},
        '19e':{lat:48.8817,lng:2.3822},'20e':{lat:48.8638,lng:2.3986},
        'Montreuil':{lat:48.8638,lng:2.4433},'Pantin':{lat:48.8934,lng:2.4047},
        'Saint-Denis':{lat:48.9362,lng:2.3574},'Aubervilliers':{lat:48.9147,lng:2.3822},
        'Bagnolet':{lat:48.8689,lng:2.4205},'Les Lilas':{lat:48.8797,lng:2.4172},
        'Ivry':{lat:48.8153,lng:2.3847},'Vitry':{lat:48.7875,lng:2.3928},
        'Gentilly':{lat:48.8136,lng:2.3461},'Montrouge':{lat:48.8181,lng:2.3192},
        'Boulogne':{lat:48.8397,lng:2.2400},'Neuilly':{lat:48.8847,lng:2.2686},
        'Levallois':{lat:48.8936,lng:2.2878},'Clichy':{lat:48.9039,lng:2.3064},
        'Saint-Ouen':{lat:48.9119,lng:2.3339},'Vincennes':{lat:48.8478,lng:2.4392},
        'Saint-Mandé':{lat:48.8392,lng:2.4178},'Charenton':{lat:48.8214,lng:2.4133}
    },
    Lyon:{
        '1er':{lat:45.7676,lng:4.8344},'2e':{lat:45.7533,lng:4.8321},'3e':{lat:45.7606,lng:4.8574},
        '4e':{lat:45.7746,lng:4.8280},'5e':{lat:45.7597,lng:4.8200},'6e':{lat:45.7700,lng:4.8506},
        '7e':{lat:45.7461,lng:4.8400},'8e':{lat:45.7350,lng:4.8700},'9e':{lat:45.7750,lng:4.8050}
    },
    Marseille:{
        '1er':{lat:43.2965,lng:5.3698},'2e':{lat:43.3100,lng:5.3650},'3e':{lat:43.3100,lng:5.3800},
        '4e':{lat:43.3050,lng:5.4000},'5e':{lat:43.2950,lng:5.4000},'6e':{lat:43.2870,lng:5.3830},
        '7e':{lat:43.2800,lng:5.3650},'8e':{lat:43.2550,lng:5.3850}
    }
};

function show(t){document.getElementById('loading').classList.remove('hidden');document.getElementById('loadingText').textContent=t||'Chargement...';}
function hide(){document.getElementById('loading').classList.add('hidden');}
function invaderSVG(c,s,inR){const st=inR?'stroke="#ffd93d" stroke-width="2"':'';return`<svg width="${s}" height="${s}" viewBox="0 0 24 24"><path ${st} fill="${c}" d="M3 4h2v2H3V4zm4 0h2v2H7V4zm8 0h2v2h-2V4zm4 0h2v2h-2V4zM5 6h2v2H5V6zm12 0h2v2h-2V6zM3 8h18v2H3V8zm0 2h2v2H3v-2zm4 0h2v2H7v-2zm4 0h2v2h-2v-2zm4 0h2v2h-2v-2zm4 0h2v2h-2v-2zM5 12h2v2H5v-2zm4 0h2v2H9v-2zm4 0h2v2h-2v-2zm4 0h2v2h-2v-2zM3 14h4v2H3v-2zm14 0h4v2h-4v-2zM5 16h2v2H5v-2zm12 0h2v2h-2v-2z"/></svg>`;}
function getSize(p){return Math.round(20+(Math.max(10,Math.min(100,p||10))-10)/90*20);}

// V4: Détecter les invaders restaurés (était destroyed/damaged, maintenant OK, non flashé)
function isRestored(i){
    const s=(i.status||'OK').toLowerCase();
    const prev=(i.previous_status||'').toLowerCase();
    const isNowOk=s===''||s==='ok';
    const wasDestroyed=prev.includes('destroy')||prev.includes('détruit');
    const wasDamaged=prev.includes('damag')||prev.includes('dégradé')||prev.includes('abîmé');
    return isNowOk&&(wasDestroyed||wasDamaged);
}

function getCat(i){
    const s=(i.status||'OK').toLowerCase();
    const name=i.name;
    const isFlashed=flashed.has(name)||flashed.has(name.toUpperCase())||flashed.has(name.toLowerCase())||flashed.has(name.replace(/_/g,'-'))||flashed.has(name.replace(/-/g,'_'));
    const isDamaged=s.includes('damaged')||s.includes('degraded');
    const isHidden=s.includes('hidden')||s.includes('masked')||s.includes('covered');
    const isDestroyed=s.includes('destroyed')||s.includes('removed')||s.includes('missing');
    const isUnknown=i.location_unknown===true;
    // Flashé+abîmé = flashé (vert, comptabilisé comme flashé)
    if(isFlashed){if(isDestroyed)return'flashedDead';if(isHidden)return'flashedHidden';return'flashed';}
    if(isDestroyed)return'destroyed';if(isHidden)return'hidden';if(isDamaged)return'damaged';
    if(isUnknown)return'unknown';
    return'hunt';
}

// Texte du badge selon le statut exact
function getStatusBadge(status,cat,previousStatus){
    const s=(status||'').toLowerCase();
    const prev=(previousStatus||'').toLowerCase();
    
    // V4: Badge spécial si réparé/restauré (était détruit ou abîmé, maintenant OK)
    const wasDestroyed=prev.includes('destroy')||prev.includes('détruit');
    const wasDamaged=prev.includes('damag')||prev.includes('dégradé')||prev.includes('abîmé');
    const isNowOk=s===''||s==='ok';
    const isDamaged=s.includes('damaged')||s.includes('degraded');
    
    // Flashé: vérifier si aussi abîmé pour badge plus précis
    if(cat==='flashed'){
        if(isDamaged)return'<span class="pop-badge flashed">✓ Flashé (abîmé)</span>';
        return'<span class="pop-badge flashed">✓ OK</span>';
    }
    if(cat.startsWith('flashed'))return'<span class="pop-badge damaged">✓ '+cat.replace('flashed','')+'</span>';
    
    // Badge réparé/restauré
    if(isNowOk&&wasDestroyed)return'<span class="pop-badge" style="background:#e8f5e9;color:#2e7d32">♻️ Restauré</span>';
    if(isNowOk&&wasDamaged)return'<span class="pop-badge" style="background:#e8f5e9;color:#43a047">🔧 Réparé</span>';
    
    if(s.includes('a little')||s.includes('slightly'))return'<span class="pop-badge damaged" style="background:#fff8e1;color:#ffa000">⚠ Peu abîmé</span>';
    if(cat==='damaged')return'<span class="pop-badge damaged">⚠ Abîmé</span>';
    if(cat==='hidden')return'<span class="pop-badge hidden">👁 Caché</span>';
    if(cat==='destroyed')return'<span class="pop-badge destroyed">✗ Détruit</span>';
    if(cat==='unknown')return'<span class="pop-badge" style="background:#e3f2fd;color:#0288d1">📍 Position approximative</span>';
    return'<span class="pop-badge hunt">🎯 À chasser</span>';
}

function getPhotoUrls(i){
    // Utiliser les URLs du JSON si disponibles, sinon fallback sur Google
    const googleUrl=`https://www.google.com/search?q=${encodeURIComponent(i.name+' invader mosaic')}&tbm=isch`;
    
    // Enregistrer les URLs pour le mode offline
    if(i.image_invader)window.imgUrls[i.name+'_invader']=i.image_invader;
    if(i.image_lieu)window.imgUrls[i.name+'_lieu']=i.image_lieu;
    
    return{
        invader: i.image_invader || null,
        lieu: i.image_lieu || null,
        google: googleUrl
    };
}

// Registre des URLs d'images
window.imgUrls={};

// Modal image
function openImgModal(title){
    document.getElementById('imgModalTitle').textContent=title||'';
    document.getElementById('imgModalContent').innerHTML='<span class="img-modal-loading">Chargement...</span>';
    document.getElementById('imgModal').classList.add('show');
    document.body.style.overflow='hidden';
}

function showImgInModal(src,title){
    const img=new Image();
    img.onload=()=>{
        document.getElementById('imgModalContent').innerHTML='';
        document.getElementById('imgModalContent').appendChild(img);
    };
    img.onerror=()=>{
        document.getElementById('imgModalContent').innerHTML='<span class="img-modal-loading">❌ Impossible de charger cette image</span>';
    };
    img.src=src;
    document.getElementById('imgModalTitle').textContent=title||'';
}

function closeImgModal(){
    document.getElementById('imgModal').classList.remove('show');
    document.body.style.overflow='';
}

// Debug: lister le contenu du cache
async function debugCache(){
    try{
        const db=await openCacheDB();
        const tx=db.transaction('images','readonly');
        const store=tx.objectStore('images');
        const all=await new Promise(r=>{
            const req=store.getAll();
            req.onsuccess=()=>r(req.result);
            req.onerror=()=>r([]);
        });
        console.log('=== CACHE DEBUG ===');
        console.log('Total images en cache:',all.length);
        all.slice(0,5).forEach(img=>{
            console.log('- URL:',img.url?.substring(0,80)+'...');
            console.log('  City:',img.city);
            console.log('  Data:',img.data?'OK ('+img.data.length+' chars)':'MISSING');
        });
        console.log('===================');
        return all.length;
    }catch(e){
        console.error('debugCache error:',e);
        return 0;
    }
}

// Exposer pour test dans la console
window.debugCache=debugCache;

// Charger image depuis le cache quand le src échoue
async function loadCachedImg(img){
    const name=img.dataset.name;
    const type=img.dataset.type||'invader';
    const url=window.imgUrls[name+'_'+type];
    console.log('loadCachedImg:',name,type,'URL:',url?.substring(0,50));
    if(!url){img.style.display='none';return;}
    
    try{
        const cached=await getImageFromDB(url);
        console.log('Cache result:',cached?'FOUND ('+cached.length+' chars)':'NOT FOUND');
        if(cached){
            img.src=cached;
        }else{
            img.style.display='none';
        }
    }catch(e){
        console.error('loadCachedImg error:',e);
        img.style.display='none';
    }
}

// Intercepter les clics sur les boutons photo pour le mode offline
document.addEventListener('click',async function(e){
    // Clic sur preview image
    const preview=e.target.closest('.pop-preview');
    if(preview){
        e.preventDefault();
        const name=preview.dataset.name;
        const type=preview.dataset.type||'invader';
        const url=window.imgUrls[name+'_'+type];
        if(!url)return;
        
        // Chercher dans le cache d'abord
        try{
            const cached=await getImageFromDB(url);
            if(cached){
                openImgViewer(cached,name);
            }else{
                openImgViewer(url,name);
            }
        }catch(err){
            openImgViewer(url,name);
        }
        return;
    }
    
    // Clic sur bouton photo
    const btn=e.target.closest('.photo-btn');
    if(!btn)return;
    
    e.preventDefault();
    const name=btn.dataset.name;
    const type=btn.dataset.type;
    const url=window.imgUrls[name+'_'+type];
    if(!url)return;
    
    const title=name+' - '+(type==='lieu'?'Lieu':'Mosaïque');
    
    // Chercher dans le cache d'abord
    try{
        const cached=await getImageFromDB(url);
        if(cached){
            openImgViewer(cached,title);
        }else{
            openImgViewer(url,title);
        }
    }catch(err){
        openImgViewer(url,title);
    }
});

function getDistance(lat1,lon1,lat2,lon2){const R=6371,dLat=(lat2-lat1)*Math.PI/180,dLon=(lon2-lon1)*Math.PI/180,a=Math.sin(dLat/2)**2+Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dLon/2)**2;return R*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));}

document.addEventListener('DOMContentLoaded',async()=>{
    const uid=localStorage.getItem('uid');if(uid)document.getElementById('uidInput').value=uid;
    map=L.map('map',{zoomControl:false}).setView([48.8566,2.3522],13);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',{maxZoom:19}).addTo(map);
    L.control.zoom({position:'topright'}).addTo(map);
    
    // Clic long pour définir point de départ (via le conteneur DOM)
    let pressTimer=null,pressPos=null;
    const mapEl=document.getElementById('map');
    
    function startPress(e){
        const touch=e.touches?e.touches[0]:e;
        pressPos={x:touch.clientX,y:touch.clientY,lat:null,lng:null};
        // Récupérer la position sur la carte
        const rect=mapEl.getBoundingClientRect();
        const point=L.point(touch.clientX-rect.left,touch.clientY-rect.top);
        const latlng=map.containerPointToLatLng(point);
        pressPos.lat=latlng.lat;
        pressPos.lng=latlng.lng;
        
        pressTimer=setTimeout(()=>{
            if(pressPos&&pressPos.lat&&!clusterMode){
                setCustomStart(pressPos.lat,pressPos.lng);
            }
            pressTimer=null;
        },700);
    }
    
    function cancelPress(){
        if(pressTimer){clearTimeout(pressTimer);pressTimer=null;}
    }
    
    function moveCheck(e){
        if(!pressTimer||!pressPos)return;
        const touch=e.touches?e.touches[0]:e;
        const dx=Math.abs(touch.clientX-pressPos.x);
        const dy=Math.abs(touch.clientY-pressPos.y);
        if(dx>15||dy>15)cancelPress();
    }
    
    mapEl.addEventListener('mousedown',startPress);
    mapEl.addEventListener('touchstart',startPress,{passive:true});
    mapEl.addEventListener('mouseup',cancelPress);
    mapEl.addEventListener('touchend',cancelPress);
    mapEl.addEventListener('mousemove',moveCheck);
    mapEl.addEventListener('touchmove',moveCheck,{passive:true});
    mapEl.addEventListener('mouseleave',cancelPress);
    
    // Clic droit aussi (desktop) - pas en mode cluster
    map.on('contextmenu',e=>{
        e.originalEvent.preventDefault();
        if(!clusterMode)setCustomStart(e.latlng.lat,e.latlng.lng);
    });
    
    // Clustering selon le zoom
    map.on('zoomend',updateClusters);
    
    await loadCities();await loadCity('PA');
    if(uid){try{await loadFlashed();}catch(e){console.error('Auto loadFlashed error:',e);}}
});

async function loadCities(){show('Chargement...');const r=await fetch('/api/cities'),d=await r.json();window.citiesData=d.cities;document.getElementById('citySelect').innerHTML=d.cities.map(c=>`<option value="${c.code}"${c.code==='PA'?' selected':''}>${c.name} (${c.count})</option>`).join('');hide();}
async function changeCity(){await loadCity(document.getElementById('citySelect').value);}
async function loadCity(code){show('Chargement...');route=[];const r=await fetch(`/api/invaders?city=${code}`),d=await r.json();invaders=d.invaders||[];cityCenter=d.center;const c=window.citiesData?.find(x=>x.code===code);cityName=c?.name||code;if(d.center)map.setView([d.center.lat,d.center.lng],13);loadSavedRoute();render();stats();updateInvaderSelect();hide();}
async function loadFlashed(){const uid=document.getElementById('uidInput').value.trim();if(!uid){alert('Entre ton UID!');return;}localStorage.setItem('uid',uid);show('Chargement...');
    try{const r=await fetch(`https://api.space-invaders.com/flashinvaders_v3_pas_trop_predictif/api/gallery?uid=${encodeURIComponent(uid)}`);const data=await r.json();
        flashed=new Set();flashedData=[];const invadersData=data.invaders||{};
        Object.values(invadersData).forEach(inv=>{
            const name=inv.name||'';
            if(name){
                flashed.add(name);flashed.add(name.replace(/_/g,'-'));flashed.add(name.replace(/-/g,'_'));flashed.add(name.toUpperCase());flashed.add(name.toLowerCase());
                flashedData.push({name:name,date:inv.date_flash,points:inv.point||10,city:inv.city_id});
            }
        });
        let matches=0;invaders.forEach(inv=>{if(flashed.has(inv.name)||flashed.has(inv.name.toUpperCase())||flashed.has(inv.name.toLowerCase()))matches++;});
        alert(`✅ ${Object.keys(invadersData).length} invaders flashés chargés!\n${matches} correspondent à ${cityName}.`);
        document.getElementById('tFlash').classList.add('on');document.getElementById('tFlashedIndispo').classList.add('on');
        render();stats();updateInvaderSelect();try{updateReplayDaysList();}catch(e){console.warn('Replay list error:',e);}
    }catch(e){console.error('loadFlashed error:',e);alert('❌ Erreur. Vérifie ton UID.');}
    hide();hidePanel('uidPanel');}

function render(){
    markers.forEach(m=>map.removeLayer(m));markers=[];
    const sh={hunt:document.getElementById('tHunt').classList.contains('on'),restored:document.getElementById('tRestored').classList.contains('on'),flashed:document.getElementById('tFlash').classList.contains('on'),damaged:document.getElementById('tDamaged').classList.contains('on'),hidden:document.getElementById('tHidden').classList.contains('on'),destroyed:document.getElementById('tDestroyed').classList.contains('on'),flashedHidden:document.getElementById('tFlashedIndispo').classList.contains('on'),flashedDead:document.getElementById('tFlashedIndispo').classList.contains('on'),unknown:document.getElementById('tUnknownLoc')?.classList.contains('on')??true};
    const showUnknownLoc=document.getElementById('tUnknownLoc')?.classList.contains('on')??true;
    
    // Filtre par points
    const ptsFilter=new Set();
    if(document.getElementById('pts10')?.classList.contains('on'))ptsFilter.add(10);
    if(document.getElementById('pts20')?.classList.contains('on'))ptsFilter.add(20);
    if(document.getElementById('pts30')?.classList.contains('on'))ptsFilter.add(30);
    if(document.getElementById('pts40')?.classList.contains('on'))ptsFilter.add(40);
    if(document.getElementById('pts50')?.classList.contains('on'))ptsFilter.add(50);
    if(document.getElementById('pts100')?.classList.contains('on'))ptsFilter.add(100);
    
    // Charger notes et signalements utilisateur
    const userNotes=JSON.parse(localStorage.getItem('invaderNotes')||'{}');
    const userReports=JSON.parse(localStorage.getItem('invaderReports')||'{}');
    
    invaders.forEach(i=>{
        const cat=getCat(i),inR=route.some(r=>r.name===i.name);
        const isNearby=nearbyHighlight.includes(i.name);
        const hasUnknownLoc=i.location_unknown===true;
        
        // Si position inconnue et filtre désactivé, ne pas afficher (sauf si dans parcours)
        if(!inR&&!isNearby&&hasUnknownLoc&&!showUnknownLoc)return;
        
        // Filtrage par statut (avec support des restaurés)
        const restored=isRestored(i);
        if(!inR&&!isNearby){
            // Si les deux filtres actifs → seulement restaurés à chasser
            if(sh.restored&&sh.hunt){
                if(!(restored&&cat==='hunt'))return;
            }
            // Si seulement restaurés → tous les restaurés (flashés ou non)
            else if(sh.restored){
                if(!restored)return;
            }
            // Sinon vérifier le filtre de catégorie standard
            else if(!sh[cat])return;
        }
        if(!inR&&!isNearby&&ptsFilter.size>0&&!ptsFilter.has(i.points))return;
        const col=inR?COL.route:(hasUnknownLoc&&cat==='hunt'?COL.unknown:COL[cat]);
        const sz=getSize(i.points);
        const op=(cat==='flashed'&&!inR)?.6:1;
        const nearbyClass=isNearby?'nearby-highlight':'';
        const icon=L.divIcon({className:'invader-icon',html:`<div class="${nearbyClass}" style="opacity:${op}">${invaderSVG(col,sz,inR)}</div>`,iconSize:[sz,sz],iconAnchor:[sz/2,sz/2]});
        const m=L.marker([i.lat,i.lng],{icon});
        // Ajouter à la carte seulement si pas en mode cluster
        if(!(map.getZoom()<CLUSTER_ZOOM&&getZones()))m.addTo(map);
        
        const badge=getStatusBadge(i.status,cat,i.previous_status);
        
        // V4: Statut avec ancien statut - affichage amélioré
        let statusText='';
        const hasStatusChange=i.previous_status&&i.previous_status.toLowerCase()!==((i.status||'OK').toLowerCase());
        const isNotOk=i.status&&i.status.toLowerCase()!=='ok';
        
        if(isNotOk||hasStatusChange){
            const currentStatus=i.status||'OK';
            if(hasStatusChange){
                // Affichage clair du changement
                statusText=`<div class="pop-status-change">
                    <div style="font-weight:600;margin-bottom:2px">⚠️ Changement de statut</div>
                    <div><span style="text-decoration:line-through;color:#999">${i.previous_status}</span> → <span style="font-weight:600">${currentStatus}</span></div>
                    ${i.previous_status_date?`<div style="font-size:10px;color:#888;margin-top:2px">📅 ${i.previous_status_date}</div>`:''}
                </div>`;
            }else{
                statusText=`<div class="pop-status">État: ${currentStatus}</div>`;
            }
        }
        
        // V4: Infos complémentaires (date de pose, date du statut)
        let infoHtml='';
        const infoParts=[];
        if(i.landing_date)infoParts.push(`<span>📅 Posé le ${i.landing_date}</span>`);
        if(i.status_date){
            const src=i.status_source?` (${i.status_source})`:'';
            infoParts.push(`<span>🔄 Statut: ${i.status_date}${src}</span>`);
        }
        
        // Infos géolocalisation pour les invaders ajoutés manuellement
        if(i.missing_from_github||i.geo_source){
            let geoText='📍 ';
            const srcLabels={
                'manual_address':'Géoloc. manuelle',
                'city_center':'Centre ville (approx.)',
                'web_search':'Recherche web',
                'aroundus':'AroundUs',
                'illuminate':'Illuminate',
                'pnote':'Pnote.eu',
                'flickr':'Flickr EXIF',
                'ocr':'OCR plaque de rue',
                'exif':'EXIF photo',
                'google_lens':'Google Lens',
                'vision':'Claude Vision',
                'vision_address':'Vision (adresse)',
                'vision_landmark':'Vision (repère)',
                'vision_shop':'Vision (enseigne)',
                'vision_district':'Vision (quartier)',
                'vision_road':'Vision (rue)',
                'interactive_lens':'Google Lens interactif',
            };
            geoText+=srcLabels[i.geo_source]||i.geo_source||'Ajouté manuellement';
            
            if(i.geo_confidence){
                const confLabels={'high':'haute','medium':'moyenne','low':'basse','very_low':'très basse'};
                const confIcons={'high':'🟢','medium':'🟡','low':'🟠','very_low':'🔴'};
                const cl=i.geo_confidence;
                geoText+=` <span class="pop-geo-confidence ${cl}">${confIcons[cl]||'⚪'} ${confLabels[cl]||cl}</span>`;
            }
            infoParts.push(`<span>${geoText}</span>`);
            
            if(i.address)infoParts.push(`<span>🏠 ${i.address}</span>`);
            
            // Afficher le hint de géolocalisation (indices Vision, quartier, enseignes...)
            if(i.geo_hint){
                const hintParts=i.geo_hint.split(' | ').filter(h=>h.length>0);
                if(hintParts.length>0){
                    const hintHtml=hintParts.map(h=>{
                        // Coloriser les types de hint
                        if(h.startsWith('quartier:'))return`<span>🏘️ ${h.replace('quartier: ','')}</span>`;
                        if(h.startsWith('enseigne:'))return`<span>🏪 ${h.replace('enseigne: ','')}</span>`;
                        if(h.startsWith('repère:'))return`<span>🏛️ ${h.replace('repère: ','')}</span>`;
                        if(h.startsWith('près de'))return`<span>📌 ${h}</span>`;
                        if(h.startsWith('probablement'))return`<span>❓ ${h}</span>`;
                        if(h.startsWith('entre'))return`<span>↔️ ${h}</span>`;
                        return`<span>💡 ${h}</span>`;
                    }).join('');
                    infoParts.push(`<div class="pop-geo-hint"><span class="hint-label">🔎 Indices:</span> ${hintHtml}</div>`);
                }
            }
        }
        
        if(infoParts.length>0)infoHtml=`<div class="pop-info">${infoParts.join('')}</div>`;
        
        // URLs des images
        const urls=getPhotoUrls(i);
        let photoLinks='';
        if(urls.invader)photoLinks+=`<a href="${urls.invader}" target="_blank" class="photo-btn" data-name="${i.name}" data-type="invader" title="Photo mosaïque">🎨</a>`;
        if(urls.lieu)photoLinks+=`<a href="${urls.lieu}" target="_blank" class="photo-btn" data-name="${i.name}" data-type="lieu" title="Photo lieu">📍</a>`;
        photoLinks+=`<a href="${urls.google}" target="_blank" title="Google Images">🔍</a>`;
        
        // Preview image avec fallback cache
        const previewImg=urls.invader?`<img class="pop-preview" src="${urls.invader}" data-name="${i.name}" data-type="invader" onerror="loadCachedImg(this)" alt="${i.name}">`:'';
        
        // Note utilisateur
        const userNote=userNotes[i.name];
        const noteHtml=userNote?`<div class="pop-note">📝 ${userNote}</div>`:'';
        
        // Signalement utilisateur
        const userReport=userReports[i.name];
        const reportHtml=userReport?`<div class="pop-user-status">⚠️ Signalé: ${userReport}</div>`:'';
        
        // Date de flash si flashé
        const isFlashedAlready=cat.startsWith('flashed')||cat==='flashed';
        let flashDateHtml='';
        if(isFlashedAlready){
            const flashInfo=flashedData.find(f=>f.name===i.name||f.name.toUpperCase()===i.name.toUpperCase()||f.name.replace(/_/g,'-')===i.name.replace(/_/g,'-'));
            if(flashInfo&&flashInfo.date){
                const d=new Date(flashInfo.date);
                if(!isNaN(d.getTime())){
                    const dateStr=d.toLocaleDateString('fr-FR',{day:'2-digit',month:'2-digit',year:'numeric'});
                    const timeStr=d.toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'});
                    flashDateHtml=`<div style="background:#e8f5e9;color:#2e7d32;padding:6px 8px;border-radius:6px;font-size:11px;margin-top:6px">✅ Flashé le ${dateStr} à ${timeStr}</div>`;
                }
            }
        }
        
        m.bindPopup(`
            ${previewImg}
            <div class="pop-head"><span class="pop-name ${cat}">${i.name}</span>${badge}</div>
            <div class="pop-pts">${i.points} pts</div>
            ${flashDateHtml}
            ${statusText}
            ${infoHtml}
            ${reportHtml}
            ${noteHtml}
            <div class="pop-photos">${photoLinks}</div>
            ${i.hint?`<div class="pop-hint">💡 ${i.hint}</div>`:''}
            <div class="pop-actions">
                <button class="pop-go" onclick="navigate(${i.lat},${i.lng})">🧭 Go</button>
                <button class="pop-add" onclick="toggleRoute('${i.name}',${i.lat},${i.lng},${i.points})">${inR?'➖':'➕'}</button>
            </div>
            <div class="pop-extra">
                <button onclick="openReport('${i.name}')">⚠️ Signaler</button>
                <button onclick="openNote('${i.name}')">📝 Note</button>
                <button onclick="openGitHubReport('${i.name}')" style="background:#24292e;color:#fff">🐙 GitHub</button>
            </div>
        `,{maxWidth:280,autoPanPaddingTopLeft:[10,80],autoPanPaddingBottomRight:[10,10]});
        m.inv=i;markers.push(m);
    });
    
    if(window.routeLine)map.removeLayer(window.routeLine);
    if(route.length>=2)window.routeLine=L.polyline(route.map(r=>[r.lat,r.lng]),{color:'#ffd93d',weight:5,opacity:.8,dashArray:'12,8'}).addTo(map);
    updateRoutePanel();
    updateClusters();
}

function stats(){let h=0,f=0,dam=0,hid=0,dest=0,fhid=0,fdest=0,rest=0;
    invaders.forEach(i=>{
        const c=getCat(i);
        // Compter les restaurés (flashés ou non)
        if(isRestored(i))rest++;
        // Compter par catégorie
        if(c==='hunt')h++;
        else if(c==='flashed')f++;
        else if(c==='damaged')dam++;
        else if(c==='hidden')hid++;
        else if(c==='destroyed')dest++;
        else if(c==='flashedHidden')fhid++;
        else if(c==='flashedDead')fdest++;
    });
    document.getElementById('sHunt').textContent=h;document.getElementById('sFlash').textContent=f;document.getElementById('sRestored').textContent=rest;document.getElementById('sDamaged').textContent=dam;document.getElementById('sHidden').textContent=hid;document.getElementById('sDestroyed').textContent=dest;document.getElementById('sFlashedIndispo').textContent=fhid+fdest;}

function updateInvaderSelect(){const sel=document.getElementById('invaderSelect'),sorted=[...invaders].sort((a,b)=>a.name.localeCompare(b.name,undefined,{numeric:true,sensitivity:'base'}));
    sel.innerHTML='<option value="">-- Choisis ('+invaders.length+') --</option>'+sorted.map(i=>{const cat=getCat(i);let icon='🔴';if(cat==='flashed')icon='✅';else if(cat.startsWith('flashed'))icon='🟠';else if(cat==='damaged')icon='🟡';else if(cat==='hidden')icon='🟣';else if(cat==='destroyed')icon='⚫';else if(isRestored(i))icon='♻️';return`<option value="${i.name}">${icon} ${i.name} (${i.points}pts)</option>`;}).join('');
    document.getElementById('searchInfo').textContent=`${invaders.length} invaders à ${cityName}`;}

function goToInvader(){const name=document.getElementById('invaderSelect').value;if(!name)return;const inv=invaders.find(i=>i.name===name);if(inv){map.setView([inv.lat,inv.lng],18);const m=markers.find(x=>x.inv?.name===inv.name);if(m)setTimeout(()=>m.openPopup(),300);hidePanel('searchPanel');}}
function navigate(lat,lng){const ios=/iPhone|iPad|iPod/.test(navigator.userAgent);window.open(ios?`maps://maps.apple.com/?daddr=${lat},${lng}&dirflg=w`:`https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}&travelmode=walking`);}
function toggleRoute(name,lat,lng,pts){const i=route.findIndex(r=>r.name===name);if(i>=0)route.splice(i,1);else if(route.length<20)route.push({name,lat,lng,points:pts});else{alert('Max 20!');return;}saveRoute();render();document.getElementById('sRoute').textContent=route.length;}

function saveRoute(){
    try{
        localStorage.setItem('currentRoute',JSON.stringify(route));
        localStorage.setItem('currentRouteCity',cityName);
    }catch(e){console.warn('Cannot save route:',e);}
}

function loadSavedRoute(){
    try{
        const saved=localStorage.getItem('currentRoute');
        const savedCity=localStorage.getItem('currentRouteCity');
        if(saved&&savedCity===cityName){
            const parsed=JSON.parse(saved);
            if(Array.isArray(parsed)&&parsed.length>0){
                route=parsed;
                document.getElementById('sRoute').textContent=route.length;
                showPosAlert('info','🗺️',`Parcours restauré (${route.length} invaders)`);
                return true;
            }
        }
    }catch(e){console.warn('Cannot load route:',e);}
    return false;
}

function clearSavedRoute(){
    localStorage.removeItem('currentRoute');
    localStorage.removeItem('currentRouteCity');
}
function updateRoutePanel(){
    const list=document.getElementById('routeList');
    const startInfo=document.getElementById('startPointInfo');
    
    // Afficher l'info du point de départ
    const noStartHint=document.getElementById('noStartHint');
    if(customStart){
        startInfo.style.display='block';
        document.getElementById('startPointText').textContent='Point personnalisé 🚩';
        noStartHint.style.display='none';
    }else if(myPosition){
        startInfo.style.display='block';
        document.getElementById('startPointText').textContent='Ma position actuelle';
        noStartHint.style.display='none';
    }else{
        startInfo.style.display='none';
        noStartHint.style.display=route.length>0?'block':'none';
    }
    
    if(!route.length){
        list.innerHTML='<div style="text-align:center;color:#888;padding:20px">Clique ➕ sur un invader</div>';
        document.getElementById('routeTotal').textContent='0 points';
        return;
    }
    const tot=route.reduce((s,r)=>s+r.points,0);
    list.innerHTML=route.map((r,i)=>`<div class="route-item"><div class="route-num">${i+1}</div><div class="route-info"><div class="route-name">${r.name}</div><div class="route-pts">${r.points}pts</div></div><button class="route-del" onclick="toggleRoute('${r.name}',${r.lat},${r.lng},${r.points})">✕</button></div>`).join('');
    document.getElementById('routeTotal').textContent=`${tot} points`;
}
function openGMaps(){if(!route.length)return;const p=route.slice(0,10);
    // Priorité: customStart > myPosition > premier invader
    let origin=customStart?`${customStart.lat},${customStart.lng}`:myPosition?`${myPosition.lat},${myPosition.lng}`:`${p[0].lat},${p[0].lng}`;
    let url=`https://www.google.com/maps/dir/?api=1&travelmode=walking&origin=${origin}&destination=${p[p.length-1].lat},${p[p.length-1].lng}`;
    // Ajouter tous les invaders comme waypoints si on a un point de départ externe
    let hasExternalStart=customStart||myPosition;
    let waypoints=hasExternalStart?p:p.slice(1,-1);
    if(waypoints.length>0&&(hasExternalStart||p.length>2))url+=`&waypoints=${encodeURIComponent(waypoints.slice(0,-1).map(x=>`${x.lat},${x.lng}`).join('|'))}`;
    window.open(url);}
function openApple(){if(!route.length)return;
    // Priorité: customStart > myPosition > premier invader
    let saddr=customStart?`${customStart.lat},${customStart.lng}`:myPosition?`${myPosition.lat},${myPosition.lng}`:`${route[0].lat},${route[0].lng}`;
    window.open(`maps://maps.apple.com/?saddr=${saddr}&daddr=${route[route.length-1].lat},${route[route.length-1].lng}&dirflg=w`);}
function clearRoute(){route=[];saveRoute();render();document.getElementById('sRoute').textContent='0';}
function centerOnMe(){if(!navigator.geolocation){showPosAlert('error','❌','Géoloc non disponible');return;}show('Localisation...');navigator.geolocation.getCurrentPosition(pos=>{hide();const lat=pos.coords.latitude,lng=pos.coords.longitude;myPosition={lat,lng};if(window.myPosMarker)map.removeLayer(window.myPosMarker);window.myPosMarker=L.circleMarker([lat,lng],{radius:14,fillColor:'#4285f4',fillOpacity:1,color:'#fff',weight:4}).addTo(map);map.setView([lat,lng],17);window.myPosMarker.bindPopup('📍 Moi').openPopup();showPosAlert('success','✅','Position trouvée!');updateRoutePanel();},err=>{hide();showPosAlert('error','❌',err.code===1?'Autorise la géoloc':'Position indisponible');},{enableHighAccuracy:true,timeout:15000,maximumAge:0});}
function showPosAlert(type,icon,msg){const el=document.getElementById('posAlert');el.className='pos-alert '+type;document.getElementById('posIcon').textContent=icon;document.getElementById('posMsg').textContent=msg;el.classList.remove('hidden');setTimeout(()=>el.classList.add('hidden'),4000);}
function toggleFilter(id){document.getElementById(id).classList.toggle('on');render();updateInvaderSelect();}
function toggleLegend(){document.getElementById('legendPanel').classList.toggle('hidden');}

// === RADAR MODE ===
function toggleRadar(){
    if(radarMode)stopRadar();
    else startRadar();
}
function startRadar(){
    if(!navigator.geolocation){showPosAlert('error','❌','Géoloc non disponible');return;}
    radarMode=true;
    document.getElementById('radarBtn').classList.add('radar-active');
    document.getElementById('radarIndicator').classList.add('show');
    document.getElementById('radarStatus').textContent='Recherche GPS...';
    radarWatchId=navigator.geolocation.watchPosition(onRadarPos,onRadarErr,{enableHighAccuracy:true,timeout:10000,maximumAge:0});
    showPosAlert('success','📡','Radar activé!');
}
function stopRadar(){
    radarMode=false;
    if(radarWatchId){navigator.geolocation.clearWatch(radarWatchId);radarWatchId=null;}
    document.getElementById('radarBtn').classList.remove('radar-active');
    document.getElementById('radarIndicator').classList.remove('show');
    document.getElementById('radarDistance').classList.remove('show');
    document.getElementById('radarArrow').classList.remove('show');
    document.getElementById('radarAlert').classList.remove('show');
    showPosAlert('info','📡','Radar désactivé');
}
function onRadarPos(pos){
    const lat=pos.coords.latitude,lng=pos.coords.longitude;
    myPosition={lat,lng};
    if(window.myPosMarker)map.removeLayer(window.myPosMarker);
    window.myPosMarker=L.circleMarker([lat,lng],{radius:14,fillColor:'#4285f4',fillOpacity:1,color:'#fff',weight:4}).addTo(map);
    
    const huntable=invaders.filter(i=>{const c=getCat(i);return c==='hunt'||c==='damaged'||c==='unknown';});
    if(!huntable.length){document.getElementById('radarStatus').textContent='Aucun invader à chasser';return;}
    
    let closest=null,minDist=Infinity;
    huntable.forEach(inv=>{const d=getDist(lat,lng,inv.lat,inv.lng);if(d<minDist){minDist=d;closest=inv;}});
    
    document.getElementById('radarStatus').textContent=closest.name+' - '+Math.round(minDist)+'m';
    document.getElementById('radarDistance').textContent=Math.round(minDist)+'m';
    document.getElementById('radarDistance').classList.add('show');
    
    // Flèche directionnelle
    const bearing=getBearing(lat,lng,closest.lat,closest.lng);
    const arrow=document.getElementById('radarArrow');
    arrow.querySelector('svg').style.transform='rotate('+bearing+'deg)';
    arrow.classList.add('show');
    
    // Couleur selon distance
    const arrowCol=minDist<=50?'#ff6b6b':minDist<=100?'#ff9800':minDist<=200?'#ffc107':'#4caf50';
    arrow.querySelector('polygon').setAttribute('fill',arrowCol);
    
    if(minDist<=RADAR_ALERT_DIST)triggerRadarAlert(closest,minDist);
    else document.getElementById('radarAlert').classList.remove('show');
}
function triggerRadarAlert(inv,dist){
    const now=Date.now();
    if(alertCooldown[inv.name]&&now-alertCooldown[inv.name]<RADAR_COOLDOWN)return;
    if(navigator.vibrate)navigator.vibrate([200,100,200,100,300]);
    document.getElementById('radarAlertName').textContent=inv.name+' ('+inv.points+'pts)';
    document.getElementById('radarAlert').classList.add('show');
    setTimeout(()=>document.getElementById('radarAlert').classList.remove('show'),5000);
    alertCooldown[inv.name]=now;
    map.setView([inv.lat,inv.lng],18);
    const m=markers.find(x=>x.inv&&x.inv.name===inv.name);
    if(m)setTimeout(()=>m.openPopup(),300);
}
function onRadarErr(err){document.getElementById('radarStatus').textContent=err.code===1?'GPS refusé':'GPS indisponible';}
function getDist(lat1,lng1,lat2,lng2){
    const R=6371000,dLat=(lat2-lat1)*Math.PI/180,dLng=(lng2-lng1)*Math.PI/180;
    const a=Math.sin(dLat/2)**2+Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dLng/2)**2;
    return R*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
}
function getBearing(lat1,lng1,lat2,lng2){
    const dLng=(lng2-lng1)*Math.PI/180;
    const y=Math.sin(dLng)*Math.cos(lat2*Math.PI/180);
    const x=Math.cos(lat1*Math.PI/180)*Math.sin(lat2*Math.PI/180)-Math.sin(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.cos(dLng);
    return(Math.atan2(y,x)*180/Math.PI+360)%360;
}

// === CLUSTERING ===
function getZones(){
    if(ZONES[cityName])return ZONES[cityName];
    // Grille auto pour autres villes (pas pour les régions trop dispersées)
    if(invaders.length<10)return null;
    
    let minLat=90,maxLat=-90,minLng=180,maxLng=-180;
    invaders.forEach(i=>{minLat=Math.min(minLat,i.lat);maxLat=Math.max(maxLat,i.lat);minLng=Math.min(minLng,i.lng);maxLng=Math.max(maxLng,i.lng);});
    
    // Vérifier si la zone n'est pas trop dispersée (max 30km)
    const spanKm=getDist(minLat,minLng,maxLat,maxLng)/1000;
    if(spanKm>30){
        // Région trop grande, pas de clustering
        return null;
    }
    
    const zones={},n=invaders.length>100?4:3;
    const dLat=(maxLat-minLat)/n,dLng=(maxLng-minLng)/n;
    
    // Labels: directions cardinales pour 3x3, numérotés pour 4x4
    // 3x3: SO,S,SE / O,C,E / NO,N,NE (de bas en haut, de gauche à droite)
    const labels3=[
        ['SO','S','SE'],
        ['O','Centre','E'],
        ['NO','N','NE']
    ];
    // 4x4: numérotation simple par zone
    const labels4=[
        ['Zone 1','Zone 2','Zone 3','Zone 4'],
        ['Zone 5','Zone 6','Zone 7','Zone 8'],
        ['Zone 9','Zone 10','Zone 11','Zone 12'],
        ['Zone 13','Zone 14','Zone 15','Zone 16']
    ];
    const labelGrid=n===3?labels3:labels4;
    
    for(let i=0;i<n;i++){
        for(let j=0;j<n;j++){
            const label=labelGrid[i][j];
            zones[label]={
                lat:minLat+(i+.5)*dLat,
                lng:minLng+(j+.5)*dLng,
                minLat:minLat+i*dLat,
                maxLat:minLat+(i+1)*dLat,
                minLng:minLng+j*dLng,
                maxLng:minLng+(j+1)*dLng
            };
        }
    }
    return zones;
}
function getZone(inv){
    const zones=getZones();
    if(!zones)return null;
    // Zones avec bounds (grille auto)
    for(const[z,d]of Object.entries(zones)){
        if(d.minLat!==undefined&&inv.lat>=d.minLat&&inv.lat<d.maxLat&&inv.lng>=d.minLng&&inv.lng<d.maxLng)return z;
    }
    // Zones sans bounds: plus proche
    let closest=null,minD=Infinity;
    for(const[z,d]of Object.entries(zones)){
        const dist=getDist(inv.lat,inv.lng,d.lat,d.lng);
        if(dist<minD){minD=dist;closest=z;}
    }
    return closest;
}
function renderClusters(){
    clusterMarkers.forEach(m=>map.removeLayer(m));
    clusterMarkers=[];
    const zones=getZones();
    if(!zones)return;
    
    const stats={};
    Object.keys(zones).forEach(z=>stats[z]={total:0,flashed:0,hunt:0,pts:0,fpts:0});
    invaders.forEach(inv=>{
        const z=getZone(inv);
        if(!z||!stats[z])return;
        const cat=getCat(inv);
        stats[z].total++;
        stats[z].pts+=inv.points||10;
        if(cat==='flashed'||cat.startsWith('flashed')){stats[z].flashed++;stats[z].fpts+=inv.points||10;}
        else if(cat==='hunt'||cat==='damaged')stats[z].hunt++;
    });
    
    // Max points pour taille relative
    let maxPts=0;
    Object.values(stats).forEach(s=>{if(s.pts>maxPts)maxPts=s.pts;});
    
    for(const[z,d]of Object.entries(zones)){
        const s=stats[z];
        if(!s||s.total===0)continue;
        // % = flashés / (flashés + chassables), exclut détruits/cachés
        const base=s.flashed+s.hunt;
        const pct=base>0?Math.round(s.flashed/base*100):0;
        const col=pct>=100?'#00aa55':pct>=75?'#4caf50':pct>=50?'#ffc107':pct>=25?'#ff9800':'#ff6b6b';
        // Taille selon points ET zoom (zoom 10-14)
        const zoom=map.getZoom();
        const zoomFactor=Math.max(0.5,Math.min(1,(zoom-9)/5)); // 0.5 à zoom 9, 1 à zoom 14
        const baseSize=maxPts>0?40+40*(s.pts/maxPts):50;
        const sz=Math.round(baseSize*zoomFactor);
        const r=Math.max(8,(sz-10)/2),circ=2*Math.PI*r,off=circ*(1-pct/100);
        const fs=Math.max(7,Math.round((9+5*(s.pts/maxPts))*zoomFactor));
        const sw=Math.max(3,Math.round(sz/15));
        const html=`<div class="cluster-marker" style="width:${sz}px;height:${sz}px;position:relative">
            <svg width="${sz}" height="${sz}" style="transform:rotate(-90deg)">
                <circle cx="${sz/2}" cy="${sz/2}" r="${r}" fill="white" stroke="#e0e0e0" stroke-width="${sw}"/>
                <circle cx="${sz/2}" cy="${sz/2}" r="${r}" fill="none" stroke="${col}" stroke-width="${sw}" stroke-dasharray="${circ}" stroke-dashoffset="${off}" stroke-linecap="round"/>
            </svg>
            <div style="position:absolute;top:0;left:0;width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center">
                <div style="font-size:${fs}px;font-weight:700;color:${col}">${pct}%</div>
                <div style="font-size:${Math.max(7,fs-4)}px;color:#666">${z}</div>
            </div>
        </div>`;
        const icon=L.divIcon({className:'',html:html,iconSize:[sz,sz],iconAnchor:[sz/2,sz/2]});
        const m=L.marker([d.lat,d.lng],{icon}).addTo(map);
        m.bindPopup(`<div style="text-align:center;min-width:140px">
            <div style="font-size:15px;font-weight:700;margin-bottom:6px">${z}</div>
            <div style="font-size:24px;font-weight:800;color:${col}">${pct}%</div>
            <div style="font-size:12px;color:#666;margin:6px 0">✅ ${s.flashed}/${base} chassables<br>🎯 ${s.hunt} restants<br>👾 ${s.total} invaders</div>
            <div style="font-size:11px;color:#888">${s.fpts}/${s.pts} pts</div>
            <button onclick="map.setView([${d.lat},${d.lng}],16);map.closePopup()" style="margin-top:8px;padding:6px 14px;border:none;border-radius:6px;background:#667eea;color:#fff;font-size:12px;cursor:pointer">🔍 Zoomer</button>
        </div>`);
        clusterMarkers.push(m);
    }
}
function updateClusters(){
    const zoom=map.getZoom();
    const zones=getZones();
    const shouldCluster=zoom<CLUSTER_ZOOM&&zones;
    
    if(shouldCluster){
        // Mode cluster: retirer marqueurs de la carte, afficher clusters
        if(!clusterMode){
            markers.forEach(m=>map.removeLayer(m));
        }
        clusterMode=true;
        renderClusters();
    }else{
        // Mode normal: retirer clusters, remettre marqueurs
        if(clusterMode){
            clusterMarkers.forEach(m=>map.removeLayer(m));
            clusterMarkers=[];
            markers.forEach(m=>map.addLayer(m));
        }
        clusterMode=false;
    }
}

// === FILTRES PAR POINTS ===
function togglePtsFilter(id){document.getElementById(id).classList.toggle('on');render();updateInvaderSelect();}
function ptsOnly(...pts){
    ['pts10','pts20','pts30','pts40','pts50','pts100'].forEach(id=>{
        const el=document.getElementById(id);
        const val=parseInt(id.replace('pts',''));
        if(pts.includes(val))el.classList.add('on');
        else el.classList.remove('on');
    });
    render();updateInvaderSelect();
}
function ptsAll(){
    ['pts10','pts20','pts30','pts40','pts50','pts100'].forEach(id=>document.getElementById(id).classList.add('on'));
    render();updateInvaderSelect();
}

function filterUnknownOnly(){
    // Désactiver tous les filtres sauf position inconnue
    ['tHunt','tRestored','tFlash','tDamaged','tHidden','tDestroyed','tFlashedIndispo'].forEach(id=>{
        document.getElementById(id)?.classList.remove('on');
    });
    document.getElementById('tUnknownLoc')?.classList.add('on');
    // Activer tous les points
    ['pts10','pts20','pts30','pts40','pts50','pts100'].forEach(id=>document.getElementById(id)?.classList.add('on'));
    render();updateInvaderSelect();
    
    // Compter les invaders avec position inconnue
    const count=invaders.filter(i=>i.location_unknown===true).length;
    showPosAlert('info','📍',`${count} invader${count>1?'s':''} avec position inconnue`);
}

function filterReset(){
    // Réinitialiser les filtres par défaut
    document.getElementById('tHunt')?.classList.add('on');
    document.getElementById('tRestored')?.classList.remove('on');
    document.getElementById('tFlash')?.classList.remove('on');
    document.getElementById('tDamaged')?.classList.add('on');
    document.getElementById('tHidden')?.classList.remove('on');
    document.getElementById('tDestroyed')?.classList.remove('on');
    document.getElementById('tFlashedIndispo')?.classList.remove('on');
    document.getElementById('tUnknownLoc')?.classList.add('on');
    ['pts10','pts20','pts30','pts40','pts50','pts100'].forEach(id=>document.getElementById(id)?.classList.add('on'));
    render();updateInvaderSelect();
}

// === POINT DE DÉPART CUSTOM ===
function setCustomStart(lat,lng){
    customStart={lat,lng};
    if(customStartMarker)map.removeLayer(customStartMarker);
    customStartMarker=L.marker([lat,lng],{
        icon:L.divIcon({
            className:'start-marker',
            html:'<div style="width:30px;height:30px;background:#4CAF50;border:3px solid #fff;border-radius:50%;box-shadow:0 2px 8px rgba(0,0,0,.3);display:flex;align-items:center;justify-content:center;color:#fff;font-size:16px">🚩</div>',
            iconSize:[30,30],iconAnchor:[15,15]
        })
    }).addTo(map);
    customStartMarker.bindPopup('<b>🚩 Point de départ</b><br><button onclick="clearStartPoint()" style="margin-top:8px;padding:6px 12px;border:none;border-radius:6px;background:#f44336;color:#fff;cursor:pointer">Supprimer</button>');
    showPosAlert('success','🚩','Point de départ défini!');
    updateRoutePanel();
}
function clearStartPoint(){
    customStart=null;
    if(customStartMarker){map.removeLayer(customStartMarker);customStartMarker=null;}
    updateRoutePanel();
    showPosAlert('success','✓','Point de départ supprimé');
}

function showUid(){showPanel('uidPanel');}
function showFilters(){showPanel('filterPanel');}
function showRoute(){showPanel('routePanel');}
function showSearch(){showPanel('searchPanel');}
function showPanel(id){['uidPanel','filterPanel','routePanel','searchPanel','helpPanel'].forEach(p=>document.getElementById(p).classList.add('hidden'));document.getElementById(id).classList.remove('hidden');}
function hidePanel(id){document.getElementById(id).classList.add('hidden');}
function showHelp(){showPanel('helpPanel');}

// === GÉNÉRATEUR DE PARCOURS ===
let genMode='count',genValue=8,genFilters=['hunt'],myPosition=null;

function getStartPoint(){
    // Priorité: customStart > myPosition
    return customStart || myPosition;
}

function showRouteGenerator(){
    hidePanel('routePanel');
    
    // Si on a un point de départ custom, l'utiliser directement
    if(customStart){
        document.getElementById('genModal').classList.add('show');
        updateGenPreview();
        return;
    }
    
    // Sinon demander la géolocalisation
    if(!navigator.geolocation){alert('Géolocalisation non disponible. Fais un clic long sur la carte pour définir un point de départ.');return;}
    show('Localisation...');
    navigator.geolocation.getCurrentPosition(pos=>{
        hide();myPosition={lat:pos.coords.latitude,lng:pos.coords.longitude};
        document.getElementById('genModal').classList.add('show');
        updateGenPreview();
    },err=>{hide();alert('Géolocalisation refusée. Fais un clic long sur la carte pour définir un point de départ.');},{enableHighAccuracy:true,timeout:15000,maximumAge:0});
}
function closeGenModal(){document.getElementById('genModal').classList.remove('show');}

function selectGenMode(mode){
    genMode=mode;
    // Mettre à jour les tabs
    document.querySelectorAll('.gen-mode-tab').forEach(t=>t.classList.remove('active'));
    document.querySelector(`.gen-mode-tab[data-mode="${mode}"]`).classList.add('active');
    
    // Afficher les bonnes options
    document.getElementById('genCountOpts').classList.toggle('hidden',mode!=='count');
    document.getElementById('genDurationOpts').classList.toggle('hidden',mode!=='duration');
    document.getElementById('genDistanceOpts').classList.toggle('hidden',mode!=='distance');
    
    // Valeur par défaut selon le mode
    if(mode==='count')genValue=8;
    else if(mode==='duration')genValue=60;
    else if(mode==='distance')genValue=2;
    
    updateGenPreview();
}

function selectOpt(el,val){el.parentElement.querySelectorAll('.gen-opt').forEach(o=>o.classList.remove('selected'));el.classList.add('selected');genValue=val;updateGenPreview();}
function toggleGenFilter(el){el.classList.toggle('active');const s=el.dataset.status;if(el.classList.contains('active')){if(!genFilters.includes(s))genFilters.push(s);}else{genFilters=genFilters.filter(f=>f!==s);}updateGenPreview();}

function updateGenPreview(){
    const start=getStartPoint();
    if(!start)return;
    const result=calculateRoute();
    document.getElementById('previewCount').textContent=result.invaders.length;
    document.getElementById('previewDist').textContent=result.totalDistance.toFixed(1);
    document.getElementById('previewTime').textContent=Math.round(result.totalTime);
    document.getElementById('previewPts').textContent=result.totalPoints;
    document.getElementById('genBtn').disabled=result.invaders.length===0;
}

function calculateRoute(){
    const start=getStartPoint();
    if(!start)return{invaders:[],totalDistance:0,totalTime:0,totalPoints:0};
    
    // Vitesse marche ~5km/h, temps par invader ~2min (photo, chercher, etc.)
    // Facteur 1.4 pour convertir vol d'oiseau -> distance réelle à pied
    const WALK_SPEED=5,TIME_PER_INVADER=2,ROUTE_FACTOR=1.4;
    
    // Filtrer les invaders disponibles
    let available=invaders.filter(i=>{
        const cat=getCat(i);
        const restored=isRestored(i);
        
        // Filtre Restaurés actif
        if(genFilters.includes('restored')){
            // Si À chasser aussi actif → restaurés non flashés seulement
            if(genFilters.includes('hunt')){
                return restored&&!cat.startsWith('flashed');
            }
            // Restaurés seul → tous les restaurés (flashés ou non)
            return restored;
        }
        
        // Filtres standards (sans restaurés)
        if(cat.startsWith('flashed'))return false;
        return genFilters.includes(cat);
    });
    
    if(available.length===0)return{invaders:[],totalDistance:0,totalTime:0,totalPoints:0};
    available=available.map(i=>({...i,distFromMe:getDistance(start.lat,start.lng,i.lat,i.lng)}));
    available.sort((a,b)=>a.distFromMe-b.distFromMe);
    
    let selected=[],currentPos={...start},totalDistanceRaw=0,totalPoints=0;
    // Limites en "équivalent vol d'oiseau" pour que le résultat final soit correct
    let maxDistRaw=genMode==='distance'?genValue/ROUTE_FACTOR:Infinity;
    let maxTimeRaw=genMode==='duration'?genValue/(ROUTE_FACTOR*60/WALK_SPEED+TIME_PER_INVADER/1000):Infinity;
    let maxCount=genMode==='count'?genValue:100;
    
    while(available.length>0&&selected.length<maxCount){
        let bestIdx=0,bestDist=Infinity;
        for(let i=0;i<available.length;i++){const d=getDistance(currentPos.lat,currentPos.lng,available[i].lat,available[i].lng);if(d<bestDist){bestDist=d;bestIdx=i;}}
        const next=available[bestIdx];
        const distToNextRaw=getDistance(currentPos.lat,currentPos.lng,next.lat,next.lng);
        
        // Calculer la distance et temps réels estimés si on ajoute cet invader
        const newTotalDistRaw=totalDistanceRaw+distToNextRaw;
        const newTotalDist=newTotalDistRaw*ROUTE_FACTOR;
        const newTotalTime=(newTotalDist/WALK_SPEED)*60+(selected.length+1)*TIME_PER_INVADER;
        
        // Vérifier les limites
        if(genMode==='distance'&&newTotalDist>genValue)break;
        if(genMode==='duration'&&newTotalTime>genValue)break;
        
        selected.push(next);
        totalDistanceRaw=newTotalDistRaw;
        totalPoints+=next.points;
        currentPos={lat:next.lat,lng:next.lng};
        available.splice(bestIdx,1);
    }
    
    const totalDistance=totalDistanceRaw*ROUTE_FACTOR;
    const totalTime=(totalDistance/WALK_SPEED)*60+selected.length*TIME_PER_INVADER;
    return{invaders:selected,totalDistance,totalTime,totalPoints};
}

function generateRoute(){
    const start=getStartPoint();
    const result=calculateRoute();
    if(result.invaders.length===0){alert('Aucun invader trouvé avec ces critères.');return;}
    route=result.invaders.map(i=>({name:i.name,lat:i.lat,lng:i.lng,points:i.points}));
    saveRoute();
    closeGenModal();render();
    document.getElementById('sRoute').textContent=route.length;
    showPanel('routePanel');
    if(route.length>0&&start){const bounds=L.latLngBounds(route.map(r=>[r.lat,r.lng]));bounds.extend([start.lat,start.lng]);map.fitBounds(bounds,{padding:[50,50]});}
    showPosAlert('success','✅',`Parcours: ${result.invaders.length} invaders, ${result.totalDistance.toFixed(1)}km, ~${Math.round(result.totalTime)}min`);
}

// === NOUVELLES FONCTIONNALITÉS ===

// 1. PROXIMITÉ - 10 plus proches non flashés (visualisation uniquement)
let nearbyHighlight=[];
function findNearby(){
    const start=getStartPoint();
    if(!start){
        if(!navigator.geolocation){alert('Active la géoloc ou fais un clic long sur la carte');return;}
        show('Localisation...');
        navigator.geolocation.getCurrentPosition(pos=>{
            hide();
            myPosition={lat:pos.coords.latitude,lng:pos.coords.longitude};
            doFindNearby(myPosition);
        },()=>{hide();alert('Géoloc refusée. Fais un clic long sur la carte.');});
        return;
    }
    doFindNearby(start);
}
function doFindNearby(pos){
    const available=invaders.filter(i=>{const cat=getCat(i);return cat==='hunt'||cat==='damaged';});
    if(!available.length){alert('Aucun invader à chasser!');return;}
    const sorted=available.map(i=>({...i,dist:getDistance(pos.lat,pos.lng,i.lat,i.lng)})).sort((a,b)=>a.dist-b.dist);
    const top10=sorted.slice(0,10);
    
    // Stocker les noms pour highlight
    nearbyHighlight=top10.map(i=>i.name);
    render(); // Re-render pour appliquer le highlight
    
    // Zoomer sur la zone
    const bounds=L.latLngBounds(top10.map(i=>[i.lat,i.lng]));
    bounds.extend([pos.lat,pos.lng]);
    map.fitBounds(bounds,{padding:[50,50]});
    
    // Afficher les distances
    const distances=top10.map((i,idx)=>`${idx+1}. ${i.name}: ${(i.dist*1000).toFixed(0)}m`).join('\\n');
    showPosAlert('success','📍',`10 plus proches affichés`);
    
    // Fermer après 10 secondes
    setTimeout(()=>{nearbyHighlight=[];render();},15000);
}
function addNearbyToRoute(){
    if(!nearbyHighlight.length){alert('Utilise "10 proches" avant');return;}
    const toAdd=invaders.filter(i=>nearbyHighlight.includes(i.name));
    toAdd.forEach(i=>{
        if(!route.find(r=>r.name===i.name)&&route.length<20){
            route.push({name:i.name,lat:i.lat,lng:i.lng,points:i.points});
        }
    });
    saveRoute();
    render();
    document.getElementById('sRoute').textContent=route.length;
    showPosAlert('success','✅',`${toAdd.length} invaders ajoutés au parcours`);
}

// 2. OPTIMISATION TSP (plus proche voisin)
function optimizeRoute(){
    if(route.length<3){alert('Ajoute au moins 3 invaders pour optimiser');return;}
    const start=getStartPoint()||{lat:route[0].lat,lng:route[0].lng};
    const optimized=[],remaining=[...route];
    let current=start;
    
    while(remaining.length>0){
        let bestIdx=0,bestDist=Infinity;
        for(let i=0;i<remaining.length;i++){
            const d=getDistance(current.lat,current.lng,remaining[i].lat,remaining[i].lng);
            if(d<bestDist){bestDist=d;bestIdx=i;}
        }
        optimized.push(remaining[bestIdx]);
        current=remaining[bestIdx];
        remaining.splice(bestIdx,1);
    }
    
    // Calculer gain
    const oldDist=calcRouteDist(route,start);
    const newDist=calcRouteDist(optimized,start);
    const gain=((oldDist-newDist)/oldDist*100).toFixed(0);
    
    route=optimized;
    saveRoute();
    render();
    showPosAlert('success','🔀',`Parcours optimisé! ${gain}% plus court`);
}

function calcRouteDist(r,start){
    let d=0,prev=start;
    r.forEach(p=>{d+=getDistance(prev.lat,prev.lng,p.lat,p.lng);prev=p;});
    return d;
}

// 3. MODE CIRCUIT (retour au départ)
function toggleCircuit(){
    circuitMode=!circuitMode;
    document.getElementById('circuitToggle').classList.toggle('active',circuitMode);
    updateRoutePanel();
}

// 4. EXPORT GPX
function exportGPX(){
    if(!route.length){alert('Ajoute des invaders au parcours!');return;}
    const start=getStartPoint();
    let gpx=`<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="TotalInvadersSearch">
<metadata><name>Parcours Invaders - ${cityName}</name><time>${new Date().toISOString()}</time></metadata>
<trk><name>Chasse aux Invaders</name><trkseg>
`;
    if(start)gpx+=`<trkpt lat="${start.lat}" lon="${start.lng}"><name>Départ</name></trkpt>\n`;
    route.forEach((r,i)=>{gpx+=`<trkpt lat="${r.lat}" lon="${r.lng}"><name>${r.name}</name></trkpt>\n`;});
    if(circuitMode&&start)gpx+=`<trkpt lat="${start.lat}" lon="${start.lng}"><name>Retour</name></trkpt>\n`;
    gpx+=`</trkseg></trk>
`;
    route.forEach(r=>{gpx+=`<wpt lat="${r.lat}" lon="${r.lng}"><name>${r.name}</name><desc>${r.points} points</desc></wpt>\n`;});
    gpx+=`</gpx>`;
    
    const blob=new Blob([gpx],{type:'application/gpx+xml'});
    const url=URL.createObjectURL(blob);
    const a=document.createElement('a');
    a.href=url;a.download=`invaders_${cityName}_${new Date().toISOString().slice(0,10)}.gpx`;
    a.click();
    URL.revokeObjectURL(url);
    showPosAlert('success','💾','Fichier GPX téléchargé!');
}

// 5. STATS & PANNEAU
function showStats(){
    updateStats();
    updateZoneProgress();
    updateProgressChart();
    updateReplayDaysList();
    updateCacheStatus();
    updateOnlineStatus();
    showPanel('statsPanel');
}

function updateZoneProgress(){
    const container=document.getElementById('zoneProgress');
    const list=document.getElementById('zoneProgressList');
    if(!container||!list)return;
    const zones=getZones();
    if(!zones){container.style.display='none';return;}
    container.style.display='block';
    
    const stats={};
    Object.keys(zones).forEach(z=>stats[z]={total:0,flashed:0,hunt:0});
    invaders.forEach(inv=>{
        const z=getZone(inv);
        if(!z||!stats[z])return;
        const cat=getCat(inv);
        stats[z].total++;
        if(cat==='flashed'||cat.startsWith('flashed'))stats[z].flashed++;
        else if(cat==='hunt'||cat==='damaged')stats[z].hunt++;
    });
    
    const sorted=Object.keys(zones).sort((a,b)=>{
        const nA=parseInt(a),nB=parseInt(b);
        if(!isNaN(nA)&&!isNaN(nB))return nA-nB;
        if(!isNaN(nA))return -1;
        if(!isNaN(nB))return 1;
        return a.localeCompare(b);
    });
    
    let html='';
    sorted.forEach(z=>{
        const s=stats[z];
        if(!s||s.total===0)return;
        // % = flashés / (flashés + chassables)
        const base=s.flashed+s.hunt;
        const pct=base>0?Math.round(s.flashed/base*100):0;
        const col=pct>=100?'#00aa55':pct>=75?'#4caf50':pct>=50?'#ffc107':pct>=25?'#ff9800':'#ff6b6b';
        html+=`<div style="padding:6px 8px;background:#f8f9fa;border-radius:6px;cursor:pointer" onclick="map.setView([${zones[z].lat},${zones[z].lng}],16)">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px">
                <span style="font-weight:600;font-size:11px;max-width:65%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${z}</span>
                <span style="font-weight:700;font-size:12px;color:${col}">${pct}%</span>
            </div>
            <div style="height:3px;background:#e0e0e0;border-radius:2px;overflow:hidden">
                <div style="height:100%;width:${pct}%;background:${col}"></div>
            </div>
            <div style="font-size:9px;color:#888;margin-top:2px">${s.flashed}/${base}${s.hunt>0?' • 🎯'+s.hunt:''}</div>
        </div>`;
    });
    list.innerHTML=html;
}

// === GRAPHIQUE PROGRESSION ===
let progressChart=null,chartPeriod='all',chartMode='count';

function updateProgressChart(){
    const container=document.getElementById('progressChart');
    if(!flashedData.length){container.style.display='none';return;}
    container.style.display='block';
    
    // Trier par date
    const sorted=[...flashedData].filter(d=>d.date).sort((a,b)=>new Date(a.date)-new Date(b.date));
    if(!sorted.length){container.style.display='none';return;}
    
    // Filtrer par période
    let filtered=sorted;
    const now=new Date();
    if(chartPeriod==='year'){
        const yearAgo=new Date(now.getFullYear()-1,now.getMonth(),now.getDate());
        filtered=sorted.filter(d=>new Date(d.date)>=yearAgo);
    }else if(chartPeriod==='month'){
        const monthAgo=new Date(now.getFullYear(),now.getMonth()-1,now.getDate());
        filtered=sorted.filter(d=>new Date(d.date)>=monthAgo);
    }
    
    if(!filtered.length){
        document.getElementById('chartStats').innerHTML='<span style="color:#888">Aucun flash sur cette période</span>';
        if(progressChart){progressChart.destroy();progressChart=null;}
        return;
    }
    
    // Agrégation: mois si tout/année, jour si mois
    const byDay=chartPeriod==='month';
    const aggregated=aggregateByPeriod(filtered,byDay);
    
    // Données selon le mode (invaders ou points)
    const isPoints=chartMode==='points';
    const barData=aggregated.map(d=>isPoints?d.points:d.count);
    const avgData=aggregated.map(d=>d.count>0?(d.points/d.count).toFixed(1):0);
    let cumul=0;
    const cumulData=aggregated.map(d=>{cumul+=(isPoints?d.points:d.count);return cumul;});
    
    // Stats
    const totalFlashed=filtered.length;
    const totalPts=filtered.reduce((s,d)=>s+(d.points||10),0);
    const avgPts=(totalPts/totalFlashed).toFixed(1);
    const periodLabel=byDay?'jour':'mois';
    const modeLabel=isPoints?'points':'invaders';
    
    document.getElementById('chartStats').innerHTML=`
        <span>👾 ${totalFlashed} flashés</span>
        <span>💰 ${totalPts} pts</span>
        ${isPoints?`<span>📊 Moy: ${avgPts} pts/inv</span>`:''}
        <span>📈 Total: ${cumulData[cumulData.length-1]} ${modeLabel}</span>
    `;
    
    // Couleurs selon le mode
    const barColor=isPoints?'rgba(102,126,234,0.7)':'rgba(0,170,85,0.7)';
    const barBorder=isPoints?'#667eea':'#00aa55';
    const lineColor=isPoints?'#ff9800':'#667eea';
    
    // Datasets
    const datasets=[{
        label:(isPoints?'Points':'Flashés')+' par '+periodLabel,
        data:barData,
        backgroundColor:barColor,
        borderColor:barBorder,
        borderWidth:1,
        yAxisID:'y',
        order:2
    },{
        label:'Cumul '+(isPoints?'points':'flashés'),
        data:cumulData,
        type:'line',
        borderColor:lineColor,
        backgroundColor:'transparent',
        borderWidth:2,
        tension:0.3,
        pointRadius:2,
        yAxisID:'y1',
        order:1
    }];
    
    // Ajouter la moyenne par période en mode points
    if(isPoints){
        datasets.push({
            label:'Moy pts/inv',
            data:avgData,
            type:'line',
            borderColor:'#e91e63',
            backgroundColor:'transparent',
            borderWidth:2,
            borderDash:[5,5],
            tension:0.3,
            pointRadius:3,
            pointBackgroundColor:'#e91e63',
            yAxisID:'y2',
            order:0
        });
    }
    
    // Scales
    const scales={
        x:{ticks:{maxRotation:45,font:{size:9}},grid:{display:false}},
        y:{beginAtZero:true,position:'left',title:{display:true,text:(isPoints?'Points':'Invaders')+'/'+periodLabel,font:{size:10}}},
        y1:{beginAtZero:true,position:'right',grid:{drawOnChartArea:false},title:{display:true,text:'Cumul',font:{size:10}}}
    };
    
    // Axe pour la moyenne en mode points
    if(isPoints){
        scales.y2={beginAtZero:true,position:'right',grid:{drawOnChartArea:false},title:{display:true,text:'Moy/inv',font:{size:10}},ticks:{color:'#e91e63'}};
    }
    
    // Créer/mettre à jour le graphique
    const ctx=document.getElementById('flashedChart').getContext('2d');
    if(progressChart)progressChart.destroy();
    
    progressChart=new Chart(ctx,{
        type:'bar',
        data:{
            labels:aggregated.map(d=>d.label),
            datasets:datasets
        },
        options:{
            responsive:true,
            maintainAspectRatio:false,
            interaction:{intersect:false,mode:'index'},
            plugins:{legend:{display:true,position:'top',labels:{boxWidth:12,font:{size:10}}}},
            scales:scales
        }
    });
}

function aggregateByPeriod(data,byDay){
    const groups={};
    data.forEach(d=>{
        const date=new Date(d.date);
        let key;
        if(byDay){
            key=date.toLocaleDateString('fr-FR',{day:'2-digit',month:'short'});
        }else{
            key=date.toLocaleDateString('fr-FR',{month:'short',year:'2-digit'});
        }
        if(!groups[key])groups[key]={label:key,count:0,points:0};
        groups[key].count++;
        groups[key].points+=d.points||10;
    });
    return Object.values(groups);
}

function setChartPeriod(period){
    chartPeriod=period;
    document.querySelectorAll('.chart-period-btn').forEach(b=>b.classList.toggle('active',b.dataset.period===period));
    updateProgressChart();
}

function setChartMode(mode){
    chartMode=mode;
    document.querySelectorAll('.chart-mode-btn').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode));
    updateProgressChart();
}

// === REPLAY DES JOURNÉES DE CHASSE ===
let replayMode=false;
let replayMarkers=[];
let replayLine=null;

function updateReplayDaysList(){
    const container=document.getElementById('replayDaysList');
    if(!container)return;
    if(!flashedData||!flashedData.length){
        container.innerHTML='<div style="color:#888;font-size:12px;padding:10px;text-align:center">Charge tes flashés pour voir ton historique</div>';
        return;
    }
    
    // Grouper par jour
    const days={};
    let withDate=0,withoutDate=0;
    flashedData.forEach(f=>{
        if(!f.date){withoutDate++;return;}
        try{
            const d=new Date(f.date);
            if(isNaN(d.getTime())){withoutDate++;return;}
            const key=d.toISOString().slice(0,10);
            if(!days[key])days[key]={date:key,count:0,points:0,flashes:[]};
            days[key].count++;
            days[key].points+=f.points||10;
            days[key].flashes.push(f);
            withDate++;
        }catch(e){withoutDate++;}
    });
    
    // Trier par date décroissante
    const sortedDays=Object.values(days).sort((a,b)=>b.date.localeCompare(a.date));
    
    if(sortedDays.length===0){
        container.innerHTML=`<div style="color:#888;font-size:12px;padding:10px;text-align:center">Aucune date de flash disponible${withoutDate>0?`<br>(${withoutDate} flashs sans date)`:''}</div>`;
        return;
    }
    
    // Header avec stats
    let html=`<div style="font-size:11px;color:#666;margin-bottom:8px;padding:4px 8px;background:#f0f0f0;border-radius:4px">
        📆 ${sortedDays.length} journées de chasse${withoutDate>0?` • ${withoutDate} flashs sans date`:''}
    </div>`;
    
    // Liste des jours (sans limite)
    html+=sortedDays.map(day=>{
        const dateObj=new Date(day.date+'T12:00:00');
        const dateStr=dateObj.toLocaleDateString('fr-FR',{weekday:'short',day:'numeric',month:'short',year:'numeric'});
        return `
            <div class="replay-day" onclick="showReplayDay('${day.date}')" data-date="${day.date}">
                <div class="replay-day-date">${dateStr}</div>
                <div class="replay-day-count">👾 ${day.count}</div>
                <div class="replay-day-pts">+${day.points}pts</div>
                <button class="replay-day-btn" onclick="event.stopPropagation();showReplayDay('${day.date}')">📍 Voir</button>
            </div>
        `;
    }).join('');
    
    container.innerHTML=html;
}

function showReplayDay(dateStr){
    // Trouver les flashs de ce jour pour la ville actuelle
    const dayFlashes=flashedData.filter(f=>{
        if(!f.date)return false;
        try{
            const d=new Date(f.date);
            if(isNaN(d.getTime()))return false;
            const key=d.toISOString().slice(0,10);
            return key===dateStr;
        }catch(e){return false;}
    });
    
    if(dayFlashes.length===0){
        showPosAlert('error','❌','Aucun flash trouvé pour ce jour');
        return;
    }
    
    // Trier par heure
    dayFlashes.sort((a,b)=>new Date(a.date)-new Date(b.date));
    
    // Trouver les invaders correspondants dans la ville actuelle
    const dayInvaders=[];
    dayFlashes.forEach(f=>{
        const inv=invaders.find(i=>
            i.name===f.name||
            i.name.toUpperCase()===f.name.toUpperCase()||
            i.name.replace(/_/g,'-')===f.name.replace(/_/g,'-')
        );
        if(inv){
            dayInvaders.push({
                ...inv,
                flashTime:f.date,
                flashPoints:f.points
            });
        }
    });
    
    // Activer le mode replay
    clearReplay();
    replayMode=true;
    
    // Marquer le jour actif
    document.querySelectorAll('.replay-day').forEach(el=>el.classList.remove('active'));
    const activeDay=document.querySelector(`.replay-day[data-date="${dateStr}"]`);
    if(activeDay)activeDay.classList.add('active');
    
    // Afficher les contrôles
    const dateObj=new Date(dateStr+'T12:00:00');
    const dateLabel=dateObj.toLocaleDateString('fr-FR',{weekday:'long',day:'numeric',month:'long',year:'numeric'});
    const replayControls=document.getElementById('replayControls');
    const replayInfo=document.getElementById('replayInfo');
    const replayStats=document.getElementById('replayStats');
    if(replayControls)replayControls.style.display='block';
    if(replayInfo)replayInfo.textContent=`📅 ${dateLabel}`;
    
    const totalPts=dayFlashes.reduce((s,f)=>s+(f.points||10),0);
    const inCity=dayInvaders.length;
    const cityPts=dayInvaders.reduce((s,i)=>s+(i.points||10),0);
    
    let statsHtml=`👾 ${dayFlashes.length} flashés ce jour (${totalPts} pts)`;
    if(inCity<dayFlashes.length){
        statsHtml+=`<br>📍 ${inCity} visibles à ${cityName} (${cityPts} pts)`;
    }
    
    // Ajouter les heures si disponibles
    if(dayInvaders.length>0){
        const firstTime=new Date(dayInvaders[0].flashTime).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'});
        const lastTime=new Date(dayInvaders[dayInvaders.length-1].flashTime).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'});
        if(dayInvaders.length>1){
            statsHtml+=`<br>⏱️ De ${firstTime} à ${lastTime}`;
            
            // Calculer la distance parcourue
            let dist=0;
            for(let i=1;i<dayInvaders.length;i++){
                dist+=getDistance(dayInvaders[i-1].lat,dayInvaders[i-1].lng,dayInvaders[i].lat,dayInvaders[i].lng);
            }
            dist*=1.3; // Facteur route (chemins pas droits)
            statsHtml+=`<br>📏 ~${dist.toFixed(1)} km parcourus`;
            
            // Calculer la durée de chasse
            const duration=new Date(dayInvaders[dayInvaders.length-1].flashTime)-new Date(dayInvaders[0].flashTime);
            const hours=Math.floor(duration/3600000);
            const mins=Math.floor((duration%3600000)/60000);
            if(hours>0){
                statsHtml+=` • ${hours}h${mins.toString().padStart(2,'0')}`;
            }else if(mins>0){
                statsHtml+=` • ${mins} min`;
            }
        }else{
            statsHtml+=`<br>⏱️ À ${firstTime}`;
        }
    }
    if(replayStats)replayStats.innerHTML=statsHtml;
    
    if(dayInvaders.length===0){
        showPosAlert('info','ℹ️',`${dayFlashes.length} flashés ce jour, mais aucun à ${cityName}`);
        return;
    }
    
    // Créer les marqueurs replay
    dayInvaders.forEach((inv,idx)=>{
        const time=new Date(inv.flashTime).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'});
        const icon=L.divIcon({
            className:'replay-marker',
            html:`<div style="
                width:32px;height:32px;
                background:linear-gradient(135deg,#4caf50,#2e7d32);
                border:3px solid #fff;
                border-radius:50%;
                display:flex;align-items:center;justify-content:center;
                color:#fff;font-weight:700;font-size:12px;
                box-shadow:0 2px 8px rgba(0,0,0,0.3);
            ">${idx+1}</div>`,
            iconSize:[32,32],
            iconAnchor:[16,16]
        });
        
        const marker=L.marker([inv.lat,inv.lng],{icon}).addTo(map);
        marker.bindPopup(`
            <div style="text-align:center;min-width:120px">
                <div style="font-size:14px;font-weight:700;color:#2e7d32">${inv.name}</div>
                <div style="font-size:18px;font-weight:700;margin:4px 0">${inv.points} pts</div>
                <div style="font-size:12px;color:#666">⏱️ ${time}</div>
                <div style="font-size:11px;color:#888;margin-top:4px">Étape ${idx+1}/${dayInvaders.length}</div>
            </div>
        `);
        replayMarkers.push(marker);
    });
    
    // Tracer le parcours
    if(dayInvaders.length>=2){
        const coords=dayInvaders.map(i=>[i.lat,i.lng]);
        replayLine=L.polyline(coords,{
            color:'#4caf50',
            weight:4,
            opacity:0.8,
            dashArray:'10,6'
        }).addTo(map);
        
        // Ajouter des flèches de direction
        // (optionnel - Leaflet n'a pas de support natif, on utilise juste la ligne)
    }
    
    // Ajuster la vue
    if(dayInvaders.length>0){
        const bounds=L.latLngBounds(dayInvaders.map(i=>[i.lat,i.lng]));
        map.fitBounds(bounds,{padding:[50,50],maxZoom:15});
    }
    
    showPosAlert('success','📅',`Replay: ${dayInvaders.length} invaders`);
}

function clearReplay(){
    replayMode=false;
    
    // Supprimer les marqueurs replay
    replayMarkers.forEach(m=>{try{map.removeLayer(m);}catch(e){}});
    replayMarkers=[];
    
    // Supprimer la ligne
    if(replayLine){
        try{map.removeLayer(replayLine);}catch(e){}
        replayLine=null;
    }
    
    // Masquer les contrôles
    const ctrl=document.getElementById('replayControls');
    if(ctrl)ctrl.style.display='none';
    
    // Démarquer les jours
    document.querySelectorAll('.replay-day').forEach(el=>el.classList.remove('active'));
}

function updateStats(){
    let flashedCount=0,flashedPts=0;
    let destroyedCount=0,destroyedPts=0;
    let huntableCount=0,huntablePts=0;
    
    invaders.forEach(i=>{
        const cat=getCat(i);
        // Flashés (y compris flashés+indispo)
        if(cat==='flashed'||cat.startsWith('flashed')){
            flashedCount++;
            flashedPts+=i.points;
        }
        // Détruits non flashés (perdus définitivement)
        else if(cat==='destroyed'){
            destroyedCount++;
            destroyedPts+=i.points;
        }
        // Chassables (hunt, damaged, hidden)
        else{
            huntableCount++;
            huntablePts+=i.points;
        }
    });
    
    const totalCount=invaders.length;
    const totalPts=flashedPts+destroyedPts+huntablePts;
    const percent=totalCount?Math.round(flashedCount/totalCount*100):0;
    
    document.getElementById('statsCityName').textContent=cityName;
    document.getElementById('statsFlashedCount').textContent=flashedCount;
    document.getElementById('statsTotalCount').textContent=totalCount;
    document.getElementById('statsPercent').textContent=percent;
    document.getElementById('statsProgressBar').style.width=percent+'%';
    document.getElementById('statsPoints').textContent=flashedPts;
    document.getElementById('statsRemaining').textContent=huntableCount;
    document.getElementById('statsRemainingPts').innerHTML=`${huntablePts} <span style="font-size:11px;color:#868e96">(+${destroyedPts} 💀)</span>`;
    document.getElementById('statsDestroyed').textContent=destroyedCount;
}

// 7. MODE SOMBRE
function toggleDarkMode(){
    darkMode=!darkMode;
    document.body.classList.toggle('dark-mode',darkMode);
    document.getElementById('darkToggle').classList.toggle('active',darkMode);
    document.getElementById('darkToggle').textContent=darkMode?'☀️':'🌙';
    localStorage.setItem('darkMode',darkMode);
}

// 8. HEATMAP
function toggleHeatmap(){
    if(heatmapLayer){
        map.removeLayer(heatmapLayer);
        heatmapLayer=null;
        document.getElementById('heatmapBtn').textContent='🔥 Afficher la heatmap';
        return;
    }
    // Points = invaders non flashés (zones à explorer)
    const points=invaders.filter(i=>{const cat=getCat(i);return cat==='hunt'||cat==='damaged';}).map(i=>[i.lat,i.lng,0.5]);
    if(!points.length){alert('Tous les invaders sont flashés!');return;}
    
    if(typeof L.heatLayer==='undefined'){alert('Plugin heatmap non chargé');return;}
    heatmapLayer=L.heatLayer(points,{radius:25,blur:15,maxZoom:17,gradient:{0.2:'blue',0.4:'lime',0.6:'yellow',0.8:'orange',1:'red'}}).addTo(map);
    document.getElementById('heatmapBtn').textContent='❌ Masquer la heatmap';
}

// Mise à jour panneau route avec distance et circuit
function updateRoutePanelExtended(){
    const start=getStartPoint();
    
    if(route.length>1){
        let dist=0,prev=start||route[0];
        route.forEach(r=>{dist+=getDistance(prev.lat,prev.lng,r.lat,r.lng);prev=r;});
        if(circuitMode&&start)dist+=getDistance(route[route.length-1].lat,route[route.length-1].lng,start.lat,start.lng);
        dist*=1.4; // Facteur route
        const time=Math.round((dist/5)*60+route.length*2);
        document.getElementById('routeDistance').textContent=`📏 ${dist.toFixed(1)}km • ⏱️ ~${time}min${circuitMode?' (circuit)':''}`;
    }else{
        document.getElementById('routeDistance').textContent='';
    }
}

// Override updateRoutePanel pour ajouter les infos
const _origUpdateRoutePanel=updateRoutePanel;
updateRoutePanel=function(){_origUpdateRoutePanel();updateRoutePanelExtended();}

// Init dark mode from localStorage
document.addEventListener('DOMContentLoaded',()=>{
    if(localStorage.getItem('darkMode')==='true'){
        darkMode=true;
        document.body.classList.add('dark-mode');
        document.getElementById('darkToggle')?.classList.add('active');
        const btn=document.getElementById('darkToggle');if(btn)btn.textContent='☀️';
    }
    
    // Détection offline
    updateOnlineStatus();
    window.addEventListener('online',updateOnlineStatus);
    window.addEventListener('offline',updateOnlineStatus);
});

// === SIGNALEMENT & NOTES ===
let currentReportInvader=null,currentReportMode=null;

function openReport(name){
    currentReportInvader=name;
    currentReportMode='report';
    const reports=JSON.parse(localStorage.getItem('invaderReports')||'{}');
    const current=reports[name]||'';
    
    document.getElementById('reportTitle').innerHTML='⚠️ Signaler '+name;
    document.getElementById('reportBody').innerHTML=`
        <div class="report-options">
            <div class="report-opt ${current==='Détruit'?'selected':''}" onclick="selectReportOpt(this,'Détruit')">💀 Détruit / Disparu</div>
            <div class="report-opt ${current==='Abîmé'?'selected':''}" onclick="selectReportOpt(this,'Abîmé')">🔨 Abîmé / Dégradé</div>
            <div class="report-opt ${current==='Caché'?'selected':''}" onclick="selectReportOpt(this,'Caché')">👁 Caché / Masqué</div>
            <div class="report-opt ${current==='Inconnu'?'selected':''}" onclick="selectReportOpt(this,'Inconnu')">❓ Inconnu</div>
            <div class="report-opt ${current==='OK'?'selected':''}" onclick="selectReportOpt(this,'OK')">✅ En bon état</div>
            <div class="report-opt ${current===''?'selected':''}" onclick="selectReportOpt(this,'')">🗑️ Supprimer signalement</div>
        </div>
    `;
    document.getElementById('reportModal').classList.add('show');
}

function openNote(name){
    currentReportInvader=name;
    currentReportMode='note';
    const notes=JSON.parse(localStorage.getItem('invaderNotes')||'{}');
    const current=notes[name]||'';
    
    document.getElementById('reportTitle').innerHTML='📝 Note pour '+name;
    document.getElementById('reportBody').innerHTML=`
        <textarea class="report-textarea" id="noteText" rows="4" placeholder="Ex: Derrière le panneau, visible le matin...">${current}</textarea>
        <div style="font-size:11px;color:#888;margin-top:8px">💡 Ces notes sont stockées localement sur ton appareil</div>
    `;
    document.getElementById('reportModal').classList.add('show');
}

function selectReportOpt(el,val){
    el.parentElement.querySelectorAll('.report-opt').forEach(o=>o.classList.remove('selected'));
    el.classList.add('selected');
    el.dataset.value=val;
}

function closeReportModal(){
    document.getElementById('reportModal').classList.remove('show');
    currentReportInvader=null;
    currentReportMode=null;
}

function saveReport(){
    if(!currentReportInvader)return;
    
    if(currentReportMode==='report'){
        const selected=document.querySelector('.report-opt.selected');
        const val=selected?.textContent?.includes('Détruit')?'Détruit':
                  selected?.textContent?.includes('Abîmé')?'Abîmé':
                  selected?.textContent?.includes('Caché')?'Caché':
                  selected?.textContent?.includes('bon état')?'OK':'';
        
        const reports=JSON.parse(localStorage.getItem('invaderReports')||'{}');
        if(val){
            reports[currentReportInvader]=val;
        }else{
            delete reports[currentReportInvader];
        }
        localStorage.setItem('invaderReports',JSON.stringify(reports));
        showPosAlert('success','✅','Signalement enregistré');
    }else if(currentReportMode==='note'){
        const noteText=document.getElementById('noteText').value.trim();
        const notes=JSON.parse(localStorage.getItem('invaderNotes')||'{}');
        if(noteText){
            notes[currentReportInvader]=noteText;
        }else{
            delete notes[currentReportInvader];
        }
        localStorage.setItem('invaderNotes',JSON.stringify(notes));
        showPosAlert('success','✅','Note enregistrée');
    }
    
    closeReportModal();
    render();
}

// === SIGNALEMENT GITHUB ===
const GITHUB_REPO='jojosh1er/space-invaders-db';

function openGitHubReport(name){
    const inv=invaders.find(i=>i.name===name);
    if(!inv)return;
    
    const currentStatus=inv.status||'OK';
    const userReport=JSON.parse(localStorage.getItem('invaderReports')||'{}')[name];
    const newStatus=userReport||'';
    const userNote=JSON.parse(localStorage.getItem('invaderNotes')||'{}')[name]||'';
    const hasUnknownLocation=inv.location_unknown===true||(inv.lat===0&&inv.lng===0);
    
    currentReportInvader=name;
    currentReportMode='github';
    window.currentGitHubGeoLoc=null;
    
    document.getElementById('reportTitle').innerHTML='🐙 Report to GitHub';
    document.getElementById('reportBody').innerHTML=`
        <div style="margin-bottom:12px">
            <div style="font-weight:600;margin-bottom:4px">Invader: ${name}</div>
            <div style="font-size:13px;color:#666">Current status: ${currentStatus}</div>
            ${hasUnknownLocation?'<div style="font-size:12px;color:#17a2b8;margin-top:4px">📍 Location currently unknown or approximate</div>':''}
        </div>
        <div style="margin-bottom:12px">
            <label style="font-size:12px;color:#666;display:block;margin-bottom:4px">New observed status:</label>
            <select id="githubStatus" style="width:100%;padding:10px;border:2px solid #eee;border-radius:8px;font-size:14px">
                <option value="OK" ${newStatus==='OK'?'selected':''}>✅ OK / Good condition</option>
                <option value="Damaged" ${newStatus==='Abîmé'||newStatus==='Damaged'?'selected':''}>⚠️ Damaged / Degraded</option>
                <option value="Destroyed" ${newStatus==='Détruit'||newStatus==='Destroyed'?'selected':''}>💀 Destroyed / Gone</option>
                <option value="Hidden" ${newStatus==='Caché'||newStatus==='Hidden'?'selected':''}>👁 Hidden / Covered</option>
                <option value="Unknown" ${newStatus==='Inconnu'||newStatus==='Unknown'?'selected':''}>❓ Unknown / Inconnu</option>
            </select>
        </div>
        <div style="margin-bottom:12px;padding:12px;background:#e3f2fd;border-radius:10px">
            <div style="font-size:13px;font-weight:600;color:#1565c0;margin-bottom:8px">📍 Report exact location</div>
            <div style="font-size:12px;color:#666;margin-bottom:8px">Are you in front of the invader? Capture your current GPS position:</div>
            <button onclick="captureGeoLocation()" id="geoCapBtn" style="width:100%;padding:10px;border:none;border-radius:8px;background:#1976d2;color:#fff;font-size:13px;cursor:pointer">
                📡 Capture my current location
            </button>
            <div id="geoCaptureResult" style="margin-top:8px;font-size:12px;display:none"></div>
        </div>
        <div style="margin-bottom:12px">
            <label style="font-size:12px;color:#666;display:block;margin-bottom:4px">Notes (optional):</label>
            <textarea class="report-textarea" id="githubNotes" rows="3" placeholder="Additional details...">${userNote}</textarea>
        </div>
        <div style="margin-bottom:12px;padding:12px;background:#f3e5f5;border-radius:10px">
            <div style="font-size:13px;font-weight:600;color:#7b1fa2;margin-bottom:8px">📸 Photos (optional)</div>
            <div style="font-size:12px;color:#666;margin-bottom:8px">Paste image URLs (Imgur, Google Photos share link, etc.)</div>
            <label style="font-size:11px;color:#888;display:block;margin-bottom:2px">Image of the invader:</label>
            <input type="text" id="githubImgInvader" placeholder="https://..." style="width:100%;padding:8px;border:2px solid #eee;border-radius:8px;font-size:13px;margin-bottom:8px;box-sizing:border-box">
            <label style="font-size:11px;color:#888;display:block;margin-bottom:2px">Image of the location:</label>
            <input type="text" id="githubImgLieu" placeholder="https://..." style="width:100%;padding:8px;border:2px solid #eee;border-radius:8px;font-size:13px;box-sizing:border-box">
        </div>
        <div style="background:#f0f7ff;padding:10px;border-radius:8px;font-size:11px;color:#1565c0">
            ℹ️ This will open a pre-filled GitHub issue. You need a GitHub account to submit.
        </div>
    `;
    document.getElementById('reportModal').classList.add('show');
}

function openNewInvaderReport(){
    currentReportInvader='__NEW__';
    currentReportMode='new-invader';
    window.currentGitHubGeoLoc=null;
    
    // Pré-remplir le code ville si on est sur une ville
    const cityPrefix=typeof cityCode!=='undefined'&&cityCode?cityCode+'_':'';
    
    document.getElementById('reportTitle').innerHTML='➕ Signaler un nouvel invader';
    document.getElementById('reportBody').innerHTML=`
        <div style="margin-bottom:12px;padding:12px;background:#e8f5e9;border-radius:10px">
            <div style="font-size:13px;font-weight:600;color:#2e7d32;margin-bottom:8px">🛸 Nouvel invader découvert !</div>
            <div style="font-size:12px;color:#666;margin-bottom:8px">Tu as trouvé un invader qui n'est pas dans la base ?</div>
        </div>
        <div style="margin-bottom:12px">
            <label style="font-size:12px;color:#666;display:block;margin-bottom:4px">Code invader (ex: PA_1530, LY_78) :</label>
            <input type="text" id="newInvaderId" placeholder="${cityPrefix}" style="width:100%;padding:10px;border:2px solid #eee;border-radius:8px;font-size:14px;text-transform:uppercase;box-sizing:border-box" autocapitalize="characters">
        </div>
        <div style="margin-bottom:12px">
            <label style="font-size:12px;color:#666;display:block;margin-bottom:4px">Points estimés :</label>
            <select id="newInvaderPoints" style="width:100%;padding:10px;border:2px solid #eee;border-radius:8px;font-size:14px">
                <option value="0">? Inconnu</option>
                <option value="10">10 pts</option>
                <option value="20">20 pts</option>
                <option value="30">30 pts</option>
                <option value="40">40 pts</option>
                <option value="50" selected>50 pts</option>
                <option value="100">100 pts</option>
            </select>
        </div>
        <div style="margin-bottom:12px">
            <label style="font-size:12px;color:#666;display:block;margin-bottom:4px">Statut observé :</label>
            <select id="newInvaderStatus" style="width:100%;padding:10px;border:2px solid #eee;border-radius:8px;font-size:14px">
                <option value="OK" selected>✅ OK / En bon état</option>
                <option value="Damaged">⚠️ Abîmé / Dégradé</option>
                <option value="Destroyed">💀 Détruit / Disparu</option>
                <option value="Hidden">👁 Caché / Masqué</option>
                <option value="Unknown">❓ Inconnu</option>
            </select>
        </div>
        <div style="margin-bottom:12px;padding:12px;background:#e3f2fd;border-radius:10px">
            <div style="font-size:13px;font-weight:600;color:#1565c0;margin-bottom:8px">📍 Position (recommandé)</div>
            <div style="font-size:12px;color:#666;margin-bottom:8px">Tu es devant l'invader ? Capture ta position GPS :</div>
            <button onclick="captureGeoLocation()" id="geoCapBtn" style="width:100%;padding:10px;border:none;border-radius:8px;background:#1976d2;color:#fff;font-size:13px;cursor:pointer">
                📡 Capturer ma position
            </button>
            <div id="geoCaptureResult" style="margin-top:8px;font-size:12px;display:none"></div>
        </div>
        <div style="margin-bottom:12px;padding:12px;background:#f3e5f5;border-radius:10px">
            <div style="font-size:13px;font-weight:600;color:#7b1fa2;margin-bottom:8px">📸 Photos (optionnel)</div>
            <label style="font-size:11px;color:#888;display:block;margin-bottom:2px">Image de l'invader :</label>
            <input type="text" id="githubImgInvader" placeholder="https://..." style="width:100%;padding:8px;border:2px solid #eee;border-radius:8px;font-size:13px;margin-bottom:8px;box-sizing:border-box">
            <label style="font-size:11px;color:#888;display:block;margin-bottom:2px">Image du lieu :</label>
            <input type="text" id="githubImgLieu" placeholder="https://..." style="width:100%;padding:8px;border:2px solid #eee;border-radius:8px;font-size:13px;box-sizing:border-box">
        </div>
        <div style="margin-bottom:12px">
            <label style="font-size:12px;color:#666;display:block;margin-bottom:4px">Notes (optionnel) :</label>
            <textarea class="report-textarea" id="newInvaderNotes" rows="3" placeholder="Ex: Au coin de la rue, 3ème étage..."></textarea>
        </div>
        <div style="background:#f0f7ff;padding:10px;border-radius:8px;font-size:11px;color:#1565c0">
            ℹ️ Une issue GitHub sera créée. Tu as besoin d'un compte GitHub pour valider.
        </div>
    `;
    document.getElementById('reportModal').classList.add('show');
}

function submitNewInvaderReport(){
    const invId=(document.getElementById('newInvaderId')?.value||'').trim().toUpperCase().replace(/[- ]/g,'_');
    if(!invId||!/^[A-Z]+_\\d+$/.test(invId)){
        showPosAlert('error','❌','Code invader invalide (ex: PA_1530)');
        return;
    }
    
    const status=document.getElementById('newInvaderStatus').value;
    const points=document.getElementById('newInvaderPoints').value;
    const notes=document.getElementById('newInvaderNotes')?.value.trim()||'';
    const geoLoc=window.currentGitHubGeoLoc;
    const imgInvader=document.getElementById('githubImgInvader')?.value.trim()||'';
    const imgLieu=document.getElementById('githubImgLieu')?.value.trim()||'';
    
    // Ville depuis le code
    const cityMatch=invId.match(/^([A-Z]+)_/);
    const city=cityMatch?cityMatch[1]:'?';
    
    let geoSection='';
    let labels='new-invader';
    
    if(geoLoc){
        geoSection=`
### 📍 Location
- **Latitude:** ${geoLoc.lat.toFixed(6)}
- **Longitude:** ${geoLoc.lng.toFixed(6)}
- **GPS Accuracy:** ±${geoLoc.accuracy}m
- **Google Maps link:** [View on map](https://www.google.com/maps?q=${geoLoc.lat},${geoLoc.lng})

> ⚠️ These coordinates were captured on-site by the user.
`;
        labels+=',geolocation';
    }
    
    let imgSection='';
    if(imgInvader||imgLieu){
        imgSection=`
### 📸 Photos
`;
        if(imgInvader) imgSection+=`- **Image invader:** ${imgInvader}
`;
        if(imgLieu) imgSection+=`- **Image location:** ${imgLieu}
`;
        labels+=',photos';
    }
    
    const title=encodeURIComponent(`[New Invader] ${invId} (${city})`);
    const body=encodeURIComponent(`## 🛸 New invader report

**Invader:** \`${invId}\`
**City:** ${city}
**Points:** ${points}
**Status:** ${status}
${geoSection}${imgSection}
### Notes
${notes||'_No additional notes_'}

### Information
- Report date: ${new Date().toISOString().slice(0,16).replace('T',' ')} UTC
- Source: Total Invaders Search App

---
_This report was generated via the Total Invaders Search app._`);
    
    const url=`https://github.com/${GITHUB_REPO}/issues/new?title=${title}&body=${body}&labels=${labels}`;
    
    window.open(url,'_blank');
    closeReportModal();
    window.currentGitHubGeoLoc=null;
    const extras=[geoLoc?'location':'',imgInvader||imgLieu?'photos':''].filter(Boolean).join(' + ');
    showPosAlert('success','➕',extras?`New invader ${invId} reported (with ${extras})`:`New invader ${invId} reported`);
}

function captureGeoLocation(){
    const btn=document.getElementById('geoCapBtn');
    const result=document.getElementById('geoCaptureResult');
    
    btn.disabled=true;
    btn.innerHTML='⏳ Capturing...';
    result.style.display='block';
    result.innerHTML='<span style="color:#666">Searching GPS...</span>';
    
    if(!navigator.geolocation){
        btn.disabled=false;
        btn.innerHTML='📡 Capture my current location';
        result.innerHTML='<span style="color:#c00">❌ Geolocation not supported by your browser</span>';
        return;
    }
    
    navigator.geolocation.getCurrentPosition(
        (pos)=>{
            const lat=pos.coords.latitude;
            const lng=pos.coords.longitude;
            const accuracy=Math.round(pos.coords.accuracy);
            
            window.currentGitHubGeoLoc={lat,lng,accuracy};
            
            btn.innerHTML='✅ Location captured!';
            btn.style.background='#4caf50';
            result.innerHTML=`
                <div style="color:#2e7d32">
                    ✅ <b>Location captured</b><br>
                    📍 ${lat.toFixed(6)}, ${lng.toFixed(6)}<br>
                    🎯 Accuracy: ±${accuracy}m<br>
                    <a href="https://www.google.com/maps?q=${lat},${lng}" target="_blank" style="color:#1976d2">Check on Google Maps</a>
                </div>
            `;
        },
        (err)=>{
            btn.disabled=false;
            btn.innerHTML='📡 Try again';
            let msg='Unknown error';
            if(err.code===1)msg='Permission denied - allow geolocation';
            if(err.code===2)msg='Position unavailable';
            if(err.code===3)msg='Timeout - please retry';
            result.innerHTML=`<span style="color:#c00">❌ ${msg}</span>`;
        },
        {enableHighAccuracy:true,timeout:15000,maximumAge:0}
    );
}

function submitGitHubReport(){
    if(!currentReportInvader||currentReportMode!=='github')return;
    
    const inv=invaders.find(i=>i.name===currentReportInvader);
    const currentStatus=inv?.status||'OK';
    const newStatus=document.getElementById('githubStatus').value;
    const notes=document.getElementById('githubNotes').value.trim();
    const geoLoc=window.currentGitHubGeoLoc;
    const imgInvader=document.getElementById('githubImgInvader')?.value.trim()||'';
    const imgLieu=document.getElementById('githubImgLieu')?.value.trim()||'';
    
    // Prepare geolocation section
    let geoSection='';
    let labels='status-update';
    
    if(geoLoc){
        geoSection=`
### 📍 New location reported
- **Latitude:** ${geoLoc.lat.toFixed(6)}
- **Longitude:** ${geoLoc.lng.toFixed(6)}
- **GPS Accuracy:** ±${geoLoc.accuracy}m
- **Google Maps link:** [View on map](https://www.google.com/maps?q=${geoLoc.lat},${geoLoc.lng})

> ⚠️ These coordinates were captured on-site by the user.
`;
        labels='status-update,geolocation';
    }
    
    // Prepare images section
    let imgSection='';
    if(imgInvader||imgLieu){
        imgSection=`
### 📸 Photos
`;
        if(imgInvader) imgSection+=`- **Image invader:** ${imgInvader}
`;
        if(imgLieu) imgSection+=`- **Image location:** ${imgLieu}
`;
        labels+=',photos';
    }
    
    const currentCoords=inv?`${inv.lat?.toFixed(6)||'?'}, ${inv.lng?.toFixed(6)||'?'}`:'Not available';
    const hasUnknownLocation=inv?.location_unknown===true||(inv?.lat===0&&inv?.lng===0);
    
    // Build issue URL
    const title=encodeURIComponent(`[${geoLoc?'Location+Status':'Status'} Update] ${currentReportInvader}: ${currentStatus} → ${newStatus}`);
    const body=encodeURIComponent(`## ${geoLoc?'Location and status':'Status'} change report

**Invader:** \`${currentReportInvader}\`
**City:** ${cityName}

### Status
| | Value |
|---|---|
| Current status in database | ${currentStatus} |
| New observed status | **${newStatus}** |

### Current location in database
- Coordinates: ${currentCoords}
- Approximate location: ${hasUnknownLocation?'⚠️ Yes':'No'}
${geoSection}${imgSection}
### Notes
${notes||'_No additional notes_'}

### Information
- Report date: ${new Date().toISOString().slice(0,16).replace('T',' ')} UTC
- Source: Total Invaders Search App

---
_This report was generated via the Total Invaders Search app._`);
    
    const url=`https://github.com/${GITHUB_REPO}/issues/new?title=${title}&body=${body}&labels=${labels}`;
    
    window.open(url,'_blank');
    closeReportModal();
    window.currentGitHubGeoLoc=null;
    const extras=[geoLoc?'location':'',imgInvader||imgLieu?'photos':''].filter(Boolean).join(' + ');
    showPosAlert('success','🐙',extras?`GitHub issue opened (with ${extras})`:'GitHub issue opened');
}

// Modifier saveReport pour gérer GitHub et Nouveau
const _origSaveReport=saveReport;
saveReport=function(){
    if(currentReportMode==='github'){
        submitGitHubReport();
        return;
    }
    if(currentReportMode==='new-invader'){
        submitNewInvaderReport();
        return;
    }
    _origSaveReport();
}

// === MODE OFFLINE AVEC INDEXEDDB (PAR VILLE) ===
let cacheDB=null;
const DB_NAME='InvadersOfflineDB';
const DB_VERSION=3; // Version 3 pour support par ville

// Ouvrir/créer la base IndexedDB
function openCacheDB(){
    return new Promise((resolve,reject)=>{
        if(cacheDB&&cacheDB.objectStoreNames&&cacheDB.objectStoreNames.length>0){
            try{
                cacheDB.transaction('images','readonly');
                resolve(cacheDB);
                return;
            }catch(e){
                cacheDB=null;
            }
        }
        const req=indexedDB.open(DB_NAME,DB_VERSION);
        req.onerror=()=>reject(req.error);
        req.onsuccess=()=>{cacheDB=req.result;resolve(cacheDB);};
        req.onupgradeneeded=(e)=>{
            const db=e.target.result;
            // Store pour les images
            if(!db.objectStoreNames.contains('images')){
                db.createObjectStore('images',{keyPath:'url'});
            }
            // Store pour les tuiles
            if(!db.objectStoreNames.contains('tiles')){
                db.createObjectStore('tiles',{keyPath:'url'});
            }
            // Store pour les métadonnées
            if(!db.objectStoreNames.contains('meta')){
                db.createObjectStore('meta',{keyPath:'key'});
            }
        };
    });
}

// Sauvegarder une image en base64 (avec ville)
// Convertir blob en base64
function blobToBase64(blob){
    return new Promise((resolve,reject)=>{
        const reader=new FileReader();
        reader.onload=()=>resolve(reader.result);
        reader.onerror=reject;
        reader.readAsDataURL(blob);
    });
}

async function saveImageToDB(url,blob,city){
    // Lire le blob AVANT d'ouvrir la transaction
    const data=await blobToBase64(blob);
    const db=await openCacheDB();
    return new Promise((resolve,reject)=>{
        const tx=db.transaction('images','readwrite');
        const store=tx.objectStore('images');
        const req=store.put({url,data,date:Date.now(),city:city||cityName});
        req.onsuccess=()=>resolve();
        req.onerror=()=>reject(req.error);
    });
}

// Récupérer une image depuis IndexedDB
async function getImageFromDB(url){
    const db=await openCacheDB();
    return new Promise((resolve)=>{
        const tx=db.transaction('images','readonly');
        const store=tx.objectStore('images');
        const req=store.get(url);
        req.onsuccess=()=>resolve(req.result?.data||null);
        req.onerror=()=>resolve(null);
    });
}

// Sauvegarder une tuile (avec ville)
async function saveTileToDB(url,blob,city){
    // Lire le blob AVANT d'ouvrir la transaction
    const data=await blobToBase64(blob);
    const db=await openCacheDB();
    return new Promise((resolve,reject)=>{
        const tx=db.transaction('tiles','readwrite');
        const store=tx.objectStore('tiles');
        const req=store.put({url,data,date:Date.now(),city:city||cityName});
        req.onsuccess=()=>resolve();
        req.onerror=()=>reject(req.error);
    });
}

// Récupérer une tuile depuis IndexedDB
async function getTileFromDB(url){
    const db=await openCacheDB();
    return new Promise((resolve)=>{
        const tx=db.transaction('tiles','readonly');
        const store=tx.objectStore('tiles');
        const req=store.get(url);
        req.onsuccess=()=>resolve(req.result?.data||null);
        req.onerror=()=>resolve(null);
    });
}

// Mettre à jour la barre de progression
function updateProgress(current,total,text){
    const pct=Math.round(current/total*100);
    document.getElementById('cacheProgress').style.display='block';
    document.getElementById('cacheProgressText').textContent=text;
    document.getElementById('cacheProgressPercent').textContent=pct+'%';
    document.getElementById('cacheProgressBar').style.width=pct+'%';
}
function hideProgress(){
    document.getElementById('cacheProgress').style.display='none';
}

function updateOnlineStatus(){
    const indicator=document.getElementById('offlineIndicator');
    const statusEl=document.getElementById('connectionStatus');
    if(!navigator.onLine){
        indicator?.classList.add('show');
        if(statusEl){
            statusEl.style.background='#ffebee';
            statusEl.style.color='#c62828';
            statusEl.innerHTML='🔴 Hors-ligne - Mode cache activé';
        }
    }else{
        indicator?.classList.remove('show');
        if(statusEl){
            statusEl.style.background='#e8f5e9';
            statusEl.style.color='#2e7d32';
            statusEl.innerHTML='🟢 En ligne';
        }
    }
}

async function updateCacheStatus(){
    const infoEl=document.getElementById('cacheInfo');
    if(!infoEl)return;
    
    try{
        const db=await new Promise((resolve,reject)=>{
            const req=indexedDB.open(DB_NAME,DB_VERSION);
            req.onerror=()=>reject(req.error);
            req.onsuccess=()=>resolve(req.result);
            req.onupgradeneeded=(e)=>{
                // Créer les stores si besoin
                const d=e.target.result;
                if(!d.objectStoreNames.contains('images'))d.createObjectStore('images',{keyPath:'url'});
                if(!d.objectStoreNames.contains('tiles'))d.createObjectStore('tiles',{keyPath:'url'});
                if(!d.objectStoreNames.contains('meta'))d.createObjectStore('meta',{keyPath:'key'});
            };
        });
        
        // Vérifier que les stores existent
        if(!db.objectStoreNames.contains('images')||!db.objectStoreNames.contains('tiles')){
            db.close();
            infoEl.innerHTML='<div style="color:#c62828;padding:10px;background:#ffebee;border-radius:8px">⚠️ Base corrompue<br><button onclick="resetDB()" style="margin-top:8px;padding:8px 16px;background:#ff5722;color:#fff;border:none;border-radius:6px;cursor:pointer">🔄 Reset DB</button></div>';
            return;
        }
        
        // Collecter les villes avec images
        const imgCities=await new Promise(resolve=>{
            const cities=new Set();
            try{
                const tx=db.transaction('images','readonly');
                const store=tx.objectStore('images');
                const cursor=store.openCursor();
                cursor.onsuccess=(e)=>{
                    const c=e.target.result;
                    if(c){
                        if(c.value.city)cities.add(c.value.city);
                        c.continue();
                    }else{
                        resolve(cities);
                    }
                };
                cursor.onerror=()=>resolve(new Set());
            }catch(e){
                resolve(new Set());
            }
        });
        
        // Collecter les villes avec tuiles
        const tileCities=await new Promise(resolve=>{
            const cities=new Set();
            try{
                const tx=db.transaction('tiles','readonly');
                const store=tx.objectStore('tiles');
                const cursor=store.openCursor();
                cursor.onsuccess=(e)=>{
                    const c=e.target.result;
                    if(c){
                        if(c.value.city)cities.add(c.value.city);
                        c.continue();
                    }else{
                        resolve(cities);
                    }
                };
                cursor.onerror=()=>resolve(new Set());
            }catch(e){
                resolve(new Set());
            }
        });
        
        db.close();
        
        // Fusionner toutes les villes
        const allCities=new Set([...imgCities,...tileCities]);
        
        // Ajouter les villes du localStorage
        for(let i=0;i<localStorage.length;i++){
            const key=localStorage.key(i);
            if(key.startsWith('cachedInvaders_')){
                allCities.add(key.replace('cachedInvaders_',''));
            }
        }
        
        // Enlever 'unknown'
        allCities.delete('unknown');
        
        let html='<div style="font-weight:600;margin-bottom:10px">📦 Villes en cache:</div>';
        
        if(allCities.size===0){
            html+='<div style="color:#888;font-size:12px;padding:10px;text-align:center">Aucune ville en cache</div>';
        }else{
            const citiesArray=[...allCities].sort();
            
            citiesArray.forEach(city=>{
                const date=localStorage.getItem('cacheDate_'+city);
                const dateStr=date?new Date(date).toLocaleDateString('fr-FR'):'';
                const isCurrent=city===cityName;
                const hasData=localStorage.getItem('cachedInvaders_'+city);
                const hasImg=imgCities.has(city);
                const hasTile=tileCities.has(city);
                
                // Icônes de ce qui est en cache
                let icons=[];
                if(hasData)icons.push('📋');
                if(hasImg)icons.push('🖼️');
                if(hasTile)icons.push('🗺️');
                
                html+=`<div style="display:flex;justify-content:space-between;align-items:center;padding:8px;margin:4px 0;border-radius:8px;${isCurrent?'background:#e3f2fd;border:1px solid #90caf9':'background:#f5f5f5'}">
                    <div>
                        <div style="font-weight:${isCurrent?'600':'400'};font-size:13px">${city}${isCurrent?' 📍':''}</div>
                        <div style="font-size:10px;color:#888">${icons.join(' ')} ${dateStr?'• '+dateStr:''}</div>
                    </div>
                    <button onclick="deleteCityCache('${city}')" style="background:#ffebee;border:none;border-radius:6px;color:#c62828;padding:6px 10px;font-size:12px;cursor:pointer">🗑️</button>
                </div>`;
            });
        }
        
        // Avertissement si ville actuelle pas en cache
        if(cityName&&!allCities.has(cityName)){
            html+=`<div style="margin-top:10px;padding:10px;background:#fff3e0;border-radius:8px;font-size:12px;color:#e65100">
                ⚠️ <strong>${cityName}</strong> n'est pas en cache
            </div>`;
        }
        
        infoEl.innerHTML=html;
    }catch(e){
        console.error('updateCacheStatus error:',e);
        infoEl.innerHTML='<div style="color:#c62828;padding:10px;background:#ffebee;border-radius:8px">⚠️ Erreur base de données<br><small>'+e.message+'</small><br><button onclick="resetDB()" style="margin-top:8px;padding:8px 16px;background:#ff5722;color:#fff;border:none;border-radius:6px;cursor:pointer">🔄 Reset DB</button></div>';
    }
}

// Supprimer le cache d'une ville spécifique
async function deleteCityCache(city){
    if(!confirm(`Supprimer le cache de ${city}?`))return;
    
    try{
        const db=await openCacheDB();
        
        // Supprimer les images de cette ville (sans utiliser l'index)
        await new Promise((resolve,reject)=>{
            const tx=db.transaction('images','readwrite');
            const store=tx.objectStore('images');
            const req=store.openCursor();
            req.onsuccess=(e)=>{
                const cursor=e.target.result;
                if(cursor){
                    if(cursor.value.city===city){
                        cursor.delete();
                    }
                    cursor.continue();
                }else{
                    resolve();
                }
            };
            req.onerror=()=>resolve(); // Ignorer les erreurs
        });
        
        // Supprimer les tuiles de cette ville
        await new Promise((resolve,reject)=>{
            const tx=db.transaction('tiles','readwrite');
            const store=tx.objectStore('tiles');
            const req=store.openCursor();
            req.onsuccess=(e)=>{
                const cursor=e.target.result;
                if(cursor){
                    if(cursor.value.city===city){
                        cursor.delete();
                    }
                    cursor.continue();
                }else{
                    resolve();
                }
            };
            req.onerror=()=>resolve();
        });
        
        // Supprimer du localStorage
        localStorage.removeItem('cachedInvaders_'+city);
        localStorage.removeItem('cacheDate_'+city);
        
        showPosAlert('success','🗑️',`Cache de ${city} supprimé`);
        await new Promise(r=>setTimeout(r,200));
        await updateCacheStatus();
    }catch(e){
        console.error('deleteCityCache error:',e);
        showPosAlert('error','❌','Erreur suppression');
    }
}

// Cache des données JSON
async function cacheForOffline(){
    try{
        const dataStr=JSON.stringify(invaders);
        localStorage.setItem('cachedInvaders_'+cityName,dataStr);
        localStorage.setItem('cachedCities',JSON.stringify(window.citiesData));
        localStorage.setItem('cacheDate_'+cityName,new Date().toISOString());
        showPosAlert('success','💾',`Données ${cityName}: ${invaders.length} invaders`);
        await updateCacheStatus();
    }catch(e){
        showPosAlert('error','❌','Erreur: '+e.message);
    }
}

// Cache des images d'invaders ET des lieux
async function cacheImages(){
    // Collecter toutes les images (invader + lieu)
    const images=[];
    let countInvader=0,countLieu=0;
    invaders.forEach(i=>{
        if(i.image_invader){images.push({url:i.image_invader,type:'invader'});countInvader++;}
        if(i.image_lieu){images.push({url:i.image_lieu,type:'lieu'});countLieu++;}
    });
    
    if(!images.length){showPosAlert('error','❌','Aucune image à cacher');return;}
    
    showPosAlert('info','🖼️',`${countInvader} invaders + ${countLieu} lieux à télécharger`);
    
    // Liste de proxies CORS à essayer
    const proxies=[
        url=>'https://corsproxy.io/?'+encodeURIComponent(url),
        url=>'https://api.allorigins.win/raw?url='+encodeURIComponent(url),
        url=>'https://api.codetabs.com/v1/proxy?quest='+encodeURIComponent(url),
    ];
    
    let success=0,errors=0,skipped=0;
    const total=images.length;
    let currentProxyIndex=0;
    let consecutiveErrors=0;
    
    for(let i=0;i<images.length;i++){
        updateProgress(i+1,total,`Images: ${i+1}/${total} (${success} ✓ ${errors} ✗)`);
        
        try{
            // Vérifier si déjà en cache
            const cached=await getImageFromDB(images[i].url);
            if(cached){skipped++;success++;continue;}
            
            // Essayer avec le proxy actuel, puis les autres en cas d'échec
            let blob=null;
            for(let p=0;p<proxies.length;p++){
                const proxyIndex=(currentProxyIndex+p)%proxies.length;
                const proxyUrl=proxies[proxyIndex](images[i].url);
                
                try{
                    const resp=await fetch(proxyUrl);
                    if(resp.ok){
                        blob=await resp.blob();
                        // Si on a dû changer de proxy, le garder pour les prochaines
                        if(p>0){
                            currentProxyIndex=proxyIndex;
                            console.log('Switched to proxy',proxyIndex);
                        }
                        consecutiveErrors=0;
                        break;
                    }
                }catch(e){
                    console.log('Proxy',proxyIndex,'failed:',e.message);
                }
            }
            
            if(blob){
                await saveImageToDB(images[i].url,blob,cityName);
                success++;
            }else{
                errors++;
                consecutiveErrors++;
            }
        }catch(e){
            console.log('Image error:',images[i].url,e.message);
            errors++;
            consecutiveErrors++;
        }
        
        // Pause adaptative: plus longue si beaucoup d'erreurs
        let delay=100;
        if(consecutiveErrors>5)delay=2000;
        else if(consecutiveErrors>2)delay=500;
        else if(i%5===0)delay=200;
        
        await new Promise(r=>setTimeout(r,delay));
        
        // Si trop d'erreurs consécutives, arrêter
        if(consecutiveErrors>20){
            showPosAlert('error','❌','Erreurs multiples, arrêt du téléchargement');
            break;
        }
    }
    
    hideProgress();
    const newDownloaded=success-skipped;
    showPosAlert('success','🖼️',`${success} images (${newDownloaded} nouvelles)${errors?' • '+errors+' erreurs':''}`);
    // Attendre que IndexedDB finalise les écritures
    await new Promise(r=>setTimeout(r,300));
    await updateCacheStatus();
}

// Cache des tuiles de carte pour la zone actuelle
async function cacheTiles(){
    if(!cityCenter){showPosAlert('error','❌','Charge une ville avant');return;}
    
    const bounds=map.getBounds();
    const zoomLevels=[14,15,16,17,18]; // Niveaux de zoom à cacher
    let tiles=[];
    
    // Calculer les tuiles nécessaires pour chaque niveau de zoom
    zoomLevels.forEach(z=>{
        const nw=bounds.getNorthWest();
        const se=bounds.getSouthEast();
        const minX=Math.floor((nw.lng+180)/360*Math.pow(2,z));
        const maxX=Math.floor((se.lng+180)/360*Math.pow(2,z));
        const minY=Math.floor((1-Math.log(Math.tan(nw.lat*Math.PI/180)+1/Math.cos(nw.lat*Math.PI/180))/Math.PI)/2*Math.pow(2,z));
        const maxY=Math.floor((1-Math.log(Math.tan(se.lat*Math.PI/180)+1/Math.cos(se.lat*Math.PI/180))/Math.PI)/2*Math.pow(2,z));
        
        for(let x=minX;x<=maxX;x++){
            for(let y=minY;y<=maxY;y++){
                tiles.push({z,x,y});
            }
        }
    });
    
    // Limiter à 5500 tuiles max
    if(tiles.length>5500){
        showPosAlert('error','⚠️',`Trop de tuiles (${tiles.length}). Zoome sur une zone plus petite.`);
        return;
    }
    
    let success=0,errors=0,skipped=0;
    const total=tiles.length;
    const subdomains=['a','b','c'];
    
    for(let i=0;i<tiles.length;i++){
        const t=tiles[i];
        const s=subdomains[i%3];
        const url=`https://${s}.basemaps.cartocdn.com/light_all/${t.z}/${t.x}/${t.y}.png`;
        
        updateProgress(i+1,total,`Tuiles: ${i+1}/${total} (${success} ✓)`);
        
        try{
            // Vérifier si déjà en cache
            const cached=await getTileFromDB(url);
            if(cached){skipped++;success++;continue;}
            
            const resp=await fetch(url);
            if(resp.ok){
                const blob=await resp.blob();
                await saveTileToDB(url,blob,cityName);
                success++;
            }else{errors++;}
        }catch(e){errors++;}
        
        // Mise à jour du compteur toutes les 20 tuiles
        if(i%20===0){
            await new Promise(r=>setTimeout(r,30));
        }
    }
    
    hideProgress();
    const newDownloaded=success-skipped;
    showPosAlert('success','🗺️',`${success} tuiles (${newDownloaded} nouvelles, zoom 14-18)`);
    // Attendre que IndexedDB finalise les écritures
    await new Promise(r=>setTimeout(r,300));
    await updateCacheStatus();
}

// Cache tout (données + images + tuiles)
async function cacheAll(){
    showPosAlert('info','⬇️','Téléchargement complet en cours...');
    await cacheForOffline();
    await cacheImages();
    await cacheTiles();
    // Mise à jour finale
    await new Promise(r=>setTimeout(r,300));
    await updateCacheStatus();
    showPosAlert('success','✅',`${cityName} entièrement en cache!`);
}

// Vider le cache
async function clearCache(){
    if(!confirm('Supprimer tout le cache offline (données, images, tuiles)?'))return;
    
    // Vider localStorage
    const toRemove=[];
    for(let i=0;i<localStorage.length;i++){
        const key=localStorage.key(i);
        if(key.startsWith('cachedInvaders_')||key.startsWith('cacheDate_')){
            toRemove.push(key);
        }
    }
    toRemove.forEach(k=>localStorage.removeItem(k));
    localStorage.removeItem('cachedCities');
    
    // Fermer la connexion existante
    if(cacheDB){
        try{cacheDB.close();}catch(e){}
        cacheDB=null;
    }
    
    // Supprimer complètement la base IndexedDB
    try{
        await new Promise((resolve,reject)=>{
            const req=indexedDB.deleteDatabase(DB_NAME);
            req.onsuccess=()=>{console.log('IndexedDB deleted');resolve();};
            req.onerror=()=>reject(req.error);
            req.onblocked=()=>{console.log('IndexedDB delete blocked');resolve();};
        });
    }catch(e){console.error('deleteDatabase error:',e);}
    
    // Attendre puis mettre à jour
    await new Promise(r=>setTimeout(r,300));
    await updateCacheStatus();
    showPosAlert('success','🗑️','Cache entièrement vidé');
}

// Reset complet de la base IndexedDB (force delete + reload)
async function resetDB(){
    if(!confirm('⚠️ Reset complet de IndexedDB?\\nCela va supprimer toutes les données en cache et recharger la page.'))return;
    
    // Fermer toute connexion
    if(cacheDB){
        try{cacheDB.close();}catch(e){}
        cacheDB=null;
    }
    
    // Vider tout le localStorage lié au cache
    const keys=[];
    for(let i=0;i<localStorage.length;i++){
        const k=localStorage.key(i);
        if(k.startsWith('cachedInvaders_')||k.startsWith('cacheDate_'))keys.push(k);
    }
    keys.forEach(k=>localStorage.removeItem(k));
    
    // Supprimer la base IndexedDB
    try{
        const req=indexedDB.deleteDatabase(DB_NAME);
        req.onsuccess=()=>console.log('DB deleted OK');
        req.onerror=(e)=>console.error('DB delete error:',e);
        req.onblocked=()=>console.log('DB delete blocked, reloading anyway');
    }catch(e){
        console.error('deleteDatabase error:',e);
    }
    
    // Recharger la page après un court délai
    setTimeout(()=>{
        window.location.reload();
    },500);
}

function loadFromCache(){
    const cached=localStorage.getItem('cachedInvaders_'+cityName);
    if(cached){
        invaders=JSON.parse(cached);
        render();stats();updateInvaderSelect();
        const date=localStorage.getItem('cacheDate_'+cityName);
        const dateStr=date?new Date(date).toLocaleDateString('fr-FR'):'?';
        showPosAlert('success','📱',`Cache du ${dateStr}`);
        return true;
    }
    return false;
}

// Layer de tuiles avec cache IndexedDB
function createCachedTileLayer(){
    return L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',{
        maxZoom:19,
        subdomains:'abc'
    });
}

// Intercepter le chargement des images pour utiliser le cache
async function loadCachedImage(url,imgElement){
    const cached=await getImageFromDB(url);
    if(cached){
        imgElement.src=cached;
        return true;
    }
    return false;
}

// Modifier loadCity pour utiliser le cache offline
const _origLoadCity=loadCity;
loadCity=async function(code){
    if(!navigator.onLine){
        const c=window.citiesData?.find(x=>x.code===code);
        cityName=c?.name||code;
        if(loadFromCache()){
            route=[];
            loadSavedRoute();
            return;
        }
        alert('Pas de connexion et pas de cache pour cette ville');
        return;
    }
    return _origLoadCity(code);
}
</script>

<!-- Modal Viewer d'image -->
<div id="imgViewer" onclick="if(event.target===this)closeImgViewer()" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.95);z-index:10000;touch-action:manipulation">
    <button onclick="closeImgViewer()" style="position:absolute;top:env(safe-area-inset-top,15px);right:15px;width:60px;height:60px;border-radius:50%;border:none;background:rgba(255,255,255,0.3);color:#fff;font-size:32px;cursor:pointer;z-index:10001;display:flex;align-items:center;justify-content:center;margin-top:15px">×</button>
    <div id="imgViewerTitle" style="position:absolute;top:env(safe-area-inset-top,15px);left:15px;right:80px;color:#fff;font-size:16px;font-weight:600;z-index:10001;text-shadow:0 1px 3px rgba(0,0,0,0.5);margin-top:20px"></div>
    <div id="imgViewerLoading" style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#fff;font-size:16px">Chargement...</div>
    <img id="imgViewerImg" style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);max-width:95%;max-height:85%;object-fit:contain;display:none">
    <div onclick="closeImgViewer()" style="position:absolute;bottom:env(safe-area-inset-bottom,20px);left:50%;transform:translateX(-50%);padding:12px 30px;background:rgba(255,255,255,0.2);color:#fff;border-radius:25px;font-size:14px;cursor:pointer;margin-bottom:15px">Fermer</div>
</div>

<script>
function openImgViewer(src,title){
    document.getElementById('imgViewerTitle').textContent=title||'';
    document.getElementById('imgViewerLoading').style.display='block';
    document.getElementById('imgViewerImg').style.display='none';
    document.getElementById('imgViewer').style.display='block';
    document.body.style.overflow='hidden';
    
    const img=document.getElementById('imgViewerImg');
    img.onload=function(){
        document.getElementById('imgViewerLoading').style.display='none';
        img.style.display='block';
    };
    img.onerror=function(){
        document.getElementById('imgViewerLoading').textContent='Erreur de chargement';
    };
    img.src=src;
}

function closeImgViewer(){
    document.getElementById('imgViewer').style.display='none';
    document.getElementById('imgViewerImg').src='';
    document.body.style.overflow='';
}

// Fermer avec Escape
document.addEventListener('keydown',function(e){
    if(e.key==='Escape')closeImgViewer();
});
</script>
</body>
</html>'''

if __name__ == '__main__':
    app.run(debug=True, port=5000)
