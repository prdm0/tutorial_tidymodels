#!/usr/bin/env python3
"""Testes de comportamento do pipeline de mídias (sem rede).

Exercita as funções reais de ``scripts/media.py``, ``scripts/check_media.py``
e ``scripts/build_deck.py`` sobre fixtures pequenas, porém reais: PNG/GIF
gerados com Pillow e MP4 gerado com FFmpeg.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_deck  # noqa: E402
import check_media  # noqa: E402
import media as mediamod  # noqa: E402

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
def png_bytes(size=(32, 24), color=(200, 40, 60)) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def gif_bytes(frames=3, broken=False) -> bytes:
    import io

    from PIL import Image

    imgs = [Image.new("P", (16, 16), i * 40) for i in range(frames)]
    buf = io.BytesIO()
    imgs[0].save(buf, format="GIF", save_all=True, append_images=imgs[1:], duration=80)
    data = buf.getvalue()
    if broken:
        # corrompe o fluxo de dados do último quadro, preservando o cabeçalho
        cut = data.rfind(b"\x2c")  # último Image Descriptor
        data = data[: cut + 12] + b"\x00" * 6
    return data


def make_mp4(path: Path, seconds: float = 1.0) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"testsrc=size=160x120:rate=15:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-crf", "28", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-movflags", "+faststart", str(path)],
        check=True, capture_output=True,
    )


REVEAL_SHIM = """
window.Reveal = {
  _i: 0,
  isReady: function () { return true; },
  getSlides: function () { return Array.prototype.slice.call(
      document.querySelectorAll('section.slide')); },
  getIndices: function (el) { return {h: Reveal.getSlides().indexOf(el), v: 0}; },
  getCurrentSlide: function () { return Reveal.getSlides()[Reveal._i]; },
  getSlideBackground: function (el) {
      return el.querySelector('.slide-background'); },
  availableFragments: function () { return {next: false, prev: false}; },
  nextFragment: function () { return false; },
  slide: function (h) {
      Reveal._i = h;
      Reveal.getSlides().forEach(function (s, i) {
          s.style.display = (i === h) ? 'block' : 'none';
          if (i === h) {
              s.querySelectorAll('[data-src]').forEach(function (e) {
                  e.setAttribute('src', e.getAttribute('data-src'));
                  e.removeAttribute('data-src');
              });
          }
      });
  }
};
Reveal.slide(0);
"""


def make_site(root: Path, *, remote_background=False, remote_data_src=False,
              remote_iframe_dep=False, lazy_png=True, video=True,
              case_mismatch=False) -> Path:
    """Monta um site mínimo com a API Reveal necessária à auditoria."""
    (root / "imgs").mkdir(parents=True, exist_ok=True)
    (root / "media" / "images").mkdir(parents=True, exist_ok=True)
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "imgs" / "capa.png").write_bytes(png_bytes())
    (root / "imgs" / "late.png").write_bytes(png_bytes(color=(10, 90, 180)))
    (root / "media" / "images" / "fundo.png").write_bytes(png_bytes((64, 48)))
    (root / "assets" / "nested-img.png").write_bytes(png_bytes((20, 20)))
    nested_dep = ('<img src="https://example.invalid/x.png">'
                  if remote_iframe_dep else '<img src="nested-img.png">')
    (root / "assets" / "nested.html").write_text(
        f"<!doctype html><meta charset='utf-8'><title>Relatório</title>"
        f"<body><p>relatório local</p>{nested_dep}</body>",
        encoding="utf-8",
    )
    (root / "site.css").write_text(
        ".flow { background-image: url(\"%s\"); }\n"
        % ("https://images.example.invalid/t.jpg" if remote_background
           else "media/images/fundo.png"),
        encoding="utf-8",
    )
    lazy_src = ("https://example.invalid/late.png" if remote_data_src
                else ("imgs/Late.png" if case_mismatch else "imgs/late.png"))
    video_html = (
        '<video controls playsinline preload="metadata">'
        '<source src="media/videos/fixture.mp4" type="video/mp4"></video>'
        if video else ""
    )
    html = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Deck</title><link rel="stylesheet" href="site.css"></head><body>
<div class="reveal"><div class="slides">
<section class="slide"><h2>Capa</h2><img src="imgs/capa.png" alt="capa"></section>
<section class="slide"><h2>Meu segundo lar</h2>
  <div class="slide-background" style="background-image: url('media/images/fundo.png')"></div>
</section>
<section class="slide"><h2>Lazy</h2><img data-src="{lazy_src}" alt="tardia"></section>
<section class="slide"><h2>Vídeo</h2>{video_html}</section>
<section class="slide"><h2>Relatório</h2>
  <iframe src="assets/nested.html" width="100%" height="300"></iframe></section>
</div></div>
<script>{REVEAL_SHIM}</script></body></html>
"""
    (root / "index.html").write_text(html, encoding="utf-8")
    if video:
        (root / "media" / "videos").mkdir(parents=True, exist_ok=True)
        if HAS_FFMPEG:
            make_mp4(root / "media" / "videos" / "fixture.mp4", seconds=3.0)
    return root


