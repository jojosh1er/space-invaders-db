#!/usr/bin/env python3
"""
send_notifications.py — Envoi d'emails personnalisés post-workflow

Lit la config depuis la variable d'environnement EMAIL_CONFIG (secret GitHub)
et envoie un email personnalisé à chaque destinataire.

Format du secret EMAIL_CONFIG (JSON) :
[
    {
        "email": "jocelyn@mail.com",
        "name": "Jocelyn",
        "greeting": "Salut chef !",
        "detail_level": "full"
    },
    {
        "email": "ami@mail.com",
        "name": "Pierre",
        "greeting": "Hey Pierre, voici les news de la chasse !",
        "detail_level": "summary"
    },
    {
        "email": "curieux@mail.com",
        "name": "Marie",
        "greeting": "Coucou Marie !",
        "detail_level": "minimal"
    }
]

detail_level :
  - "full"    : rapport complet avec tableau des changements + stats géoloc
  - "summary" : stats globales + nombre de changements (pas le détail ligne par ligne)
  - "minimal" : juste le statut (succès/échec) et le lien vers GitHub
"""

import json
import os
import smtplib
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime


def load_config():
    """Charge la config depuis EMAIL_CONFIG (env var / secret GitHub)."""
    raw = os.environ.get('EMAIL_CONFIG', '').strip()
    if not raw:
        print("⚠️  EMAIL_CONFIG non défini, aucun email envoyé")
        return []
    try:
        config = json.loads(raw)
        if not isinstance(config, list):
            print("❌ EMAIL_CONFIG doit être un tableau JSON")
            return []
        return config
    except json.JSONDecodeError as e:
        print(f"❌ EMAIL_CONFIG JSON invalide: {e}")
        return []


def load_report_data():
    """Charge les données du rapport depuis les fichiers générés par le workflow."""
    data = {
        'has_changes': os.environ.get('HAS_CHANGES', 'false') == 'true',
        'change_count': int(os.environ.get('CHANGE_COUNT', '0')),
        'total_invaders': os.environ.get('TOTAL_INVADERS', '?'),
        'total_cities': os.environ.get('TOTAL_CITIES', '?'),
        'job_status': os.environ.get('JOB_STATUS', 'unknown'),
        'run_url': os.environ.get('RUN_URL', ''),
        'repo_name': os.environ.get('REPO_NAME', 'space-invaders-db'),
    }

    # Lire le rapport détaillé (texte)
    detail_file = '/tmp/email_body.txt'
    if os.path.exists(detail_file):
        with open(detail_file, 'r') as f:
            data['detail_text'] = f.read()
    else:
        data['detail_text'] = ''

    # Lire les stats géoloc depuis metadata si disponible
    try:
        with open('data/metadata.json') as f:
            m = json.load(f)
        data['total_invaders'] = m.get('total_invaders', data['total_invaders'])
        data['total_cities'] = m.get('total_cities', data['total_cities'])
        data['with_coordinates'] = m.get('with_coordinates', '?')
        data['status_counts'] = m.get('status_counts', {})
    except:
        data['with_coordinates'] = '?'
        data['status_counts'] = {}

    # Stats géoloc détaillées
    try:
        with open('data/invaders_master.json') as f:
            db = json.load(f)
        data['geolocated'] = sum(1 for inv in db if inv.get('geo_source') not in (None, 'city_center', 'unknown'))
        data['exhausted'] = sum(1 for inv in db if inv.get('geo_search_exhausted'))
        data['city_center'] = sum(1 for inv in db if inv.get('geo_source') == 'city_center')
    except:
        data['geolocated'] = '?'
        data['exhausted'] = '?'
        data['city_center'] = '?'

    # Rapport de géolocalisation des nouveaux invaders
    data['geoloc_results'] = []
    for geoloc_file in ['data/invaders_relocalized.json', 'data/invaders_geolocated.json']:
        if os.path.exists(geoloc_file):
            try:
                with open(geoloc_file) as f:
                    geoloc_data = json.load(f)
                for inv in geoloc_data:
                    inv_id = inv.get('id', '?')
                    lat = inv.get('lat')
                    lng = inv.get('lng')
                    source = inv.get('geo_source', '?')
                    confidence = inv.get('geo_confidence', '?')
                    address = inv.get('address', '')
                    hint = inv.get('geo_hint', '')
                    conf_icon = {'high': '🟢', 'medium': '🟡', 'low': '🔴'}.get(confidence, '❓')

                    entry = {
                        'id': inv_id,
                        'lat': lat,
                        'lng': lng,
                        'source': source,
                        'confidence': confidence,
                        'conf_icon': conf_icon,
                        'address': address,
                        'hint': hint,
                        'location_unknown': inv.get('location_unknown', True),
                    }
                    data['geoloc_results'].append(entry)
                print(f"📍 {len(data['geoloc_results'])} résultats géoloc chargés depuis {geoloc_file}")
                break  # Un seul fichier suffit
            except Exception as e:
                print(f"⚠️ Erreur lecture {geoloc_file}: {e}")

    return data


