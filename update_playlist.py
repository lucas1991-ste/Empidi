#!/usr/bin/env python3
"""
IPTV Playlist + EPG Generator - Sky/NowTV Channels via Amstaff API
Genera playlist M3U con flussi MPD + clearkey e guida programmi XMLTV
per canali Sky italiani. I link sono dinamici e vengono aggiornati ad ogni esecuzione.

Fonte stream: Amstaff API con credenziali Mandrakodi
Fonte EPG: API ufficiale Sky (apid.sky.it/gtv/v1)
Decrittazione: XOR con chiave -> JSON con manifest/kid/key

CREDENZIALI: Tutte le credenziali sensibili vengono lette da variabili d'ambiente.
             Non hardcodare nulla in questo file.

Formati di output:
  - playlist_kodi.m3u:     M3U per Sparkle TV / Kodi / UHF (KODIPROP)
  - playlist_tivimate.m3u: M3U per Tivimate/iMPlayer (formato pipe key)
  - epg.xml:               Guida programmi XMLTV
  - epg.xml.gz:            Guida programmi compressa (per app che lo supportano)
"""

import json
import base64
import re
import sys
import os
import gzip
from datetime import datetime, timezone

from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ============================================================
# CONFIGURAZIONE - TUTTO DA ENV VARS
# ============================================================

AMSTAFF_LIST_URL = os.environ.get("AMSTAFF_LIST_URL", "")
AMSTAFF_RESOLVE_URL = os.environ.get("AMSTAFF_RESOLVE_URL", "")
AMSTAFF_USER_AGENT = os.environ.get("AMSTAFF_USER_AGENT", "")
XOR_SECRET = os.environ.get("XOR_SECRET", "")

def check_env():
    """Verifica che tutte le env vars obbligatorie siano impostate."""
    missing = []
    if not AMSTAFF_LIST_URL:
        missing.append("AMSTAFF_LIST_URL")
    if not AMSTAFF_RESOLVE_URL:
        missing.append("AMSTAFF_RESOLVE_URL")
    if not AMSTAFF_USER_AGENT:
        missing.append("AMSTAFF_USER_AGENT")
    if not XOR_SECRET:
        missing.append("XOR_SECRET")
    if missing:
        print(f"[ERRORE] Variabili d'ambiente mancanti: {', '.join(missing)}")
        print("Impostale nel tuo .env file o nelle GitHub Secrets.")
        sys.exit(1)


# ============================================================
# DEFINIZIONE CANALI
# ============================================================

# ID Amstaff -> nome pulito
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

# Loghi da tv-logo/tv-logos via jsDelivr CDN (PNG trasparenti, stabili, veloci)
# Fonte: https://github.com/tv-logo/tv-logos
LOGO_CDN = "https://cdn.jsdelivr.net/gh/tv-logo/tv-logos@main/countries/italy"
LOGO_CDN_UK = "https://cdn.jsdelivr.net/gh/tv-logo/tv-logos@main/countries/united-kingdom"

LOGO_MAP = {
    # Intrattenimento
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
    # Sport
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
    # Sky Sport 251-259: canali evento, usano logo Sky Sport Calcio
    "skysport251": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport252": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport253": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport254": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport255": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport256": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport257": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport258": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    "skysport259": f"{LOGO_CDN}/sky-sport-calcio-it.png",
    # Cinema
    "skycinemauno": f"{LOGO_CDN}/sky-cinema-uno-it.png",
    "skycinemaaction": f"{LOGO_CDN}/sky-cinema-action-it.png",
    "skycinemacomedy": f"{LOGO_CDN}/sky-cinema-comedy-it.png",
    "skycinemadrama": f"{LOGO_CDN}/sky-cinema-drama-it.png",
    "skycinemafamily": f"{LOGO_CDN}/sky-cinema-family-it.png",
    "skycinemaromance": f"{LOGO_CDN}/sky-cinema-romance-it.png",
    "skycinemasuspense": f"{LOGO_CDN}/sky-cinema-suspense-it.png",
    "skycinemastories": f"{LOGO_CDN}/sky-cinema-due-it.png",
    # Kids
    "nickelodeon": f"{LOGO_CDN}/nickelodeon-it.png",
    "deakids": f"{LOGO_CDN}/dea-kids-it.png",
    "boomerang": f"{LOGO_CDN}/boomerang-it.png",
    "cartoonnetwork": f"{LOGO_CDN}/cartoon-network-it.png",
}

