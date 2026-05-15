#!/usr/bin/env python3
"""
IPTV Playlist Generator - Sky/NowTV Channels via Amstaff API
Genera una playlist M3U con flussi MPD + clearkey per canali Sky italiani.
I link sono dinamici e vengono aggiornati ad ogni esecuzione.

Fonte: Amstaff API con credenziali Mandrakodi
Decrittazione: XOR con chiave -> JSON con manifest/kid/key

CREDENZIALI: Tutte le credenziali sensibili vengono lette da variabili d'ambiente.
             Non hardcodare nulla in questo file.

Formati di output supportati:
  - m3u_kodi:     M3U per Kodi + InputStream Adaptive (KODIPROP)
  - m3u_tivimate: M3U per Tivimate/iMPlayer (formato pipe key)
  - m3u_stremio:  JSON per Stremio addon
"""

import json
import base64
import re
import sys
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ============================================================
# CONFIGURAZIONE - TUTTO DA ENV VARS
# ============================================================

# Obbligatorie: il script fallisce se non sono impostate
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

# Canali noti: ID -> nome pulito
# I primi 14 sono nell'API listing (sky@@), gli altri sono risolvibili direttamente
CHANNEL_NAMES = {
    # --- Intrattenimento (dal listing) ---
    "tg24": "Sky TG24",
    "skyuno": "Sky Uno",
    "skyatlantic": "Sky Atlantic",
    "skyserie": "Sky Serie",
    "skycollection": "Sky Collection",
    "skyinvestigation": "Sky Investigation",
    "skyadventure": "Sky Adventure",
    "skycrime": "Sky Crime",
    "comedycentral": "Comedy Central",
    # --- Documentari/Cultura (dal listing) ---
    "skydocumentaries": "Sky Documentaries",
    "skynature": "Sky Nature",
    "historychannel": "History Channel",
    "skyarte": "Sky Arte",
    # --- Musica (dal listing) ---
    "mtv": "MTV",
    # --- Sport ---
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
    # --- Calcio numerato ---
    "skysport251": "Sky Sport 251",
    "skysport252": "Sky Sport 252",
    "skysport253": "Sky Sport 253",
    "skysport254": "Sky Sport 254",
    "skysport255": "Sky Sport 255",
    "skysport256": "Sky Sport 256",
    "skysport257": "Sky Sport 257",
    "skysport258": "Sky Sport 258",
    "skysport259": "Sky Sport 259",
    # --- Cinema ---
    "skycinemauno": "Sky Cinema Uno",
    "skycinemaaction": "Sky Cinema Action",
    "skycinemacomedy": "Sky Cinema Comedy",
    "skycinemadrama": "Sky Cinema Drama",
    "skycinemafamily": "Sky Cinema Family",
    "skycinemaromance": "Sky Cinema Romance",
    "skycinemasuspense": "Sky Cinema Suspense",
    "skycinemastories": "Sky Cinema Stories",
    # --- Kids ---
    "nickelodeon": "Nickelodeon",
    "deakids": "DeAKids",
    "boomerang": "Boomerang",
    "cartoonnetwork": "Cartoon Network",
}

