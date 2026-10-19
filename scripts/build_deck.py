#!/usr/bin/env python3
"""Render, auditoria e promoção atômica do deck.

    python3 scripts/build_deck.py

Não instala nada, não faz commit/push e nunca publica build parcial:
o site só substitui `apresentacao/docs/` e `docs/` depois de renderizar,
passar na auditoria e gerar o recibo `media-build.json`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_media  # noqa: E402
import media as mediamod  # noqa: E402

REPO_ROOT = mediamod.REPO_ROOT
PRES = mediamod.PRES
BUILD_DIR = mediamod.BUILD_DIR
PROMOTION = BUILD_DIR / "promotion.json"
TARGETS = (PRES / "docs", REPO_ROOT / "docs")
RECEIPT = check_media.RECEIPT_NAME


def log(msg: str) -> None:
    print(f"[build] {msg}", file=sys.stderr, flush=True)


class BuildError(RuntimeError):
    pass


# --------------------------------------------------------------------------
def tree_hashes(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            out[str(path.relative_to(root))] = mediamod.sha256_file(path)
    return out


def write_json_durable(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def quarantine_dir(path: Path, reason: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest = BUILD_DIR / "quarantine" / f"{stamp}-{reason}-{path.name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    return dest


# --------------------------------------------------------------------------
def recover_promotion() -> None:
    """Conclui a recuperação de uma promoção interrompida."""
    if not PROMOTION.exists():
        return
    state = json.loads(PROMOTION.read_text(encoding="utf-8"))
    if state.get("state") == "committed":
        log("promoção anterior concluída; nada a recuperar")
        PROMOTION.unlink()
        return
    if state.get("state") != "prepared":
        PROMOTION.unlink()
        return
    log("promoção anterior interrompida: restaurando backups")
    for item in state.get("targets", []):
        target = Path(item["target"])
        backup = Path(item["backup"])
        if backup.exists():
            if target.exists():
                quarantine_dir(target, "rollback")
            shutil.move(str(backup), str(target))
            log(f"restaurado {target}")
        elif not item.get("original_exists", True) and target.exists():
            quarantine_dir(target, "rollback-novo")
            log(f"recolhido diretório novo {target}")
    PROMOTION.unlink()


# --------------------------------------------------------------------------
def check_tools() -> None:
    for tool in ("quarto", "Rscript"):
        mediamod.require_tool(tool)
    for mod in ("playwright", "PIL", "tinycss2"):
        try:
            __import__(mod)
        except ImportError as exc:
            raise BuildError(
                f"dependência Python ausente: {mod} "
                "(instale scripts/requirements-media.txt)"
            ) from exc
    mediamod.require_tool("ffmpeg")
    mediamod.require_tool("ffprobe")


def render(staging_rel: str) -> None:
    cmd = ["quarto", "render", "index.qmd", "--to", "revealjs",
           "--output-dir", staging_rel]
    log(f"render: {' '.join(cmd)} (cwd={PRES})")
    proc = subprocess.run(cmd, cwd=PRES, check=False)
    if proc.returncode != 0:
        raise BuildError(f"quarto render falhou (exit {proc.returncode})")


def audit(root: Path, report: Path, *, require_receipt: bool) -> int:
    argv = ["--root", str(root), "--source", str(PRES), "--report", str(report)]
    if require_receipt:
        argv.append("--require-receipt")
    return check_media.main(argv)


def restore_from_source(root: Path, report_path: Path) -> int:
    """Repõe no staging estáticos que o Quarto não copiou (ou copiou errado)."""
    data = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = check_media._load_manifest(PRES / "media" / "manifest.json")
    fixed = 0
    wanted: set[str] = set()
    for err in data.get("errors", []):
        reason = err.get("reason", "")
        if "recurso local ausente" in reason:
            owner = Path(err.get("where", "index.html"))
            ref = (err.get("url") or "").split("#")[0].split("?")[0]
            if not ref or ref.startswith(("http", "//", "data:")):
                continue
            if ref.startswith("/"):
                rel = ref[len(check_media.SITE_PREFIX):] if ref.startswith(
                    check_media.SITE_PREFIX) else ref.lstrip("/")
            else:
                rel = str((owner.parent / ref))
            wanted.add(os.path.normpath(rel))
        elif "cópia publicada difere do original travado" in reason:
            wanted.add(os.path.normpath(err.get("where", "")))
    for rel in sorted(w for w in wanted if w and not w.startswith("..")):
        src = PRES / rel
        if not src.is_file():
            log(f"sem original para {rel}: falha não é reparável")
            continue
        entry = manifest.get(rel)
        if entry and mediamod.sha256_file(src) != entry["sha256"]:
            log(f"original {rel} não confere com o manifest; não será copiado")
            continue
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        log(f"restaurado no staging: {rel}")
        fixed += 1
    return fixed


def make_receipt(root: Path) -> dict:
    inputs = check_media.build_input_map(REPO_ROOT)
    outputs = {
        str(p.relative_to(root)): mediamod.sha256_file(p)
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != RECEIPT
    }
    receipt = {
        "version": 1,
        "built_at": mediamod.utcnow(),
        "inputs": inputs,
        "outputs": dict(sorted(outputs.items())),
    }
    write_json_durable(root / RECEIPT, receipt)
    return receipt


def verify_receipt(root: Path) -> None:
    report = check_media.Report()
    check_media.check_receipt(root, REPO_ROOT, report)
    if report.errors:
        for err in report.errors[:10]:
            log(f"recibo inconsistente: {err}")
        raise BuildError("recibo recém-gerado não confere com a árvore")


# --------------------------------------------------------------------------
def promote(staging: Path, run_dir: Path, before: dict[Path, dict[str, str]]) -> None:
    candidates: list[dict] = []
    for target in TARGETS:
        cand = run_dir / f"cand-{target.parent.name}-{target.name}"
        if cand.exists():
            shutil.rmtree(cand)
        shutil.copytree(staging, cand)
        candidates.append({
            "target": str(target),
            "backup": str(run_dir / f"backup-{target.parent.name}-{target.name}"),
            "candidate": str(cand),
            "original_exists": target.exists(),
        })
    for target in TARGETS:
        if tree_hashes(target) != before[target]:
            raise BuildError(
                f"{target} mudou durante o build; promoção abortada para não "
                "sobrescrever alterações concorrentes"
            )
    write_json_durable(PROMOTION, {"state": "prepared", "targets": candidates})
    try:
        for item in candidates:
            target = Path(item["target"])
            backup = Path(item["backup"])
            if target.exists():
                os.rename(target, backup)
            os.rename(item["candidate"], target)
            log(f"promovido {target}")
    except Exception:
        log("falha na promoção; restaurando estado anterior")
        for item in candidates:
            target = Path(item["target"])
            backup = Path(item["backup"])
            if backup.exists():
                if target.exists():
                    quarantine_dir(target, "rollback")
                shutil.move(str(backup), str(target))
            elif not item["original_exists"] and target.exists():
                quarantine_dir(target, "rollback-novo")
        PROMOTION.unlink(missing_ok=True)
        raise
    hashes = [tree_hashes(t) for t in TARGETS]
    if hashes[0] != hashes[1]:
        write_json_durable(PROMOTION, {"state": "prepared", "targets": candidates})
        raise BuildError("as duas árvores promovidas divergem")
    write_json_durable(PROMOTION, {"state": "committed", "targets": candidates})
    log("promoção concluída e verificada (árvores idênticas)")


# --------------------------------------------------------------------------
def ensure_gitignore() -> None:
    path = PRES / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if "/.media-build/" not in text:
        path.write_text(text.rstrip("\n") + "\n\n/.media-build/\n", encoding="utf-8")
        log("adicionado /.media-build/ ao .gitignore")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep-staging", action="store_true",
                    help="preserva o diretório de staging após promover")
    args = ap.parse_args(argv)
    try:
        BUILD_DIR.mkdir(parents=True, exist_ok=True)
        ensure_gitignore()
        recover_promotion()
        check_tools()

        log("verificando/reparando mídias travadas")
        if mediamod.cmd_repair() != 0:
            raise BuildError("repair de mídias falhou; build abortado")

        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = BUILD_DIR / run_id
        staging = run_dir / "site"
        staging.parent.mkdir(parents=True, exist_ok=True)
        before = {t: tree_hashes(t) for t in TARGETS}

        render(f".media-build/{run_id}/site")
        if not (staging / "index.html").exists():
            raise BuildError(f"render não produziu {staging}/index.html")

        report = run_dir / "check-staging.json"
        code = audit(staging, report, require_receipt=False)
        if code != 0:
            fixed = restore_from_source(staging, report)
            if not fixed:
                raise BuildError("auditoria do staging falhou sem reparo possível")
            log(f"{fixed} recurso(s) restaurado(s); nova auditoria (única)")
            code = audit(staging, run_dir / "check-staging-2.json",
                         require_receipt=False)
            if code != 0:
                raise BuildError("auditoria do staging falhou após o reparo")

        make_receipt(staging)
        verify_receipt(staging)
        promote(staging, run_dir, before)
        if not args.keep_staging:
            shutil.rmtree(staging, ignore_errors=True)
        log("build concluído")
        return 0
    except (BuildError, mediamod.MediaError) as exc:
        log(f"ERRO: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
