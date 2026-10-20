#!/usr/bin/env python3
"""Provisionamento e reparo determinístico das mídias da apresentação.

Comandos:
  prepare [--refresh-lock]   adquire e trava (lock) as mídias originais
  repair                     restaura mídias travadas sem alterar conteúdo

O lock vive em ``apresentacao/media/manifest.json``. Nada aqui atualiza
hashes silenciosamente: ``prepare`` só grava hashes depois de validar o
conteúdo adquirido, e ``repair`` nunca sobrescreve arquivo íntegro cujo
hash divergiu do lock (possível edição intencional).
"""

from __future__ import annotations

import argparse
import base64
import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parent.parent
PRES = REPO_ROOT / "apresentacao"
MEDIA_DIR = PRES / "media"
MANIFEST_PATH = MEDIA_DIR / "manifest.json"
MANIFEST_REL = "media/manifest.json"
BUILD_DIR = PRES / ".media-build"
BACKUP_DIR = BUILD_DIR / "media-backup"
QUARANTINE_DIR = BUILD_DIR / "quarantine"

USER_AGENT = "tutorial_tidymodels-media/1.0 (+https://github.com/prdm0/tutorial_tidymodels)"
HTTP_TIMEOUT = 30
MAX_ATTEMPTS = 3
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER = 30

KATEX_VERSION = "0.19.0"
KATEX_BASE = f"https://cdn.jsdelivr.net/npm/katex@{KATEX_VERSION}/dist/"
KATEX_DIR = f"media/vendor/katex-{KATEX_VERSION}"

OSM_BBOX = (-34.8502, -7.1434, -34.8422, -7.1374)  # west, south, east, north
MAP_VIEW_BBOX = (-34.8496, -7.1420, -34.8430, -7.1387)  # recorte do SVG, dentro de OSM_BBOX
OSM_URL = (
    "https://api.openstreetmap.org/api/0.6/map.json?bbox="
    f"{OSM_BBOX[0]},{OSM_BBOX[1]},{OSM_BBOX[2]},{OSM_BBOX[3]}"
)
OSM_JSON_REL = "media/maps/ufpb.osm.json"
OSM_MAP_REL = "media/maps/ufpb.map.json"
DEPT_WAY_ID = 194940322
MARKER_LON = -34.846199
MARKER_LAT = -7.140400
MAP_LABEL = "Departamento de Estatística — UFPB"
MAP_SUBLABEL = "Prédio “Bolo de Noiva”"
MAP_ZOOM = (16, 19)
MAP_REFERENCES = (
    (194940317, "CCEN"),
    (494426486, "Central de Aulas"),
    (421702887, "Biblioteca CCEN"),
)

VIDEO_URL = "https://www.youtube.com/watch?v=Zt_Fr7YbU1c"
VIDEO_REL = "media/videos/cnn-mask.mp4"
VIDEO_TITLE = "Rede Neural Convolucional: Detectando uso de máscara"

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".webm", ".mov", ".m4v"}
FONT_EXT = {".ttf", ".otf", ".woff", ".woff2"}


# --------------------------------------------------------------------------
# infraestrutura
# --------------------------------------------------------------------------
def log(msg: str) -> None:
    print(f"[media] {msg}", file=sys.stderr, flush=True)


