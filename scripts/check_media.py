#!/usr/bin/env python3
"""Auditoria das mídias de um site renderizado da apresentação.

    python3 scripts/check_media.py --root <dir-do-site> --source apresentacao \\
        --report <arquivo.json> [--require-receipt]

Nunca corrige nada e nunca atualiza hashes: devolve 0 somente quando todas
as verificações passam. Timeout ou mídia não examinada contam como falha.
"""

from __future__ import annotations

import argparse
import base64
import functools
import http.server
import json
import os
import re
import socketserver
import sys
import threading
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Sequence
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import media as mediamod  # noqa: E402  (helpers compartilhados)

SITE_PREFIX = "/tutorial_tidymodels/"
RECEIPT_NAME = "media-build.json"
REMOTE_RE = re.compile(r"^(?:https?:)?//", re.I)
BROWSERS = ("chromium", "webkit")

MEDIA_ATTRS = {
    "img": ("src", "data-src", "srcset", "data-srcset"),
    "source": ("src", "data-src", "srcset"),
    "video": ("src", "data-src", "poster"),
    "audio": ("src", "data-src"),
    "iframe": ("src", "data-src"),
    "embed": ("src",),
    "object": ("data",),
    "script": ("src",),
    "input": ("src",),
    "track": ("src",),
    "image": ("href", "xlink:href"),
    "use": ("href", "xlink:href"),
}
BACKGROUND_ATTRS = (
    "data-background-image",
    "data-background-video",
    "data-background-iframe",
)
LOCAL_LINK_EXT = {".csv", ".json", ".pdf", ".zip", ".qmd", ".r", ".html", ".txt",
                  ".mp4", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"}


# --------------------------------------------------------------------------
@dataclass
class Report:
    errors: list[dict] = field(default_factory=list)
    resources: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def error(self, where: str, reason: str, **extra) -> None:
        item = {"where": where, "reason": reason}
        item.update(extra)
        self.errors.append(item)
        print(f"[check] ERRO {where}: {reason}", file=sys.stderr, flush=True)

    def note(self, **kw) -> None:
        self.resources.append(kw)


def log(msg: str) -> None:
    print(f"[check] {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# parser HTML (comentários são ignorados por omissão)
# --------------------------------------------------------------------------
class Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, str, str]] = []   # (tag, attr, value)
        self.links: list[str] = []
        self.styles: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        amap = {k.lower(): (v or "") for k, v in attrs}
        for attr in MEDIA_ATTRS.get(tag, ()):
            if amap.get(attr):
                self.refs.append((tag, attr, amap[attr]))
        for attr in BACKGROUND_ATTRS:
            if amap.get(attr):
                self.refs.append((tag, attr, amap[attr]))
        if tag == "link":
            rel = amap.get("rel", "").lower()
            href = amap.get("href", "")
            if href and any(
                k in rel for k in ("stylesheet", "icon", "preload", "prefetch", "manifest")
            ):
                self.refs.append((tag, "href", href))
        if tag == "a" and amap.get("href"):
            self.links.append(amap["href"])
        if amap.get("style"):
            self.styles.append(amap["style"])
        if tag == "style":
            self._in_style = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.styles.append(data)


def split_srcset(value: str) -> list[str]:
    out = []
    for part in value.split(","):
        part = part.strip()
        if part:
            out.append(part.split()[0])
    return out


def css_urls(text: str) -> list[str]:
    """URLs de um bloco CSS via tinycss2 (declarações, @import e @font-face)."""
    import tinycss2

    urls: list[str] = []

    def walk(nodes) -> None:
        for node in nodes or []:
            t = node.type
            if t == "url":
                urls.append(node.value)
            elif t == "function" and node.lower_name == "url":
                for arg in node.arguments:
                    if arg.type == "string":
                        urls.append(arg.value)
            elif t == "function":
                walk(node.arguments)
            elif t in ("[] block", "() block", "{} block"):
                walk(node.content)
            elif t in ("qualified-rule", "at-rule"):
                # `content` é a lista bruta de component values: cobre tanto
                # declarações (@font-face) quanto regras aninhadas (@media).
                walk(node.prelude)
                walk(node.content)
            elif t == "declaration":
                walk(node.value)
    try:
        rules = tinycss2.parse_stylesheet(text, skip_comments=True, skip_whitespace=True)
    except Exception:
        return urls
    walk(rules)
    return urls


