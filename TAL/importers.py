import json
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from .downloads import parallel_download_files


def import_curseforge_modpack(zip_path: Path, dest_modpack_dir: Path) -> Optional[dict]:
    manifest = None

    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()

        manifest_name = None
        for name in namelist:
            if name.endswith("manifest.json"):
                manifest_name = name
                break

        if manifest_name:
            with zf.open(manifest_name) as mf:
                manifest = json.loads(mf.read().decode("utf-8"))

        overrides_prefix = "overrides/"
        for name in namelist:
            if name.startswith(overrides_prefix) and not name.endswith("/"):
                rel = name[len(overrides_prefix):]
                target = dest_modpack_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as out_f:
                    shutil.copyfileobj(src, out_f)

    return manifest


def import_modrinth_modpack(zip_path: Path, dest_modpack_dir: Path, logger):
    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()

        index_name = None
        for name in namelist:
            if name.endswith("modrinth.index.json"):
                index_name = name
                break

        if not index_name:
            raise RuntimeError("modrinth.index.json not found in .mrpack")

        with zf.open(index_name) as idx_f:
            index = json.loads(idx_f.read().decode("utf-8"))

        files = index.get("files", [])
        download_tasks = []
        for file_info in files:
            path = file_info.get("path")
            downloads = file_info.get("downloads") or []
            if not path or not downloads:
                continue
            url = downloads[0]
            target = dest_modpack_dir / path
            download_tasks.append((url, target, f"mrpack {Path(path).name}"))

        if download_tasks:
            parallel_download_files(download_tasks, logger)

        overrides_prefix = "overrides/"
        for name in namelist:
            if name.startswith(overrides_prefix) and not name.endswith("/"):
                rel = name[len(overrides_prefix):]
                target = dest_modpack_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as out_f:
                    shutil.copyfileobj(src, out_f)

        return index
