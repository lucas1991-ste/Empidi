#!/usr/bin/env python3
"""
IPTV Playlist Generator - Canali Sky e DAZN italiani
Genera playlist M3U con flussi MPD + clearkey per canali Sky e DAZN italiani.
I link sono dinamici e vengono aggiornati ad ogni esecuzione.

Fonti stream:
  - Sky: API esterna con decrittazione XOR (resolve server-side)
  - DAZN/Sport: API esterna con payload pre-risolto (base64 amstaff/daznToken)
Fonte EPG: iptv-epg.org (11 giorni, canali Sky, aggiornato quotidianamente)

CREDENZIALI: Tutte le credenziali sensibili vengono lette da variabili d'ambiente.
             Non hardcodare nulla in questo file.

Formati di output:
  - playlist_kodi.m3u:     M3U per Sparkle TV / Kodi / UHF (KODIPROP)
  - playlist_tivimate.m3u: M3U per Tivimate/iMPlayer (formato pipe key)
  - epg.xml:               Guida programmi XMLTV (filtrata per i nostri canali)
  - epg.xml.gz:            Guida programmi compressa (per app che lo supportano)
"""

import json
import base64
import re
import sys
import os
import gzip
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote

# ============================================================
# CONFIGURAZIONE - TUTTO DA ENV VARS
# ============================================================

STREAM_LIST_URL = os.environ.get("STREAM_LIST_URL", "")
STREAM_LIST_URL_DAZN = os.environ.get("STREAM_LIST_URL_DAZN", "")
STREAM_RESOLVE_URL = os.environ.get("STREAM_RESOLVE_URL", "")
STREAM_USER_AGENT = os.environ.get("STREAM_USER_AGENT", "")
XOR_SECRET = os.environ.get("XOR_SECRET", "")

# Se True, include nel M3U anche i canali sportivi non-DAZN dal listing A1A103
# (IzziESPN, BeIN, Eleven, Ziggo, Setanta, NBA TV, LBATV, etc.)
INCLUDE_SPORT_EXTRA = os.environ.get("INCLUDE_SPORT_EXTRA", "true").lower() == "true"

def check_env():
    """Verifica che tutte le env vars obbligatorie siano impostate."""
    missing = []
    if not STREAM_LIST_URL:
        missing.append("STREAM_LIST_URL")
    if not STREAM_RESOLVE_URL:
        missing.append("STREAM_RESOLVE_URL")
    if not STREAM_USER_AGENT:
        missing.append("STREAM_USER_AGENT")
    if not XOR_SECRET:
        missing.append("XOR_SECRET")
    if missing:
        print(f"[ERRORE] Variabili d'ambiente mancanti: {', '.join(missing)}")
        print("Impostale nel tuo .env file o nelle GitHub Secrets.")
        sys.exit(1)


def get_dazn_list_url():
    """Ricava l'URL del listing DAZN. Se STREAM_LIST_URL_DAZN non e' impostato,
    prova a derivarlo dal listing Sky sostituendo il codice API A1A260 -> A1A103."""
    if STREAM_LIST_URL_DAZN:
        return STREAM_LIST_URL_DAZN
    if STREAM_LIST_URL and "A1A260" in STREAM_LIST_URL:
        derived = STREAM_LIST_URL.replace("A1A260", "A1A103")
        print(f"  [INFO] DAZN listing URL derivato: {derived}")
        return derived
    return None


# ============================================================
# DEFINIZIONE CANALI SKY
# ============================================================

CHANNEL_NAMES = {
    "tg24": "Sky TG24",
    "skyuno": "Sky Uno",
    "skyatlantic": "Sky Atlantic",
    "skyserie": "Sky Serie",
    "skycollection": "Sky Collection",
    "skyinvestigation": "Sky Investigation",
    "skyadventure": "Sky Adventure",
    "skycrime": "Sky Crime",
    "comedycentral": "Comedy Central",
    "skydocumentaries": "Sky Documentaries",
    "skynature": "Sky Nature",
    "historychannel": "History Channel",
    "skyarte": "Sky Arte",
    "mtv": "MTV",
    "skysport24": "Sky Sport 24",
    "skysportuno": "Sky Sport Uno",
    "skysportarena": "Sky Sport Arena",
    "skysportf1": "Sky Sport F1",
    "skysportmotogp": "Sky Sport MotoGP",
    "skysportgolf": "Sky Sport Golf",
    "skysporttennis": "Sky Sport Tennis",
    "skysportmix": "Sky Sport Mix",
    "skysportbasket": "Sky Sport Basket",
    "skysportlegend": "Sky Sport Legend",
    "skysportmax": "Sky Sport Max",
    "skysportcalcio": "Sky Sport Calcio",
    "skysport251": "Sky Sport 251",
    "skysport252": "Sky Sport 252",
    "skysport253": "Sky Sport 253",
    "skysport254": "Sky Sport 254",
    "skysport255": "Sky Sport 255",
    "skysport256": "Sky Sport 256",
    "skysport257": "Sky Sport 257",
    "skysport258": "Sky Sport 258",
    "skysport259": "Sky Sport 259",
    "skycinemauno": "Sky Cinema Uno",
    "skycinemaaction": "Sky Cinema Action",
    "skycinemacomedy": "Sky Cinema Comedy",
    "skycinemadrama": "Sky Cinema Drama",
    "skycinemafamily": "Sky Cinema Family",
    "skycinemaromance": "Sky Cinema Romance",
    "skycinemasuspense": "Sky Cinema Suspense",
    "skycinemastories": "Sky Cinema Stories",
    "nickelodeon": "Nickelodeon",
    "deakids": "DeAKids",
    "boomerang": "Boomerang",
    "cartoonnetwork": "Cartoon Network",
}

LOGO_CDN = "https://cdn.jsdelivr.net/gh/tv-logo/tv-logos@main/countries/italy"
LOGO_CDN_UK = "https://cdn.jsdelivr.net/gh/tv-logo/tv-logos@main/countries/united-kingdom"