def build_subject(report, recipient):
    """Construit le sujet du mail."""
    status_icon = '✅' if report['job_status'] == 'success' else '❌'
    if report['has_changes']:
        return f"🛸 Invaders Update [{report['change_count']} changements] {status_icon}"
    else:
        return f"🛸 Invaders Update [Aucun changement] {status_icon}"


def build_body_minimal(report, recipient):
    """Corps minimal : statut + lien."""
    name = recipient.get('name', '')
    greeting = recipient.get('greeting', f'Bonjour{" " + name if name else ""} !')

    status_label = {
        'success': '✅ Succès',
        'failure': '❌ Échec',
        'cancelled': '⚠️ Annulé'
    }.get(report['job_status'], report['job_status'])

    lines = [
        greeting,
        '',
        f"Statut du workflow : {status_label}",
        '',
    ]

    if report['has_changes']:
        lines.append(f"📊 {report['change_count']} changements détectés")
    else:
        lines.append("Aucun changement cette semaine.")

    lines.extend([
        '',
        f"→ Voir le rapport : {report['run_url']}",
        '',
        '---',
        'Space Invaders Bot 🛸',
    ])

    return '\n'.join(lines)


def build_body_summary(report, recipient):
    """Corps résumé : stats globales sans le détail des changements."""
    name = recipient.get('name', '')
    greeting = recipient.get('greeting', f'Bonjour{" " + name if name else ""} !')

    status_label = {
        'success': '✅ Succès',
        'failure': '❌ Échec',
        'cancelled': '⚠️ Annulé'
    }.get(report['job_status'], report['job_status'])

    lines = [
        greeting,
        '',
        f"Rapport hebdomadaire — {report['repo_name']}",
        f"Date : {datetime.now().strftime('%d/%m/%Y %H:%M UTC')}",
        f"Statut : {status_label}",
        '',
        '📊 Statistiques :',
        f"  • Total invaders : {report['total_invaders']}",
        f"  • Villes : {report['total_cities']}",
        f"  • Avec coordonnées : {report.get('with_coordinates', '?')}",
        f"  • Géolocalisés (précis) : {report.get('geolocated', '?')}",
        '',
    ]

    if report['has_changes']:
        lines.append(f"🔄 {report['change_count']} changements cette semaine")
    else:
        lines.append("✅ Aucun changement cette semaine")

    # Section géolocalisation des nouveaux invaders
    geoloc = report.get('geoloc_results', [])
    if geoloc:
        lines.append('')
        found = [g for g in geoloc if g['source'] not in ('city_center', None, 'unknown')]
        not_found = [g for g in geoloc if g['source'] in ('city_center', None, 'unknown')]

        lines.append(f"📍 Géolocalisation : {len(found)} localisés / {len(geoloc)} nouveaux")
        lines.append('')

        if found:
            lines.append("  Localisés :")
            for g in found:
                addr = f" — {g['address'][:50]}" if g['address'] else ''
                lines.append(f"    {g['conf_icon']} {g['id']} ({g['source']}, {g['confidence'].upper()}){addr}")

        if not_found:
            lines.append("  Non localisés :")
            for g in not_found:
                hint = f" — 💡 {g['hint'][:60]}" if g['hint'] else ''
                lines.append(f"    🔴 {g['id']}{hint}")

    lines.extend([
        '',
        f"→ Rapport détaillé : {report['run_url']}",
        '',
        '---',
        'Space Invaders Bot 🛸',
    ])

    return '\n'.join(lines)