# Loghi ufficiali Sky/NowTV
LOGO_MAP = {
    "tg24": "https://pixel.disco.nowtv.it/logo/skychb_519_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skyuno": "https://pixel.disco.nowtv.it/logo/skychb_477_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skyatlantic": "https://pixel.disco.nowtv.it/logo/skychb_226_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skyserie": "https://pixel.disco.nowtv.it/logo/skychb_684_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skycollection": "https://pixel.disco.nowtv.it/logo/skychb_431_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skyinvestigation": "https://pixel.disco.nowtv.it/logo/skychb_686_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skyadventure": "https://pixel.disco.nowtv.it/logo/skychb_961_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skycrime": "https://pixel.disco.nowtv.it/logo/skychb_249_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skydocumentaries": "https://pixel.disco.nowtv.it/logo/skychb_877_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skynature": "https://pixel.disco.nowtv.it/logo/skychb_417_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skyarte": "https://pixel.disco.nowtv.it/logo/skychb_986_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "mtv": "https://pixel.disco.nowtv.it/logo/skychb_128_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "comedycentral": "https://pixel.disco.nowtv.it/logo/skychb_312_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "historychannel": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/23/History_Logo.svg/200px-History_Logo.svg.png",
    "skysport24": "https://pixel.disco.nowtv.it/logo/skychb_35skysport24hddark/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skysportuno": "https://pixel.disco.nowtv.it/logo/skychb_23skysportunohddark/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skysportarena": "https://pixel.disco.nowtv.it/logo/skychb_24skysportarenahddark/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skysportf1": "https://pixel.disco.nowtv.it/logo/skychb_478skysportf1hddark/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skysportmotogp": "https://pixel.disco.nowtv.it/logo/skychb_483skysportmotogphddark/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skysportgolf": "https://pixel.disco.nowtv.it/logo/skychb_234skysportdark/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skysporttennis": "https://pixel.disco.nowtv.it/logo/skychb_559skysporttennisdark/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skysportmix": "https://pixel.disco.nowtv.it/logo/skychb_877_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skysportlegend": "https://pixel.disco.nowtv.it/logo/skychb_234skysportdark/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skysportbasket": "https://pixel.disco.nowtv.it/logo/skychb_764skysportnbahddark/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skycinemauno": "https://pixel.disco.nowtv.it/logo/skychb_402_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skycinemaaction": "https://pixel.disco.nowtv.it/logo/skychb_309_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skycinemacomedy": "https://pixel.disco.nowtv.it/logo/skychb_418_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skycinemadrama": "https://pixel.disco.nowtv.it/logo/skychb_979_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skycinemafamily": "https://pixel.disco.nowtv.it/logo/skychb_298_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
    "skycinemaromance": "https://pixel.disco.nowtv.it/logo/skychb_670_lightnow/LOGO_CHANNEL_DARK/4000?language=it-IT&proposition=NOWOTT",
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

# EPG ID mapping
EPG_MAP = {
    "tg24": "skytg24.it", "skyuno": "skyuno.it", "skyatlantic": "skyatlantic.it",
    "skyserie": "skyserie.it", "skycollection": "skycollection.it",
    "skysport24": "skysport24.it", "skysportuno": "skysport1.it",
    "skysportarena": "skysportarena.it", "skysportf1": "skysportf1.it",
    "skysportmotogp": "skysportmotogp.it", "skysportbasket": "skysportnba.it",
    "skysport251": "skysport251.it", "skysport252": "skysport252.it",
    "skysport253": "skysport253.it", "skysport254": "skysport254.it",
    "skysport255": "skysport255.it", "skysport256": "skysport256.it",
    "skysport257": "skysport257.it", "skysport258": "skysport258.it",
    "skysport259": "skysport259.it",
    "skycinemauno": "skycinema1.it", "skycinemaaction": "skycinemaaction.it",
    "skycinemacomedy": "skycinemacomedy.it", "skycinemadrama": "skycinemadrama.it",
    "skycinemafamily": "skycinemafamily.it", "skycinemaromance": "skycinemaromance.it",
}


# ============================================================
# FUNZIONI CORE
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
            result["epg_id"] = EPG_MAP.get(ch_id, "")
            resolved.append(result)
            print(f"  ✅ {name}")
        else:
            failed.append((ch_id, name))
            print(f"  ❌ {name} (non disponibile)")

    print(f"\n[3] Risolti: {len(resolved)}/{len(all_channels)}")
    if failed:
        print(f"    Non disponibili: {', '.join(n for _, n in failed)}")

    return resolved


# ============================================================
# GENERATORI M3U
# ============================================================

def generate_m3u_kodi(channels):
    """
    Genera M3U in formato compatibile con Sparkle TV, Kodi, UHF, etc.
    Usa il formato license_type + license_key (non drm_legacy).
    KODIPROP dopo EXTINF, come nelle liste M3U standard.
    Nessun stream_headers/manifest_headers per massima compatibilità.
    """
    lines = ["#EXTM3U"]

    for ch in channels:
        kid = ch["kid"]
        key = ch["key"]
        manifest = ch["manifest"]
        group = ch.get("group", "Sky")
        logo = ch.get("logo", "")
        epg_id = ch.get("epg_id", "")

        # EXTINF prima delle KODIPROP (formato standard M3U)
        tvg_id = f' tvg-id="{epg_id}"' if epg_id else ""
        tvg_logo = f' tvg-logo="{logo}"' if logo else ""
        group_title = f' group-title="{group}"' if group else ""
        lines.append(f'#EXTINF:-1{tvg_id}{tvg_logo}{group_title},{ch["name"]}')

        # KODIPROP dopo EXTINF, formato classico license_type + license_key
        lines.append(f'#KODIPROP:inputstream.adaptive.license_type=org.w3.clearkey')
        lines.append(f'#KODIPROP:inputstream.adaptive.license_key={kid}:{key}')
        lines.append(manifest)

    return "\n".join(lines) + "\n"


def generate_m3u_pipe(channels):
    """
    Genera M3U con formato pipe per player che supportano
    clearkey via URL: manifest.mpd|key_id=XXX&key=YYY
    Compatibile con: Tivimate, iMPlayer, Televizo, etc.
    """
    lines = ["#EXTM3U"]

    for ch in channels:
        kid = ch["kid"]
        key = ch["key"]
        manifest = ch["manifest"]
        group = ch.get("group", "Sky")
        logo = ch.get("logo", "")
        epg_id = ch.get("epg_id", "")

        tvg_id = f' tvg-id="{epg_id}"' if epg_id else ""
        tvg_logo = f' tvg-logo="{logo}"' if logo else ""
        group_title = f' group-title="{group}"' if group else ""

        lines.append(f'#EXTINF:-1{tvg_id}{tvg_logo}{group_title},{ch["name"]}')
        lines.append(f"{manifest}|key_id={kid}&key={key}")

    return "\n".join(lines) + "\n"


def generate_m3u_stremio(channels):
    """
    Genera JSON nel formato Stremio addon (manifest + streams).
    """
    streams = {}
    for ch in channels:
        streams[ch["id"]] = {
            "name": ch["name"],
            "manifest": ch["manifest"],
            "kid": ch["kid"],
            "key": ch["key"],
            "group": ch.get("group", ""),
            "logo": ch.get("logo", ""),
            "epg_id": ch.get("epg_id", ""),
        }

    return json.dumps({
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "amstaff-mandrakodi",
        "channel_count": len(channels),
        "channels": streams,
    }, indent=2, ensure_ascii=False)


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

    # Genera tutti i formati
    outputs = {
        "playlist_kodi.m3u": generate_m3u_kodi(channels),
        "playlist_tivimate.m3u": generate_m3u_pipe(channels),
        "playlist_stremio.json": generate_m3u_stremio(channels),
    }

    for filename, content in outputs.items():
        filepath = os.path.join(out_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"\n[OUTPUT] {filepath} ({len(content)} bytes)")

    # Genera anche un file di stato
    status = {
        "last_update": datetime.now(timezone.utc).isoformat(),
        "total_channels": len(channels),
        "channels": [
            {
                "id": ch["id"],
                "name": ch["name"],
                "group": ch.get("group", ""),
                "manifest_expires": ch["manifest"].split("/v~1-0-0_e~")[1].split("_")[0] if "/v~1-0-0_e~" in ch["manifest"] else "unknown",
            }
            for ch in channels
        ],
    }
    status_path = os.path.join(out_dir, "status.json")
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)
    print(f"[OUTPUT] {status_path}")

    print(f"\n=== Completato: {len(channels)} canali ===")


if __name__ == "__main__":
    main()