LOGO_MAP = {
    "tg24": f"{LOGO_CDN}/sky-tg24-it.png",
    "skyuno": f"{LOGO_CDN}/sky-uno-it.png",
    "skyatlantic": f"{LOGO_CDN}/sky-atlantic-it.png",
    "skyserie": f"{LOGO_CDN}/sky-serie-it.png",
    "skycollection": f"{LOGO_CDN}/sky-collection-it.png",
    "skyinvestigation": f"{LOGO_CDN}/sky-investigation-it.png",
    "skyadventure": f"{LOGO_CDN}/sky-adventure-it.png",
    "skycrime": f"{LOGO_CDN}/sky-crime-it.png",
    "comedycentral": f"{LOGO_CDN_UK}/comedy-central-uk.png",
    "skydocumentaries": f"{LOGO_CDN}/sky-documentaries-it.png",
    "skynature": f"{LOGO_CDN}/sky-nature-it.png",
    "historychannel": f"{LOGO_CDN}/history-channel-it.png",
    "skyarte": f"{LOGO_CDN}/sky-arte-it.png",
    "mtv": f"{LOGO_CDN}/mtv-it.png",
    "skysport24": f"{LOGO_CDN}/sky-sport-24-it.png",
    "skysportuno": f"{LOGO_CDN}/sky-sport-uno-it.png",
    "skysportarena": f"{LOGO_CDN}/sky-sport-arena-it.png",
    "skysportf1": f"{LOGO_CDN}/sky-sport-f1-it.png",
    "skysportmotogp": f"{LOGO_CDN}/sky-sport-motogp-it.png",
    "skysportgolf": f"{LOGO_CDN}/sky-sport-golf-it.png",
    "skysporttennis": f"{LOGO_CDN}/sky-sport-tennis-it.png",
    "skysportmix": f"{LOGO_CDN}/sky-sport-mix-it.png",
    "skysportbasket": f"{LOGO_CDN}/sky-sport-nba-it.png",
    "skysportlegend": f"{LOGO_CDN}/sky-sport-legend-it.png",
    "skysportmax": f"{LOGO_CDN}/sky-sport-max-it.png",
    "skysportcalcio": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport251": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport252": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport253": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport254": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport255": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport256": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport257": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport258": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport259": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skycinemauno": f"{LOGO_CDN}/sky-cinema-uno-it.png",
    "skycinemaaction": f"{LOGO_CDN}/sky-cinema-action-it.png",
    "skycinemacomedy": f"{LOGO_CDN}/sky-cinema-comedy-it.png",
    "skycinemadrama": f"{LOGO_CDN}/sky-cinema-drama-it.png",
    "skycinemafamily": f"{LOGO_CDN}/sky-cinema-family-it.png",
    "skycinemaromance": f"{LOGO_CDN}/sky-cinema-romance-it.png",
    "skycinemasuspense": f"{LOGO_CDN}/sky-cinema-suspense-it.png",
    "skycinemastories": f"{LOGO_CDN}/sky-cinema-due-it.png",
    "nickelodeon": f"{LOGO_CDN}/nickelodeon-it.png",
    "deakids": f"{LOGO_CDN}/dea-kids-it.png",
    "boomerang": f"{LOGO_CDN}/boomerang-it.png",
    "cartoonnetwork": f"{LOGO_CDN}/cartoon-network-it.png",
}

GROUP_MAP = {
    "tg24": "Sky Informazione",
    "skyuno": "Sky Intrattenimento",
    "skyatlantic": "Sky Intrattenimento",
    "skyserie": "Sky Intrattenimento",
    "skycollection": "Sky Intrattenimento",
    "skyinvestigation": "Sky Intrattenimento",
    "skyadventure": "Sky Intrattenimento",
    "skycrime": "Sky Intrattenimento",
    "comedycentral": "Sky Intrattenimento",
    "skydocumentaries": "Sky Documentari",
    "skynature": "Sky Documentari",
    "skyarte": "Sky Cultura",
    "mtv": "Sky Musica",
    "historychannel": "Sky Documentari",
    "nickelodeon": "Sky Kids",
    "deakids": "Sky Kids",
    "boomerang": "Sky Kids",
    "cartoonnetwork": "Sky Kids",
    "skysportcalcio": "Sky Sport Calcio",
    "skysportmax": "Sky Sport",
}

def get_group(ch_id):
    """Determina il gruppo di un canale Sky."""
    if ch_id.startswith("skysport2") and ch_id not in ("skysport24",):
        return "Sky Sport Calcio"
    if ch_id.startswith("skysport"):
        return "Sky Sport"
    if ch_id.startswith("skycinema"):
        return "Sky Cinema"
    return GROUP_MAP.get(ch_id, "Sky")


# ============================================================
# DEFINIZIONE CANALI DAZN / SPORT EXTRA
# ============================================================

# I canali dall'API A1A103 hanno nomi DINAMICI basati sull'evento.
# Non esistono nomi fissi come "DAZN 1" nel listing MandraKodi.
# Usiamo il titolo del listing direttamente.

# Logo DAZN: usiamo il logo DAZN generico per tutti i canali DAZN
DAZN_LOGO = f"{LOGO_CDN}/dazn-it.png"

# CDN domains che identificano i flussi DAZN
DAZN_CDN_DOMAINS = [
    "dazn.ticdn.it",
    "daznedge.net",
    "dai.google.com",
    "mocdn.tv",          # DAZN Serie B
]

# CDN domains per altri provider sportivi (non DAZN)
SPORT_CDN_DOMAINS = {
    "izzigo.tv": "Izzi TV",
    "otte.live": "BeIN/OTT",
    "t-mobile.pl": "Eleven",
    "pv-cdn.net": "CBS Golazo",
    "tv.odido.nl": "Ziggo",
    "cgates.lt": "Setanta",
    "aiv-cdn.net": "Prime/NBA",
    "c4assets.com": "Seven TV",
    "akamaized.net": "LBA TV",
    "msvdn.net": "SuperTennis",
}

