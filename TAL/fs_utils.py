import os
import shutil
from pathlib import Path

from .paths import ASSETS_DIR, INSTALL_DIR, LIBRARIES_DIR


def copy_tree(src: str, dst: str):
    if not os.path.exists(src):
        return
    os.makedirs(dst, exist_ok=True)
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        dest_root = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(dest_root, exist_ok=True)
        for file in files:
            src_file = os.path.join(root, file)
            dst_file = os.path.join(dest_root, file)
            shutil.copy2(src_file, dst_file)


def clean_dir(path: str):
    if not os.path.exists(path):
        return
    for item in os.listdir(path):
        full = os.path.join(path, item)
        if os.path.isdir(full):
            shutil.rmtree(full)
        else:
            os.remove(full)


def merge_move_tree(src: Path, dst: Path):
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)

    for p in src.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.move(str(p), str(target))

    for p in sorted(src.rglob("*"), reverse=True):
        if p.is_dir():
            try:
                p.rmdir()
            except OSError:
                pass
    try:
        src.rmdir()
    except OSError:
        pass


def migrate_legacy_global_resources(logger=None):
    legacy_root = INSTALL_DIR / "global"
    if not legacy_root.exists():
        return

    legacy_libs = legacy_root / "libraries"
    legacy_assets = legacy_root / "assets"

    if logger:
        logger("Migrating legacy USERDIR/global -> USERDIR/{libraries,assets}...", source="LAUNCHER")

    merge_move_tree(legacy_libs, LIBRARIES_DIR)
    merge_move_tree(legacy_assets, ASSETS_DIR)

    try:
        shutil.rmtree(legacy_root)
    except OSError:
        pass