# Gruppi
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
    """Determina il gruppo di un canale."""
    if ch_id.startswith("skysport2") and ch_id not in ("skysport24",):
        return "Sky Sport Calcio"
    if ch_id.startswith("skysport"):
        return "Sky Sport"
    if ch_id.startswith("skycinema"):
        return "Sky Cinema"
    return GROUP_MAP.get(ch_id, "Sky")

# ============================================================
# EPG: MAPPING CANALI -> epgshare01
# ============================================================

# ID Amstaff -> tvg-id nel formato epgshare01 (es. "Sky.Uno.it")
# Fonte EPG: https://epgshare01.online/epgshare01/epg_ripper_IT1.xml.gz
TVG_ID_MAP = {
    "tg24": "Sky.TG24.it",
    "skyuno": "Sky.Uno.it",
    "skyatlantic": "Sky.Atlantic.it",
    "skyserie": "Sky.Serie.it",
    "skycollection": "Sky.Cinema.Collection.it",
    "skyinvestigation": "Sky.Investigation.it",
    "skyadventure": "Sky.Adventure.it",
    "skycrime": "Sky.Crime.it",
    "comedycentral": "Comedy.Central.it",
    "skydocumentaries": "Sky.Documentaries.it",
    "skynature": "Sky.Nature.it",
    "historychannel": "History.it",
    "skyarte": "Sky.Arte.it",
    "mtv": "MTV.it",
    "skysport24": "Sky.Sport.24.it",
    "skysportuno": "Sky.Sport.Uno.it",
    "skysportarena": "Sky.Sport.Arena.it",
    "skysportf1": "Sky.Sport.F1.it",
    "skysportmotogp": "Sky.Sport.MotoGP.it",
    "skysportgolf": "Sky.Sport.Golf.it",
    "skysporttennis": "Sky.Sport.Tennis.it",
    "skysportmix": "Sky.Sport.Mix.it",
    "skysportbasket": "Sky.Sport.NBA.it",
    "skysportlegend": "Sky.Sport.Legend.it",
    "skysportmax": "Sky.Sport.Max.it",
    "skysportcalcio": "Sky.Sport.Calcio.it",
    "skysport251": "Sky.Sport.251.it",
    "skysport252": "Sky.Sport.252.it",
    "skysport253": "Sky.Sport.253.it",
    "skysport254": "Sky.Sport.254.it",
    "skysport255": "Sky.Sport.255.it",
    "skysport256": "Sky.Sport.256.it",
    "skysport257": "Sky.Sport.257.it",
    "skysport258": "Sky.Sport.258.it",
    "skysport259": "Sky.Sport.259.it",
    "skycinemauno": "Sky.Cinema.Uno.it",
    "skycinemaaction": "Sky.Cinema.Action.it",
    "skycinemacomedy": "Sky.Cinema.Comedy.it",
    "skycinemadrama": "Sky.Cinema.Drama.it",
    "skycinemafamily": "Sky.Cinema.Family.it",
    "skycinemaromance": "Sky.Cinema.Romance.it",
    "skycinemasuspense": "Sky.Cinema.Suspense.it",
    "skycinemastories": "Sky.Cinema.Collection.it",
    "nickelodeon": "Nickelodeon.it",
    "deakids": "DeA.Kids.it",
    "boomerang": "Boomerang.it",
    "cartoonnetwork": "Cartoon.Network.it",
}

# URL fonte EPG (epgshare01, aggiornata giornalmente)
EPG_SOURCE_URL = "https://epgshare01.online/epgshare01/epg_ripper_IT1.xml.gz"


# ============================================================
# FUNZIONI CORE - STREAM
# ============================================================

def xor_decrypt(data_b64, key):
    """Decrittazione XOR come nel myResolver.py di Mandrakodi."""
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


def get_listing_channels():
    """Ottiene la lista dei canali dall'API Amstaff (listing endpoint)."""
    raw = fetch_url(AMSTAFF_LIST_URL, headers={"User-Agent": AMSTAFF_USER_AGENT})
    if not raw:
        return []

    data = json.loads(raw)
    channels = []

    def extract(obj):
        if isinstance(obj, dict):
            if "myresolve" in obj and obj["myresolve"].startswith("sky@@"):
                title = re.sub(r"\[COLOR [^\]]+\]", "", obj.get("title", "")).replace("[/COLOR]", "").strip()
                ch_id = obj["myresolve"].replace("sky@@", "")
                channels.append((ch_id, title))
            for v in obj.values():
                extract(v)
        elif isinstance(obj, list):
            for item in obj:
                extract(item)

    extract(data)
    return channels