# Loghi per canali Sport Extra (per provider che hanno logo nel CDN)
SPORT_LOGO_MAP = {
    "supertennis": f"{LOGO_CDN}/super-tennis-it.png",
    "eurosport": f"{LOGO_CDN}/eurosport-1-it.png",
    "eurosport2": f"{LOGO_CDN}/eurosport-2-it.png",
    "sportitalia": f"{LOGO_CDN}/sportitalia-it.png",
    "nbatv": "",
    "milantv": f"{LOGO_CDN}/milan-tv-it.png",
    "intertv": f"{LOGO_CDN}/inter-tv-it.png",
    "romatv": f"{LOGO_CDN}/roma-tv-it.png",
    "laziostylech": f"{LOGO_CDN}/lazio-style-channel-it.png",
}


def classify_manifest(manifest_url):
    """Classifica un manifest URL per tipo di provider.
    Ritorna (stream_type, group, logo):
      - stream_type: 'dazn', 'sport', o 'other'
      - group: nome del gruppo per l'M3U
      - logo: URL del logo
    """
    lower = manifest_url.lower()

    # Check DAZN CDN
    for domain in DAZN_CDN_DOMAINS:
        if domain in lower:
            group = "DAZN Serie B" if "mocdn" in lower else "DAZN Sport"
            return "dazn", group, DAZN_LOGO

    # Check SuperTennis (ha logo e EPG dedicati)
    if "msvdn.net" in lower:
        return "sport", "Sport Extra (SuperTennis)", SPORT_LOGO_MAP.get("supertennis", "")

    # Check altri provider sportivi
    for domain, provider_name in SPORT_CDN_DOMAINS.items():
        if domain in lower:
            return "sport", f"Sport Extra ({provider_name})", ""

    # Sconosciuto
    return "other", "Sport Extra", ""


def clean_channel_title(title):
    """Pulisce il titolo di un canale rimuovendo tag Kodi e suffissi tecnici."""
    clean = re.sub(r"\[COLOR [^\]]+\]", "", title).replace("[/COLOR]", "").strip()
    # Rimuovi suffissi tecnici come (MPD), (ITA - MPD), etc.
    clean = re.sub(r"\s*\((?:MPD|M3U8|ITA\s*[-/]\s*MPD|ENG\s*[-/]\s*MPD|ITA/ESP\s*[-/]\s*MPD|ITA/NED\s*[-/]\s*MPD|POL\s*[-/]\s*MPD|GR\s*[-/]\s*M3U8|ITA\s*[-/]\s*M3U8)\)$", "", clean)
    return clean.strip()


def title_to_ch_id(title):
    """Converte il titolo di un canale in un ID pulito per uso interno."""
    clean = clean_channel_title(title)
    clean = clean.lower().replace(" ", "_").replace("-", "_").replace("'", "")
    clean = re.sub(r"[^a-z0-9_]", "", clean)
    clean = re.sub(r"_+", "_", clean)
    return clean.strip("_")


# ============================================================
# EPG: MAPPING CANALI -> iptv-epg.org
# ============================================================

TVG_ID_MAP = {
    "tg24": "SkyTG24.it",
    "skyuno": "SkyUno.it",
    "skyatlantic": "SkyAtlantic.it",
    "skyserie": "SkySerie.it",
    "skycollection": "SkyCinemaCollection.it",
    "skyinvestigation": "SkyInvestigation.it",
    "skyadventure": "SkyAdventure.it",
    "skycrime": "SkyCrime.it",
    "comedycentral": "ComedyCentral.it",
    "skydocumentaries": "SkyDocumentaries.it",
    "skynature": "SkyNature.it",
    "historychannel": "History.it",
    "skyarte": "SkyArte.it",
    "mtv": "MTV.it",
    "skysport24": "SkySport24.it",
    "skysportuno": "SkySportUno.it",
    "skysportarena": "SkySportArena.it",
    "skysportf1": "SkySportF1.it",
    "skysportmotogp": "SkySportMotoGP.it",
    "skysportgolf": "SkySportGolf.it",
    "skysporttennis": "SkySportTennis.it",
    "skysportmix": "SkySportMix.it",
    "skysportbasket": "SkySportNBA.it",
    "skysportlegend": "SkySportLegend.it",
    "skysportmax": "SkySportMax.it",
    "skysportcalcio": "SkySportCalcio.it",
    "skysport251": "SkySport251.it",
    "skysport252": "SkySport252.it",
    "skysport253": "SkySport253.it",
    "skysport254": "SkySport254.it",
    "skysport255": "SkySport255.it",
    "skysport256": "SkySport256.it",
    "skysport257": "SkySport257.it",
    "skysport258": "SkySport258.it",
    "skysport259": "SkySport259.it",
    "skycinemauno": "SkyCinemaUno.it",
    "skycinemaaction": "SkyCinemaAction.it",
    "skycinemacomedy": "SkyCinemaComedy.it",
    "skycinemadrama": "SkyCinemaDrama.it",
    "skycinemafamily": "SkyCinemaFamily.it",
    "skycinemaromance": "SkyCinemaRomance.it",
    "skycinemasuspense": "SkyCinemaSuspense.it",
    "skycinemastories": "SkyCinemaDue.it",
    "nickelodeon": "Nickelodeon.it",
    "deakids": "DeAKids.it",
    "boomerang": "Boomerang.it",
    "cartoonnetwork": "CartoonNetwork.it",
}

# DAZN tvg-id mapping (iptv-epg.org)
# iptv-epg.org ha DAZN1.it -> DAZN100.it + ZONADAZN.it -> ZONADAZN5.it
DAZN_TVG_ID_MAP = {
    # Canali DAZN numerati
    **{f"dazn{i}": f"DAZN{i}.it" for i in range(1, 101)},
    # Zona DAZN
    "zonadazn": "ZONADAZN.it",
    **{f"zonadazn{i}": f"ZONADAZN{i}.it" for i in range(2, 6)},
}