class MediaError(RuntimeError):
    """Falha que deve interromper o provisionamento/reparo."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_relpath(rel: str) -> str:
    """Normaliza e rejeita caminhos perigosos (absolutos, `..`, raiz externa)."""
    if not rel or rel.startswith(("/", "\\")) or ":" in rel.split("/")[0][1:2]:
        raise MediaError(f"caminho inválido (absoluto): {rel!r}")
    if Path(rel).is_absolute():
        raise MediaError(f"caminho inválido (absoluto): {rel!r}")
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise MediaError(f"caminho inválido (escapa da raiz): {rel!r}")
    return "/".join(parts)


def resolve_in_pres(rel: str) -> Path:
    rel = safe_relpath(rel)
    target = PRES / rel
    base = PRES.resolve()
    probe = target
    while True:
        if probe.is_symlink():
            if not probe.resolve().is_relative_to(base):
                raise MediaError(f"symlink aponta para fora da árvore: {rel}")
        if probe == PRES or probe.parent == probe:
            break
        probe = probe.parent
    return target


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_get(url: str, *, accept: str | None = None) -> tuple[bytes, str]:
    """GET com retries limitados. Devolve (bytes, content_type)."""
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    last: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                status = getattr(resp, "status", resp.getcode())
                if status != 200:
                    raise MediaError(f"HTTP {status} em {url}")
                return resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in RETRY_STATUS and attempt < MAX_ATTEMPTS:
                delay = min(MAX_RETRY_AFTER, _retry_after(exc) or 2 * attempt)
                log(f"HTTP {exc.code} em {url}; nova tentativa em {delay}s")
                time.sleep(delay)
                continue
            raise MediaError(f"HTTP {exc.code} em {url}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt < MAX_ATTEMPTS:
                log(f"falha de rede em {url} ({exc}); nova tentativa")
                time.sleep(2 * attempt)
                continue
            raise MediaError(f"falha de rede em {url}: {exc}") from exc
    raise MediaError(f"falha ao baixar {url}: {last}")


def _retry_after(exc: urllib.error.HTTPError) -> int | None:
    raw = exc.headers.get("Retry-After") if exc.headers else None
    if not raw:
        return None
    try:
        return max(0, int(raw.strip()))
    except ValueError:
        return None


def run(cmd: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(cmd), capture_output=True, text=True, check=False, **kwargs
    )


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise MediaError(f"ferramenta ausente no PATH: {name}")
    return path


# --------------------------------------------------------------------------
# validação de conteúdo
# --------------------------------------------------------------------------
def validate_image(path: Path) -> None:
    from PIL import Image

    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        im.load()
        if im.width <= 0 or im.height <= 0:
            raise MediaError(f"{path.name}: dimensões inválidas")
        frames = getattr(im, "n_frames", 1)
        if frames > 1:
            for idx in range(frames):
                im.seek(idx)
                im.load()


def validate_font_bytes(path: Path) -> None:
    data = path.read_bytes()
    if len(data) < 1024:
        raise MediaError(f"{path.name}: fonte truncada ({len(data)} bytes)")
    sig = data[:4]
    if sig not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf", b"wOFF", b"wOF2"):
        raise MediaError(f"{path.name}: assinatura de fonte desconhecida {sig!r}")


def validate_video(path: Path, *, expect_duration: float | None = None) -> dict:
    ffmpeg = require_tool("ffmpeg")
    ffprobe = require_tool("ffprobe")
    dec = run([ffmpeg, "-v", "error", "-xerror", "-err_detect", "explode",
               "-i", str(path), "-f", "null", "-"])
    if dec.returncode != 0 or dec.stderr.strip():
        raise MediaError(
            f"{path.name}: decodificação completa falhou "
            f"(exit {dec.returncode}): {dec.stderr.strip()[:400]}"
        )
    pro = run([ffprobe, "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", str(path)])
    if pro.returncode != 0:
        raise MediaError(f"{path.name}: ffprobe falhou: {pro.stderr.strip()[:400]}")
    info = json.loads(pro.stdout)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError(f"{path.name}: sem fluxo de vídeo")
    if video.get("codec_name") != "h264":
        raise MediaError(f"{path.name}: codec {video.get('codec_name')} != h264")
    if video.get("pix_fmt") != "yuv420p":
        raise MediaError(f"{path.name}: pix_fmt {video.get('pix_fmt')} != yuv420p")
    if not video.get("width") or not video.get("height"):
        raise MediaError(f"{path.name}: dimensões nulas")
    duration = float(info.get("format", {}).get("duration", 0.0))
    if duration <= 0:
        raise MediaError(f"{path.name}: duração inválida")
    if expect_duration is not None and abs(duration - expect_duration) > 1.0:
        raise MediaError(
            f"{path.name}: duração {duration:.2f}s incompatível com o "
            f"original ({expect_duration:.2f}s)"
        )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    return {
        "duration": duration,
        "width": video["width"],
        "height": video["height"],
        "audio_codec": audio.get("codec_name") if audio else None,
    }


REMOTE_RE = re.compile(r"""(?:https?:)?//""", re.I)


