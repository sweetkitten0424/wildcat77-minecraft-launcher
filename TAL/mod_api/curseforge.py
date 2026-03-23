import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from ..constants import (
    CURSEFORGE_API_KEY,
    CURSEFORGE_CORE_API_HOST,
    CURSEFORGE_CORE_API_URL,
    CURSEFORGE_GAME_ID_MINECRAFT,
    CURSEFORGE_MODLOADER_TYPE_IDS,
)
from ..downloads import download_to_file
from ..instance import normalize_loader_name


def api_request(path: str) -> dict:
    api_key = CURSEFORGE_API_KEY.strip()
    if not api_key:
        raise RuntimeError("CURSEFORGE_API_KEY is empty.")

    url = CURSEFORGE_CORE_API_URL.rstrip("/") + "/" + path.lstrip("/")
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    req.add_header("Host", CURSEFORGE_CORE_API_HOST)
    req.add_header("x-api-key", api_key)

    with urllib.request.urlopen(req) as resp:
        data = resp.read().decode("utf-8")
    return json.loads(data)


def resolve_project(text: str) -> int:
    parsed = urllib.parse.urlparse(text)
    slug = text.strip()
    if parsed.scheme in ("http", "https") and parsed.netloc:
        parts = [p for p in parsed.path.split("/") if p]
        if "mc-mods" in parts:
            i = parts.index("mc-mods")
            if i + 1 < len(parts):
                slug = parts[i + 1]

    q = urllib.parse.urlencode(
        {
            "gameId": CURSEFORGE_GAME_ID_MINECRAFT,
            "classId": 6,
            "searchFilter": slug,
            "pageSize": 1,
        }
    )
    data = api_request(f"mods/search?{q}")
    mods = data.get("data") or []
 []
    if not mods:
        raise RuntimeError(f"CurseForge project not found for '{text}'.")
    return int(mods[0]["id"])


def pick_file_for_mod(mod_id: int, target_mc_version: Optional[str], target_loader: Optional[str]) -> dict:
    query = {}
    if target_mc_version:
        query["gameVersion"] = target_mc_version

    if target_loader:
        norm_loader = normalize_loader_name(target_loader)
        mlt = CURSEFORGE_MODLOADER_TYPE_IDS.get(norm_loader)
        if mlt is not None:
            query["modLoaderType"] = mlt

    if query:
        try:
            data = api_request(f"mods/{mod_id}/files?{urllib.parse.urlencode(query)}")
            files = data.get("data", [])
            if files:
                return files[0]
        except Exception:
            pass

    data = api_request(f"mods/{mod_id}/files")
    files = data.get("data", [])
    if not files:
        raise RuntimeError(f"No files found for CurseForge mod id={mod_id}.")

    return files[0]


def add_mod(
    text: str,
    mods_dir: Path,
    logger,
    target_mc_version: Optional[str],
    target_loader: Optional[str],
):
    text = text.strip()
    parsed = urllib.parse.urlparse(text)
    path = parsed.path or ""
    is_http_url = parsed.scheme in ("http", "https") and parsed.netloc != ""

    if is_http_url and path.lower().endswith(".jar"):
        logger(f"Downloading CurseForge mod from direct URL '{text}'...", source="LAUNCHER")
        name = os.path.basename(path) or "curseforge_mod.jar"
        download_to_file(text, mods_dir / name)
        return

    if not CURSEFORGE_API_KEY.strip():
        raise RuntimeError("CURSEFORGE_API_KEY is empty. Set it or use a direct .jar URL.")

    if not is_http_url and text.isdigit():
        mod_id = int(text)
    else:
        mod_id = resolve_project(text)

    file_info = pick_file_for_mod(mod_id, target_mc_version, target_loader)
    file_name = file_info.get("fileName") or "curseforge_mod.jar"
    download_url = file_info.get("downloadUrl")
    if not download_url:
        raise RuntimeError("CurseForge file has no downloadUrl.")

    target = mods_dir / file_name
    logger(f"Downloading CurseForge mod id={mod_id} -> {file_name}", source="LAUNCHER")
    download_to_file(download_url, target)