def guess_dazn_tvg_id(title):
    """Prova a dedurre il tvg-id DAZN dal titolo del canale.

    Pattern riconosciuti:
      - 'DAZN 1', 'DAZN1', 'DAZN 1 ...' → DAZN1.it
      - 'ZONA DAZN', 'ZONA DAZN 2' → ZONADAZN.it, ZONADAZN2.it
      - 'DAZN 1 Serie B', 'DAZN 1 S.B.' → DAZN1.it

    Ritorna il tvg-id (es. 'DAZN1.it') o stringa vuota se non riconosciuto.
    """
    clean = clean_channel_title(title).upper()

    # Pattern: ZONA DAZN N
    m = re.search(r'ZONA\s+DAZN\s*(\d+)?', clean)
    if m:
        num = m.group(1) or ""
        tvg_id = f"ZONADAZN{num}.it" if num else "ZONADAZN.it"
        return tvg_id

    # Pattern: DAZN N (con o senza spazi, seguito da eventuali suffissi)
    m = re.search(r'DAZN\s*(\d+)', clean)
    if m:
        num = m.group(1)
        tvg_id = f"DAZN{num}.it"
        # Verifica che il tvg_id esista nella mappa
        key = f"dazn{num}"
        if key in DAZN_TVG_ID_MAP:
            return tvg_id

    return ""


# EPG tvg-id mapping per canali Sport Extra (iptv-epg.org)
SPORT_TVG_ID_MAP = {
    # SuperTennis
    "supertennis": "SuperTennis.it",
    "super_tennis": "SuperTennis.it",
    # Eurosport
    "eurosport": "Eurosport.it",
    "eurosport1": "Eurosport.it",
    "eurosport2": "Eurosport2.it",
    # Sportitalia
    "sportitalia": "Sportitalia.it",
    # NBA
    "nbatv": "",
    "nba_tv": "",
    # Milan TV
    "milantv": "MilanTV.it",
    "milan_tv": "MilanTV.it",
    # Inter TV
    "intertv": "InterTV.it",
    "inter_tv": "InterTV.it",
    # Roma TV
    "romatv": "RomaTV.it",
    "roma_tv": "RomaTV.it",
    # Lazio Style Channel
    "laziostylech": "LazioStyleCh.it",
    "lazio_style_channel": "LazioStyleCh.it",
    # Torino Channel
    "torinochannel": "TorinoChannel.it",
    "torino_channel": "TorinoChannel.it",
    # Serie A team channels (per eventi specifici)
    "juventus": "JUVENTUS.SerieA",
    "inter": "INTER.SerieA",
    "milan": "MILAN.SerieA",
    "roma": "ROMA.SerieA",
    "lazio": "LAZIO.SerieA",
    "napoli": "NAPOLI.SerieA",
    "fiorentina": "FIORENTINA.SerieA",
    "atalanta": "ATALANTA.SerieA",
    "bologna": "BOLOGNA.SerieA",
    "torino": "TORINO.SerieA",
    "udinese": "UDINESE.SerieA",
    "cagliari": "CAGLIARI.SerieA",
    "genoa": "GENOA.SerieA",
    "parma": "PARMA.SerieA",
    "lecce": "LECCE.SerieA",
    "como": "COMO.SerieA",
    "sassuolo": "SASSUOLO.SerieA",
    "verona": "HELLASVERONA.SerieA",
    "cremonese": "CREMONESE.SerieA",
    "pisa": "PISA.SerieA",
    # Motori
    "acisporttv": "ACISportTv.it",
    "aci_sport_tv": "ACISportTv.it",
    # Altri
    "horse_tv": "HorseTV.it",
    "horsetv": "HorseTV.it",
    "automototv": "Automoto.it",
    "automoto": "Automoto.it",
    "biketv": "BIKE.it",
    "bike": "BIKE.it",
    "uniresat": "UnireSat.it",
    "italianfishingtv": "ItalianFishingTV.it",
    "cacciaepesca": "CACCIAePesca.it",
    "cacciaepestv": "CacciaePESCA.it",
}


def guess_sport_tvg_id(title):
    """Prova a dedurre il tvg-id per canali Sport Extra dal titolo.

    Strategie di matching (in ordine di priorità):
    1. Match esatto con parole chiave nel titolo (es. 'SuperTennis' → SuperTennis.it)
    2. Ricerca nome squadra per eventi calcistici (es. 'Juve vs Milan' → JUVENTUS.SerieA)
    3. Ricerca provider nel titolo (es. 'Eurosport 1' → Eurosport.it)

    Ritorna il tvg-id (es. 'SuperTennis.it') o stringa vuota se non riconosciuto.
    """
    clean = clean_channel_title(title)
    lower = clean.lower()

    # 1. Match diretto con chiavi note
    for key, tvg_id in SPORT_TVG_ID_MAP.items():
        if key in lower.replace(" ", "").replace("-", ""):
            return tvg_id

    # 2. Ricerca parole nel titolo (per match parziali tipo "SuperTennis", "Eurosport")
    #    Controlla parole intere per evitare falsi positivi
    words = re.split(r'[\s\-_.,/|]+', lower)
    for word in words:
        for key, tvg_id in SPORT_TVG_ID_MAP.items():
            if word == key:
                return tvg_id

    # 3. Pattern specifici per eventi sportivi (squadre nel titolo)
    #    Es. "Serie A - Juventus vs Milan" → JUVENTUS.SerieA (prima squadra)
    team_patterns = [
        (r'juve(?:ntus)?', "JUVENTUS.SerieA"),
        (r'inter(?:\s+milano|\s+milan)?', "INTER.SerieA"),
        (r'milan(?:\s+ac)?', "MILAN.SerieA"),
        (r'roma(?:\s+fc)?', "ROMA.SerieA"),
        (r'lazio', "LAZIO.SerieA"),
        (r'napoli', "NAPOLI.SerieA"),
        (r'fiorentina', "FIORENTINA.SerieA"),
        (r'atalanta', "ATALANTA.SerieA"),
        (r'bologna', "BOLOGNA.SerieA"),
        (r'torino(?:\s+fc)?', "TORINO.SerieA"),
        (r'udinese', "UDINESE.SerieA"),
        (r'cagliari', "CAGLIARI.SerieA"),
        (r'genoa', "GENOA.SerieA"),
        (r'parma', "PARMA.SerieA"),
        (r'lecce', "LECCE.SerieA"),
        (r'como', "COMO.SerieA"),
        (r'sassuolo', "SASSUOLO.SerieA"),
        (r'(?:verona|hellas)', "HELLASVERONA.SerieA"),
        (r'cremonese', "CREMONESE.SerieA"),
        (r'pisa', "PISA.SerieA"),
    ]
    for pattern, tvg_id in team_patterns:
        if re.search(pattern, lower):
            return tvg_id

    # 4. Pattern per tipologie di sport
    sport_type_patterns = [
        (r'moto(?:\s*gp)?|sbk|motocross', "ACISportTv.it"),
        (r'formula\s*1|f1|gp\s*formula', "ACISportTv.it"),
        (r'bike|ciclismo|giro\s*d.italia', "BIKE.it"),
        (r'tennis|atp|wta', "SuperTennis.it"),
        (r'ippica|horse|galoppo', "HorseTV.it"),
        (r'pesca|fishing', "ItalianFishingTV.it"),
        (r'caccia|hunting', "CACCIAePesca.it"),
        (r'nba|basket', ""),  # Nessun canale NBA in EPG italiana
        (r'eurosport', "Eurosport.it"),
    ]
    for pattern, tvg_id in sport_type_patterns:
        if re.search(pattern, lower):
            return tvg_id

    return ""