def make_source(source: Path, site: Path) -> Path:
    """Fonte mínima com manifest travando os originais do site."""
    (source / "media" / "images").mkdir(parents=True, exist_ok=True)
    (source / "imgs").mkdir(parents=True, exist_ok=True)
    assets = []
    for rel in ("imgs/capa.png", "imgs/late.png", "media/images/fundo.png"):
        dest = source / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(site / rel, dest)
        assets.append({
            "path": rel, "kind": "image",
            "sha256": mediamod.sha256_file(dest), "bytes": dest.stat().st_size,
            "origin": "fixture", "license": None, "repair": "git",
        })
    (source / "media").mkdir(parents=True, exist_ok=True)
    (source / "media" / "manifest.json").write_text(
        json.dumps({"version": 1, "assets": assets}, indent=2), encoding="utf-8"
    )
    return source


def run_check(site: Path, source: Path, report: Path, *, browser=False,
              receipt=False) -> tuple[int, dict]:
    argv = ["--root", str(site), "--source", str(source), "--report", str(report)]
    if not browser:
        argv.append("--skip-browser")
    if receipt:
        argv.append("--require-receipt")
    code = check_media.main(argv)
    return code, json.loads(report.read_text(encoding="utf-8"))


def reasons(data: dict) -> str:
    return " | ".join(f"{e['where']}::{e['reason']}" for e in data["errors"])


class TempCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="media-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.site = self.tmp / "site"
        self.src = self.tmp / "src"
        self.site.mkdir()
        self.src.mkdir()