def resolve_channel(ch_id):
    """Risolve un singolo canale ottenendo manifest URL + chiavi clearkey."""
    url = AMSTAFF_RESOLVE_URL + ch_id
    raw = fetch_url(url, headers={"User-Agent": AMSTAFF_USER_AGENT}, timeout=15)
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
        }
    except Exception as e:
        print(f"  [WARN] Errore risoluzione {ch_id}: {e}", file=sys.stderr)
        return None


def fetch_all_channels():
    """Fetch e risoluzione di tutti i canali disponibili."""
    print("=== IPTV Playlist Generator ===")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")

    # 1. Canali dall'API listing
    listing = get_listing_channels()
    print(f"\n[1] Canali trovati nell'API listing: {len(listing)}")

    # 2. Unisci: i nomi da CHANNEL_NAMES sovrascrivono quelli del listing
    all_channels = {}
    for ch_id, name in listing:
        all_channels[ch_id] = CHANNEL_NAMES.get(ch_id, name)
    for ch_id, name in CHANNEL_NAMES.items():
        if ch_id not in all_channels:
            all_channels[ch_id] = name

    print(f"[2] Canali totali (con extra): {len(all_channels)}")

    # 3. Risolvi ogni canale
    resolved = []
    failed = []
    for ch_id, name in sorted(all_channels.items()):
        result = resolve_channel(ch_id)
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

    print(f"\n[3] Risolti: {len(resolved)}/{len(all_channels)}")
    if failed:
        print(f"    Non disponibili: {', '.join(n for _, n in failed)}")

    return resolved


# ============================================================
# GENERATORI M3U
# ============================================================

def generate_m3u_kodi(channels, epg_url=""):
    """
    Genera M3U in formato compatibile con Sparkle TV, Kodi, UHF, etc.
    Usa il formato license_type + license_key (non drm_legacy).
    """
    # Header con eventuale riferimento EPG
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

        # EXTINF
        tid = f' tvg-id="{tvg_id}"' if tvg_id else ""
        tlogo = f' tvg-logo="{logo}"' if logo else ""
        gtitle = f' group-title="{group}"' if group else ""
        lines.append(f'#EXTINF:-1{tid}{tlogo}{gtitle},{ch["name"]}')

        # KODIPROP formato classico
        lines.append(f'#KODIPROP:inputstream.adaptive.license_type=org.w3.clearkey')
        lines.append(f'#KODIPROP:inputstream.adaptive.license_key={kid}:{key}')
        lines.append(manifest)

    return "\n".join(lines) + "\n"