def css_decl_urls(text: str) -> list[str]:
    """Para blocos `style="..."` (lista de declarações)."""
    import tinycss2

    urls: list[str] = []
    for decl in tinycss2.parse_blocks_contents(
        tinycss2.parse_component_value_list(text)
    ):
        if decl.type == "declaration":
            for node in decl.value:
                if node.type == "url":
                    urls.append(node.value)
                elif node.type == "function" and node.lower_name == "url":
                    for arg in node.arguments:
                        if arg.type == "string":
                            urls.append(arg.value)
    return urls


# --------------------------------------------------------------------------
# grafo estático
# --------------------------------------------------------------------------
class GraphWalker:
    def __init__(self, root: Path, report: Report) -> None:
        self.root = root.resolve()
        self.report = report
        self.visited: set[Path] = set()
        self.required: set[Path] = set()
        self.remote: list[tuple[str, str]] = []

    # -- resolução ---------------------------------------------------------
    def resolve(self, owner: Path, ref: str) -> Path | None:
        ref = ref.strip()
        if not ref or ref.startswith(("#", "mailto:", "tel:", "javascript:")):
            return None
        clean = ref.split("#")[0].split("?")[0]
        if not clean:
            return None
        clean = urllib.parse.unquote(clean)
        if clean.startswith("/"):
            if clean.startswith(SITE_PREFIX):
                clean = clean[len(SITE_PREFIX):]
            else:
                clean = clean.lstrip("/")
            candidate = self.root / clean
        else:
            candidate = owner.parent / clean
        try:
            resolved = candidate.resolve()
        except OSError:
            return None
        if not str(resolved).startswith(str(self.root)):
            self.report.error(str(owner.relative_to(self.root)),
                              "referência escapa da raiz do site", url=ref)
            return None
        if candidate.is_symlink() or any(
            p.is_symlink() for p in _ancestors(candidate, self.root)
        ):
            if not str(resolved).startswith(str(self.root)):
                self.report.error(str(owner.relative_to(self.root)),
                                  "symlink para fora da raiz", url=ref)
                return None
        return candidate

    def exists_case_sensitive(self, path: Path) -> bool:
        if not path.exists():
            return False
        try:
            return path.name in os.listdir(path.parent)
        except OSError:
            return False

    # -- travessia ---------------------------------------------------------
    def walk_html(self, path: Path, origin: str = "") -> None:
        path = path.resolve()
        if path in self.visited or not path.exists():
            return
        self.visited.add(path)
        rel = _rel(path, self.root)
        text = path.read_text(encoding="utf-8", errors="replace")
        col = Collector()
        col.feed(text)
        for tag, attr, value in col.refs:
            values = split_srcset(value) if "srcset" in attr else [value]
            for raw in values:
                self.handle_ref(path, f"{tag}[{attr}]", raw)
        for block in col.styles:
            urls = css_urls(block) if "{" in block else css_decl_urls(block)
            for url in urls:
                self.handle_ref(path, "style", url)
        for href in col.links:
            if REMOTE_RE.match(href.strip()) or href.strip().startswith("#"):
                continue
            target = self.resolve(path, href)
            if target is None:
                continue
            suffix = target.suffix.lower()
            if suffix in LOCAL_LINK_EXT and not self.exists_case_sensitive(target):
                self.report.error(rel, "link local para arquivo inexistente", url=href)

    def handle_ref(self, owner: Path, where: str, ref: str) -> None:
        ref = ref.strip()
        if not ref:
            return
        rel_owner = _rel(owner, self.root)
        if ref.startswith("data:"):
            self.check_data_uri(rel_owner, where, ref)
            return
        if ref.startswith(("blob:", "about:", "javascript:")):
            return
        if REMOTE_RE.match(ref) or re.match(r"^[a-z]+:", ref, re.I) and not ref.startswith("file:"):
            self.remote.append((rel_owner, ref))
            self.report.error(rel_owner, "recurso obrigatório remoto", url=ref,
                              attribute=where)
            return
        target = self.resolve(owner, ref)
        if target is None:
            return
        if not self.exists_case_sensitive(target):
            self.report.error(rel_owner, "recurso local ausente (ou caixa diferente)",
                              url=ref, attribute=where)
            return
        self.required.add(target.resolve())
        self.report.note(owner=rel_owner, attribute=where, path=_rel(target, self.root))
        suffix = target.suffix.lower()
        if suffix in (".html", ".htm"):
            self.walk_html(target)
        elif suffix == ".css":
            self.walk_css(target)
        elif suffix == ".svg":
            self.walk_svg(target)

    def walk_css(self, path: Path) -> None:
        path = path.resolve()
        if path in self.visited:
            return
        self.visited.add(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        for url in css_urls(text):
            self.handle_ref(path, "css url()", url)

    def walk_svg(self, path: Path) -> None:
        path = path.resolve()
        if path in self.visited:
            return
        self.visited.add(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = _rel(path, self.root)
        try:
            tree = ET.fromstring(text)
        except ET.ParseError as exc:
            self.report.error(rel, f"SVG inválido: {exc}")
            return
        for el in tree.iter():
            for key in ("href", "{http://www.w3.org/1999/xlink}href", "src"):
                if key in el.attrib:
                    self.handle_ref(path, f"svg[{key.split('}')[-1]}]", el.attrib[key])
            style = el.attrib.get("style", "")
            if "url(" in style:
                for url in css_decl_urls(style):
                    self.handle_ref(path, "svg style", url)
        for block in tree.iter("{http://www.w3.org/2000/svg}style"):
            for url in css_urls(block.text or ""):
                self.handle_ref(path, "svg <style>", url)

    def check_data_uri(self, owner: str, where: str, ref: str) -> None:
        head, _, payload = ref.partition(",")
        if ";base64" not in head:
            return
        payload = urllib.parse.unquote(re.sub(r"\s+", "", payload))
        payload += "=" * (-len(payload) % 4)
        try:
            data = base64.b64decode(payload, validate=False)
        except Exception as exc:
            self.report.error(owner, f"data: inválido ({exc})", attribute=where)
            return
        if head.startswith("data:image/") and "svg" not in head:
            import io

            from PIL import Image

            try:
                with Image.open(io.BytesIO(data)) as im:
                    im.verify()
                with Image.open(io.BytesIO(data)) as im:
                    im.load()
            except Exception as exc:
                self.report.error(owner, f"imagem data: não decodifica ({exc})",
                                  attribute=where)


def _ancestors(path: Path, root: Path) -> Iterable[Path]:
    cur = path
    while cur != root and cur.parent != cur:
        yield cur
        cur = cur.parent


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------
# conteúdo dos arquivos publicados
# --------------------------------------------------------------------------
def check_contents(root: Path, source: Path, report: Report,
                   required: set[Path]) -> None:
    entries = {}
    manifest = source / "media" / "manifest.json"
    if not manifest.exists():
        report.error("media/manifest.json", "manifest ausente na fonte")
    else:
        try:
            entries = _load_manifest(manifest)
        except Exception as exc:
            report.error("media/manifest.json", f"manifest ilegível: {exc}")
    # originais da fonte contra o lock
    for rel, entry in sorted(entries.items()):
        src_file = source / rel
        if not src_file.exists():
            report.error(f"apresentacao/{rel}", "original travado ausente na fonte")
            continue
        digest = mediamod.sha256_file(src_file)
        if digest != entry["sha256"]:
            report.error(f"apresentacao/{rel}", "original difere do manifest",
                         expected=entry["sha256"], found=digest)
            continue
        published = root / rel
        if published.exists() and mediamod.sha256_file(published) != digest:
            report.error(rel, "cópia publicada difere do original travado")
    # decodificação real de tudo que o site precisa
    checked = {"images": 0, "videos": 0, "fonts": 0}
    for path in sorted(required):
        suffix = path.suffix.lower()
        rel = _rel(path, root)
        try:
            if suffix in mediamod.IMAGE_EXT:
                mediamod.validate_image(path)
                checked["images"] += 1
            elif suffix == ".svg":
                mediamod.validate_svg(path)
                checked["images"] += 1
            elif suffix in mediamod.VIDEO_EXT:
                mediamod.validate_video(path)
                checked["videos"] += 1
            elif suffix in mediamod.FONT_EXT:
                mediamod.validate_font_bytes(path)
                checked["fonts"] += 1
        except Exception as exc:
            report.error(rel, f"conteúdo inválido: {exc}")
    report.summary["decoded"] = checked


def _load_manifest(path: Path) -> dict[str, dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("version") != 1:
        raise ValueError(f"versão inesperada: {raw.get('version')!r}")
    return {item["path"]: item for item in raw.get("assets", [])}


# --------------------------------------------------------------------------
# recibo de build
# --------------------------------------------------------------------------
def check_receipt(root: Path, repo_root: Path, report: Report) -> None:
    receipt_path = root / RECEIPT_NAME
    if not receipt_path.exists():
        report.error(RECEIPT_NAME, "recibo de build ausente (--require-receipt)")
        return
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except Exception as exc:
        report.error(RECEIPT_NAME, f"recibo ilegível: {exc}")
        return
    if receipt.get("version") != 1:
        report.error(RECEIPT_NAME, f"versão inesperada: {receipt.get('version')!r}")
        return
    inputs = receipt.get("inputs") or {}
    outputs = receipt.get("outputs") or {}
    if not inputs or not outputs:
        report.error(RECEIPT_NAME, "recibo sem inputs/outputs")
        return
    current_inputs = build_input_map(repo_root)
    missing = sorted(set(inputs) - set(current_inputs))
    extra = sorted(set(current_inputs) - set(inputs))
    for rel in missing:
        report.error(rel, "entrada do recibo ausente na árvore atual")
    for rel in extra:
        report.error(rel, "entrada nova não coberta pelo recibo (render desatualizado)")
    for rel in sorted(set(inputs) & set(current_inputs)):
        if inputs[rel] != current_inputs[rel]:
            report.error(rel, "fonte alterada após o build (recibo desatualizado)")
    current_outputs = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != RECEIPT_NAME:
            current_outputs[str(path.relative_to(root))] = mediamod.sha256_file(path)
    for rel in sorted(set(outputs) - set(current_outputs)):
        report.error(rel, "saída do recibo ausente no site")
    for rel in sorted(set(current_outputs) - set(outputs)):
        report.error(rel, "arquivo publicado fora do recibo")
    for rel in sorted(set(outputs) & set(current_outputs)):
        if outputs[rel] != current_outputs[rel]:
            report.error(rel, "saída publicada difere do recibo")
    report.summary["receipt"] = {
        "inputs": len(inputs), "outputs": len(outputs),
        "built_at": receipt.get("built_at"),
    }


INPUT_DIRS = ("_extensions", "imgs", "gifs", "media", "assets", "dados")
INPUT_FILES = ("index.qmd", "_quarto.yml", "style.scss")
SCRIPT_FILES = ("scripts/media.py", "scripts/check_media.py", "scripts/build_deck.py",
                "scripts/requirements-media.txt")
EXCLUDE_PARTS = {".media-build", ".git", ".quarto", "docs", "index_cache",
                 "index_files", "__pycache__", ".ipynb_checkpoints"}


def build_input_map(repo_root: Path) -> dict[str, str]:
    """Impressão digital das fontes do deck, relativa à raiz do repositório."""
    pres = repo_root / "apresentacao"
    out: dict[str, str] = {}

    def add(path: Path) -> None:
        if not path.is_file() or path.is_symlink():
            return
        rel_parts = path.relative_to(repo_root).parts
        if any(part in EXCLUDE_PARTS for part in rel_parts):
            return
        if path.name in (".DS_Store", ".RData", ".Rhistory"):
            return
        if path.suffix.lower() in (".rdb", ".rdx"):
            return
        out[str(path.relative_to(repo_root))] = mediamod.sha256_file(path)

    for name in INPUT_FILES:
        add(pres / name)
    for name in INPUT_DIRS:
        base = pres / name
        if base.is_dir():
            for path in sorted(base.rglob("*")):
                add(path)
    for name in SCRIPT_FILES:
        add(repo_root / name)
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------
# servidor local
# --------------------------------------------------------------------------
class _Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:  # type: ignore[override]
        parsed = urllib.parse.urlparse(path).path
        if parsed.startswith(SITE_PREFIX):
            parsed = parsed[len(SITE_PREFIX):]
        elif parsed == SITE_PREFIX.rstrip("/"):
            parsed = ""
        return super().translate_path("/" + parsed.lstrip("/"))

    def do_GET(self) -> None:  # type: ignore[override]
        """Suporta Range: sem 206 o navegador não consegue buscar no vídeo."""
        rng = self.headers.get("Range", "")
        match = re.match(r"bytes=(\d*)-(\d*)\s*$", rng)
        path = self.translate_path(self.path)
        if not match or not os.path.isfile(path):
            super().do_GET()
            return
        size = os.path.getsize(path)
        first, last = match.group(1), match.group(2)
        if first == "":
            length = int(last or 0)
            start, end = max(0, size - length), size - 1
        else:
            start = int(first)
            end = int(last) if last else size - 1
        end = min(end, size - 1)
        if start > end or start >= size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return
        with open(path, "rb") as fh:
            fh.seek(start)
            data = fh.read(end - start + 1)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self) -> None:  # type: ignore[override]
        if not self.headers.get("Range"):
            self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def log_message(self, *args) -> None:  # silencioso
        pass


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(root: Path) -> tuple[_Server, str]:
    handler = functools.partial(_Handler, directory=str(root))
    httpd = _Server(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[0], httpd.server_address[1]
    return httpd, f"http://{host}:{port}{SITE_PREFIX}"


# --------------------------------------------------------------------------
# verificação no navegador
# --------------------------------------------------------------------------
SLIDE_JS = r"""
async (already) => {
  const done = new Set(already);
  const out = {images: [], backgrounds: [], videos: [], problems: [], iframes: []};
  const slide = window.Reveal ? Reveal.getCurrentSlide() : document.body;
  if (!slide) { out.problems.push('slide atual indisponível'); return out; }
  const bg = window.Reveal && Reveal.getSlideBackground
    ? Reveal.getSlideBackground(slide) : null;
  const roots = [slide];
  if (bg) roots.push(bg);
  const decode = async (url) => {
    if (url.startsWith('data:')) return {ok: true, w: 1, h: 1, cached: false};
    try {
      const img = new Image();
      img.src = url;
      await img.decode();
      return {ok: img.naturalWidth > 0 && img.naturalHeight > 0,
              w: img.naturalWidth, h: img.naturalHeight, cached: false};
    } catch (e) { return {ok: false, error: String(e), cached: false}; }
  };
  const seenHere = new Set();
  for (const root of roots) {
    for (const img of root.querySelectorAll('img')) {
      const src = img.currentSrc || img.src;
      const rec = {src, w: img.naturalWidth, h: img.naturalHeight,
                   complete: img.complete, lazy: img.hasAttribute('data-src')};
      if (!rec.lazy && !done.has(src) && !seenHere.has(src)) {
        seenHere.add(src);
        Object.assign(rec, await decode(src));
      } else {
        rec.ok = true; rec.cached = true;
      }
      out.images.push(rec);
    }
    const els = [root, ...root.querySelectorAll('*')];
    for (const el of els) {
      for (const pseudo of [null, '::before', '::after']) {
        const cs = getComputedStyle(el, pseudo);
        const bi = cs.backgroundImage;
        if (!bi || bi === 'none') continue;
        for (const m of bi.matchAll(/url\((\"|')?([^)"']+)\1?\)/g)) {
          const url = m[2];
          if (seenHere.has(url)) continue;
          seenHere.add(url);
          const rec = {url, element: el.className || el.tagName, pseudo};
          if (done.has(url)) { rec.ok = true; rec.cached = true; }
          else { Object.assign(rec, await decode(url)); }
          out.backgrounds.push(rec);
        }
      }
    }
    for (const v of root.querySelectorAll('video')) {
      out.videos.push({src: v.currentSrc || v.src, w: v.videoWidth, h: v.videoHeight,
                       error: v.error ? v.error.code : null});
    }
    for (const f of root.querySelectorAll('iframe')) {
      out.iframes.push({src: f.getAttribute('src') || f.getAttribute('data-src') || ''});
    }
  }
  return out;
}
"""

VIDEO_JS = r"""
async (sel) => {
  const v = sel ? document.querySelector(sel) : document.querySelector('video');
  if (!v) return {ok: false, error: 'sem elemento <video>'};
  const waitEvent = (name, ms) => new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error('timeout de ' + name)), ms);
    v.addEventListener(name, () => { clearTimeout(t); res(true); }, {once: true});
  });
  const nextFrame = () => new Promise((res) => {
    if (v.requestVideoFrameCallback) {
      const t = setTimeout(() => res(false), 4000);
      v.requestVideoFrameCallback(() => { clearTimeout(t); res(true); });
    } else { setTimeout(() => res(false), 500); }
  });
  const advance = async (from, ms) => {
    const limit = Date.now() + ms;
    while (Date.now() < limit) {
      if (v.currentTime > from + 0.2) return v.currentTime;
      await new Promise((r) => setTimeout(r, 100));
    }
    return v.currentTime;
  };
  try {
    v.muted = true;
    if (v.readyState < 2) {
      v.load();
      await Promise.race([
        waitEvent('loadeddata', 30000),
        waitEvent('canplay', 30000),
      ]);
    }
    if (v.error) return {ok: false, error: 'MediaError ' + v.error.code};
    if (!v.videoWidth || !v.videoHeight) return {ok: false, error: 'dimensões nulas'};
    v.currentTime = 0;
    const playSafely = async () => {
      try { await v.play(); } catch (e) {
        if (!String(e).includes('AbortError')) throw e;
      }
    };
    await playSafely();
    const t0 = v.currentTime;
    const framed = await nextFrame();
    const t1 = await advance(t0, 6000);
    v.pause();
    const seekTo = async (t) => {
      v.currentTime = t;
      await waitEvent('seeked', 20000);
      await playSafely();
      await nextFrame();
      v.pause();
      return v.currentTime;
    };
    const mid = await seekTo(v.duration / 2);
    const near = await seekTo(Math.max(v.duration * 0.9, v.duration - 1.0));
    const q = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : null;
    const frames = q ? q.totalVideoFrames : (v.webkitDecodedFrameCount || null);
    const ok = t1 > t0 + 0.2 && mid > 0 && near > mid
               && (frames === null || frames > 0);
    return {ok, duration: v.duration, w: v.videoWidth, h: v.videoHeight,
            advanced: t1 - t0, mid, near, frames, framed,
            paused: v.paused, error: ok ? null : 'avanço/decodificação insuficiente'};
  } catch (e) { return {ok: false, error: String(e)}; }
}
"""


def browser_pass(root: Path, report: Report, base_url: str | None,
                 shots_dir: Path, *, offline: bool) -> None:
    from playwright.sync_api import sync_playwright

    index = root / "index.html"
    mode = "file://offline" if offline else "http"
    with sync_playwright() as pw:
        for name in BROWSERS:
            btype = getattr(pw, name)
            browser = btype.launch()
            try:
                _run_browser(browser, name, root, index, base_url, report,
                             shots_dir, offline=offline, mode=mode)
            except Exception as exc:
                report.error(f"{name}/{mode}",
                             f"execução no navegador falhou: {exc}".splitlines()[0])
            finally:
                browser.close()


def _run_browser(browser, name: str, root: Path, index: Path, base_url: str | None,
                 report: Report, shots_dir: Path, *, offline: bool, mode: str) -> None:
    label = f"{name}/{mode}"
    log(f"navegador {label}: iniciando")
    # O WebKit não navega para file:// com emulação de offline do contexto;
    # nesse caso o isolamento vem apenas do bloqueio de requisições abaixo,
    # que aborta (e registra) qualquer acesso fora da origem local.
    emulate_offline = offline and name != "webkit"
    context = browser.new_context(
        viewport={"width": 1600, "height": 900},
        service_workers="block",
        offline=emulate_offline,
    )
    allowed_prefix = base_url.rsplit(SITE_PREFIX, 1)[0] if base_url else ""
    blocked: list[str] = []

    def route(route_obj, request):
        url = request.url
        if url.startswith(("data:", "blob:", "about:", "file://")) or (
            allowed_prefix and url.startswith(allowed_prefix)
        ):
            route_obj.continue_()
            return
        blocked.append(url)
        route_obj.abort()

    context.route("**/*", route)
    page = context.new_page()
    js_errors: list[str] = []
    page.on("pageerror", lambda e: js_errors.append(str(e)))
    page.on("websocket", lambda ws: blocked.append(f"websocket {ws.url}"))

    def on_response(resp):
        if resp.status >= 400:
            report.error(f"{label}:{resp.url}", f"HTTP {resp.status} em recurso")

    page.on("response", on_response)

    target = base_url + "index.html" if base_url else index.as_uri()
    page.goto(target, wait_until="load", timeout=120_000)
    page.wait_for_function("window.Reveal && Reveal.isReady()", timeout=120_000)
    page.wait_for_function("document.fonts.status === 'loaded'", timeout=60_000)

    fonts = page.evaluate(
        r"""async () => {
          const out = {};
          for (const family of ['Fira Code', 'Source Sans Pro']) {
            try { await document.fonts.load(`16px "${family}"`); } catch (e) {}
            out[family] = document.fonts.check(`16px "${family}"`);
          }
          return {fira: out['Fira Code'], sans: out['Source Sans Pro'],
                  bad: Array.from(document.fonts)
                    .filter(f => f.status === 'error').map(f => f.family)};
        }"""
    )
    if not fonts["fira"]:
        report.error(label, "fonte Fira Code não carregou localmente")
    if fonts["bad"]:
        report.error(label, f"fontes com erro de carga: {fonts['bad']}")

    total = page.evaluate("Reveal.getSlides().length")
    log(f"navegador {label}: {total} slides")
    checked_images = 0
    checked_bgs = 0
    video_slides: list[int] = []
    decoded: set[str] = set()
    shot_tag = "file" if offline else "http"

    for idx in range(total):
        page.evaluate(
            "(i) => { const el = Reveal.getSlides()[i];"
            " const ix = Reveal.getIndices(el); Reveal.slide(ix.h, ix.v); }", idx
        )
        page.wait_for_timeout(50)
        # avançar fragmentos do slide corrente
        for _ in range(40):
            if not page.evaluate(
                "() => { const a = Reveal.availableFragments();"
                " if (a && a.next) { Reveal.nextFragment(); return true; } return false; }"
            ):
                break
        page.wait_for_function(
            "() => { const s = Reveal.getCurrentSlide();"
            " return s && s.querySelectorAll('img[data-src], iframe[data-src],"
            " video[data-src]').length === 0; }",
            timeout=30_000,
        )
        data = page.evaluate(SLIDE_JS, sorted(decoded))
        slide_id = page.evaluate(
            "() => { const s = Reveal.getCurrentSlide(); if (!s) return '';"
            " const h = s.querySelector('h1,h2,h3');"
            " return (h ? h.textContent : s.id || '').trim().slice(0, 60); }"
        )
        where = f"{label}:slide[{idx}] {slide_id}"
        for problem in data["problems"]:
            report.error(where, problem)
        for img in data["images"]:
            if img["lazy"]:
                report.error(where, "imagem com data-src não exercitada", url=img["src"])
                continue
            if img.get("cached"):
                continue
            if not img.get("ok") or not img.get("w") or not img.get("h"):
                report.error(where, f"imagem não decodifica: {img.get('error')}",
                             url=img["src"])
                continue
            decoded.add(img["src"])
            checked_images += 1
        for bg in data["backgrounds"]:
            url = bg["url"]
            if url.startswith("data:") or bg.get("cached"):
                continue
            if not bg.get("ok"):
                report.error(where, f"fundo CSS não decodifica: {bg.get('error')}",
                             url=url, selector=str(bg["element"]))
                continue
            decoded.add(url)
            checked_bgs += 1
        if data["videos"]:
            video_slides.append(idx)
            for vid in data["videos"]:
                if vid["error"] is not None:
                    report.error(where, f"MediaError {vid['error']}", url=vid["src"])
            result = page.evaluate(VIDEO_JS, None)
            if not result.get("ok"):
                report.error(where, f"vídeo não reproduziu: {result.get('error')}",
                             detail=json.dumps(result, ensure_ascii=False))
            else:
                report.summary.setdefault("video", {})[label] = result
                _shot(page, shots_dir / f"video-{name}-{shot_tag}.png")
        for frame_info in data["iframes"]:
            src = frame_info["src"]
            if not src:
                continue
            if REMOTE_RE.match(src):
                report.error(where, "iframe remoto no slide", url=src)
                continue
            _check_local_frame(page, src, report, where)
        srcs = " ".join(img.get("src", "") for img in data["images"])
        if idx == 0:
            _shot(page, shots_dir / f"capa-{name}-{shot_tag}.png")
        if "media/maps/ufpb.svg" in srcs:
            _shot(page, shots_dir / f"mapa-{name}-{shot_tag}.png")
        if not offline and "media/previews/future.png" in srcs:
            _shot(page, shots_dir / f"doc-{name}.png")
        if not offline and "media/previews/app-" in srcs:
            tag = "api" if "app-api" in srcs else "teresina"
            _shot(page, shots_dir / f"app-{tag}-{name}.png")

    katex = page.evaluate(
        "() => ({ok: document.querySelectorAll('.katex').length,"
        " err: document.querySelectorAll('.katex-error').length})"
    )
    if katex["err"]:
        report.error(label, f"{katex['err']} fórmulas com .katex-error")
    if not video_slides:
        report.error(label, "nenhum elemento <video> encontrado no deck")
    if blocked:
        uniq = sorted(set(blocked))
        for url in uniq[:20]:
            report.error(label, "requisição externa bloqueada durante a execução",
                         url=url)
    for err in js_errors[:10]:
        report.error(label, f"erro JS não tratado: {err}")
    report.summary.setdefault("browsers", {})[label] = {
        "slides": total, "images": checked_images, "backgrounds": checked_bgs,
        "katex": katex["ok"], "katex_errors": katex["err"],
        "video_slides": video_slides, "blocked": sorted(set(blocked)),
        "fonts": fonts,
    }
    context.close()


def _check_local_frame(page, src: str, report: Report, where: str) -> None:
    """Avalia o frame diretamente (funciona em http e em file://)."""
    tail = urllib.parse.unquote(src.split("#")[0].split("?")[0]).lstrip("./")
    frame = None
    for candidate in page.frames:
        if candidate == page.main_frame:
            continue
        url = urllib.parse.unquote(candidate.url)
        if url.endswith(tail):
            frame = candidate
            break
    if frame is None:
        report.error(where, "iframe local não carregou como frame do navegador",
                     url=src)
        return
    try:
        frame.wait_for_load_state("load", timeout=30_000)
        info = frame.evaluate(
            r"""async () => {
              const imgs = [];
              for (const i of Array.from(document.images)) {
                let ok = i.naturalWidth > 0 && i.naturalHeight > 0;
                try { await i.decode(); } catch (e) { ok = false; }
                imgs.push({w: i.naturalWidth, h: i.naturalHeight, ok,
                           src: (i.src || '').slice(0, 48)});
              }
              return {images: imgs, title: document.title,
                      body: document.body ? document.body.innerText.length : 0};
            }"""
        )
    except Exception as exc:
        report.error(where, f"iframe local inacessível: {exc}", url=src)
        return
    broken = [i for i in info["images"] if not i["ok"]]
    if broken:
        report.error(where,
                     f"{len(broken)} imagem(ns) quebrada(s) no iframe local",
                     url=src, detail=json.dumps(broken[:3], ensure_ascii=False))
    if not info["body"]:
        report.error(where, "iframe local sem conteúdo", url=src)
    report.summary.setdefault("iframes", {})[src] = {
        "images": len(info["images"]), "title": info["title"],
    }


def _shot(page, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(400)  # deixa a transição do Reveal terminar
    page.screenshot(path=str(path))


# --------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True, help="diretório do site renderizado")
    ap.add_argument("--source", required=True, help="diretório fonte (apresentacao)")
    ap.add_argument("--report", required=True, help="arquivo JSON de relatório")
    ap.add_argument("--require-receipt", action="store_true",
                    help="exige media-build.json consistente antes do navegador")
    ap.add_argument("--skip-browser", action="store_true",
                    help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    source = Path(args.source).resolve()
    report_path = Path(args.report).resolve()
    report = Report()
    if not (root / "index.html").exists():
        report.error(str(root), "index.html ausente na raiz do site")
        return _finish(report, report_path)
    repo_root = source.parent

    if args.require_receipt:
        check_receipt(root, repo_root, report)
        if report.errors:
            log("recibo inválido: abortando antes do navegador")
            return _finish(report, report_path)

    walker = GraphWalker(root, report)
    walker.walk_html(root / "index.html")
    report.summary["graph"] = {
        "files": len(walker.visited), "required": len(walker.required),
        "remote": len(walker.remote),
    }
    check_contents(root, source, report, walker.required)

    if not args.skip_browser:
        shots_dir = report_path.parent / (report_path.stem + "-shots")
        httpd, base_url = serve(root)
        try:
            browser_pass(root, report, base_url, shots_dir, offline=False)
        finally:
            httpd.shutdown()
            httpd.server_close()
        browser_pass(root, report, None, shots_dir, offline=True)
        report.summary["screenshots"] = sorted(
            str(p.relative_to(report_path.parent)) for p in shots_dir.glob("*.png")
        ) if shots_dir.exists() else []
    return _finish(report, report_path)


def _finish(report: Report, report_path: Path) -> int:
    report.summary["errors"] = len(report.errors)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {"errors": report.errors, "resources": report.resources,
             "summary": report.summary},
            ensure_ascii=False, indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    if report.errors:
        log(f"FALHA: {len(report.errors)} erro(s) — relatório em {report_path}")
        return 1
    log(f"OK — relatório em {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