EPG_SOURCE_URL = "https://iptv-epg.org/files/epg-it.xml.gz"
EPG_PUBLIC_URL = "https://raw.githubusercontent.com/lucas1991-ste/Empidi/refs/heads/main/output/epg.xml"
ITALY_TZ_OFFSET = "+0200"


# ============================================================
# DAZN: USER-AGENT E HEADER COSTANTI
# ============================================================

DAZN_UA_LGTV = (
    "Mozilla/5.0 (Web0S; Linux/SmartTV) AppleWebKit/537.41 (KHTML, like Gecko) "
    "Large Screen Safari/537.41 LG Browser/7.00.00(LGE; WEBOS1; 05.06.10; 1); "
    "webOS.TV-2014; LG NetCast.TV-2013 Compatible (LGE, WEBOS1, wireless)"
)

DAZN_UA_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)

DAZN_UA_FIREFOX = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:144.0) Gecko/20100101 Firefox/144.0"
)


# ============================================================
# FUNZIONI CORE - UTILITA
# ============================================================

def xor_decrypt(data_b64, key):
    """Decrittazione XOR dei dati stream Sky."""
    data = base64.b64decode(data_b64)
    key_bytes = key.encode()
    out = bytearray()
    for i in range(len(data)):
        out.append(data[i] ^ key_bytes[i % len(key_bytes)])
    return out.decode("utf-8")


def fetch_url(url, headers=None, timeout=30):
    """Fetch URL con gestione errori."""
    req = Request(url, headers=headers or {})
    try:
        resp = urlopen(req, timeout=timeout)
        return resp.read().decode("utf-8")
    except (HTTPError, URLError) as e:
        print(f"  [WARN] Errore fetching {url}: {e}", file=sys.stderr)
        return None


def fix_base64_padding(s):
    """Corregge il padding base64 (==) per la decodifica."""
    s = s.strip()
    missing = len(s) % 4
    if missing == 0:
        return s
    elif missing == 2:
        return s + "=="
    elif missing == 3:
        return s + "="
    else:
        return None


def format_headers_kodiprop(headers):
    """Formatta un dict di header HTTP come valore KODIPROP stream_headers."""
    parts = []
    for k, v in headers.items():
        encoded_value = quote(v, safe='')
        parts.append(f"{k}={encoded_value}")
    return "&".join(parts)


# ============================================================
# FUNZIONI CORE - STREAM LISTING E RESOLVE
# ============================================================

def get_listing_channels(url, prefixes, user_agent=None):
    """Ottiene la lista dei canali dall'API listing, filtrando per prefissi myresolve.
    Ritorna lista di dict: {title, prefix, resolve_data}
    """
    raw = fetch_url(url, headers={"User-Agent": user_agent or STREAM_USER_AGENT})
    if not raw:
        return []

    data = json.loads(raw)
    channels = []

    def extract(obj):
        if isinstance(obj, dict):
            if "myresolve" in obj:
                for prefix in prefixes:
                    if obj["myresolve"].startswith(prefix):
                        title = (
                            re.sub(r"\[COLOR [^\]]+\]", "", obj.get("title", ""))
                            .replace("[/COLOR]", "")
                            .strip()
                        )
                        resolve_data = obj["myresolve"][len(prefix):]
                        channels.append({
                            "title": title,
                            "prefix": prefix,
                            "resolve_data": resolve_data,
                        })
                        break
            for v in obj.values():
                extract(v)
        elif isinstance(obj, list):
            for item in obj:
                extract(item)

    extract(data)
    return channels


def resolve_sky_channel(ch_id):
    """Risolve un singolo canale Sky ottenendo manifest URL + chiavi clearkey."""
    url = STREAM_RESOLVE_URL + ch_id
    raw = fetch_url(url, headers={"User-Agent": STREAM_USER_AGENT}, timeout=15)
    if not raw:
        return None

    try:
        data = json.loads(raw)
        if "data" not in data:
            return None
        decrypted = json.loads(xor_decrypt(data["data"], XOR_SECRET))
        return {
            "manifest": decrypted["manifest"],
            "kid": decrypted["kid"],
            "key": decrypted["key"],
            "stream_type": "sky",
            "headers": {},
        }
    except Exception as e:
        print(f"  [WARN] Errore risoluzione Sky {ch_id}: {e}", file=sys.stderr)
        return None


