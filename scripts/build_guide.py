#!/usr/bin/env python3
"""Prépare le guide TV pour la page Programme TV.

Télécharge un guide XMLTV des chaînes françaises, puis écrit des fichiers JSON
légers dans docs/data/ :
  - meta.json          date de mise à jour, jours disponibles
  - channels.json      chaînes (nom, logo, ordre TNT)
  - days/AAAA-MM-JJ.json  programmes du jour, par chaîne

Bibliothèque standard Python uniquement (aucune installation nécessaire).

Usage :
  python scripts/build_guide.py                 # télécharge la source
  python scripts/build_guide.py --file guide.xml # utilise un fichier local
"""
import argparse
import gzip
import io
import json
import os
import re
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta, timezone

# Sources essayées dans l'ordre ; la première qui répond est utilisée.
# On peut les remplacer avec la variable d'environnement SOURCE_URLS
# (adresses séparées par des espaces).
DEFAULT_SOURCES = [
    "https://xmltvfr.fr/xmltv/xmltv.zip",
    "https://xmltvfr.fr/xmltv/xmltv.xml.gz",
    "https://xmltvfr.fr/xmltv/xmltv.xml",
    "https://xmltvfr.fr/xmltv/xmltv_tnt.zip",
    "https://xmltvfr.fr/xmltv/xmltv_tnt.xml",
]

DAYS_AHEAD = 8          # aujourd'hui + 7 jours
DESC_MAX = 500          # longueur max d'un résumé (caractères)
# Chaînes retenues : identifiants XMLTV se terminant par ce suffixe (chaînes françaises).
KEEP_SUFFIX = os.environ.get("KEEP_SUFFIX", ".fr")

# Chaînes de la TNT gratuite, dans l'ordre d'affichage.
# Chaque entrée : liste de variantes de nom (normalisées, voir norm()).
TNT = [
    ["tf1"],
    ["france2"],
    ["france3"],
    ["canalplus", "canal"],
    ["france5"],
    ["m6"],
    ["arte"],
    ["lcp", "lcpan", "lcpassembleenationale", "lcppublicsenat"],
    ["publicsenat"],
    ["france4"],
    ["w9"],
    ["tmc"],
    ["tfx"],
    ["gulli"],
    ["bfmtv", "bfm"],
    ["cnews"],
    ["lci"],
    ["franceinfo", "franceinfotv", "franceinfo27"],
    ["cstar"],
    ["t18"],
    ["novo19"],
    ["tf1seriesfilms"],
    ["lequipe", "lequipetv", "lequipe21", "chainelequipe"],
    ["6ter"],
    ["rmcstory"],
    ["rmcdecouverte"],
    ["cherie25"],
]
TNT_INDEX = {v: i for i, variants in enumerate(TNT) for v in variants}


def norm(s):
    """Nom simplifié pour comparer : minuscules, sans accents ni ponctuation."""
    s = (s or "").replace("+", "plus")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"\.(fr|tv|com)$", "", s.strip())
    s = re.sub(r"[^a-z0-9]", "", s)
    return re.sub(r"(hd|fhd|uhd|4k)$", "", s)


def tnt_rank(cid, name):
    for key in (norm(name), norm(cid)):
        if key in TNT_INDEX:
            return TNT_INDEX[key]
    return None


def parse_time(s):
    """'20261109203000 +0100' -> secondes epoch (UTC)."""
    s = (s or "").strip()
    m = re.match(r"(\d{14})\s*([+-]\d{4})?", s)
    if not m:
        return None
    dt = datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    off = m.group(2) or "+0000"
    sign = 1 if off[0] == "+" else -1
    delta = timedelta(hours=int(off[1:3]), minutes=int(off[3:5])) * sign
    return int((dt - delta).replace(tzinfo=timezone.utc).timestamp())


def fetch(urls):
    last = None
    for url in urls:
        try:
            print(f"Téléchargement : {url}", flush=True)
            req = urllib.request.Request(url, headers={"User-Agent": "programme-tv-guide/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            if len(data) < 1000:
                raise ValueError(f"réponse trop courte ({len(data)} octets)")
            print(f"  reçu {len(data)/1e6:.1f} Mo", flush=True)
            return url, unpack(data)
        except Exception as e:  # on essaie la source suivante
            print(f"  échec : {e}", flush=True)
            last = e
    raise SystemExit(f"Aucune source n'a répondu (dernière erreur : {last})")


def unpack(data):
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".xml")] or z.namelist()
            return z.read(names[0])
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    return data


def text(el, tag):
    """Premier texte d'une balise, en préférant la version française."""
    best = None
    for child in el.findall(tag):
        if child.text and child.text.strip():
            if child.get("lang", "fr").startswith("fr"):
                return child.text.strip()
            best = best or child.text.strip()
    return best


