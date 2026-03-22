import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from ..constants import MODRINTH_API_URL
from ..downloads import download_to_file
from ..instance import normalize_loader_name


def resolve_project_id(text: str) -> str:
    parsed = urllib.parse.urlparse(text.strip())
    if parsed.scheme in ("http", "https") and parsed.netloc:
        parts = [p for p in parsed.path.split("/") if p]
        if "mod" in parts:
            i = parts.index("mod")
            if i + 1 < len(parts):
                return parts[i + 1]
        if len(parts) >= 2 and parts[0] == "mod":
            return parts[1]
        if parts:
            return parts[-1]
    return text.strip()


def add_mod(
    text: str,
    mods_dir: Path,
    logger,
    target_mc_version: Optional[str],
    target_loader: Optional[str],
):
    project_id = resolve_project_id(text)

    with urllib.request.urlopen(f"{MODRINTH_API_URL}/project/{project_id}") as resp:
        proj = json.loads(resp.read().decode("utf-8"))

    real_id = proj.get("id") or project_id
    title = proj.get("title") or project_id

    params = {}
    if target_mc_version:
        params["game_versions"] = json.dumps([target_mc_version])
    if target_loader:
        params["loaders"] = json.dumps([normalize_loader_name(target_loader)])

    url = f"{MODRINTH_API_URL}/project/{real_id}/version"
    if params:
        url = url + "?" + urllib.parse.urlencode(params)

    try:
        with urllib.request.urlopen(url) as resp:
            versions = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        with urllib.request.urlopen(f"{MODRINTH_API_URL}/project/{real_id}/version") as resp:
            versions = json.loads(resp.read().decode("utf-8"))

    if not versions:
        raise RuntimeError(f"No versions found for Modrinth project {title}.")

    chosen = versions[0]
    files = chosen.get("files") or []
    if not files:
        raise RuntimeError("Modrinth version has no files.")

    main_file = None
    for f in files:
        if f.get("primary"):
            main_file = f
            break
    if main_file is None:
        main_file = files[0]

    file_url = main_file.get("url")
    filename = main_file.get("filename")
    if not file_url or not filename:
        raise RuntimeError("Modrinth file info missing.")

    target = mods_dir / filename
    logger(f"Downloading Modrinth mod '{title}' -> {filename}", source="LAUNCHER")
    download_to_file(file_url, target)