# --------------------------------------------------------------------------
class TestImageValidation(TempCase):
    def test_valid_png_passes(self) -> None:
        path = self.tmp / "ok.png"
        path.write_bytes(png_bytes())
        mediamod.validate_image(path)

    def test_html_disguised_as_png_fails(self) -> None:
        path = self.tmp / "fake.png"
        path.write_bytes(b"<!doctype html><html><body>Access blocked</body></html>")
        with self.assertRaises(Exception):
            mediamod.validate_image(path)

    def test_truncated_png_fails(self) -> None:
        data = png_bytes((64, 64))
        path = self.tmp / "trunc.png"
        path.write_bytes(data[: len(data) // 2])
        with self.assertRaises(Exception):
            mediamod.validate_image(path)

    def test_gif_with_broken_frame_fails(self) -> None:
        good = self.tmp / "ok.gif"
        good.write_bytes(gif_bytes())
        mediamod.validate_image(good)
        bad = self.tmp / "bad.gif"
        bad.write_bytes(gif_bytes(broken=True))
        with self.assertRaises(Exception):
            mediamod.validate_image(bad)


class TestStaticGraph(TempCase):
    def test_remote_css_background_fails(self) -> None:
        make_site(self.site, remote_background=True, video=False)
        make_source(self.src, self.site)
        code, data = run_check(self.site, self.src, self.tmp / "r.json")
        self.assertEqual(code, 1)
        self.assertIn("recurso obrigatório remoto", reasons(data))
        self.assertIn("site.css", reasons(data))

    def test_remote_data_src_fails(self) -> None:
        make_site(self.site, remote_data_src=True, video=False)
        make_source(self.src, self.site)
        code, data = run_check(self.site, self.src, self.tmp / "r.json")
        self.assertEqual(code, 1)
        self.assertTrue(
            any(e.get("attribute") == "img[data-src]"
                and "remoto" in e["reason"] for e in data["errors"]),
            data["errors"],
        )

    def test_remote_dependency_inside_local_iframe_fails(self) -> None:
        make_site(self.site, remote_iframe_dep=True, video=False)
        make_source(self.src, self.site)
        code, data = run_check(self.site, self.src, self.tmp / "r.json")
        self.assertEqual(code, 1)
        self.assertIn("assets/nested.html", reasons(data))

    def test_remote_font_face_fails(self) -> None:
        make_site(self.site, video=False)
        make_source(self.src, self.site)
        css = self.site / "site.css"
        css.write_text(
            css.read_text(encoding="utf-8")
            + '@font-face { font-family: "X"; '
              'src: url("https://fonts.example.invalid/x.woff2") format("woff2"); }\n',
            encoding="utf-8",
        )
        code, data = run_check(self.site, self.src, self.tmp / "r.json")
        self.assertEqual(code, 1)
        self.assertIn("x.woff2", reasons(data) + json.dumps(data["errors"]))

    def test_local_font_face_file_must_exist(self) -> None:
        make_site(self.site, video=False)
        make_source(self.src, self.site)
        css = self.site / "site.css"
        css.write_text(
            css.read_text(encoding="utf-8")
            + '@font-face { font-family: "X"; src: url("fonts/ausente.ttf"); }\n',
            encoding="utf-8",
        )
        code, data = run_check(self.site, self.src, self.tmp / "r.json")
        self.assertEqual(code, 1)
        self.assertIn("recurso local ausente", reasons(data))

    def test_case_sensitive_reference_fails(self) -> None:
        make_site(self.site, case_mismatch=True, video=False)
        make_source(self.src, self.site)
        code, data = run_check(self.site, self.src, self.tmp / "r.json")
        self.assertEqual(code, 1)
        self.assertIn("caixa diferente", reasons(data))

    def test_escaping_reference_is_rejected(self) -> None:
        make_site(self.site, video=False)
        make_source(self.src, self.site)
        outside = self.tmp / "fora.png"
        outside.write_bytes(png_bytes())
        html = (self.site / "index.html").read_text(encoding="utf-8")
        html = html.replace('<img src="imgs/capa.png"', '<img src="../fora.png"')
        (self.site / "index.html").write_text(html, encoding="utf-8")
        code, data = run_check(self.site, self.src, self.tmp / "r.json")
        self.assertEqual(code, 1)
        self.assertIn("escapa da raiz", reasons(data))

    def test_external_symlink_is_rejected(self) -> None:
        make_site(self.site, video=False)
        make_source(self.src, self.site)
        target = self.tmp / "externa.png"
        target.write_bytes(png_bytes())
        link = self.site / "imgs" / "link.png"
        link.symlink_to(target)
        html = (self.site / "index.html").read_text(encoding="utf-8")
        html = html.replace('<img src="imgs/capa.png"', '<img src="imgs/link.png"')
        (self.site / "index.html").write_text(html, encoding="utf-8")
        code, data = run_check(self.site, self.src, self.tmp / "r.json")
        self.assertEqual(code, 1)
        self.assertIn("escapa da raiz", reasons(data))

    def test_clean_site_passes(self) -> None:
        make_site(self.site, video=False)
        make_source(self.src, self.site)
        code, data = run_check(self.site, self.src, self.tmp / "r.json")
        self.assertEqual(code, 0, reasons(data))


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe indisponíveis")
class TestVideoValidation(TempCase):
    def test_real_mp4_validates(self) -> None:
        path = self.tmp / "ok.mp4"
        make_mp4(path)
        info = mediamod.validate_video(path)
        self.assertGreater(info["duration"], 0.5)
        self.assertEqual(info["audio_codec"], "aac")

    def test_truncated_mp4_fails(self) -> None:
        path = self.tmp / "ok.mp4"
        make_mp4(path, seconds=2.0)
        data = path.read_bytes()
        bad = self.tmp / "trunc.mp4"
        bad.write_bytes(data[: int(len(data) * 0.6)])
        with self.assertRaises(mediamod.MediaError):
            mediamod.validate_video(bad)

    def test_valid_metadata_with_broken_frames_fails(self) -> None:
        path = self.tmp / "ok.mp4"
        make_mp4(path, seconds=2.0)
        data = bytearray(path.read_bytes())
        idx = data.find(b"mdat")
        self.assertGreater(idx, 0)
        for i in range(idx + 8, min(idx + 4000, len(data))):
            data[i] ^= 0xFF
        bad = self.tmp / "frames.mp4"
        bad.write_bytes(bytes(data))
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", str(bad)],
            capture_output=True, text=True,
        )
        self.assertEqual(probe.returncode, 0, "metadados deveriam continuar legíveis")
        with self.assertRaises(mediamod.MediaError):
            mediamod.validate_video(bad)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe indisponíveis")
class TestBrowserPass(TempCase):
    def setUp(self) -> None:
        super().setUp()
        self._browsers = check_media.BROWSERS
        check_media.BROWSERS = ("chromium",)
        self.addCleanup(setattr, check_media, "BROWSERS", self._browsers)

    def test_lazy_and_iframe_images_are_exercised(self) -> None:
        make_site(self.site)
        make_source(self.src, self.site)
        code, data = run_check(self.site, self.src, self.tmp / "r.json", browser=True)
        self.assertEqual(code, 0, reasons(data))
        summary = data["summary"]["browsers"]["chromium/http"]
        self.assertEqual(summary["images"], 2, "capa e imagem lazy decodificadas")
        self.assertEqual(summary["backgrounds"], 1)
        self.assertEqual(data["summary"]["iframes"]["assets/nested.html"]["images"], 1)
        self.assertTrue(data["summary"]["video"]["chromium/http"]["ok"])

    def test_broken_lazy_image_is_not_masked_by_cover(self) -> None:
        make_site(self.site)
        make_source(self.src, self.site)
        target = self.site / "imgs" / "late.png"
        target.write_bytes(target.read_bytes()[:40])
        code, data = run_check(self.site, self.src, self.tmp / "r.json", browser=True)
        self.assertEqual(code, 1)
        self.assertIn("late.png", reasons(data))

    def test_broken_image_inside_local_iframe_fails(self) -> None:
        make_site(self.site)
        make_source(self.src, self.site)
        target = self.site / "assets" / "nested-img.png"
        target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        code, data = run_check(self.site, self.src, self.tmp / "r.json", browser=True)
        self.assertEqual(code, 1)
        self.assertIn("nested", reasons(data).lower())

    def test_truncated_video_is_not_approved(self) -> None:
        make_site(self.site)
        make_source(self.src, self.site)
        video = self.site / "media" / "videos" / "fixture.mp4"
        video.write_bytes(video.read_bytes()[: 1024])
        code, data = run_check(self.site, self.src, self.tmp / "r.json", browser=True)
        self.assertEqual(code, 1)
        self.assertIn("fixture.mp4", reasons(data))

    def test_video_with_broken_frames_is_not_approved(self) -> None:
        make_site(self.site)
        make_source(self.src, self.site)
        video = self.site / "media" / "videos" / "fixture.mp4"
        data = bytearray(video.read_bytes())
        idx = data.find(b"mdat")
        self.assertGreater(idx, 0)
        for i in range(idx + 8, len(data)):
            data[i] ^= 0xFF
        video.write_bytes(bytes(data))
        code, report = run_check(self.site, self.src, self.tmp / "r.json",
                                 browser=True)
        self.assertEqual(code, 1)
        self.assertTrue(
            any("slide" in e["where"] and "vídeo não reproduziu" in e["reason"]
                for e in report["errors"]),
            reasons(report),
        )


class TestManifestRepair(TempCase):
    def setUp(self) -> None:
        super().setUp()
        self.pres = self.tmp / "apresentacao"
        (self.pres / "media").mkdir(parents=True)
        saved = {name: getattr(mediamod, name) for name in
                 ("REPO_ROOT", "PRES", "MEDIA_DIR", "MANIFEST_PATH", "BUILD_DIR",
                  "BACKUP_DIR", "QUARANTINE_DIR")}
        self.addCleanup(lambda: [setattr(mediamod, k, v) for k, v in saved.items()])
        mediamod.REPO_ROOT = self.tmp
        mediamod.PRES = self.pres
        mediamod.MEDIA_DIR = self.pres / "media"
        mediamod.MANIFEST_PATH = self.pres / "media" / "manifest.json"
        mediamod.BUILD_DIR = self.pres / ".media-build"
        mediamod.BACKUP_DIR = mediamod.BUILD_DIR / "media-backup"
        mediamod.QUARANTINE_DIR = mediamod.BUILD_DIR / "quarantine"

    def _lock(self, rel: str, data: bytes, **kw) -> mediamod.Entry:
        path = self.pres / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        entry = mediamod.Entry(
            path=rel, kind=kw.get("kind", "image"),
            sha256=mediamod.sha256_bytes(data), bytes=len(data),
            origin="fixture", license=None, repair=kw.get("repair", "manual"),
        )
        entries = mediamod.load_manifest()
        entries[rel] = entry
        mediamod.save_manifest(entries)
        mediamod.backup(rel)
        return entry

    def test_missing_file_is_restored_from_backup(self) -> None:
        data = png_bytes()
        self._lock("media/images/a.png", data)
        (self.pres / "media/images/a.png").unlink()
        self.assertEqual(mediamod.cmd_repair(), 0)
        self.assertEqual((self.pres / "media/images/a.png").read_bytes(), data)

    def test_corrupted_file_is_restored(self) -> None:
        data = png_bytes()
        self._lock("media/images/a.png", data)
        (self.pres / "media/images/a.png").write_bytes(b"not an image")
        self.assertEqual(mediamod.cmd_repair(), 0)
        self.assertEqual((self.pres / "media/images/a.png").read_bytes(), data)

    def test_valid_local_change_is_not_overwritten(self) -> None:
        self._lock("media/images/a.png", png_bytes())
        changed = png_bytes(color=(1, 2, 3))
        shutil.rmtree(mediamod.BACKUP_DIR)
        (self.pres / "media/images/a.png").write_bytes(changed)
        self.assertEqual(mediamod.cmd_repair(), 1)
        self.assertEqual((self.pres / "media/images/a.png").read_bytes(), changed)

    def test_unrecoverable_asset_fails(self) -> None:
        self._lock("media/videos/v.mp4", b"\x00" * 64, kind="binary")
        shutil.rmtree(mediamod.BACKUP_DIR)
        (self.pres / "media/videos/v.mp4").unlink()
        self.assertEqual(mediamod.cmd_repair(), 1)

    def test_intact_assets_are_not_reacquired(self) -> None:
        calls = self._fake_group()
        self.assertEqual(mediamod.cmd_prepare(), 0)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(mediamod.cmd_prepare(), 0)
        self.assertEqual(calls["n"], 1, "arquivo íntegro não deve ser readquirido")

    def _fake_group(self) -> dict:
        calls = {"n": 0}

        def fake() -> list[mediamod.Acquired]:
            calls["n"] += 1
            return [mediamod.Acquired("media/images/b.png", png_bytes(), "image",
                                      "fixture", None, "manual")]

        saved_groups = mediamod.GROUPS
        saved_refs = mediamod.referenced_local_media
        mediamod.GROUPS = [("fixture", ("media/images/b.png",), fake)]
        mediamod.referenced_local_media = lambda: []
        self.addCleanup(setattr, mediamod, "GROUPS", saved_groups)
        self.addCleanup(setattr, mediamod, "referenced_local_media", saved_refs)
        saved_checks = mediamod._browser_checks
        mediamod._browser_checks = lambda: None
        self.addCleanup(setattr, mediamod, "_browser_checks", saved_checks)
        return calls

    def test_prepare_refuses_divergent_locked_asset(self) -> None:
        calls = self._fake_group()
        self.assertEqual(mediamod.cmd_prepare(), 0)
        self.assertEqual(calls["n"], 1)
        path = self.pres / "media/images/b.png"
        locked = mediamod.load_manifest()["media/images/b.png"].sha256
        changed = png_bytes(color=(1, 2, 3))
        path.write_bytes(changed)

        self.assertEqual(mediamod.cmd_prepare(), 1)
        self.assertEqual(calls["n"], 1, "divergência válida não pode readquirir")
        self.assertEqual(path.read_bytes(), changed)
        self.assertEqual(mediamod.load_manifest()["media/images/b.png"].sha256,
                         locked, "lock não pode ser regravado sem --refresh-lock")

        self.assertEqual(mediamod.cmd_prepare(refresh=True), 0)
        self.assertEqual(calls["n"], 2)

    def test_prepare_reacquires_corrupted_asset(self) -> None:
        calls = self._fake_group()
        self.assertEqual(mediamod.cmd_prepare(), 0)
        path = self.pres / "media/images/b.png"
        path.write_bytes(b"nao e png")

        self.assertEqual(mediamod.cmd_prepare(), 0)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


class TestReceipt(TempCase):
    def _repo(self) -> tuple[Path, Path]:
        repo = self.tmp / "repo"
        pres = repo / "apresentacao"
        site = pres / "docs"
        (pres / "media").mkdir(parents=True)
        site.mkdir(parents=True)
        (pres / "index.qmd").write_text("# deck\n", encoding="utf-8")
        (pres / "_quarto.yml").write_text("project:\n  output-dir: docs\n",
                                          encoding="utf-8")
        (pres / "style.scss").write_text("/* tema */\n", encoding="utf-8")
        make_site(site, video=False)
        make_source(pres, site)
        return repo, site

    def test_source_change_without_rebuild_fails(self) -> None:
        repo, site = self._repo()
        receipt = {
            "version": 1, "built_at": mediamod.utcnow(),
            "inputs": check_media.build_input_map(repo),
            "outputs": {str(p.relative_to(site)): mediamod.sha256_file(p)
                        for p in sorted(site.rglob("*")) if p.is_file()},
        }
        (site / check_media.RECEIPT_NAME).write_text(json.dumps(receipt),
                                                     encoding="utf-8")
        report = check_media.Report()
        check_media.check_receipt(site, repo, report)
        self.assertEqual(report.errors, [])
        (repo / "apresentacao" / "index.qmd").write_text("# deck novo\n",
                                                         encoding="utf-8")
        report = check_media.Report()
        check_media.check_receipt(site, repo, report)
        self.assertTrue(any("recibo desatualizado" in e["reason"]
                            for e in report.errors), report.errors)

    def test_receipt_alone_does_not_replace_media_audit(self) -> None:
        repo, site = self._repo()
        broken = site / "imgs" / "capa.png"
        broken.write_bytes(broken.read_bytes()[:30])
        receipt = {
            "version": 1, "built_at": mediamod.utcnow(),
            "inputs": check_media.build_input_map(repo),
            "outputs": {str(p.relative_to(site)): mediamod.sha256_file(p)
                        for p in sorted(site.rglob("*")) if p.is_file()},
        }
        (site / check_media.RECEIPT_NAME).write_text(json.dumps(receipt),
                                                     encoding="utf-8")
        report = check_media.Report()
        check_media.check_receipt(site, repo, report)
        self.assertEqual(report.errors, [], "recibo coerente, porém mídia quebrada")
        code, data = run_check(site, repo / "apresentacao", self.tmp / "r.json",
                               receipt=True)
        self.assertEqual(code, 1)
        self.assertIn("capa.png", reasons(data))

    def test_missing_receipt_fails(self) -> None:
        repo, site = self._repo()
        code, data = run_check(site, repo / "apresentacao", self.tmp / "r.json",
                               receipt=True)
        self.assertEqual(code, 1)
        self.assertIn("recibo de build ausente", reasons(data))


class TestPromotion(TempCase):
    def setUp(self) -> None:
        super().setUp()
        self.a = self.tmp / "a" / "docs"
        self.b = self.tmp / "b" / "docs"
        self.a.mkdir(parents=True)
        self.b.mkdir(parents=True)
        (self.a / "index.html").write_text("antigo A", encoding="utf-8")
        (self.b / "index.html").write_text("antigo A", encoding="utf-8")
        saved = (build_deck.TARGETS, build_deck.BUILD_DIR, build_deck.PROMOTION)
        self.addCleanup(lambda: (
            setattr(build_deck, "TARGETS", saved[0]),
            setattr(build_deck, "BUILD_DIR", saved[1]),
            setattr(build_deck, "PROMOTION", saved[2]),
        ))
        build_deck.TARGETS = (self.a, self.b)
        build_deck.BUILD_DIR = self.tmp / ".media-build"
        build_deck.PROMOTION = build_deck.BUILD_DIR / "promotion.json"
        self.run_dir = build_deck.BUILD_DIR / "run"
        self.run_dir.mkdir(parents=True)
        self.staging = self.run_dir / "site"
        self.staging.mkdir()
        (self.staging / "index.html").write_text("novo B", encoding="utf-8")

    def test_successful_promotion_replaces_both(self) -> None:
        before = {t: build_deck.tree_hashes(t) for t in build_deck.TARGETS}
        build_deck.promote(self.staging, self.run_dir, before)
        self.assertEqual((self.a / "index.html").read_text(encoding="utf-8"), "novo B")
        self.assertEqual((self.b / "index.html").read_text(encoding="utf-8"), "novo B")
        state = json.loads(build_deck.PROMOTION.read_text(encoding="utf-8"))
        self.assertEqual(state["state"], "committed")

    def test_failure_between_promotions_restores_pair(self) -> None:
        before = {t: build_deck.tree_hashes(t) for t in build_deck.TARGETS}
        real_rename = os.rename
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 3:  # falha ao renomear o segundo alvo
                raise OSError("falha simulada entre promoções")
            return real_rename(src, dst)

        os.rename = flaky
        self.addCleanup(setattr, os, "rename", real_rename)
        with self.assertRaises(OSError):
            build_deck.promote(self.staging, self.run_dir, before)
        os.rename = real_rename
        self.assertEqual((self.a / "index.html").read_text(encoding="utf-8"), "antigo A")
        self.assertEqual((self.b / "index.html").read_text(encoding="utf-8"), "antigo A")
        self.assertEqual({t: build_deck.tree_hashes(t) for t in build_deck.TARGETS},
                         before)
        self.assertFalse(build_deck.PROMOTION.exists())

    def test_concurrent_change_aborts_promotion(self) -> None:
        before = {t: build_deck.tree_hashes(t) for t in build_deck.TARGETS}
        (self.a / "index.html").write_text("mudou durante o build", encoding="utf-8")
        with self.assertRaises(build_deck.BuildError):
            build_deck.promote(self.staging, self.run_dir, before)
        self.assertEqual((self.a / "index.html").read_text(encoding="utf-8"),
                         "mudou durante o build")
        self.assertEqual((self.b / "index.html").read_text(encoding="utf-8"), "antigo A")

    def test_interrupted_promotion_is_recovered(self) -> None:
        before = {t: build_deck.tree_hashes(t) for t in build_deck.TARGETS}
        real_rename = os.rename
        calls = {"n": 0}

        def crash(src, dst):
            calls["n"] += 1
            if calls["n"] == 3:
                raise KeyboardInterrupt("interrupção durante a promoção")
            return real_rename(src, dst)

        os.rename = crash
        try:
            with self.assertRaises(KeyboardInterrupt):
                build_deck.promote(self.staging, self.run_dir, before)
        finally:
            os.rename = real_rename
        # estado durável deixado como "prepared": a próxima execução recupera
        state = json.loads(build_deck.PROMOTION.read_text(encoding="utf-8"))
        self.assertEqual(state["state"], "prepared")
        build_deck.recover_promotion()
        self.assertEqual({t: build_deck.tree_hashes(t) for t in build_deck.TARGETS},
                         before)

    def test_divergent_trees_restore_previous_pair(self) -> None:
        before = {t: build_deck.tree_hashes(t) for t in build_deck.TARGETS}
        real_rename = os.rename
        calls = {"n": 0}

        def divergent(src, dst):
            calls["n"] += 1
            result = real_rename(src, dst)
            if calls["n"] == 4:  # segundo alvo recém-instalado
                (Path(dst) / "extra.txt").write_text("divergência",
                                                     encoding="utf-8")
            return result

        os.rename = divergent
        try:
            with self.assertRaises(build_deck.BuildError):
                build_deck.promote(self.staging, self.run_dir, before)
        finally:
            os.rename = real_rename
        self.assertEqual((self.a / "index.html").read_text(encoding="utf-8"),
                         "antigo A")
        self.assertEqual((self.b / "index.html").read_text(encoding="utf-8"),
                         "antigo A")
        self.assertEqual({t: build_deck.tree_hashes(t) for t in build_deck.TARGETS},
                         before)
        self.assertFalse(build_deck.PROMOTION.exists())


class TestStagingRestore(TempCase):
    def test_missing_output_is_restored_from_source(self) -> None:
        make_site(self.site, video=False)
        make_source(self.src, self.site)
        (self.site / "imgs" / "capa.png").unlink()
        report = self.tmp / "r.json"
        code, data = run_check(self.site, self.src, report)
        self.assertEqual(code, 1)
        saved = mediamod.PRES
        mediamod.PRES = self.src
        build_pres = build_deck.PRES
        build_deck.PRES = self.src
        try:
            fixed = build_deck.restore_from_source(self.site, report)
        finally:
            mediamod.PRES = saved
            build_deck.PRES = build_pres
        self.assertEqual(fixed, 1)
        code, data = run_check(self.site, self.src, report)
        self.assertEqual(code, 0, reasons(data))

    def test_unknown_output_is_not_invented(self) -> None:
        make_site(self.site, video=False)
        make_source(self.src, self.site)
        html = (self.site / "index.html").read_text(encoding="utf-8")
        (self.site / "index.html").write_text(
            html.replace('src="imgs/capa.png"', 'src="imgs/sem-original.png"'),
            encoding="utf-8",
        )
        report = self.tmp / "r.json"
        code, _ = run_check(self.site, self.src, report)
        self.assertEqual(code, 1)
        build_pres = build_deck.PRES
        build_deck.PRES = self.src
        try:
            fixed = build_deck.restore_from_source(self.site, report)
        finally:
            build_deck.PRES = build_pres
        self.assertEqual(fixed, 0)


if __name__ == "__main__":
    unittest.main()