def resolve_amstaff_channel(resolve_prefix, resolve_data):
    """Risolve un canale amstaff/daznToken decodificando il payload.

    Formati payload:
    - amstaff@@: base64(manifest|kid:key[|token]) o manifest|kid:key (se http in data)
    - daznToken@@: base64(manifest|kid:key|dazn_token_value[|custom_ua])

    Ritorna dict con manifest, kid, key, stream_type, headers; oppure None.
    """
    try:
        # Se il dato contiene gia' http, e' un URL raw (non base64)
        if "http" in resolve_data:
            parametro = resolve_data
        else:
            padded = fix_base64_padding(resolve_data)
            if padded is None:
                return None
            parametro = base64.b64decode(padded).decode("utf-8")

        parts = parametro.split("|")
        if len(parts) < 2:
            return None

        manifest = parts[0]
        kid_key = parts[1]

        # kid:key in formato hex ClearKey, o 0:0 / 0000 per nessun DRM
        kid, key = "", ""
        if ":" in kid_key:
            kid, key = kid_key.split(":", 1)
            # Se kid=key=0, nessun DRM
            if kid == "0" and key == "0":
                kid = ""
                key = ""
        elif kid_key == "0000":
            # Sentinella per "nessun DRM"
            pass
        else:
            # Formato non riconosciuto
            return None

        # Determina gli header in base al tipo di flusso e al dominio
        headers = {}

        if resolve_prefix == "amstaff@@":
            # Il token e' opzionale (3° campo)
            token = parts[2] if len(parts) >= 3 else ""

            if "dazn" in manifest or "dai.google.com" in manifest:
                # Flusso DAZN
                if token:
                    headers = {
                        "dazn-token": token,
                        "referer": "https://www.dazn.com/",
                        "origin": "https://www.dazn.com",
                        "user-agent": DAZN_UA_CHROME,
                    }
                else:
                    headers = {
                        "User-Agent": DAZN_UA_LGTV,
                        "Referer": "https://www.dazn.com/",
                        "Origin": "https://www.dazn.com",
                    }
            # I flussi non-DAZN (Izzi, BeIN, etc.) non hanno bisogno di header speciali

        elif resolve_prefix == "daznToken@@":
            token = parts[2] if len(parts) >= 3 else ""
            custom_ua = parts[3] if len(parts) >= 4 else None
            ua = custom_ua if custom_ua else DAZN_UA_FIREFOX
            headers = {
                "dazn-token": token,
                "User-Agent": ua,
            }

        # Classifica il canale per tipo
        stream_type, _, _ = classify_manifest(manifest)

        return {
            "manifest": manifest,
            "kid": kid,
            "key": key,
            "stream_type": stream_type,
            "headers": headers,
        }

    except Exception as e:
        print(f"  [WARN] Errore decodifica ({resolve_prefix}): {e}", file=sys.stderr)
        return None


def fetch_all_channels():
    """Fetch e risoluzione di tutti i canali disponibili (Sky + DAZN/Sport)."""
    print("=== IPTV Playlist Generator (Sky + DAZN) ===")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")

    # --------------------------------------------------------
    # 1. CANALI SKY
    # --------------------------------------------------------
    sky_listing = get_listing_channels(STREAM_LIST_URL, ["sky@@"])
    print(f"\n[1] Canali Sky trovati nell'API listing: {len(sky_listing)}")

    all_sky = {}
    for ch in sky_listing:
        ch_id = ch["resolve_data"]
        all_sky[ch_id] = CHANNEL_NAMES.get(ch_id, ch["title"])
    for ch_id, name in CHANNEL_NAMES.items():
        if ch_id not in all_sky:
            all_sky[ch_id] = name

    print(f"    Canali Sky totali (con extra): {len(all_sky)}")

    resolved = []
    failed = []
    for ch_id, name in sorted(all_sky.items()):
        result = resolve_sky_channel(ch_id)
        if result:
            result["id"] = ch_id
            result["name"] = name
            result["group"] = get_group(ch_id)
            result["logo"] = LOGO_MAP.get(ch_id, "")
            result["tvg_id"] = TVG_ID_MAP.get(ch_id, "")
            resolved.append(result)
            print(f"  OK {name}")
        else:
            failed.append((ch_id, name))
            print(f"  X  {name} (non disponibile)")

    print(f"    Sky risolti: {len(resolved)}/{len(all_sky)}")
    if failed:
        print(f"    Sky non disponibili: {', '.join(n for _, n in failed)}")

    # --------------------------------------------------------
    # 2. CANALI DAZN / SPORT EXTRA
    # --------------------------------------------------------
    dazn_url = get_dazn_list_url()
    if dazn_url:
        dazn_listing = get_listing_channels(dazn_url, ["amstaff@@", "daznToken@@"])
        print(f"\n[2] Canali trovati nell'API DAZN/Sport: {len(dazn_listing)}")

        dazn_resolved = []
        sport_resolved = []
        dazn_failed = []
        dazn_skipped = 0

        for ch in dazn_listing:
            result = resolve_amstaff_channel(ch["prefix"], ch["resolve_data"])
            if not result:
                dazn_failed.append(ch["title"])
                print(f"  X  {ch['title']} (decodifica fallita)")
                continue

            # Classifica il canale
            stream_type, auto_group, auto_logo = classify_manifest(result["manifest"])

            # Determina se includere il canale
            if stream_type == "dazn":
                # Canali DAZN sempre inclusi
                ch_id = title_to_ch_id(ch["title"])
                name = clean_channel_title(ch["title"])
                result["id"] = f"dazn_{ch_id}"
                result["name"] = name
                result["group"] = auto_group
                result["logo"] = auto_logo
                # Prova a dedurre il tvg-id dal titolo
                tvg_id = guess_dazn_tvg_id(ch["title"])
                result["tvg_id"] = tvg_id
                epg_info = f" (EPG: {tvg_id})" if tvg_id else " (no EPG)"
                dazn_resolved.append(result)
                print(f"  OK DAZN: {name}{epg_info}")

            elif stream_type == "sport":
                if INCLUDE_SPORT_EXTRA:
                    ch_id = title_to_ch_id(ch["title"])
                    name = clean_channel_title(ch["title"])
                    result["id"] = f"sport_{ch_id}"
                    result["name"] = name
                    result["group"] = auto_group
                    result["logo"] = auto_logo
                    # Prova a dedurre il tvg-id dal titolo
                    tvg_id = guess_sport_tvg_id(ch["title"])
                    result["tvg_id"] = tvg_id
                    # Se il logo non è stato impostato da classify_manifest, prova SPORT_LOGO_MAP
                    if not result["logo"]:
                        for logo_key, logo_url in SPORT_LOGO_MAP.items():
                            if logo_key in ch_id and logo_url:
                                result["logo"] = logo_url
                                break
                    epg_info = f" (EPG: {tvg_id})" if tvg_id else " (no EPG)"
                    sport_resolved.append(result)
                    print(f"  OK Sport: {name}{epg_info}")
                else:
                    dazn_skipped += 1

            else:
                # Tipo sconosciuto - salta
                dazn_skipped += 1

        resolved.extend(dazn_resolved)
        resolved.extend(sport_resolved)

        print(f"    DAZN risolti: {len(dazn_resolved)}")
        if INCLUDE_SPORT_EXTRA:
            print(f"    Sport Extra risolti: {len(sport_resolved)}")
        print(f"    Saltati: {dazn_skipped}")
        if dazn_failed:
            print(f"    Falliti: {len(dazn_failed)}")
    else:
        print("\n[2] DAZN: URL listing non configurato, salto")
        print("    Imposta STREAM_LIST_URL_DAZN o assicurati che STREAM_LIST_URL contenga A1A260")

    # Conteggi finali
    sky_count = sum(1 for c in resolved if c.get("stream_type") == "sky")
    dazn_count = sum(1 for c in resolved if c.get("stream_type") == "dazn")
    sport_count = sum(1 for c in resolved if c.get("stream_type") == "sport")

    print(f"\n[TOTALE] Canali risolti: {len(resolved)} ({sky_count} Sky + {dazn_count} DAZN + {sport_count} Sport Extra)")
    return resolved