def build_body_full(report, recipient):
    """Corps complet : stats + détail de tous les changements + géoloc avec liens Maps."""
    # Commence par le résumé
    body = build_body_summary(report, recipient)

    # Ajoute le détail des changements
    if report['detail_text']:
        body = body.replace(
            '---\nSpace Invaders Bot 🛸',
            '\n📋 DÉTAIL DES CHANGEMENTS :\n'
            + '-' * 40 + '\n'
            + report['detail_text']
            + '\n\n---\nSpace Invaders Bot 🛸'
        )

    # Ajoute les liens Maps pour les invaders géolocalisés
    geoloc = report.get('geoloc_results', [])
    found_with_coords = [g for g in geoloc if g['lat'] and g['lng']
                         and g['source'] not in ('city_center', None, 'unknown')]
    if found_with_coords:
        maps_section = '\n🗺️  LIENS GOOGLE MAPS :\n' + '-' * 40 + '\n'
        for g in found_with_coords:
            addr = f"  {g['address'][:60]}" if g['address'] else ''
            maps_section += f"\n{g['conf_icon']} {g['id']} ({g['source']}, {g['confidence'].upper()})\n"
            if addr:
                maps_section += f"  {addr}\n"
            maps_section += f"  → https://www.google.com/maps?q={g['lat']},{g['lng']}\n"
        maps_section += '\n'

        body = body.replace(
            '---\nSpace Invaders Bot 🛸',
            maps_section + '---\nSpace Invaders Bot 🛸'
        )

    return body


def send_email(smtp, sender, recipient_email, subject, body, attach_file=None):
    """Envoie un email via une connexion SMTP existante."""
    msg = MIMEMultipart()
    msg['From'] = f'Space Invaders Bot <{sender}>'
    msg['To'] = recipient_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    # Pièce jointe si demandée
    if attach_file and os.path.exists(attach_file):
        with open(attach_file, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="rapport_invaders.txt"')
        msg.attach(part)

    smtp.sendmail(sender, [recipient_email], msg.as_string())


def main():
    recipients = load_config()
    if not recipients:
        sys.exit(0)

    smtp_user = os.environ.get('SMTP_USERNAME', '')
    smtp_pass = os.environ.get('SMTP_PASSWORD', '')
    if not smtp_user or not smtp_pass:
        print("❌ SMTP_USERNAME ou SMTP_PASSWORD manquant")
        sys.exit(1)

    report = load_report_data()
    print(f"📊 Rapport : {report['change_count']} changements, statut={report['job_status']}")

    # Connexion SMTP unique pour tous les envois
    try:
        smtp = smtplib.SMTP('smtp.gmail.com', 587)
        smtp.starttls()
        smtp.login(smtp_user, smtp_pass)
    except Exception as e:
        print(f"❌ Connexion SMTP échouée : {e}")
        sys.exit(1)

    sent = 0
    errors = 0

    for r in recipients:
        email = r.get('email', '').strip()
        if not email:
            continue

        name = r.get('name', email.split('@')[0])
        level = r.get('detail_level', 'summary')

        # Construire le body selon le niveau
        if level == 'full':
            body = build_body_full(report, r)
            attach = '/tmp/email_body.txt' if report['has_changes'] else None
        elif level == 'minimal':
            body = build_body_minimal(report, r)
            attach = None
        else:  # summary (défaut)
            body = build_body_summary(report, r)
            attach = None

        subject = build_subject(report, r)

        try:
            send_email(smtp, smtp_user, email, subject, body, attach)
            print(f"  ✅ {name} <{email}> ({level})")
            sent += 1
        except Exception as e:
            print(f"  ❌ {name} <{email}> : {e}")
            errors += 1

    smtp.quit()

    print(f"\n📧 {sent} email(s) envoyé(s), {errors} erreur(s)")
    if errors > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