def generate_m3u_pipe(channels, epg_url=""):
    """
    Genera M3U con formato pipe per Tivimate/iMPlayer/Televizo.
    clearkey via URL: manifest.mpd|key_id=XXX&key=YYY
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

        tid = f' tvg-id="{tvg_id}"' if tvg_id else ""
        tlogo = f' tvg-logo="{logo}"' if logo else ""
        gtitle = f' group-title="{group}"' if group else ""

        lines.append(f'#EXTINF:-1{tid}{tlogo}{gtitle},{ch["name"]}')
        lines.append(f"{manifest}|key_id={kid}&key={key}")

    return "\n".join(lines) + "\n"


# ============================================================
# EPG: FILTRO DA FONTE ESTERNA (epgshare01)
# ============================================================

def download_and_filter_epg(channels, out_dir):
    """
    Scarica EPG da epgshare01 e filtra solo i canali della nostra playlist.
    Salva epg.xml e epg.xml.gz nella directory di output.
    Ritorna il numero di programmi trovati.
    """
    # Raccogli i tvg-id dei nostri canali risolti
    our_tvg_ids = set()
    for ch in channels:
        tvg_id = ch.get("tvg_id", "")
        if tvg_id:
            our_tvg_ids.add(tvg_id)

    if not our_tvg_ids:
        print("    Nessun canale con tvg-id, salto EPG")
        return 0

    print(f"    Canali da cercare: {len(our_tvg_ids)}")

    # Scarica EPG compresso (serve User-Agent browser)
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

    # Decomprimi
    try:
        xml_content = gzip.decompress(gz_data).decode("utf-8")
        print(f"    Decompresso: {len(xml_content)} bytes")
    except Exception as e:
        print(f"    [WARN] Errore decompressione EPG: {e}", file=sys.stderr)
        return 0

    # Filtra: estrai solo <channel> e <programme> per i nostri tvg-id
    # Usiamo regex per semplicita' e velocita' (evitiamo di caricare tutto in DOM)
    import re as _re

    # Estrai i channel elements che ci servono
    channel_pattern = _re.compile(
        r'<channel\s+id="([^"]+)"[^>]*>.*?</channel>',
        _re.DOTALL
    )
    programme_pattern = _re.compile(
        r'<programme\s+[^>]*channel="([^"]+)"[^>]*>.*?</programme>',
        _re.DOTALL
    )

    # Estrai header <tv>
    tv_match = _re.search(r'(<tv[^>]*>)', xml_content)
    tv_header = tv_match.group(1) if tv_match else '<tv>'

    # Filtra channels
    filtered_channels = []
    for m in channel_pattern.finditer(xml_content):
        ch_id = m.group(1)
        if ch_id in our_tvg_ids:
            filtered_channels.append(m.group(0))

    # Filtra programmes
    filtered_programmes = []
    for m in programme_pattern.finditer(xml_content):
        ch_id = m.group(1)
        if ch_id in our_tvg_ids:
            filtered_programmes.append(m.group(0))

    # Costruisci XML filtrato
    epg_filtered = '<?xml version="1.0" encoding="UTF-8"?>\n'
    epg_filtered += tv_header + '\n'
    for ch in filtered_channels:
        epg_filtered += ch + '\n'
    for prog in filtered_programmes:
        epg_filtered += prog + '\n'
    epg_filtered += '</tv>'

    # Salva epg.xml
    epg_path = os.path.join(out_dir, "epg.xml")
    with open(epg_path, "w", encoding="utf-8") as f:
        f.write(epg_filtered)
    print(f"    [OUTPUT] {epg_path} ({len(epg_filtered)} bytes)")

    # Salva epg.xml.gz
    epg_gz_path = os.path.join(out_dir, "epg.xml.gz")
    with open(epg_gz_path, "wb") as f:
        f.write(gzip.compress(epg_filtered.encode("utf-8")))
    print(f"    [OUTPUT] {epg_gz_path}")

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

    # Directory di output (argomento o corrente)
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out_dir, exist_ok=True)

    # ============================================================
    # EPG: Scarica e filtra da epgshare01
    # ============================================================
    print(f"\n[4] Scaricamento EPG da epgshare01...")
    epg_count = download_and_filter_epg(channels, out_dir)

    # ============================================================
    # PLAYLIST: Genera M3U con riferimento EPG
    # ============================================================
    epg_url = "epg.xml.gz"

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
        streams[ch["id"]] = {
            "name": ch["name"],
            "manifest": ch["manifest"],
            "kid": ch["kid"],
            "key": ch["key"],
            "group": ch.get("group", ""),
            "logo": ch.get("logo", ""),
            "tvg_id": ch.get("tvg_id", ""),
        }
    stremio_json = json.dumps({
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "amstaff-mandrakodi",
        "channel_count": len(channels),
        "channels": streams,
    }, indent=2, ensure_ascii=False)
    stremio_path = os.path.join(out_dir, "playlist_stremio.json")
    with open(stremio_path, "w", encoding="utf-8") as f:
        f.write(stremio_json)

    # Status
    status = {
        "last_update": datetime.now(timezone.utc).isoformat(),
        "total_channels": len(channels),
        "epg_programs": epg_count,
        "channels": [
            {
                "id": ch["id"],
                "name": ch["name"],
                "group": ch.get("group", ""),
                "tvg_id": ch.get("tvg_id", ""),
                "has_epg": bool(ch.get("tvg_id")),
            }
            for ch in channels
        ],
    }
    status_path = os.path.join(out_dir, "status.json")
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)

    print(f"\n=== Completato: {len(channels)} canali, {epg_count} programmi EPG ===")


if __name__ == "__main__":
    main()