# ============================================================
# GENERATORI M3U
# ============================================================

def generate_m3u_kodi(channels, epg_url=""):
    """
    Genera M3U in formato compatibile con Sparkle TV, Kodi, UHF, etc.
    Usa il formato license_type + license_key (non drm_legacy).
    Per i canali DAZN, aggiunge anche stream_headers e manifest_headers.
    """
    header = "#EXTM3U"
    if epg_url:
        header += f' url-tvg="{epg_url}"'
    lines = [header]

    for ch in channels:
        kid = ch["kid"]
        key = ch["key"]
        manifest = ch["manifest"]
        group = ch.get("group", "Sky")
        logo = ch.get("logo", "")
        tvg_id = ch.get("tvg_id", "")
        headers = ch.get("headers", {})

        # EXTINF
        tid = f' tvg-id="{tvg_id}"' if tvg_id else ""
        tlogo = f' tvg-logo="{logo}"' if logo else ""
        gtitle = f' group-title="{group}"' if group else ""
        lines.append(f'#EXTINF:-1{tid}{tlogo}{gtitle},{ch["name"]}')

        # KODIPROP formato classico (solo se c'e' DRM)
        if kid and key:
            lines.append(f'#KODIPROP:inputstream.adaptive.license_type=org.w3.clearkey')
            lines.append(f'#KODIPROP:inputstream.adaptive.license_key={kid}:{key}')

        # Header HTTP personalizzati (per DAZN e altri che ne hanno bisogno)
        if headers:
            headers_str = format_headers_kodiprop(headers)
            lines.append(f'#KODIPROP:inputstream.adaptive.stream_headers={headers_str}')
            lines.append(f'#KODIPROP:inputstream.adaptive.manifest_headers={headers_str}')

        lines.append(manifest)

    return "\n".join(lines) + "\n"


def generate_m3u_pipe(channels, epg_url=""):
    """
    Genera M3U con formato pipe per Tivimate/iMPlayer/Televizo.
    clearkey via URL: manifest.mpd|key_id=XXX&key=YYY
    Per i canali con header personalizzati, aggiunge KODIPROP.
    """
    header = "#EXTM3U"
    if epg_url:
        header += f' url-tvg="{epg_url}"'
    lines = [header]

    for ch in channels:
        kid = ch["kid"]
        key = ch["key"]
        manifest = ch["manifest"]
        group = ch.get("group", "Sky")
        logo = ch.get("logo", "")
        tvg_id = ch.get("tvg_id", "")
        headers = ch.get("headers", {})

        tid = f' tvg-id="{tvg_id}"' if tvg_id else ""
        tlogo = f' tvg-logo="{logo}"' if logo else ""
        gtitle = f' group-title="{group}"' if group else ""

        lines.append(f'#EXTINF:-1{tid}{tlogo}{gtitle},{ch["name"]}')

        # Per i canali con header personalizzati, aggiungi KODIPROP
        if headers:
            headers_str = format_headers_kodiprop(headers)
            lines.append(f'#KODIPROP:inputstream.adaptive.stream_headers={headers_str}')
            lines.append(f'#KODIPROP:inputstream.adaptive.manifest_headers={headers_str}')

        # Formato pipe: URL|key_id=KID&key=KEY
        if kid and key:
            lines.append(f"{manifest}|key_id={kid}&key={key}")
        else:
            # No DRM (es. SuperTennis, DAZN Serie B senza DRM)
            lines.append(manifest)

    return "\n".join(lines) + "\n"


# ============================================================
# EPG: FILTRO DA FONTE ESTERNA (iptv-epg.org)
# ============================================================

def adjust_timezone(xml_string, tz_offset=ITALY_TZ_OFFSET):
    """Converte il fuso orario nei tag <programme> da +0000 a tz_offset."""
    result = re.sub(r'(start|stop)="(\d{14}) \+0000"',
                    rf'\1="\2 {tz_offset}"',
                    xml_string)
    return result