def episode(el):
    for ep in el.findall("episode-num"):
        if ep.get("system") == "onscreen" and ep.text:
            return ep.text.strip()
    for ep in el.findall("episode-num"):
        if ep.get("system") == "xmltv_ns" and ep.text:
            parts = (ep.text.split(".") + ["", ""])[:2]
            try:
                s = int(parts[0].split("/")[0]) + 1 if parts[0].strip() else None
                e = int(parts[1].split("/")[0]) + 1 if parts[1].strip() else None
            except ValueError:
                return None
            if s and e:
                return f"S{s:02d}E{e:02d}"
            if e:
                return f"Épisode {e}"
    return None


def build(xml_bytes, out_dir, source):
    now = datetime.now(timezone.utc)
    today = now.date()
    day_list = [(today + timedelta(days=i)).isoformat() for i in range(DAYS_AHEAD)]
    day_bounds = {}
    for d in day_list:
        start = int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp())
        day_bounds[d] = (start, start + 86400)

    channels = {}
    order = []
    days = {d: {} for d in day_list}
    count = 0

    for _, el in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
        if el.tag == "channel":
            cid = el.get("id")
            name = text(el, "display-name") or cid
            icon = el.find("icon")
            channels[cid] = {
                "id": cid,
                "name": name,
                "logo": icon.get("src") if icon is not None else None,
                "tnt": tnt_rank(cid, name),
            }
            order.append(cid)
            el.clear()
        elif el.tag == "programme":
            cid = el.get("channel")
            s, e = parse_time(el.get("start")), parse_time(el.get("stop"))
            if cid and s and (not KEEP_SUFFIX or cid.endswith(KEEP_SUFFIX)):
                e = e or s + 1800
                title = text(el, "title") or "Programme"
                desc = text(el, "desc") or ""
                if len(desc) > DESC_MAX:
                    desc = desc[:DESC_MAX].rsplit(" ", 1)[0] + "…"
                icon = el.find("icon")
                rating = el.find("rating/value")
                item = [
                    s, e, title,
                    text(el, "sub-title") or "",
                    text(el, "category") or "",
                    desc,
                    icon.get("src") if icon is not None else "",
                    episode(el) or "",
                    (rating.text or "").strip() if rating is not None else "",
                ]
                for d, (ds, de) in day_bounds.items():
                    if s < de and e > ds:
                        days[d].setdefault(cid, []).append(item)
                        count += 1
            el.clear()

    # Chaînes sans aucun programme sur la période : on les retire.
    active = set()
    for d in days.values():
        active.update(d.keys())
    chan_list = [channels[c] for c in order if c in active and c in channels]
    # Chaînes citées dans les programmes mais pas déclarées
    for c in sorted(active - set(channels)):
        chan_list.append({"id": c, "name": c.split(".")[0], "logo": None, "tnt": tnt_rank(c, c)})
    chan_list.sort(key=lambda c: (c["tnt"] is None, c["tnt"] or 0, norm(c["name"])))
    # Un seul exemplaire par rang TNT (le premier trouvé)
    seen = set()
    for c in chan_list:
        if c["tnt"] is not None:
            if c["tnt"] in seen:
                c["tnt"] = None
            seen.add(c["tnt"])

    os.makedirs(os.path.join(out_dir, "days"), exist_ok=True)
    for name in os.listdir(os.path.join(out_dir, "days")):
        if name.endswith(".json") and name.split(".")[0] not in day_list:
            os.remove(os.path.join(out_dir, "days", name))

    available = []
    for d, progs in days.items():
        if not progs:
            continue
        light, details = {}, {}
        for cid, lst in progs.items():
            lst.sort(key=lambda p: p[0])
            # Fichier principal : sans résumé ni image (chargés à la demande)
            light[cid] = [[p[0], p[1], p[2], p[3], p[4], "", "", p[7], p[8]] for p in lst]
            details[cid] = [[p[5], p[6]] for p in lst]
        with open(os.path.join(out_dir, "days", f"{d}.json"), "w", encoding="utf-8") as f:
            json.dump({"date": d, "progs": light}, f, ensure_ascii=False, separators=(",", ":"))
        with open(os.path.join(out_dir, "days", f"{d}.details.json"), "w", encoding="utf-8") as f:
            json.dump({"date": d, "details": details}, f, ensure_ascii=False, separators=(",", ":"))
        available.append(d)

    with open(os.path.join(out_dir, "channels.json"), "w", encoding="utf-8") as f:
        json.dump(chan_list, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({
            "generated": int(now.timestamp()),
            "source": source,
            "days": available,
            "channels": len(chan_list),
        }, f, ensure_ascii=False)

    print(f"{len(chan_list)} chaînes, {count} programmes, jours : {', '.join(available)}")
    if not available:
        raise SystemExit("Le guide ne contient aucun programme pour les jours à venir.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="fichier XMLTV local (.xml, .gz ou .zip)")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "docs", "data"))
    args = ap.parse_args()
    if args.file:
        with open(args.file, "rb") as f:
            source, xml = args.file, unpack(f.read())
    else:
        urls = os.environ.get("SOURCE_URLS", "").split() or DEFAULT_SOURCES
        source, xml = fetch(urls)
    build(xml, os.path.abspath(args.out), source)


if __name__ == "__main__":
    main()