def validate_svg(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    try:
        ET.fromstring(text)
    except ET.ParseError as exc:
        raise MediaError(f"{path.name}: XML inválido: {exc}") from exc
    for attr in re.findall(r'(?:href|xlink:href|src)\s*=\s*"([^"]*)"', text):
        if REMOTE_RE.match(attr.strip()):
            raise MediaError(f"{path.name}: referência remota {attr!r}")
    for url in re.findall(r"url\(([^)]*)\)", text):
        if REMOTE_RE.match(url.strip().strip("'\"")):
            raise MediaError(f"{path.name}: url() remota em {url!r}")


def validate_json_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_text(path: Path) -> None:
    data = path.read_bytes()
    if not data.strip():
        raise MediaError(f"{path.name}: arquivo vazio")
    data.decode("utf-8")


def looks_like_html(data: bytes) -> bool:
    head = data[:512].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def validate_by_kind(path: Path, kind: str) -> None:
    if kind == "image":
        if path.suffix.lower() == ".svg":
            validate_svg(path)
        else:
            validate_image(path)
    elif kind == "video":
        validate_video(path)
    elif kind == "font":
        validate_font_bytes(path)
    elif kind in ("script", "style", "html", "text"):
        validate_text(path)
    elif kind == "data":
        if path.suffix.lower() == ".json":
            validate_json_file(path)
        else:
            validate_text(path)
    elif kind == "binary":
        if not path.stat().st_size:
            raise MediaError(f"{path.name}: arquivo vazio")
    else:
        raise MediaError(f"kind desconhecido: {kind}")


def kind_for(rel: str) -> str:
    ext = Path(rel).suffix.lower()
    if ext in IMAGE_EXT or ext == ".svg":
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in FONT_EXT:
        return "font"
    if ext == ".js":
        return "script"
    if ext == ".css":
        return "style"
    if ext in (".html", ".htm"):
        return "html"
    if ext in (".json", ".csv", ".txt"):
        return "data"
    return "binary"


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------
@dataclass
class Entry:
    path: str
    kind: str
    sha256: str
    bytes: int
    origin: str
    license: str | None = None
    source_url: str | None = None
    repair: str = "manual"
    captured_at: str | None = None

    def to_json(self) -> dict:
        out = {
            "path": self.path,
            "kind": self.kind,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "origin": self.origin,
            "license": self.license,
            "repair": self.repair,
        }
        if self.source_url:
            out["source_url"] = self.source_url
        if self.captured_at:
            out["captured_at"] = self.captured_at
        return out


def load_manifest() -> dict[str, Entry]:
    if not MANIFEST_PATH.exists():
        return {}
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if raw.get("version") != 1:
        raise MediaError(f"manifest versão inesperada: {raw.get('version')!r}")
    out: dict[str, Entry] = {}
    for item in raw.get("assets", []):
        entry = Entry(
            path=safe_relpath(item["path"]),
            kind=item["kind"],
            sha256=item["sha256"],
            bytes=int(item["bytes"]),
            origin=item.get("origin", ""),
            license=item.get("license"),
            source_url=item.get("source_url"),
            repair=item.get("repair", "manual"),
            captured_at=item.get("captured_at"),
        )
        out[entry.path] = entry
    return out


def save_manifest(entries: dict[str, Entry]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "assets": [entries[k].to_json() for k in sorted(entries)],
    }
    MANIFEST_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def quarantine(rel: str) -> Path | None:
    """Preserva o arquivo atual antes de substituí-lo."""
    src = resolve_in_pres(rel)
    if not src.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = QUARANTINE_DIR / stamp / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def backup(rel: str) -> None:
    src = resolve_in_pres(rel)
    dest = BACKUP_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def promote(tmp: Path, rel: str, *, kind: str) -> None:
    """Valida o temporário, põe o antigo em quarentena e instala o novo."""
    validate_by_kind(tmp, kind)
    dest = resolve_in_pres(rel)
    if dest.exists() and dest.is_dir():
        raise MediaError(f"destino é diretório: {rel}")
    quarantine(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tmp, dest)
    backup(rel)


# --------------------------------------------------------------------------
# aquisições
# --------------------------------------------------------------------------
@dataclass
class Acquired:
    rel: str
    data: bytes
    kind: str
    origin: str
    license: str | None
    repair: str
    source_url: str | None = None
    captured_at: str | None = None


def acquire_simple_downloads() -> list[Acquired]:
    specs = [
        (
            "media/images/foto_aerea_ufpb.jpeg",
            "https://raw.githubusercontent.com/prdm0/imagens/main/foto_aerea_ufpb.jpeg",
            "Foto aérea da UFPB publicada pelo autor em github.com/prdm0/imagens",
            None,
        ),
        (
            "media/images/flow-texture.jpg",
            "https://images.unsplash.com/photo-1532153975070-2e9ab71f1b14?ixlib=rb-1.2.1&ixid=MnwxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8&auto=format&fit=crop&w=1740&q=80",
            "Textura usada em .flow, originalmente carregada do Unsplash",
            "Unsplash License",
        ),
        (
            "media/fonts/FiraCode.ttf",
            "https://raw.githubusercontent.com/google/fonts/main/ofl/firacode/FiraCode%5Bwght%5D.ttf",
            "Google Fonts — ofl/firacode/FiraCode[wght].ttf",
            "OFL-1.1",
        ),
        (
            "media/fonts/OFL.txt",
            "https://raw.githubusercontent.com/google/fonts/main/ofl/firacode/OFL.txt",
            "Google Fonts — ofl/firacode/OFL.txt",
            "OFL-1.1",
        ),
    ]
    out: list[Acquired] = []
    for rel, url, origin, lic in specs:
        log(f"baixando {rel}")
        data, ctype = http_get(url)
        kind = kind_for(rel)
        if kind == "image" and looks_like_html(data):
            raise MediaError(f"{rel}: servidor devolveu HTML em vez de imagem")
        if kind == "image" and "html" in ctype.lower():
            raise MediaError(f"{rel}: Content-Type {ctype!r} não é imagem")
        out.append(Acquired(rel, data, kind, origin, lic, "download", url))
    return out


def acquire_katex() -> list[Acquired]:
    out: list[Acquired] = []
    files = [("katex.min.js", "script"), ("katex.min.css", "style")]
    css_text = ""
    for name, kind in files:
        url = KATEX_BASE + name
        log(f"baixando {name}")
        data, _ = http_get(url)
        if looks_like_html(data):
            raise MediaError(f"{name}: HTML em vez de asset")
        if name.endswith(".css"):
            css_text = data.decode("utf-8")
        out.append(
            Acquired(
                f"{KATEX_DIR}/{name}", data, kind,
                f"cdn.jsdelivr.net/npm/katex@{KATEX_VERSION}", "MIT", "download", url,
            )
        )
    lic_url = f"https://cdn.jsdelivr.net/npm/katex@{KATEX_VERSION}/LICENSE"
    data, _ = http_get(lic_url)
    out.append(
        Acquired(f"{KATEX_DIR}/LICENSE", data, "text",
                 f"katex@{KATEX_VERSION}", "MIT", "download", lic_url)
    )
    refs = sorted({m.group(1) for m in re.finditer(r"url\(([^)]+)\)", css_text)})
    fonts = []
    for ref in refs:
        ref = ref.strip().strip("'\"")
        if ref.startswith("fonts/"):
            fonts.append(ref)
    fonts = sorted(set(fonts))
    if not fonts:
        raise MediaError("katex.min.css sem referências de fontes")
    for ref in fonts:
        url = KATEX_BASE + ref
        log(f"baixando katex {ref}")
        data, _ = http_get(url)
        if looks_like_html(data):
            raise MediaError(f"{ref}: HTML em vez de fonte")
        out.append(
            Acquired(f"{KATEX_DIR}/{ref}", data, "font",
                     f"katex@{KATEX_VERSION} dist/{ref}", "MIT", "download", url)
        )
    return out


def acquire_teresina_banner() -> list[Acquired]:
    """Recupera a foto já embutida no relatório local (sem baixar outra)."""
    report = PRES / "assets" / "modelo_teresina.html"
    if not report.exists():
        raise MediaError("assets/modelo_teresina.html ausente")
    text = report.read_text(encoding="utf-8", errors="strict")
    m = re.search(r'<img[^>]+src="data:image/(jpeg|jpg|png);base64,([A-Za-z0-9+/=\s]+)"',
                  text, re.I)
    if not m:
        raise MediaError("nenhuma imagem data: encontrada no relatório local")
    data = base64.b64decode(re.sub(r"\s+", "", m.group(2)))
    from PIL import Image
    import io

    with Image.open(io.BytesIO(data)) as im:
        im.load()
        if (im.width, im.height) != (1920, 1077):
            raise MediaError(
                f"banner de Teresina com {im.width}x{im.height}, esperado 1920x1077"
            )
    return [
        Acquired(
            "media/images/teresina-banner.jpg", data, "image",
            "bytes já embutidos em assets/modelo_teresina.html (relatório do autor)",
            None, "manual",
        )
    ]


# ------------------------------- mapa -------------------------------------
def acquire_map() -> list[Acquired]:
    log("baixando extração OSM (dados vetoriais, não tiles)")
    raw, ctype = http_get(OSM_URL, accept="application/json")
    if "json" not in ctype.lower():
        raise MediaError(f"OSM devolveu Content-Type {ctype!r}")
    osm = json.loads(raw.decode("utf-8"))
    validate_osm(osm)
    pretty = json.dumps(osm, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    data = pretty.encode("utf-8")
    mapdata = render_map_data(json.loads(pretty))
    return [
        Acquired(OSM_JSON_REL, data, "data",
                 f"api.openstreetmap.org/api/0.6/map.json bbox={OSM_BBOX}",
                 "ODbL-1.0", "download", OSM_URL),
        Acquired(OSM_MAP_REL, mapdata, "data",
                 f"gerado por scripts/media.py a partir de {OSM_JSON_REL}",
                 "ODbL-1.0", "generate-map"),
    ]


def validate_osm(osm: dict) -> None:
    if str(osm.get("version")) != "0.6":
        raise MediaError(f"OSM version inesperada: {osm.get('version')!r}")
    bounds = osm.get("bounds") or {}
    for key in ("minlat", "minlon", "maxlat", "maxlon"):
        if key not in bounds:
            raise MediaError(f"OSM sem bounds.{key}")
    nodes = {e["id"]: e for e in osm.get("elements", []) if e.get("type") == "node"}
    ways = [e for e in osm.get("elements", []) if e.get("type") == "way"]
    if len(nodes) < 100:
        raise MediaError(f"extração OSM com apenas {len(nodes)} nodes")
    if not ways:
        raise MediaError("extração OSM sem ways")
    for way in ways:
        refs = way.get("nodes") or []
        if not refs:
            raise MediaError(f"way {way.get('id')} sem nodes")
        missing = [r for r in refs if r not in nodes]
        if missing and way["id"] == DEPT_WAY_ID:
            raise MediaError(f"way {DEPT_WAY_ID} com nodes ausentes")
    dept = next((w for w in ways if w.get("id") == DEPT_WAY_ID), None)
    if dept is None:
        raise MediaError(f"way {DEPT_WAY_ID} ausente na extração")
    name = (dept.get("tags") or {}).get("name", "")
    if "Física" not in name and "Estat" not in name:
        raise MediaError(f"way {DEPT_WAY_ID} com nome inesperado: {name!r}")


MAP_STYLES: dict[str, dict] = {
    "wood":            {"stroke": False, "fill": True, "fillColor": "#d5e4c8", "fillOpacity": 1, "weight": 0},
    "park":            {"stroke": False, "fill": True, "fillColor": "#e3edda", "fillOpacity": 1, "weight": 0},
    "parking":         {"stroke": True, "color": "#cbc6bc", "weight": 0.8, "opacity": 1, "fill": True, "fillColor": "#e6e3dd", "fillOpacity": 1},
    "building":        {"stroke": True, "color": "#bdb9b0", "weight": 0.8, "opacity": 1, "fill": True, "fillColor": "#dcd9d2", "fillOpacity": 1},
    "road_major_case": {"stroke": True, "color": "#c9c5bc", "weight": 10, "opacity": 1, "fill": False, "lineCap": "round", "lineJoin": "round"},
    "road_major":      {"stroke": True, "color": "#ffffff", "weight": 7, "opacity": 1, "fill": False, "lineCap": "round", "lineJoin": "round"},
    "road_minor_case": {"stroke": True, "color": "#c9c5bc", "weight": 6, "opacity": 1, "fill": False, "lineCap": "round", "lineJoin": "round"},
    "road_minor":      {"stroke": True, "color": "#ffffff", "weight": 4, "opacity": 1, "fill": False, "lineCap": "round", "lineJoin": "round"},
    "path":            {"stroke": True, "color": "#b7aa91", "weight": 2, "opacity": 1, "fill": False, "dashArray": "6,4"},
    "cycleway":        {"stroke": True, "color": "#6c9b96", "weight": 2, "opacity": 1, "fill": False, "dashArray": "8,4"},
    "dept":            {"stroke": True, "color": "#7d3b49", "weight": 1.6, "opacity": 1, "fill": True, "fillColor": "#AD5769", "fillOpacity": 0.85},
}

# o L.geoJson desenha na ordem das features: esta é a ordem de empilhamento
MAP_DRAW_ORDER = (
    "wood", "park", "parking", "building",
    "road_minor_case", "road_major_case", "road_minor", "road_major",
    "path", "cycleway", "dept",
)
MAP_AREA_LAYERS = frozenset({"dept", "wood", "park", "parking", "building"})


def map_layer_of(way: dict) -> str | None:
    """Camada única do way; None quando a feição não entra no mapa."""
    if way.get("id") == DEPT_WAY_ID:
        return "dept"
    tags = way.get("tags") or {}
    if tags.get("building"):
        return "building"
    if tags.get("natural") == "wood" or tags.get("landuse") == "forest":
        return "wood"
    if tags.get("leisure") in ("park", "garden") or tags.get("landuse") == "grass":
        return "park"
    if tags.get("amenity") == "parking":
        return "parking"
    highway = tags.get("highway")
    if highway in ("secondary", "tertiary", "residential"):
        return "road_major"
    if highway in ("footway", "track"):
        return "path"
    if highway == "cycleway":
        return "cycleway"
    if highway:
        return "road_minor"
    return None


def render_map_data(osm: dict) -> bytes:
    """Dados do mapa Leaflet (GeoJSON + âncoras) a partir do extrato OSM local."""
    nodes: dict[int, tuple[float, float]] = {}
    for el in osm.get("elements", []):
        if el.get("type") == "node":
            nodes[el["id"]] = (float(el["lon"]), float(el["lat"]))
    ways = sorted(
        (e for e in osm.get("elements", []) if e.get("type") == "way"),
        key=lambda w: w["id"],
    )

    buckets: dict[str, list[dict]] = {name: [] for name in MAP_DRAW_ORDER}
    for way in ways:
        layer = map_layer_of(way)
        if layer is None:
            continue
        refs = list(way.get("nodes") or [])
        # geometria incompleta nunca é fabricada: o way inteiro é descartado
        if len(refs) < 2 or any(ref not in nodes for ref in refs):
            continue
        pts = [[round(nodes[ref][0], 6), round(nodes[ref][1], 6)] for ref in refs]
        closed = len(refs) >= 4 and refs[0] == refs[-1]
        name = (way.get("tags") or {}).get("name")
        if layer in MAP_AREA_LAYERS:
            if not closed:
                continue
            geometry = {"type": "Polygon", "coordinates": [pts]}
            targets = [(layer, f"way/{way['id']}")]
        else:
            geometry = {"type": "LineString", "coordinates": pts}
            targets = [(layer, f"way/{way['id']}")]
            if layer in ("road_major", "road_minor"):
                targets.append((f"{layer}_case", f"way/{way['id']}/case"))
        for lyr, fid in targets:
            props: dict = {"layer": lyr, "style": MAP_STYLES[lyr]}
            if not lyr.endswith("_case"):
                if name:
                    props["name"] = name
                if lyr == "dept":
                    props["popup"] = f"<strong>{MAP_LABEL}</strong><br>{MAP_SUBLABEL}"
                elif name:
                    props["popup"] = name
            buckets[lyr].append({
                "type": "Feature",
                "id": fid,
                "properties": props,
                "geometry": geometry,
            })

    features = [feat for lyr in MAP_DRAW_ORDER for feat in buckets[lyr]]

    by_id = {way["id"]: way for way in ways}
    labels: list[dict] = []
    for way_id, text in MAP_REFERENCES:
        way = by_id.get(way_id)
        if way is None:
            continue
        refs = list(way.get("nodes") or [])
        if not refs or any(ref not in nodes for ref in refs):
            continue
        uniq = refs[:-1] if len(refs) > 1 and refs[0] == refs[-1] else refs
        pts_ref = [nodes[ref] for ref in uniq]
        if not pts_ref:
            continue
        labels.append({
            "lng": round(sum(p[0] for p in pts_ref) / len(pts_ref), 6),
            "lat": round(sum(p[1] for p in pts_ref) / len(pts_ref), 6),
            "text": text,
        })

    west, south, east, north = MAP_VIEW_BBOX
    bwest, bsouth, beast, bnorth = OSM_BBOX
    payload = {
        "version": 1,
        "view": {"west": west, "south": south, "east": east, "north": north},
        "bounds": {
            "west": bwest, "south": bsouth, "east": beast, "north": bnorth,
        },
        "zoom": {"min": MAP_ZOOM[0], "max": MAP_ZOOM[1]},
        "marker": {
            "lng": MARKER_LON, "lat": MARKER_LAT,
            "title": MAP_LABEL, "subtitle": MAP_SUBLABEL,
        },
        "labels": labels,
        "geojson": json.dumps(
            {"type": "FeatureCollection", "features": features},
            ensure_ascii=False, separators=(",", ":"),
        ),
    }
    return (
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
    ).encode("utf-8")


# ------------------------------- vídeo ------------------------------------
def acquire_video() -> list[Acquired]:
    ytdlp = require_tool("yt-dlp")
    ffmpeg = require_tool("ffmpeg")
    with tempfile.TemporaryDirectory(prefix="media-video-") as tmpd:
        tmp = Path(tmpd)
        original = tmp / "cnn-mask-original.mp4"
        log("baixando vídeo original do YouTube")
        res = run([
            ytdlp, "--no-playlist", "--no-cache-dir",
            "-f", "bestvideo[ext=mp4][vcodec^=avc1][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]",
            "--merge-output-format", "mp4",
            "-o", str(original), VIDEO_URL,
        ])
        if res.returncode != 0 or not original.exists():
            raise MediaError(
                "yt-dlp falhou ao obter o vídeo original: "
                + (res.stderr.strip()[-600:] or "sem saída")
            )
        src_info = validate_video(original)
        out = tmp / "cnn-mask.mp4"
        log("transcodificando para MP4 H.264/AAC faststart")
        res = run([
            ffmpeg, "-y", "-i", str(original), "-c:v", "libx264", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(out),
        ])
        if res.returncode != 0 or not out.exists():
            raise MediaError(f"ffmpeg falhou: {res.stderr.strip()[-600:]}")
        info = validate_video(out, expect_duration=src_info["duration"])
        if src_info["audio_codec"] and not info["audio_codec"]:
            raise MediaError("áudio do original não foi preservado")
        log(
            f"vídeo validado: {info['width']}x{info['height']}, "
            f"{info['duration']:.2f}s, áudio={info['audio_codec']}"
        )
        return [
            Acquired(
                VIDEO_REL, out.read_bytes(), "video",
                f"{VIDEO_TITLE} — canal Prof. Pedro Rafael ({VIDEO_URL})",
                None, "manual", VIDEO_URL,
            )
        ]


# ----------------------------- capturas -----------------------------------
@dataclass(frozen=True)
class PreviewSpec:
    rel: str
    url: str
    height: int
    markers: tuple[str, ...]
    app: bool = False
    title: str = ""


PREVIEWS: tuple[PreviewSpec, ...] = (
    PreviewSpec("media/previews/future.png", "https://future.futureverse.org/", 700,
                ("Unified Parallel and Distributed Processing",), False, "future"),
    PreviewSpec("media/previews/rsample.png",
                "https://rsample.tidymodels.org/reference/index.html", 700,
                ("Package index", "initial_split"), False, "rsample"),
    PreviewSpec("media/previews/recipes-find.png",
                "https://www.tidymodels.org/find/recipes/", 700,
                ("Search recipe steps", "step_intercept"), False, "recipes (busca de steps)"),
    PreviewSpec("media/previews/recipes-reference.png",
                "https://recipes.tidymodels.org/reference/index.html", 700,
                ("Package index", "recipe("), False, "recipes (referência)"),
    PreviewSpec("media/previews/parsnip-find.png",
                "https://www.tidymodels.org/find/parsnip/", 800,
                ("Search parsnip models", "engine:"), False, "parsnip (busca de modelos)"),
    PreviewSpec("media/previews/workflows.png",
                "https://workflows.tidymodels.org/reference/index.html", 800,
                ("Package index", "add_recipe"), False, "workflows"),
    PreviewSpec("media/previews/tune.png",
                "https://tune.tidymodels.org/reference/index.html", 800,
                ("Package index", "tune_grid"), False, "tune"),
    PreviewSpec("media/previews/app-api.png",
                "https://pedro-rafael.shinyapps.io/app_api/", 500,
                ("Gerar Inputs e Prever", "Nenhuma previsão ainda."), True,
                "aplicação app_api"),
    PreviewSpec("media/previews/app-teresina.png",
                "https://pedro-rafael.shinyapps.io/app_teresina/", 600,
                ("Endereço Completo", "Tipo de Imóvel", "Área Total",
                 "O valor estimado do imóvel será exibido aqui após a consulta."),
                True, "aplicação app_teresina"),
)

BLOCKERS = ("access blocked", "403 forbidden", "404 not found", "captcha",
            "sign in", "application error", "disconnected from server")


def acquire_previews(only: Sequence[str] | None = None) -> list[Acquired]:
    from playwright.sync_api import sync_playwright

    specs = [s for s in PREVIEWS if not only or s.rel in only]
    out: list[Acquired] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for spec in specs:
                out.append(_capture(browser, spec))
        finally:
            browser.close()
    return out


def _capture(browser, spec: PreviewSpec) -> Acquired:
    log(f"capturando {spec.url}")
    context = browser.new_context(
        viewport={"width": 1600, "height": spec.height},
        device_scale_factor=1,
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        resp = page.goto(spec.url, wait_until="load", timeout=90_000)
        if resp is None:
            raise MediaError(f"{spec.url}: sem resposta HTTP")
        if resp.status >= 400:
            raise MediaError(f"{spec.url}: HTTP {resp.status}")
        page.wait_for_function("document.fonts.status === 'loaded'", timeout=90_000)
        deadline = time.time() + 90
        last = ""
        while time.time() < deadline:
            text = page.evaluate("document.body ? document.body.innerText : ''")
            last = text
            lowered = text.lower()
            bad = [b for b in BLOCKERS if b in lowered]
            if bad:
                raise MediaError(f"{spec.url}: conteúdo bloqueado ({bad[0]})")
            missing = [m for m in spec.markers if m not in text]
            ready = not missing
            app_state: dict | None = None
            if ready and spec.app:
                app_state = page.evaluate(
                    "() => { const s = window.Shiny, a = s && s.shinyapp;"
                    " return {err: document.querySelectorAll('.shiny-output-error').length,"
                    " overlay: !!document.getElementById('shiny-disconnected-overlay'),"
                    " busy: document.documentElement.classList.contains('shiny-busy'),"
                    " connected: !!(a && (a.isConnected ? a.isConnected() :"
                    " (a.$socket && a.$socket.readyState === 1)))}; }"
                )
                ready = (
                    app_state["err"] == 0 and not app_state["overlay"]
                    and not app_state["busy"] and app_state["connected"]
                )
            if ready:
                page.wait_for_timeout(1500)
                break
            page.wait_for_timeout(500)
        else:
            missing = [m for m in spec.markers if m not in last]
            raise MediaError(
                f"{spec.url}: marcadores de prontidão não observados em 90s "
                f"(faltando: {missing}; estado da app: {app_state})"
            )
        page.evaluate(
            "() => Promise.all(Array.from(document.images)"
            ".filter(i => i.getBoundingClientRect().width > 0)"
            ".map(i => i.decode().catch(() => null)))"
        )
        if "loading..." in page.evaluate(
            "document.body.innerText.slice(0, 400)"
        ).lower():
            raise MediaError(f"{spec.url}: página ainda em 'Loading...'")
        shot = page.screenshot(type="png")
    finally:
        context.close()
    if errors:
        log(f"avisos JS na página {spec.url}: {errors[:2]}")
    return Acquired(
        spec.rel, shot, "image",
        f"captura local de {spec.url} (Chromium 1600x{spec.height})",
        None, "manual", spec.url, utcnow(),
    )


# --------------------------------------------------------------------------
# inventário dos originais já versionados
# --------------------------------------------------------------------------
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
LOCAL_REF_RE = re.compile(r"(?:imgs|gifs|assets|dados|media)/[\w\-./%\[\]]+")


def referenced_local_media() -> list[str]:
    """Mídias estáticas do repositório efetivamente referenciadas pelo deck."""
    sources = [PRES / "index.qmd", PRES / "style.scss"]
    css = MEDIA_DIR / "media.css"
    if css.exists():
        sources.append(css)
    found: set[str] = set()
    for src in sources:
        if not src.exists():
            continue
        text = COMMENT_RE.sub(" ", src.read_text(encoding="utf-8"))
        for raw in LOCAL_REF_RE.findall(text):
            rel = urllib.parse.unquote(raw.split("#")[0].split("?")[0]).rstrip(".,)\"'")
            if rel.startswith("media/"):
                continue  # travadas pelas aquisições
            path = PRES / rel
            if path.is_file():
                found.add(rel)
    # mídias indiretas obrigatórias
    for extra in ("assets/modelo_teresina.html", "assets/teresina.csv",
                  "dados/teresina.csv"):
        if (PRES / extra).is_file():
            found.add(extra)
    return sorted(found)


def origin_for_repo_file(rel: str) -> str:
    return f"arquivo versionado no repositório ({rel})"


# --------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------
GROUPS: list[tuple[str, tuple[str, ...], Callable[[], list[Acquired]]]] = [
    ("downloads estáticos",
     ("media/images/foto_aerea_ufpb.jpeg", "media/images/flow-texture.jpg",
      "media/fonts/FiraCode.ttf", "media/fonts/OFL.txt"),
     acquire_simple_downloads),
    ("katex", (f"{KATEX_DIR}/katex.min.js", f"{KATEX_DIR}/katex.min.css",
               f"{KATEX_DIR}/LICENSE"), acquire_katex),
    ("banner de Teresina", ("media/images/teresina-banner.jpg",),
     acquire_teresina_banner),
    ("mapa OSM", (OSM_JSON_REL, OSM_MAP_REL), acquire_map),
    ("vídeo", (VIDEO_REL,), acquire_video),
] + [
    (f"captura {spec.title}", (spec.rel,),
     functools.partial(acquire_previews, (spec.rel,)))
    for spec in PREVIEWS
]


def group_state(entries: dict[str, Entry], rels: Sequence[str]) -> str:
    """Classifica um grupo em "locked", "stale" ou "drift"."""
    if not rels:
        return "stale"
    state = "locked"
    for rel in rels:
        entry = entries.get(rel)
        if entry is None:
            return "stale"
        path = resolve_in_pres(rel)
        if not path.exists():
            return "stale"
        if sha256_file(path) == entry.sha256:
            continue
        try:
            validate_by_kind(path, entry.kind)
        except Exception:
            return "stale"
        state = "drift"
    return state


def cmd_prepare(refresh: bool = False) -> int:
    entries = load_manifest()
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    if not refresh:
        divergent: list[str] = []
        for _name, rels, _fn in GROUPS:
            if group_state(entries, rels) == "drift":
                divergent.extend(rels)
        if divergent:
            for rel in divergent:
                log(f"ERRO: {rel} difere do lock mas ainda decodifica; "
                    "use 'prepare --refresh-lock' para atualizar deliberadamente")
            return 1
    for name, rels, fn in GROUPS:
        if not refresh and group_state(entries, rels) == "locked":
            log(f"ok (lock íntegro): {name}")
            continue
        log(f"provisionando: {name}")
        for item in fn():
            rel = safe_relpath(item.rel)
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(rel).suffix) as fh:
                fh.write(item.data)
                tmp = Path(fh.name)
            try:
                promote(tmp, rel, kind=item.kind)
            finally:
                tmp.unlink(missing_ok=True)
            path = resolve_in_pres(rel)
            entries[rel] = Entry(
                path=rel, kind=item.kind, sha256=sha256_file(path),
                bytes=path.stat().st_size, origin=item.origin, license=item.license,
                source_url=item.source_url, repair=item.repair,
                captured_at=item.captured_at,
            )
            log(f"  travado {rel} ({entries[rel].bytes} bytes)")
        save_manifest({k: v for k, v in entries.items() if k != MANIFEST_REL})

    # originais já versionados
    drift: list[str] = []
    for rel in referenced_local_media():
        path = resolve_in_pres(rel)
        digest = sha256_file(path)
        entry = entries.get(rel)
        if entry is None or refresh:
            validate_by_kind(path, kind_for(rel))
            entries[rel] = Entry(
                path=rel, kind=kind_for(rel), sha256=digest,
                bytes=path.stat().st_size, origin=origin_for_repo_file(rel),
                license=None, repair="git",
            )
            backup(rel)
        elif entry.sha256 != digest:
            drift.append(rel)
        else:
            if not (BACKUP_DIR / rel).exists():
                backup(rel)
    entries.pop(MANIFEST_REL, None)
    if drift:
        for rel in drift:
            log(f"ERRO: {rel} difere do lock; use --refresh-lock se a mudança é intencional")
        return 1
    save_manifest(entries)
    log(f"manifest com {len(entries)} originais em {MANIFEST_REL}")
    _browser_checks()
    return 0


def _browser_checks() -> None:
    """Confirma no navegador que a fonte local carrega."""
    from playwright.sync_api import sync_playwright

    font = resolve_in_pres("media/fonts/FiraCode.ttf")
    if not font.exists():
        return
    html = f"""<!doctype html><meta charset="utf-8">
<style>@font-face {{ font-family: "Fira Code"; src: url("{font.as_uri()}") format("truetype"); }}
span {{ font-family: "Fira Code", monospace; }}</style>
<span id="s">tidymodels</span>"""
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as fh:
        fh.write(html)
        tmp = Path(fh.name)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(tmp.as_uri())
            page.evaluate("document.fonts.load('16px \"Fira Code\"')")
            page.wait_for_function("document.fonts.status === 'loaded'", timeout=30_000)
            loaded = page.evaluate("document.fonts.check('16px \"Fira Code\"')")
            browser.close()
        if not loaded:
            raise MediaError("Fira Code não carregou no navegador")
        log("navegador: Fira Code ok")
    finally:
        tmp.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# repair
# --------------------------------------------------------------------------
def git_blob(rel: str) -> bytes | None:
    res = subprocess.run(
        ["git", "show", f"HEAD:apresentacao/{rel}"],
        cwd=REPO_ROOT, capture_output=True, check=False,
    )
    if res.returncode != 0:
        return None
    return res.stdout


def _install_bytes(rel: str, data: bytes, kind: str) -> None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(rel).suffix) as fh:
        fh.write(data)
        tmp = Path(fh.name)
    try:
        promote(tmp, rel, kind=kind)
    finally:
        tmp.unlink(missing_ok=True)


def cmd_repair() -> int:
    entries = load_manifest()
    if not entries:
        log("ERRO: manifest ausente ou vazio; execute 'prepare' primeiro")
        return 1
    problems: list[str] = []
    repaired = 0
    for rel in sorted(entries):
        entry = entries[rel]
        path = resolve_in_pres(rel)
        if path.exists():
            if sha256_file(path) == entry.sha256:
                continue
            try:
                validate_by_kind(path, entry.kind)
                problems.append(
                    f"{rel}: conteúdo local íntegro mas com hash diferente do lock; "
                    "revise o manifest (prepare --refresh-lock) em vez de sobrescrever"
                )
                continue
            except Exception:
                log(f"{rel}: conteúdo corrompido; tentando restaurar")
        else:
            log(f"{rel}: ausente; tentando restaurar")

        restored = False
        for source, data in (("git HEAD", git_blob(rel)),
                             ("backup local", _backup_bytes(rel))):
            if data is not None and sha256_bytes(data) == entry.sha256:
                _install_bytes(rel, data, entry.kind)
                log(f"{rel}: restaurado de {source}")
                restored = True
                break
        if restored:
            repaired += 1
            continue

        if entry.repair == "download" and entry.source_url:
            try:
                data, _ = http_get(entry.source_url)
            except MediaError as exc:
                problems.append(f"{rel}: download falhou ({exc})")
                continue
            if sha256_bytes(data) != entry.sha256:
                problems.append(f"{rel}: download com hash diferente do lock")
                continue
            _install_bytes(rel, data, entry.kind)
            log(f"{rel}: restaurado da origem registrada")
            repaired += 1
            continue
        if entry.repair == "generate-map":
            osm_path = resolve_in_pres(OSM_JSON_REL)
            if not osm_path.exists():
                problems.append(f"{rel}: JSON do mapa ausente; não é possível regenerar")
                continue
            data = render_map_data(json.loads(osm_path.read_text(encoding="utf-8")))
            if sha256_bytes(data) != entry.sha256:
                problems.append(f"{rel}: regeneração não reproduziu o hash travado")
                continue
            _install_bytes(rel, data, entry.kind)
            log(f"{rel}: regenerado a partir do JSON local")
            repaired += 1
            continue
        problems.append(
            f"{rel}: sem fonte verificável (repair={entry.repair}); "
            "é necessário recuperar o original autorizado"
        )

    for p in problems:
        log(f"ERRO: {p}")
    if problems:
        return 1
    log(f"repair ok ({repaired} restaurado(s), {len(entries)} travado(s))")
    return 0


def _backup_bytes(rel: str) -> bytes | None:
    path = BACKUP_DIR / rel
    if path.is_file():
        return path.read_bytes()
    return None


# --------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    prep = sub.add_parser("prepare", help="adquire e trava as mídias originais")
    prep.add_argument("--refresh-lock", action="store_true",
                      help="reconsulta origens e regrava os hashes travados")
    sub.add_parser("repair", help="restaura mídias travadas sem mudar conteúdo")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "prepare":
            return cmd_prepare(refresh=args.refresh_lock)
        return cmd_repair()
    except MediaError as exc:
        log(f"ERRO: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