def download_and_filter_epg(channels, out_dir):
    """Scarica EPG da iptv-epg.org e filtra solo i canali della nostra playlist."""
    our_tvg_ids = set()
    for ch in channels:
        tvg_id = ch.get("tvg_id", "")
        if tvg_id:
            our_tvg_ids.add(tvg_id)

    if not our_tvg_ids:
        print("    Nessun canale con tvg-id, salto EPG")
        return 0

    print(f"    Canali da cercare: {len(our_tvg_ids)}")

    try:
        req = Request(EPG_SOURCE_URL, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            "Accept": "*/*",
        })
        resp = urlopen(req, timeout=120)
        gz_data = resp.read()
        print(f"    Scaricato EPG: {len(gz_data)} bytes (gz)")
    except Exception as e:
        print(f"    [WARN] Errore download EPG: {e}", file=sys.stderr)
        return 0

    try:
        xml_content = gzip.decompress(gz_data).decode("utf-8")
        print(f"    Decompresso: {len(xml_content)} bytes")
    except Exception as e:
        print(f"    [WARN] Errore decompressione EPG: {e}", file=sys.stderr)
        return 0

    channel_pattern = re.compile(
        r'<channel\s+id="([^"]+)"[^>]*>.*?</channel>',
        re.DOTALL
    )
    programme_pattern = re.compile(
        r'<programme\s+[^>]*channel="([^"]+)"[^>]*>.*?</programme>',
        re.DOTALL
    )

    tv_match = re.search(r'(<tv[^>]*>)', xml_content)
    tv_header = tv_match.group(1) if tv_match else '<tv>'

    filtered_channels = []
    for m in channel_pattern.finditer(xml_content):
        ch_id = m.group(1)
        if ch_id in our_tvg_ids:
            filtered_channels.append(m.group(0))

    filtered_programmes = []
    for m in programme_pattern.finditer(xml_content):
        ch_id = m.group(1)
        if ch_id in our_tvg_ids:
            filtered_programmes.append(m.group(0))

    epg_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    epg_content += tv_header + '\n'
    for ch in filtered_channels:
        epg_content += ch + '\n'
    for prog in filtered_programmes:
        epg_content += prog + '\n'
    epg_content += '</tv>'

    epg_content = adjust_timezone(epg_content)
    print(f"    Fuso orario convertito: +0000 -> {ITALY_TZ_OFFSET}")

    epg_path = os.path.join(out_dir, "epg.xml")
    with open(epg_path, "w", encoding="utf-8") as f:
        f.write(epg_content)
    print(f"    [OUTPUT] {epg_path} ({len(epg_content)} bytes)")

    epg_gz_path = os.path.join(out_dir, "epg.xml.gz")
    with gzip.open(epg_gz_path, "wb") as f:
        f.write(epg_content.encode("utf-8"))
    gz_size = os.path.getsize(epg_gz_path)
    print(f"    [OUTPUT] {epg_gz_path} ({gz_size} bytes)")

    print(f"    Canali EPG: {len(filtered_channels)}, Programmi: {len(filtered_programmes)}")
    return len(filtered_programmes)


# ============================================================
# MAIN
# ============================================================

def main():
    check_env()
    channels = fetch_all_channels()
    if not channels:
        print("\n[ERRORE] Nessun canale risolto. Uscita.")
        sys.exit(1)

    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out_dir, exist_ok=True)

    # EPG
    print(f"\n[3] Scaricamento EPG da iptv-epg.org...")
    epg_count = download_and_filter_epg(channels, out_dir)

    # PLAYLIST
    epg_url = EPG_PUBLIC_URL

    outputs = {
        "playlist_kodi.m3u": generate_m3u_kodi(channels, epg_url=epg_url),
        "playlist_tivimate.m3u": generate_m3u_pipe(channels, epg_url=epg_url),
    }

    for filename, content in outputs.items():
        filepath = os.path.join(out_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"\n[OUTPUT] {filepath} ({len(content)} bytes)")

    # Stremio JSON
    streams = {}
    for ch in channels:
        stream_entry = {
            "name": ch["name"],
            "manifest": ch["manifest"],
            "kid": ch["kid"],
            "key": ch["key"],
            "group": ch.get("group", ""),
            "logo": ch.get("logo", ""),
            "tvg_id": ch.get("tvg_id", ""),
            "stream_type": ch.get("stream_type", "sky"),
        }
        if ch.get("headers"):
            stream_entry["headers"] = ch["headers"]
        streams[ch["id"]] = stream_entry

    stremio_json = json.dumps({
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "iptv-playlist",
        "channel_count": len(channels),
        "channels": streams,
    }, indent=2, ensure_ascii=False)
    stremio_path = os.path.join(out_dir, "playlist_stremio.json")
    with open(stremio_path, "w", encoding="utf-8") as f:
        f.write(stremio_json)

    # Status
    sky_count = sum(1 for ch in channels if ch.get("stream_type") == "sky")
    dazn_count = sum(1 for ch in channels if ch.get("stream_type") == "dazn")
    sport_count = sum(1 for ch in channels if ch.get("stream_type") == "sport")
    status = {
        "last_update": datetime.now(timezone.utc).isoformat(),
        "total_channels": len(channels),
        "sky_channels": sky_count,
        "dazn_channels": dazn_count,
        "sport_channels": sport_count,
        "epg_programs": epg_count,
        "channels": [
            {
                "id": ch["id"],
                "name": ch["name"],
                "group": ch.get("group", ""),
                "tvg_id": ch.get("tvg_id", ""),
                "logo": ch.get("logo", ""),
                "stream_type": ch.get("stream_type", "sky"),
            }
            for ch in channels
        ],
    }
    status_path = os.path.join(out_dir, "status.json")
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)

    print(f"\n=== Completato: {len(channels)} canali ({sky_count} Sky + {dazn_count} DAZN + {sport_count} Sport Extra), {epg_count} programmi EPG ===")


if __name__ == "__main__":
    main()
