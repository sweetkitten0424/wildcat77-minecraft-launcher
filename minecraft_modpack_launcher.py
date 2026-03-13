import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import urllib.request
import urllib.error
import urllib.parse
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from tkinter import (
    Tk,
    Frame,
    Label,
    Button,
    Listbox,
    Scrollbar,
    Entry,
    StringVar,
    Toplevel,
    filedialog,
    messagebox,
    SINGLE,
    END,
    OptionMenu,
    Text,
    DISABLED,
    NORMAL,
)

# --------------------------------------------------------------------------------------
# Configuration / constants
# --------------------------------------------------------------------------------------

APP_NAME = "BlockCraft Launcher"
LAUNCHER_VERSION = "1.3.0"

MODPACKS_DIR = "modpacks"

# Installation directory (this is USERDIR)
INSTALL_DIR = Path(__file__).resolve().parent

# ATLauncher-like configs layout (matches your screenshots)
CONFIGS_DIR = INSTALL_DIR / "configs"
CONFIGS_COMMON_DIR = CONFIGS_DIR / "common"
CONFIGS_IMAGES_DIR = CONFIGS_DIR / "images"
CONFIGS_SKINS_DIR = CONFIGS_IMAGES_DIR / "skins"
CONFIGS_JSON_DIR = CONFIGS_DIR / "json"
CONFIGS_JSON_MINECRAFT_DIR = CONFIGS_JSON_DIR / "minecraft"
CONFIGS_THEMES_DIR = CONFIGS_DIR / "themes"

# Primary launcher settings file (ATLauncher uses configs/json/config.json)
CONFIG_FILE = CONFIGS_JSON_DIR / "config.json"
LEGACY_CONFIG_FILE = INSTALL_DIR / "launcher_config.json"

# Additional ATLauncher-like files (created for structure parity)
ATLAUNCHER_JSON_FILE = CONFIGS_DIR / "ATLauncher.json"
ACCOUNTS_JSON_FILE = CONFIGS_DIR / "accounts.json"
JAVA_RUNTIMES_JSON_FILE = CONFIGS_JSON_DIR / "java_runtimes.json"
LWJGL_JSON_FILE = CONFIGS_JSON_DIR / "lwjgl.json"
MINECRAFT_VERSIONS_JSON_FILE = CONFIGS_JSON_DIR / "minecraft_versions.json"
NEWNEWS_JSON_FILE = CONFIGS_JSON_DIR / "newnews.json"
PACKSNEW_JSON_FILE = CONFIGS_JSON_DIR / "packsnew.json"
RUNTIMES_JSON_FILE = CONFIGS_JSON_DIR / "runtimes.json"
USERS_JSON_FILE = CONFIGS_JSON_DIR / "users.json"
VERSION_JSON_FILE = CONFIGS_JSON_DIR / "version.json"

# Java runtime configuration
JAVA_RUNTIME_DIR_NAME = "runtime"
JAVA_RUNTIME_VERSION = "21.0.7"  # version we expect
JAVA_RUNTIME_VERSION_FILE = "java_runtime_version.txt"

# Vanilla args directory and pattern
VANILLA_DIR = INSTALL_DIR / "vanilla"  # all args files live here

# Shared resources (download once, reused by all versions/instances)
# Stored at:
#   USERDIR/libraries
#   USERDIR/assets
GLOBAL_LIBRARIES_DIR = INSTALL_DIR / "libraries"
GLOBAL_ASSETS_DIR = INSTALL_DIR / "assets"

# Mojang endpoints
VERSION_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
ASSET_BASE_URL = "https://resources.download.minecraft.net"

# Oracle JDK ZIP you’re using
JAVA_RUNTIME_ZIP_URL = (
    "https://download.oracle.com/java/21/latest/jdk-21_windows-x64_bin.zip"
)

# Parallel downloads configuration
PARALLEL_DOWNLOADS_ENABLED = True
MAX_PARALLEL_DOWNLOADS = 50

# CurseForge API key (hard-coded).
# WARNING: Anyone who can read this file can see your key.
# Replace the placeholder with your real key string.
CURSEFORGE_API_KEY = ""


def ensure_configs_layout():
    CONFIGS_COMMON_DIR.mkdir(parents=True, exist_ok=True)
    CONFIGS_SKINS_DIR.mkdir(parents=True, exist_ok=True)
    CONFIGS_JSON_MINECRAFT_DIR.mkdir(parents=True, exist_ok=True)
    CONFIGS_THEMES_DIR.mkdir(parents=True, exist_ok=True)

    def write_if_missing(path: Path, obj):
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, indent=2), encoding="utf-8")

    write_if_missing(ATLAUNCHER_JSON_FILE, {"appName": APP_NAME, "version": LAUNCHER_VERSION})
    write_if_missing(ACCOUNTS_JSON_FILE, {"accounts": [], "selectedAccount": None})

    # Create the files shown in ATLauncher configs/json.
    write_if_missing(JAVA_RUNTIMES_JSON_FILE, {})
    write_if_missing(LWJGL_JSON_FILE, {})
    write_if_missing(MINECRAFT_VERSIONS_JSON_FILE, {})
    write_if_missing(NEWNEWS_JSON_FILE, {})
    write_if_missing(PACKSNEW_JSON_FILE, {})
    write_if_missing(RUNTIMES_JSON_FILE, {})
    write_if_missing(USERS_JSON_FILE, {})
    write_if_missing(VERSION_JSON_FILE, {"launcherVersion": LAUNCHER_VERSION})


def _default_config() -> dict:
    return {
        "minecraft_dir": "",
        "last_selected_modpack": "",
        "java_runtime_version": "",
        # auth / game placeholders (basic, manual for now)
        "auth_player_name": "Player",
        "auth_uuid": "00000000-0000-0000-0000-000000000000",
        "auth_access_token": "0",
        "user_type": "mojang",
        "version_type": "release",
    }


def load_config():
    ensure_configs_layout()

    if not CONFIG_FILE.exists() and LEGACY_CONFIG_FILE.exists():
        try:
            legacy = json.loads(LEGACY_CONFIG_FILE.read_text(encoding="utf-8"))
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(legacy, indent=4), encoding="utf-8")
            try:
                LEGACY_CONFIG_FILE.unlink()
            except OSError:
                pass
        except Exception:
            pass

    if not CONFIG_FILE.exists():
        data = _default_config()
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
    else:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

    defaults = _default_config()
    for k, v in defaults.items():
        data.setdefault(k, v)

    return data


def save_config(config):
    ensure_configs_layout()
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)


def ensure_modpacks_dir():
    os.makedirs(MODPACKS_DIR, exist_ok=True)


def list_modpacks():
    ensure_modpacks_dir()
    entries = []
    for p in sorted(Path(MODPACKS_DIR).iterdir()):
        if p.is_dir():
            entries.append(p.name)
    return entries


def copy_tree(src, dst):
    if not os.path.exists(src):
        return
    os.makedirs(dst, exist_ok=True)
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        dest_root = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(dest_root, exist_ok=True)
        for file in files:
            src_file = os.path.join(root, file)
            dst_file = os.path.join(dest_root, file)
            shutil.copy2(src_file, dst_file)


def clean_dir(path):
    if not os.path.exists(path):
        return
    for item in os.listdir(path):
        full = os.path.join(path, item)
        if os.path.isdir(full):
            shutil.rmtree(full)
        else:
            os.remove(full)


def download_to_file(url: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as out_f:
        shutil.copyfileobj(resp, out_f)


def parallel_download_files(download_tasks: list, logger, max_workers: int = MAX_PARALLEL_DOWNLOADS):
    """Download multiple files in parallel.

    download_tasks: list of (url, dest_path, description)
    """
    if not download_tasks:
        return

    total = len(download_tasks)
    log_every = 1 if total <= 200 else 50

    if not PARALLEL_DOWNLOADS_ENABLED or total <= 1:
        done = 0
        for url, dest, desc in download_tasks:
            done += 1
            logger(f"Downloading {desc}...", source="LAUNCHER")
            download_to_file(url, dest)
            if log_every != 1 and (done % log_every == 0 or done == total):
                logger(f"Downloaded {done}/{total} files...", source="LAUNCHER")
        return

    def task_runner(task):
        url, dest, desc = task
        download_to_file(url, dest)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(task_runner, t): t for t in download_tasks}
        done = 0
        for f in as_completed(futures):
            url, dest, desc = futures[f]
            try:
                f.result()
            except Exception as e:
                logger(f"Failed to download {desc}: {e}", source="LAUNCHER")
                raise
            done += 1
            if log_every == 1:
                logger(f"Downloaded {desc} ({done}/{total})", source="LAUNCHER")
            elif done % log_every == 0 or done == total:
                logger(f"Downloaded {done}/{total} files...", source="LAUNCHER")


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


def migrate_legacy_args_files(logger=None):
    if not VANILLA_DIR.exists():
        return

    libs_root = str(GLOBAL_LIBRARIES_DIR.resolve())
    assets_root = str(GLOBAL_ASSETS_DIR.resolve())
    libs_root_posix = GLOBAL_LIBRARIES_DIR.resolve().as_posix()
    assets_root_posix = GLOBAL_ASSETS_DIR.resolve().as_posix()

    for p in VANILLA_DIR.glob("java_args_*.txt"):
        version_id = p.stem.replace("java_args_", "", 1)

        legacy_version_root = VANILLA_DIR / version_id
        legacy_libs = legacy_version_root / "libraries"
        legacy_assets = legacy_version_root / "assets"
        legacy_client = legacy_version_root / "versions" / version_id / f"{version_id}.jar"

        new_client = (
            GLOBAL_LIBRARIES_DIR
            / "net"
            / "minecraft"
            / "client"
            / version_id
            / f"{version_id}.jar"
        )

        replacements = []
        for src_path, dst_path in (
            (str(legacy_libs.resolve()), libs_root),
            (legacy_libs.resolve().as_posix(), libs_root_posix),
            (str(legacy_assets.resolve()), assets_root),
            (legacy_assets.resolve().as_posix(), assets_root_posix),
            (str(legacy_client.resolve()), str(new_client.resolve())),
            (legacy_client.resolve().as_posix(), new_client.resolve().as_posix()),
        ):
            replacements.append((src_path, dst_path))

        try:
            content = p.read_text(encoding="utf-8")
        except OSError:
            continue

        updated = content
        for src_path, dst_path in replacements:
            if src_path and dst_path:
                updated = updated.replace(src_path, dst_path)

        if updated != content:
            try:
                p.write_text(updated, encoding="utf-8")
                if logger:
                    logger(f"Updated args file paths: {p.name}")
            except OSError:
                pass


def migrate_legacy_vanilla_version_resources(logger=None):
    if not VANILLA_DIR.exists():
        return

    ensure_configs_layout()

    for version_root in sorted(VANILLA_DIR.iterdir()):
        if not version_root.is_dir():
            continue
        version_id = version_root.name

        legacy_libs = version_root / "libraries"
        legacy_assets = version_root / "assets"
        legacy_client = version_root / "versions" / version_id / f"{version_id}.jar"
        legacy_version_json = version_root / f"{version_id}.json"

        new_client_dir = GLOBAL_LIBRARIES_DIR / "net" / "minecraft" / "client" / version_id
        new_client = new_client_dir / f"{version_id}.jar"

        if legacy_libs.exists():
            if logger:
                logger(f"Migrating legacy vanilla libraries for {version_id}...")
            merge_move_tree(legacy_libs, GLOBAL_LIBRARIES_DIR)

        if legacy_assets.exists():
            if logger:
                logger(f"Migrating legacy vanilla assets for {version_id}...")
            merge_move_tree(legacy_assets, GLOBAL_ASSETS_DIR)

        if legacy_client.exists() and not new_client.exists():
            new_client_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(legacy_client), str(new_client))
            except OSError:
                try:
                    shutil.copy2(legacy_client, new_client)
                except OSError:
                    pass

        # Migrate legacy stored version JSON into configs/json/minecraft/<version>.json
        if legacy_version_json.exists():
            target = CONFIGS_JSON_MINECRAFT_DIR / f"{version_id}.json"
            if not target.exists():
                try:
                    shutil.move(str(legacy_version_json), str(target))
                except OSError:
                    try:
                        shutil.copy2(legacy_version_json, target)
                    except OSError:
                        pass

        legacy_versions_dir = version_root / "versions"
        if legacy_versions_dir.exists():
            # best-effort cleanup; keep if other data remains
            for p in sorted(legacy_versions_dir.rglob("*"), reverse=True):
                if p.is_dir():
                    try:
                        p.rmdir()
                    except OSError:
                        pass
            try:
                legacy_versions_dir.rmdir()
            except OSError:
                pass


# --------------------------------------------------------------------------------------
# Shared resources migration (remove legacy USERDIR/global)
# --------------------------------------------------------------------------------------

def migrate_legacy_global_resources(logger=None):
    """Migrate the legacy USERDIR/global folder.

    We no longer use USERDIR/global; shared resources now live at:
      USERDIR/libraries
      USERDIR/assets

    This migrates what we can, then removes USERDIR/global.
    """
    legacy_root = INSTALL_DIR / "global"
    if not legacy_root.exists():
        return

    legacy_libs = legacy_root / "libraries"
    legacy_assets = legacy_root / "assets"
    legacy_versions_dir = legacy_root / "versions"

    if logger:
        logger("Migrating legacy resources (USERDIR/global) -> USERDIR/{libraries,assets}...")

    merge_move_tree(legacy_libs, GLOBAL_LIBRARIES_DIR)
    merge_move_tree(legacy_assets, GLOBAL_ASSETS_DIR)

    # Migrate any legacy vanilla jars stored under USERDIR/global/versions/<ver>/<ver>.jar
    if legacy_versions_dir.exists():
        for ver_dir in legacy_versions_dir.iterdir():
            if not ver_dir.is_dir():
                continue
            version_id = ver_dir.name
            jar = ver_dir / f"{version_id}.jar"
            if not jar.exists():
                continue

            target_dir = GLOBAL_LIBRARIES_DIR / "net" / "minecraft" / "client" / version_id
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{version_id}.jar"

            if not target.exists():
                try:
                    shutil.move(str(jar), str(target))
                except OSError:
                    try:
                        shutil.copy2(jar, target)
                    except OSError:
                        pass

        # best-effort cleanup
        for p in sorted(legacy_versions_dir.rglob("*"), reverse=True):
            if p.is_dir():
                try:
                    p.rmdir()
                except OSError:
                    pass
        try:
            legacy_versions_dir.rmdir()
        except OSError:
            pass

    # Update existing args files that referenced USERDIR/global/{libraries,assets,versions}.
    legacy_libs_str = str(legacy_libs.resolve())
    legacy_assets_str = str(legacy_assets.resolve())
    legacy_versions_str = str((legacy_root / "versions").resolve())

    new_libs_str = str(GLOBAL_LIBRARIES_DIR.resolve())
    new_assets_str = str(GLOBAL_ASSETS_DIR.resolve())

    if VANILLA_DIR.exists():
        for p in VANILLA_DIR.glob("java_args_*.txt"):
            try:
                content = p.read_text(encoding="utf-8")
            except OSError:
                continue

            updated = (
                content
                .replace(legacy_libs_str, new_libs_str)
                .replace(legacy_assets_str, new_assets_str)
                .replace(legacy_versions_str, new_libs_str)
            )
            if updated != content:
                try:
                    p.write_text(updated, encoding="utf-8")
                except OSError:
                    pass

    # Remove legacy_root completely (it should be empty after migrations above).
    try:
        shutil.rmtree(legacy_root)
    except OSError:
        pass


# --------------------------------------------------------------------------------------
# Instance metadata (instance.json)
# --------------------------------------------------------------------------------------

def instance_json_path_for_modpack(mp_dir: Path) -> Path:
    return mp_dir / "instance.json"


def load_instance_json(mp_dir: Path) -> Optional[dict]:
    path = instance_json_path_for_modpack(mp_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_instance_json(mp_dir: Path, data: dict):
    path = instance_json_path_for_modpack(mp_dir)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_instance_minecraft_version(instance: Optional[dict]) -> Optional[str]:
    if not instance:
        return None

    launcher = instance.get("launcher") or {}

    # Prefer CurseForge file data when present
    curse_file = launcher.get("curseForgeFile") or {}
    for v in (curse_file.get("gameVersions") or []):
        if isinstance(v, str) and v and v[0].isdigit():
            return v

    # Fall back to loaderVersion rawVersion like "1.20.1-47.3.11"
    lv = launcher.get("loaderVersion") or {}
    raw = lv.get("rawVersion")
    if isinstance(raw, str) and raw:
        return raw.split("-")[0]

    return None


def normalize_loader_name(loader: str) -> str:
    loader = (loader or "").strip().lower()
    if loader in {"minecraftforge", "forge"}:
        return "forge"
    if loader in {"neoforge", "neo"}:
        return "neoforge"
    if loader in {"fabric"}:
        return "fabric"
    if loader in {"quilt"}:
        return "quilt"
    return loader


def get_instance_loader(instance: Optional[dict]) -> Optional[str]:
    if not instance:
        return None
    lv = ((instance.get("launcher") or {}).get("loaderVersion") or {})
    t = lv.get("type")
    if isinstance(t, str) and t:
        return normalize_loader_name(t)
    return None


def infer_minecraft_version_from_args_filename(args_file_name: str) -> Optional[str]:
    import re

    m = re.search(r"java_args_(\d+\.\d+(?:\.\d+)?).txt", args_file_name or "")
    if not m:
        return None
    return m.group(1)


def create_default_instance_json(mp_dir: Path, name: str) -> dict:
    return {
        "uuid": str(uuid.uuid4()),
        "launcher": {
            "name": name,
            "pack": name,
            "description": "",
            "packId": 0,
            "externalPackId": 0,
            "version": "1.0.0",
            "enableCurseForgeIntegration": False,
            "enableEditingMods": True,
            "loaderVersion": {
                "version": "",
                "rawVersion": "",
                "recommended": False,
                "type": "Forge",
                "downloadables": {},
            },
            "requiredMemory": 0,
            "requiredPermGen": 0,
            "maximumMemory": 4096,
            "additionalJvmArgs": "",
            "quickPlay": {},
            "isDev": False,
            "isPlayable": True,
            "assetsMapToResources": False,
            "checkForUpdates": True,
            "overridePaths": [],
            "mods": [],
        },
    }


# --------------------------------------------------------------------------------------
# Java runtime management
# --------------------------------------------------------------------------------------

def get_java_runtime_dir() -> Path:
    return INSTALL_DIR / JAVA_RUNTIME_DIR_NAME


def get_java_executable() -> Path:
    """Path to the bundled javaw.exe (Windows)."""
    if sys.platform.startswith("win"):
        return get_java_runtime_dir() / "bin" / "javaw.exe"
    return Path("java")


def read_local_java_runtime_version(config) -> str:
    cfg_version = config.get("java_runtime_version") or ""
    if cfg_version:
        return cfg_version

    version_file = get_java_runtime_dir() / JAVA_RUNTIME_VERSION_FILE
    if version_file.exists():
        try:
            return version_file.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


def write_local_java_runtime_version(config, version: str):
    config["java_runtime_version"] = version
    save_config(config)
    version_file = get_java_runtime_dir() / JAVA_RUNTIME_VERSION_FILE
    try:
        version_file.parent.mkdir(parents=True, exist_ok=True)
        version_file.write_text(version, encoding="utf-8")
    except OSError:
        pass


def extract_zip(zip_path: Path, dest_dir: Path):
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)


def ensure_java_runtime(config, logger):
    """Ensure Java runtime is downloaded and up to date."""
    if not sys.platform.startswith("win"):
        return

    current_local = read_local_java_runtime_version(config)
    desired = JAVA_RUNTIME_VERSION

    java_exe = get_java_executable()
    if current_local == desired and java_exe.exists():
        return

    try:
        logger(f"Downloading Java runtime {desired}...")
        java_dir = get_java_runtime_dir()
        if java_dir.exists():
            shutil.rmtree(java_dir)

        java_dir.mkdir(parents=True, exist_ok=True)
        zip_path = INSTALL_DIR / "java-runtime-download.zip"

        logger("Downloading Java runtime zip...")
        download_to_file(JAVA_RUNTIME_ZIP_URL, zip_path)

        logger("Extracting Java runtime...")
        extract_zip(zip_path, java_dir)

        try:
            zip_path.unlink()
        except OSError:
            pass

        # Flatten Oracle JDK top-level folder if present
        children = list(java_dir.iterdir())
        if len(children) == 1 and children[0].is_dir():
            inner = children[0]
            for item in inner.iterdir():
                target = java_dir / item.name
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                shutil.move(str(item), str(target))
            try:
                inner.rmdir()
            except OSError:
                pass

        write_local_java_runtime_version(config, desired)
        logger(f"Java runtime {desired} ready.")

    except urllib.error.URLError as e:
        logger(f"Failed to download Java runtime: {e}")
        messagebox.showerror(
            "Java download error",
            f"Could not download Java runtime.\n\n{e}",
        )
    except Exception as e:
        logger(f"Failed to prepare Java runtime: {e}")
        messagebox.showerror(
            "Java error",
            f"Failed to prepare Java runtime.\n\n{e}",
        )


# --------------------------------------------------------------------------------------
# CurseForge / Modrinth import helpers (modpacks)
# --------------------------------------------------------------------------------------

def import_curseforge_modpack(zip_path: Path, dest_modpack_dir: Path) -> Optional[dict]:
    """Import a CurseForge modpack zip: extract overrides/ into the modpack.

    Returns the parsed manifest.json dict if present.
    """
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
    """Import a Modrinth .mrpack into the modpack folder."""
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


# --------------------------------------------------------------------------------------
# Vanilla version download via Mojang (generic)
# --------------------------------------------------------------------------------------

def fetch_version_manifest():
    with urllib.request.urlopen(VERSION_MANIFEST_URL) as resp:
        manifest = json.loads(resp.read().decode("utf-8"))

    # Mirror ATLauncher-style cached manifest name.
    ensure_configs_layout()
    try:
        MINECRAFT_VERSIONS_JSON_FILE.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except OSError:
        pass

    return manifest


def find_version_in_manifest(manifest, version_id: str):
    versions = manifest.get("versions", [])
    for v in versions:
        if v.get("id") == version_id:
            return v
    return None


def download_vanilla_version(version_id: str, config, logger) -> Path:
    """Download vanilla client + libs + assets; generate java_args_<version>.txt.

    Uses shared libraries/assets folders so all versions can reuse them.
    """
    logger(f"Fetching manifest for version {version_id}...")
    manifest = fetch_version_manifest()
    v_entry = find_version_in_manifest(manifest, version_id)
    if not v_entry:
        raise RuntimeError(f"Version {version_id} not found in Mojang manifest.")

    version_url = v_entry["url"]
    logger(f"Downloading version JSON for {version_id}...")
    with urllib.request.urlopen(version_url) as resp:
        version_data = json.loads(resp.read().decode("utf-8"))

    # Version JSON files are stored like ATLauncher:
    #   USERDIR/configs/json/minecraft/<version>.json
    # We still keep USERDIR/vanilla/<version>/ for legacy migration helpers.
    version_root = VANILLA_DIR / version_id
    version_root.mkdir(parents=True, exist_ok=True)

    ensure_configs_layout()
    try:
        mc_json_path = CONFIGS_JSON_MINECRAFT_DIR / f"{version_id}.json"
        mc_json_path.write_text(json.dumps(version_data, indent=2), encoding="utf-8")
    except OSError:
        pass

    GLOBAL_LIBRARIES_DIR.mkdir(parents=True, exist_ok=True)
    GLOBAL_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # Store the vanilla client jar in the shared libraries folder in a Maven-like layout:
    #   USERDIR/libraries/net/minecraft/client/<mcVersion>/<mcVersion>.jar
    client_dir = GLOBAL_LIBRARIES_DIR / "net" / "minecraft" / "client" / version_id
    client_dir.mkdir(parents=True, exist_ok=True)

    client_download = version_data["downloads"]["client"]
    client_url = client_download["url"]
    client_jar_path = client_dir / f"{version_id}.jar"

    # Migrate legacy per-version client jar if present.
    legacy_client_jar = version_root / "versions" / version_id / f"{version_id}.jar"
    if not client_jar_path.exists() and legacy_client_jar.exists():
        try:
            shutil.copy2(legacy_client_jar, client_jar_path)
        except OSError:
            pass

    if not client_jar_path.exists():
        logger(f"Downloading client JAR for {version_id}...")
        download_to_file(client_url, client_jar_path)

    libraries = version_data.get("libraries", [])
    download_tasks = []

    for lib in libraries:
        downloads = lib.get("downloads", {})
        artifact = downloads.get("artifact")
        if not artifact:
            continue
        path = artifact.get("path")
        url = artifact.get("url")
        if not path or not url:
            continue
        target = GLOBAL_LIBRARIES_DIR / Path(path)
        if target.exists():
            continue
        download_tasks.append((url, target, f"library {Path(path).name}"))

    if download_tasks:
        parallel_download_files(download_tasks, logger)

    asset_index_info = version_data.get("assetIndex")
    if asset_index_info:
        asset_index_url = asset_index_info["url"]
        logger(f"Downloading asset index for {version_id}...")
        with urllib.request.urlopen(asset_index_url) as resp:
            asset_index = json.loads(resp.read().decode("utf-8"))

        (GLOBAL_ASSETS_DIR / "indexes").mkdir(parents=True, exist_ok=True)
        (GLOBAL_ASSETS_DIR / "indexes" / f"{asset_index_info['id']}.json").write_text(
            json.dumps(asset_index, indent=2), encoding="utf-8"
        )

        objects_dir = GLOBAL_ASSETS_DIR / "objects"
        objects_dir.mkdir(parents=True, exist_ok=True)

        objects = asset_index.get("objects", {})
        download_tasks = []

        for name, obj in objects.items():
            hash_ = obj["hash"]
            prefix = hash_[:2]
            url = f"{ASSET_BASE_URL}/{prefix}/{hash_}"
            target = objects_dir / prefix / hash_
            if target.exists():
                continue
            download_tasks.append((url, target, f"asset {name}"))

        if download_tasks:
            parallel_download_files(download_tasks, logger)

    args_file = generate_java_args_from_version_json(
        version_id,
        version_data,
        GLOBAL_LIBRARIES_DIR,
        GLOBAL_ASSETS_DIR,
        config,
    )

    logger(f"Downloaded vanilla {version_id}. Args file: {args_file}")
    return args_file


def generate_java_args_from_version_json(
    version_id: str,
    version_data: dict,
    libraries_dir: Path,
    assets_dir: Path,
    config: dict,
) -> Path:
    """Build a java_args_<version>.txt based on Mojang's version JSON.

    Libraries are expected to be stored in a Maven-like directory layout.
    The vanilla client jar is stored at:
      USERDIR/libraries/net/minecraft/client/<mcVersion>/<mcVersion>.jar
    """
    jvm_args = []
    game_args = []

    arguments = version_data.get("arguments")
    if arguments:
        jvm = arguments.get("jvm", [])
        game = arguments.get("game", [])
        for item in jvm:
            if isinstance(item, str):
                jvm_args.append(item)
        for item in game:
            if isinstance(item, str):
                game_args.append(item)
    else:
        legacy_args = version_data.get("minecraftArguments", "")
        if legacy_args:
            game_args.extend(legacy_args.split())

    # Build classpath from the Mojang version manifest so we only include the
    # libraries required for this specific version.
    cp_entries = []
    seen = set()

    for lib in version_data.get("libraries", []):
        downloads = lib.get("downloads", {})
        artifact = downloads.get("artifact")
        if not artifact:
            continue
        rel_path = artifact.get("path")
        if not rel_path:
            continue
        jar_path = str(libraries_dir / Path(rel_path))
        if jar_path in seen:
            continue
        seen.add(jar_path)
        cp_entries.append(jar_path)

    client_jar = libraries_dir / "net" / "minecraft" / "client" / version_id / f"{version_id}.jar"
    client_jar_str = str(client_jar)
    if client_jar.exists() and client_jar_str not in seen:
        cp_entries.append(client_jar_str)

    classpath = ";".join(cp_entries) if sys.platform.startswith("win") else ":".join(cp_entries)

    jvm_args.extend(["-cp", classpath])

    main_class = version_data.get("mainClass", "net.minecraft.client.main.Main")

    game_dir = config.get("minecraft_dir") or str((INSTALL_DIR / "instances" / version_id).resolve())
    assets_root = str(assets_dir.resolve())
    assets_index_name = version_data.get("assetIndex", {}).get("id", "assets")

    substitutions = {
        "${auth_player_name}": config.get("auth_player_name", "Player"),
        "${version_name}": version_id,
        "${game_directory}": game_dir,
        "${assets_root}": assets_root,
        "${assets_index_name}": assets_index_name,
        "${auth_uuid}": config.get("auth_uuid", "00000000-0000-0000-0000-000000000000"),
        "${auth_access_token}": config.get("auth_access_token", "0"),
        "${user_type}": config.get("user_type", "mojang"),
        "${version_type}": config.get("version_type", "release"),
        "${clientid}": "0",
        "${auth_xuid}": "",
    }

    def apply_substitutions(arg: str) -> str:
        for key, value in substitutions.items():
            arg = arg.replace(key, value)
        return arg

    game_args = [apply_substitutions(a) for a in game_args]

    args_lines = []
    for a in jvm_args:
        args_lines.append(a)
    args_lines.append(main_class)
    for a in game_args:
        args_lines.append(a)

    VANILLA_DIR.mkdir(parents=True, exist_ok=True)
    args_file = VANILLA_DIR / f"java_args_{version_id}.txt"
    args_file.write_text("\n".join(args_lines), encoding="utf-8")
    return args_file


# --------------------------------------------------------------------------------------
# GUI application with console + mod downloads
# --------------------------------------------------------------------------------------

class MinecraftLauncherApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("980x540")
        self.root.minsize(880, 460)

        self.bg_color = "#2b3a1f"
        self.panel_color = "#3e4f29"
        self.button_color = "#5f7a35"
        self.button_hover_color = "#7ea843"
        self.accent_color = "#c2a162"
        self.text_color = "#f4f4e2"

        self.root.configure(bg=self.bg_color)

        self.config = load_config()
        ensure_modpacks_dir()

        self.selected_modpack = StringVar()
        self.status_var = StringVar()
        self.status_var.set("Starting...")

        self.args_file_var = StringVar()

        self.console_window = None
        self.console_text = None
        self.console_scroll_lock = False

        self._build_ui()
        self._load_modpacks_into_list()
        self._restore_last_selection()
        self._refresh_args_file_options()

        threading.Thread(target=self._background_startup_tasks, daemon=True).start()

    # ----- console logger -----

    def log(self, text: str, source: str = "LAUNCHER"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{source}]"
        line = f"[{timestamp}] {prefix} {text}"

        if source == "LAUNCHER":
            self.status_var.set(text)

        if self.console_text is not None:
            self.console_text.config(state=NORMAL)
            self.console_text.insert(END, line + "\n")
            if not self.console_scroll_lock:
                self.console_text.see(END)
            self.console_text.config(state=DISABLED)

    def open_console_window(self):
        if self.console_window is not None and self.console_window.winfo_exists():
            self.console_window.lift()
            return

        self.console_window = Toplevel(self.root)
        self.console_window.title("BlockCraft Launcher Console")
        self.console_window.geometry("900x450")
        self.console_window.configure(bg="#1c2413")

        toolbar = Frame(self.console_window, bg="#2b3a1f")
        toolbar.pack(fill="x", side="top")

        clear_btn = Button(
            toolbar,
            text="Clear",
            command=self.console_clear,
            bg="#4d5c32",
            fg=self.text_color,
            activebackground=self.button_hover_color,
            activeforeground=self.text_color,
            relief="flat",
            padx=10,
            pady=3,
        )
        clear_btn.pack(side="left", padx=5, pady=3)

        copy_btn = Button(
            toolbar,
            text="Copy",
            command=self.console_copy_all,
            bg="#4d5c32",
            fg=self.text_color,
            activebackground=self.button_hover_color,
            activeforeground=self.text_color,
            relief="flat",
            padx=10,
            pady=3,
        )
        copy_btn.pack(side="left", padx=5, pady=3)

        save_btn = Button(
            toolbar,
            text="Save",
            command=self.console_save_to_file,
            bg="#4d5c32",
            fg=self.text_color,
            activebackground=self.button_hover_color,
            activeforeground=self.text_color,
            relief="flat",
            padx=10,
            pady=3,
        )
        save_btn.pack(side="left", padx=5, pady=3)

        self.scroll_lock_btn = Button(
            toolbar,
            text="Scroll Lock: OFF",
            command=self.console_toggle_scroll_lock,
            bg="#4d5c32",
            fg=self.text_color,
            activebackground=self.button_hover_color,
            activeforeground=self.text_color,
            relief="flat",
            padx=10,
            pady=3,
        )
        self.scroll_lock_btn.pack(side="right", padx=5, pady=3)

        text_frame = Frame(self.console_window, bg="#1c2413")
        text_frame.pack(fill="both", expand=True)

        text_widget = Text(
            text_frame,
            bg="#101509",
            fg=self.text_color,
            insertbackground=self.text_color,
            state=DISABLED,
            wrap="none",
            font=("Consolas", 9),
        )
        text_widget.pack(side="left", fill="both", expand=True, padx=5, pady=5)

        scroll = Scrollbar(text_frame, command=text_widget.yview)
        scroll.pack(side="right", fill="y")
        text_widget.config(yscrollcommand=scroll.set)

        self.console_text = text_widget

        self.log("Console opened.", source="LAUNCHER")

        def on_close():
            self.console_window.destroy()
            self.console_window = None
            self.console_text = None

        self.console_window.protocol("WM_DELETE_WINDOW", on_close)

    def console_clear(self):
        if self.console_text is None:
            return
        self.console_text.config(state=NORMAL)
        self.console_text.delete("1.0", END)
        self.console_text.config(state=DISABLED)

    def console_copy_all(self):
        if self.console_text is None:
            return
        text = self.console_text.get("1.0", END)
        self.console_window.clipboard_clear()
        self.console_window.clipboard_append(text)

    def console_save_to_file(self):
        if self.console_text is None:
            return
        content = self.console_text.get("1.0", END)
        default_name = f"BlockCraftConsole_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        path = filedialog.asksaveasfilename(
            title="Save console log",
            defaultextension=".log",
            initialfile=default_name,
            filetypes=[("Log files", "*.log"), ("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self.log(f"Console log saved to {path}.")
        except Exception as e:
            messagebox.showerror("Save error", f"Could not save log:\n{e}")

    def console_toggle_scroll_lock(self):
        self.console_scroll_lock = not self.console_scroll_lock
        state = "ON" if self.console_scroll_lock else "OFF"
        if self.scroll_lock_btn:
            self.scroll_lock_btn.config(text=f"Scroll Lock: {state}")

    # ----- background tasks -----

    def _background_startup_tasks(self):
        ensure_configs_layout()
        GLOBAL_LIBRARIES_DIR.mkdir(parents=True, exist_ok=True)
        GLOBAL_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        migrate_legacy_global_resources(self.log)
        migrate_legacy_vanilla_version_resources(self.log)
        migrate_legacy_args_files(self.log)
        ensure_java_runtime(self.config, self.log)
        self.log("Ready.")

    # ----- UI building -----

    def _build_ui(self):
        header = Frame(self.root, bg=self.panel_color, height=60)
        header.pack(fill="x", side="top")

        title_label = Label(
            header,
            text=f"{APP_NAME} v{LAUNCHER_VERSION}",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 20, "bold"),
        )
        title_label.pack(side="left", padx=20, pady=10)

        settings_frame = Frame(header, bg=self.panel_color)
        settings_frame.pack(side="right", padx=10)

        self._mk_header_button(
            settings_frame,
            "Console",
            self.open_console_window,
        ).pack(side="left", padx=5)

        self._mk_header_button(
            settings_frame,
            "Minecraft Folder",
            self.choose_minecraft_dir,
        ).pack(side="left", padx=5)

        self._mk_header_button(
            settings_frame,
            "Install Vanilla Version",
            self.install_vanilla_version_dialog,
        ).pack(side="left", padx=5)

        main_frame = Frame(self.root, bg=self.bg_color)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        left_frame = Frame(main_frame, bg=self.panel_color, bd=2)
        left_frame.pack(side="left", fill="y", padx=(0, 10), pady=0)

        right_frame = Frame(main_frame, bg=self.panel_color, bd=2)
        right_frame.pack(side="right", fill="both", expand=True, pady=0)

        list_label = Label(
            left_frame,
            text="Modpacks",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 14, "bold"),
        )
        list_label.pack(anchor="w", padx=10, pady=(10, 5))

        listbox_frame = Frame(left_frame, bg=self.panel_color)
        listbox_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.modpack_listbox = Listbox(
            listbox_frame,
            bg="#1f2616",
            fg=self.text_color,
            selectbackground=self.button_color,
            selectforeground=self.text_color,
            highlightthickness=0,
            borderwidth=0,
            activestyle="none",
            font=("Helvetica", 11),
            selectmode=SINGLE,
        )
        self.modpack_listbox.pack(side="left", fill="both", expand=True)

        scrollbar = Scrollbar(listbox_frame, command=self.modpack_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.modpack_listbox.config(yscrollcommand=scrollbar.set)
        self.modpack_listbox.bind("<<ListboxSelect>>", self._on_modpack_selected)

        mp_button_frame = Frame(left_frame, bg=self.panel_color)
        mp_button_frame.pack(fill="x", padx=10, pady=(5, 10))

        self._mk_main_button(mp_button_frame, "New", self.create_modpack_dialog).pack(
            side="left", expand=True, fill="x", padx=2
        )
        self._mk_main_button(mp_button_frame, "Edit", self.edit_modpack_dialog).pack(
            side="left", expand=True, fill="x", padx=2
        )
        self._mk_main_button(
            mp_button_frame, "Delete", self.delete_modpack
        ).pack(side="left", expand=True, fill="x", padx=2)
        self._mk_main_button(
            mp_button_frame, "Import", self.import_modpack_dialog
        ).pack(side="left", expand=True, fill="x", padx=2)

        detail_top = Frame(right_frame, bg=self.panel_color)
        detail_top.pack(fill="x", padx=10, pady=(10, 5))

        self.detail_title = Label(
            detail_top,
            text="No modpack selected",
            bg=self.panel_color,
            fg=self.accent_color,
            font=("Helvetica", 16, "bold"),
        )
        self.detail_title.pack(anchor="w")

        self.detail_info = Label(
            right_frame,
            text="Create or select a modpack to get started.",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 11),
            justify="left",
        )
        self.detail_info.pack(fill="both", expand=True, padx=10, pady=5)

        bottom_right = Frame(right_frame, bg=self.panel_color)
        bottom_right.pack(fill="x", padx=10, pady=(5, 10))

        args_label = Label(
            bottom_right,
            text="Args file (USERDIR/vanilla):",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 10),
        )
        args_label.pack(side="left", padx=(0, 5))

        self.args_menu = OptionMenu(bottom_right, self.args_file_var, "")
        self.args_menu.config(
            bg="#4d5c32",
            fg=self.text_color,
            activebackground=self.button_hover_color,
            activeforeground=self.text_color,
            relief="flat",
            highlightthickness=0,
        )
        self.args_menu["menu"].config(bg="#4d5c32", fg=self.text_color)
        self.args_menu.pack(side="left", padx=(0, 10))

        self.play_button = self._mk_big_play_button(bottom_right, "PLAY", self.play)
        self.play_button.pack(side="right", padx=5)

        status_bar = Frame(self.root, bg="#1c2413", height=24)
        status_bar.pack(fill="x", side="bottom")

        self.status_label = Label(
            status_bar,
            textvariable=self.status_var,
            bg="#1c2413",
            fg=self.text_color,
            font=("Helvetica", 10),
            anchor="w",
        )
        self.status_label.pack(fill="x", padx=10)

    def _mk_header_button(self, parent, text, command):
        return Button(
            parent,
            text=text,
            command=command,
            bg="#4d5c32",
            fg=self.text_color,
            activebackground=self.button_hover_color,
            activeforeground=self.text_color,
            relief="flat",
            padx=10,
            pady=5,
            font=("Helvetica", 9, "bold"),
        )

    def _mk_main_button(self, parent, text, command):
        return Button(
            parent,
            text=text,
            command=command,
            bg=self.button_color,
            fg=self.text_color,
            activebackground=self.button_hover_color,
            activeforeground=self.text_color,
            relief="flat",
            padx=8,
            pady=5,
            font=("Helvetica", 10),
        )

    def _mk_big_play_button(self, parent, text, command):
        return Button(
            parent,
            text=text,
            command=command,
            bg="#6eb134",
            fg="#1b250e",
            activebackground="#8ad44a",
            activeforeground="#1b250e",
            relief="flat",
            padx=25,
            pady=12,
            font=("Helvetica", 14),
        )

    # ----- Args file discovery -----

    def _refresh_args_file_options(self):
        options = []

        if VANILLA_DIR.exists():
            for p in sorted(VANILLA_DIR.glob("java_args_*.txt")):
                options.append(p.name)

        if not options:
            options = ["<no args files in USERDIR/vanilla>"]

        menu = self.args_menu["menu"]
        menu.delete(0, "end")
        for opt in options:
            menu.add_command(
                label=opt,
                command=lambda v=opt: self._on_select_args_file(v),
            )

        self.args_file_var.set(options[0])

    def _on_select_args_file(self, value):
        self.args_file_var.set(value)
        self.log(f"Using args file: USERDIR/vanilla/{value}")

    # ----- Modpack handling -----

    def _load_modpacks_into_list(self):
        self.modpack_listbox.delete(0, END)
        for name in list_modpacks():
            self.modpack_listbox.insert(END, name)

    def _restore_last_selection(self):
        last = self.config.get("last_selected_modpack") or ""
        if not last:
            return
        for idx in range(self.modpack_listbox.size()):
            if self.modpack_listbox.get(idx) == last:
                self.modpack_listbox.selection_set(idx)
                self.modpack_listbox.activate(idx)
                self._update_detail_panel(last)
                break

    def _on_modpack_selected(self, event=None):
        idxs = self.modpack_listbox.curselection()
        if not idxs:
            self.selected_modpack.set("")
            self._update_detail_panel(None)
            return
        name = self.modpack_listbox.get(idxs[0])
        self.selected_modpack.set(name)
        self.config["last_selected_modpack"] = name
        save_config(self.config)
        self._update_detail_panel(name)

    def _update_detail_panel(self, modpack_name):
        if not modpack_name:
            self.detail_title.config(text="No modpack selected")
            self.detail_info.config(
                text="Create or select a modpack to get started."
            )
            return

        mp_dir = Path(MODPACKS_DIR) / modpack_name
        mods_dir = mp_dir / "mods"
        config_dir = mp_dir / "config"
        resource_dir = mp_dir / "resourcepacks"

        instance = load_instance_json(mp_dir)
        if instance is None:
            instance = create_default_instance_json(mp_dir, modpack_name)
            save_instance_json(mp_dir, instance)

        mods_count = (
            sum(1 for _ in mods_dir.rglob("*") if _.is_file())
            if mods_dir.exists()
            else 0
        )
        config_count = (
            sum(1 for _ in config_dir.rglob("*") if _.is_file())
            if config_dir.exists()
            else 0
        )
        resource_count = (
            sum(1 for _ in resource_dir.rglob("*") if _.is_file())
            if resource_dir.exists()
            else 0
        )

        java_exec = get_java_executable()
        args_file = self.args_file_var.get()

        inst_mc = get_instance_minecraft_version(instance) or "<unknown>"
        inst_loader = get_instance_loader(instance) or "<unknown>"

        info = [
            f"Folder: {mp_dir}",
            "",
            f"Minecraft: {inst_mc}",
            f"Loader: {inst_loader}",
            "",
            f"Mods: {mods_count}",
            f"Config files: {config_count}",
            f"Resource packs: {resource_count}",
            "",
            f"Java: {java_exec} (expected {JAVA_RUNTIME_VERSION})",
            f"Args file: USERDIR/vanilla/{args_file}",
            "",
            "Tip: Use Edit -> Instance Settings to set Minecraft version/loader.",
        ]
        self.detail_title.config(text=modpack_name)
        self.detail_info.config(text="\n".join(info))

    def create_modpack_dialog(self):
        dialog = Toplevel(self.root)
        dialog.title("Create Modpack")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.resizable(False, False)

        Label(
            dialog,
            text="Modpack Name:",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 11),
        ).pack(padx=10, pady=(10, 3), anchor="w")

        name_var = StringVar()
        entry = Entry(
            dialog,
            textvariable=name_var,
            bg="#1f2616",
            fg=self.text_color,
            insertbackground=self.text_color,
            highlightthickness=1,
            highlightbackground="#101509",
            highlightcolor=self.accent_color,
        )
        entry.pack(padx=10, pady=3, fill="x")
        entry.focus_set()

        def on_create():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("Invalid name", "Please enter a modpack name.")
                return
            safe_name = "".join(c for c in name if c not in "\\/:*?\"<>|")
            if not safe_name:
                messagebox.showwarning(
                    "Invalid name",
                    "Name contains only invalid characters.",
                )
                return
            mp_dir = Path(MODPACKS_DIR) / safe_name
            if mp_dir.exists():
                messagebox.showerror(
                    "Already exists", f"A modpack named '{safe_name}' already exists."
                )
                return
            (mp_dir / "mods").mkdir(parents=True, exist_ok=True)
            (mp_dir / "config").mkdir(parents=True, exist_ok=True)
            (mp_dir / "resourcepacks").mkdir(parents=True, exist_ok=True)

            save_instance_json(mp_dir, create_default_instance_json(mp_dir, safe_name))

            self._load_modpacks_into_list()
            for idx in range(self.modpack_listbox.size()):
                if self.modpack_listbox.get(idx) == safe_name:
                    self.modpack_listbox.selection_clear(0, END)
                    self.modpack_listbox.selection_set(idx)
                    self.modpack_listbox.activate(idx)
                    self._on_modpack_selected()
                    break
            dialog.destroy()
            self.log(f"Created modpack '{safe_name}'.")

        btn_frame = Frame(dialog, bg=self.panel_color)
        btn_frame.pack(padx=10, pady=10, fill="x")

        self._mk_main_button(btn_frame, "Create", on_create).pack(
            side="right", padx=5
        )
        self._mk_main_button(btn_frame, "Cancel", dialog.destroy).pack(
            side="right", padx=5
        )

    def edit_modpack_dialog(self):
        name = self.selected_modpack.get()
        if not name:
            messagebox.showinfo("No selection", "Please select a modpack first.")
            return

        mp_dir = Path(MODPACKS_DIR) / name
        if not mp_dir.exists():
            messagebox.showerror(
                "Missing folder",
                f"The folder for '{name}' is missing.\nExpected: {mp_dir}",
            )
            return

        dialog = Toplevel(self.root)
        dialog.title(f"Edit Modpack - {name}")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.resizable(True, True)

        Label(
            dialog,
            text="Modpack Name:",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 11),
        ).pack(padx=10, pady=(10, 3), anchor="w")

        name_var = StringVar(value=name)
        entry = Entry(
            dialog,
            textvariable=name_var,
            bg="#1f2616",
            fg=self.text_color,
            insertbackground=self.text_color,
            highlightthickness=1,
            highlightbackground="#101509",
            highlightcolor=self.accent_color,
        )
        entry.pack(padx=10, pady=3, fill="x")

        def open_folder(sub):
            target = mp_dir / sub
            target.mkdir(parents=True, exist_ok=True)
            path_str = str(target.resolve())
            if sys.platform.startswith("win"):
                os.startfile(path_str)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path_str])
            else:
                subprocess.Popen(["xdg-open", path_str])

        Label(
            dialog,
            text="Open folders for this modpack:",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 11),
        ).pack(padx=10, pady=(8, 3), anchor="w")

        folder_frame = Frame(dialog, bg=self.panel_color)
        folder_frame.pack(padx=10, pady=3, fill="x")

        self._mk_main_button(
            folder_frame, "mods", lambda: open_folder("mods")
        ).pack(side="left", padx=3)
        self._mk_main_button(
            folder_frame, "config", lambda: open_folder("config")
        ).pack(side="left", padx=3)
        self._mk_main_button(
            folder_frame, "resourcepacks", lambda: open_folder("resourcepacks")
        ).pack(side="left", padx=3)

        add_mod_frame = Frame(dialog, bg=self.panel_color)
        add_mod_frame.pack(padx=10, pady=(5, 3), fill="x")

        self._mk_main_button(
            add_mod_frame,
            "Add Mod (CF/Modrinth)",
            lambda: self.add_mod_to_modpack_dialog(mp_dir),
        ).pack(side="left", padx=3)

        # Instance settings
        instance = load_instance_json(mp_dir)
        if instance is None:
            instance = create_default_instance_json(mp_dir, name)
            save_instance_json(mp_dir, instance)

        inst_loader = (get_instance_loader(instance) or "forge").lower()
        inst_mc = get_instance_minecraft_version(instance) or ""
        launcher_cfg = instance.get("launcher") or {}
        inst_max_mem = str((launcher_cfg.get("maximumMemory") or 4096))
        inst_min_mem = str((launcher_cfg.get("requiredMemory") or 0))
        inst_extra_jvm = launcher_cfg.get("additionalJvmArgs") or ""
        if not isinstance(inst_extra_jvm, str):
            inst_extra_jvm = ""

        Label(
            dialog,
            text="Instance Settings (used for Modrinth/CurseForge filtering):",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 11),
        ).pack(padx=10, pady=(10, 3), anchor="w")

        settings_frame = Frame(dialog, bg=self.panel_color)
        settings_frame.pack(padx=10, pady=3, fill="x")

        Label(
            settings_frame,
            text="Minecraft version:",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 10),
        ).grid(row=0, column=0, sticky="w")

        mc_var = StringVar(value=inst_mc)
        mc_entry = Entry(
            settings_frame,
            textvariable=mc_var,
            bg="#1f2616",
            fg=self.text_color,
            insertbackground=self.text_color,
            highlightthickness=1,
            highlightbackground="#101509",
            highlightcolor=self.accent_color,
            width=18,
        )
        mc_entry.grid(row=0, column=1, sticky="w", padx=(6, 12))

        Label(
            settings_frame,
            text="Loader:",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 10),
        ).grid(row=0, column=2, sticky="w")

        loader_var = StringVar(value=inst_loader)
        loader_menu = OptionMenu(settings_frame, loader_var, "forge", "fabric", "quilt", "neoforge")
        loader_menu.config(
            bg="#4d5c32",
            fg=self.text_color,
            activebackground=self.button_hover_color,
            activeforeground=self.text_color,
            relief="flat",
            highlightthickness=0,
        )
        loader_menu["menu"].config(bg="#4d5c32", fg=self.text_color)
        loader_menu.grid(row=0, column=3, sticky="w", padx=(6, 12))

        Label(
            settings_frame,
            text="Max memory (MB):",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 10),
        ).grid(row=0, column=4, sticky="w")

        mem_var = StringVar(value=inst_max_mem)
        mem_entry = Entry(
            settings_frame,
            textvariable=mem_var,
            bg="#1f2616",
            fg=self.text_color,
            insertbackground=self.text_color,
            highlightthickness=1,
            highlightbackground="#101509",
            highlightcolor=self.accent_color,
            width=10,
        )
        mem_entry.grid(row=0, column=5, sticky="w", padx=(6, 0))

        Label(
            settings_frame,
            text="Min memory (MB):",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 10),
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        min_mem_var = StringVar(value=inst_min_mem)
        min_mem_entry = Entry(
            settings_frame,
            textvariable=min_mem_var,
            bg="#1f2616",
            fg=self.text_color,
            insertbackground=self.text_color,
            highlightthickness=1,
            highlightbackground="#101509",
            highlightcolor=self.accent_color,
            width=10,
        )
        min_mem_entry.grid(row=1, column=1, sticky="w", padx=(6, 12), pady=(6, 0))

        Label(
            settings_frame,
            text="Extra JVM args:",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 10),
        ).grid(row=1, column=2, sticky="w", pady=(6, 0))

        extra_jvm_var = StringVar(value=inst_extra_jvm)
        extra_jvm_entry = Entry(
            settings_frame,
            textvariable=extra_jvm_var,
            bg="#1f2616",
            fg=self.text_color,
            insertbackground=self.text_color,
            highlightthickness=1,
            highlightbackground="#101509",
            highlightcolor=self.accent_color,
            width=45,
        )
        extra_jvm_entry.grid(row=1, column=3, columnspan=3, sticky="we", padx=(6, 0), pady=(6, 0))

        def save_instance_settings():
            inst = load_instance_json(mp_dir) or create_default_instance_json(mp_dir, name)
            launcher = inst.get("launcher") or {}
            lv = launcher.get("loaderVersion") or {}

            mc = mc_var.get().strip()
            loader = normalize_loader_name(loader_var.get())
            max_mem_raw = mem_var.get().strip()
            min_mem_raw = min_mem_var.get().strip()
            extra_jvm_raw = extra_jvm_var.get().strip()

            # loaderVersion.type uses capitalized loader name, rawVersion keeps "<mc>-<loaderver>".
            if loader == "forge":
                lv["type"] = "Forge"
            elif loader == "neoforge":
                lv["type"] = "NeoForge"
            elif loader == "fabric":
                lv["type"] = "Fabric"
            elif loader == "quilt":
                lv["type"] = "Quilt"
            else:
                lv["type"] = loader

            if mc:
                raw = lv.get("rawVersion")
                if isinstance(raw, str) and raw:
                    # preserve "-<loaderver>" if present
                    parts = raw.split("-", 1)
                    if len(parts) == 2:
                        lv["rawVersion"] = f"{mc}-{parts[1]}"
                    else:
                        lv["rawVersion"] = mc
                else:
                    lv["rawVersion"] = mc

            launcher["loaderVersion"] = lv

            try:
                launcher["maximumMemory"] = int(max_mem_raw) if max_mem_raw else launcher.get("maximumMemory", 4096)
            except ValueError:
                launcher["maximumMemory"] = launcher.get("maximumMemory", 4096)

            try:
                launcher["requiredMemory"] = int(min_mem_raw) if min_mem_raw else launcher.get("requiredMemory", 0)
            except ValueError:
                launcher["requiredMemory"] = launcher.get("requiredMemory", 0)

            launcher["additionalJvmArgs"] = extra_jvm_raw

            inst["launcher"] = launcher
            save_instance_json(mp_dir, inst)
            self._update_detail_panel(self.selected_modpack.get())
            self.log("Saved instance settings (instance.json).", source="LAUNCHER")

        self._mk_main_button(
            add_mod_frame,
            "Save Instance Settings",
            save_instance_settings,
        ).pack(side="left", padx=8)

        def on_save():
            old_name = name
            new_name = name_var.get().strip()
            if not new_name:
                messagebox.showwarning("Invalid name", "Please enter a modpack name.")
                return
            safe_name = "".join(c for c in new_name if c not in "\\/:*?\"<>|")
            if not safe_name:
                messagebox.showwarning(
                    "Invalid name",
                    "Name contains only invalid characters.",
                )
                return

            effective_mp_dir = mp_dir
            if safe_name != old_name:
                new_dir = Path(MODPACKS_DIR) / safe_name
                if new_dir.exists():
                    messagebox.showerror(
                        "Already exists",
                        f"A modpack named '{safe_name}' already exists.",
                    )
                    return
                mp_dir.rename(new_dir)
                effective_mp_dir = new_dir
                if self.config.get("last_selected_modpack") == old_name:
                    self.config["last_selected_modpack"] = safe_name
                self.selected_modpack.set(safe_name)

            # Ensure instance.json exists
            if load_instance_json(effective_mp_dir) is None:
                save_instance_json(
                    effective_mp_dir,
                    create_default_instance_json(effective_mp_dir, self.selected_modpack.get()),
                )

            save_config(self.config)
            self._load_modpacks_into_list()
            for idx in range(self.modpack_listbox.size()):
                if self.modpack_listbox.get(idx) == self.selected_modpack.get():
                    self.modpack_listbox.selection_clear(0, END)
                    self.modpack_listbox.selection_set(idx)
                    self.modpack_listbox.activate(idx)
                    self._on_modpack_selected()
                    break
            dialog.destroy()
            self.log(f"Updated modpack '{self.selected_modpack.get()}'.")

        btn_frame = Frame(dialog, bg=self.panel_color)
        btn_frame.pack(padx=10, pady=10, fill="x")

        self._mk_main_button(btn_frame, "Save", on_save).pack(
            side="right", padx=5
        )
        self._mk_main_button(btn_frame, "Cancel", dialog.destroy).pack(
            side="right", padx=5
        )

    def delete_modpack(self):
        name = self.selected_modpack.get()
        if not name:
            messagebox.showinfo("No selection", "Please select a modpack first.")
            return
        mp_dir = Path(MODPACKS_DIR) / name
        if not mp_dir.exists():
            messagebox.showerror(
                "Missing folder",
                f"The folder for '{name}' is missing.\nExpected: {mp_dir}",
            )
            return
        if not messagebox.askyesno(
            "Delete modpack",
            f"Are you sure you want to permanently delete '{name}'?",
        ):
            return
        shutil.rmtree(mp_dir)

        self._load_modpacks_into_list()
        self.selected_modpack.set("")
        self._update_detail_panel(None)
        if self.config.get("last_selected_modpack") == name:
            self.config["last_selected_modpack"] = ""
            save_config(self.config)
        self.log(f"Deleted modpack '{name}'.")

    # ----- Import modpack -----

    def import_modpack_dialog(self):
        file_path = filedialog.askopenfilename(
            title="Import CurseForge/Modrinth Modpack",
            filetypes=[
                ("Modpack files", "*.zip;*.mrpack"),
                ("ZIP files", "*.zip"),
                ("Modrinth packs", "*.mrpack"),
                ("All files", "*.*"),
            ],
        )
        if not file_path:
            return

        src = Path(file_path)

        dialog = Toplevel(self.root)
        dialog.title("Import Modpack")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.resizable(False, False)

        Label(
            dialog,
            text=f"Import from: {src.name}",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 10, "bold"),
        ).pack(padx=10, pady=(10, 3), anchor="w")

        Label(
            dialog,
            text="New Modpack Name:",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 11),
        ).pack(padx=10, pady=(5, 3), anchor="w")

        name_var = StringVar(value=src.stem)
        entry = Entry(
            dialog,
            textvariable=name_var,
            bg="#1f2616",
            fg=self.text_color,
            insertbackground=self.text_color,
            highlightthickness=1,
            highlightbackground="#101509",
            highlightcolor=self.accent_color,
        )
        entry.pack(padx=10, pady=3, fill="x")
        entry.focus_set()

        def on_import():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("Invalid name", "Please enter a modpack name.")
                return
            safe_name = "".join(c for c in name if c not in "\\/:*?\"<>|")
            if not safe_name:
                messagebox.showwarning(
                    "Invalid name",
                    "Name contains only invalid characters.",
                )
                return

            dest_dir = Path(MODPACKS_DIR) / safe_name
            if dest_dir.exists():
                messagebox.showerror(
                    "Already exists",
                    f"A modpack named '{safe_name}' already exists.",
                )
                return

            (dest_dir / "mods").mkdir(parents=True, exist_ok=True)
            (dest_dir / "config").mkdir(parents=True, exist_ok=True)
            (dest_dir / "resourcepacks").mkdir(parents=True, exist_ok=True)

            dialog.destroy()
            threading.Thread(
                target=self._do_import_modpack,
                args=(src, safe_name, dest_dir),
                daemon=True,
            ).start()

        btn_frame = Frame(dialog, bg=self.panel_color)
        btn_frame.pack(padx=10, pady=10, fill="x")

        self._mk_main_button(btn_frame, "Import", on_import).pack(
            side="right", padx=5
        )
        self._mk_main_button(btn_frame, "Cancel", dialog.destroy).pack(
            side="right", padx=5
        )

    def _do_import_modpack(self, src: Path, name: str, dest_dir: Path):
        try:
            ext = src.suffix.lower()
            self.log(f"Importing modpack '{name}' from {src.name}...", source="LAUNCHER")

            if ext == ".mrpack":
                import_modrinth_modpack(src, dest_dir, self.log)
                # No standardized instance metadata in .mrpack we rely on here
                if load_instance_json(dest_dir) is None:
                    save_instance_json(dest_dir, create_default_instance_json(dest_dir, name))
            else:
                manifest = import_curseforge_modpack(src, dest_dir)
                if manifest is not None:
                    inst = create_default_instance_json(dest_dir, name)
                    launcher = inst.get("launcher") or {}
                    launcher["enableCurseForgeIntegration"] = True

                    # CurseForge manifest: minecraft.modLoaders[0].id like "forge-47.3.11"
                    mc = manifest.get("minecraft") or {}
                    mod_loaders = mc.get("modLoaders") or []
                    if mod_loaders:
                        ml = mod_loaders[0] or {}
                        ml_id = ml.get("id")
                        if isinstance(ml_id, str) and ml_id:
                            if ml_id.startswith("forge-"):
                                launcher.setdefault("loaderVersion", {})
                                launcher["loaderVersion"]["type"] = "Forge"
                                launcher["loaderVersion"]["version"] = ml_id.split("-", 1)[1]
                                gv = mc.get("version")
                                if isinstance(gv, str) and gv:
                                    launcher["loaderVersion"]["rawVersion"] = f"{gv}-{launcher['loaderVersion']['version']}"
                            elif ml_id.startswith("fabric-"):
                                launcher.setdefault("loaderVersion", {})
                                launcher["loaderVersion"]["type"] = "Fabric"
                                launcher["loaderVersion"]["version"] = ml_id.split("-", 1)[1]
                                gv = mc.get("version")
                                if isinstance(gv, str) and gv:
                                    launcher["loaderVersion"]["rawVersion"] = gv

                    cf_project = manifest.get("manifest") or {}
                    if cf_project:
                        launcher["externalPackId"] = cf_project.get("projectID", 0) or 0
                        launcher["version"] = cf_project.get("version", launcher.get("version", "1.0.0"))

                    inst["launcher"] = launcher
                    save_instance_json(dest_dir, inst)
                else:
                    if load_instance_json(dest_dir) is None:
                        save_instance_json(dest_dir, create_default_instance_json(dest_dir, name))

            self.log(f"Imported modpack '{name}'.", source="LAUNCHER")
            self._load_modpacks_into_list()

            for idx in range(self.modpack_listbox.size()):
                if self.modpack_listbox.get(idx) == name:
                    self.modpack_listbox.selection_clear(0, END)
                    self.modpack_listbox.selection_set(idx)
                    self.modpack_listbox.activate(idx)
                    self._on_modpack_selected()
                    break

        except Exception as e:
            messagebox.showerror(
                "Import error",
                f"Failed to import modpack:\n{e}",
            )
            self.log("Failed to import modpack.", source="LAUNCHER")

    # ----- Add single mod (CF / Modrinth) -----

    def add_mod_to_modpack_dialog(self, mp_dir: Path):
        dialog = Toplevel(self.root)
        dialog.title("Add Mod to Modpack")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.resizable(False, False)

        Label(
            dialog,
            text="Source:",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 11),
        ).pack(padx=10, pady=(10, 3), anchor="w")

        source_var = StringVar(value="modrinth")
        source_frame = Frame(dialog, bg=self.panel_color)
        source_frame.pack(padx=10, pady=(0, 5), fill="x")

        def set_source_modrinth():
            source_var.set("modrinth")

        def set_source_curseforge():
            source_var.set("curseforge")

        self._mk_main_button(
            source_frame, "Modrinth", set_source_modrinth
        ).pack(side="left", padx=3)
        self._mk_main_button(
            source_frame, "CurseForge", set_source_curseforge
        ).pack(side="left", padx=3)

        Label(
            dialog,
            text="Mod URL or ID:",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 11),
        ).pack(padx=10, pady=(5, 3), anchor="w")

        url_var = StringVar()
        url_entry = Entry(
            dialog,
            textvariable=url_var,
            bg="#1f2616",
            fg=self.text_color,
            insertbackground=self.text_color,
            highlightthickness=1,
            highlightbackground="#101509",
            highlightcolor=self.accent_color,
            width=60,
        )
        url_entry.pack(padx=10, pady=3, fill="x")
        url_entry.focus_set()

        hint = (
            "Modrinth: paste a project URL (e.g. https://modrinth.com/mod/sodium)\n"
            "          or slug (e.g. 'sodium'). Latest version will be used.\n"
            "CurseForge: paste a direct .jar file URL OR project slug/URL/ID.\n"
            "Mods will be downloaded into this modpack's 'mods' folder."
        )
        Label(
            dialog,
            text=hint,
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 9),
            justify="left",
        ).pack(padx=10, pady=(0, 8), anchor="w")

        def on_add():
            source = source_var.get()
            text = url_var.get().strip()
            if not text:
                messagebox.showwarning("Missing URL/ID", "Please enter a URL or ID.")
                return
            dialog.destroy()
            threading.Thread(
                target=self._do_add_mod_to_modpack,
                args=(source, text, mp_dir),
                daemon=True,
            ).start()

        btn_frame = Frame(dialog, bg=self.panel_color)
        btn_frame.pack(padx=10, pady=10, fill="x")

        self._mk_main_button(btn_frame, "Add", on_add).pack(
            side="right", padx=5
        )
        self._mk_main_button(btn_frame, "Cancel", dialog.destroy).pack(
            side="right", padx=5
        )

    def _do_add_mod_to_modpack(self, source: str, text: str, mp_dir: Path):
        try:
            mods_dir = mp_dir / "mods"
            mods_dir.mkdir(parents=True, exist_ok=True)

            instance = load_instance_json(mp_dir)
            if instance is None:
                instance = create_default_instance_json(mp_dir, mp_dir.name)
                save_instance_json(mp_dir, instance)

            target_mc_version = get_instance_minecraft_version(instance)
            if not target_mc_version:
                target_mc_version = infer_minecraft_version_from_args_filename(self.args_file_var.get())

            target_loader = get_instance_loader(instance)

            if source == "modrinth":
                self._add_mod_from_modrinth(text, mods_dir, target_mc_version, target_loader)
            else:
                self._add_mod_from_curseforge(text, mods_dir, target_mc_version, target_loader)

        except Exception as e:
            messagebox.showerror(
                "Add mod error",
                f"Failed to add mod:\n{e}",
            )
            self.log("Failed to add mod.", source="LAUNCHER")

    def _add_mod_from_modrinth(
        self,
        text: str,
        mods_dir: Path,
        target_mc_version: Optional[str],
        target_loader: Optional[str],
    ):
        import re

        self.log(f"Resolving Modrinth project from '{text}'...", source="LAUNCHER")

        m = re.search(r"modrinth\.com/mod/([^/]+)", text)
        if not m:
            m = re.search(r"modrinth\.com/project/([^/]+)", text)
        if m:
            project_id = m.group(1)
        else:
            project_id = text

        url_project = f"https://api.modrinth.com/v2/project/{project_id}"
        with urllib.request.urlopen(url_project) as resp:
            project = json.loads(resp.read().decode("utf-8"))

        project_id = project["id"]
        slug = project.get("slug", project_id)
        self.log(f"Modrinth project resolved: {slug} ({project_id})", source="LAUNCHER")

        versions_url = f"https://api.modrinth.com/v2/project/{project_id}/version"

        params = {}
        if target_mc_version:
            params["game_versions"] = json.dumps([target_mc_version])
        if target_loader:
            params["loaders"] = json.dumps([normalize_loader_name(target_loader)])

        if params:
            versions_url = versions_url + "?" + urllib.parse.urlencode(params)
            self.log(
                f"Filtering Modrinth versions: mc={target_mc_version or '*'} loader={target_loader or '*'}",
                source="LAUNCHER",
            )

        with urllib.request.urlopen(versions_url) as resp:
            versions = json.loads(resp.read().decode("utf-8"))

        if not versions:
            # If filters were too strict, retry without filters
            if params:
                self.log("No matching Modrinth versions found; retrying without filters...", source="LAUNCHER")
                with urllib.request.urlopen(f"https://api.modrinth.com/v2/project/{project_id}/version") as resp:
                    versions = json.loads(resp.read().decode("utf-8"))

        if not versions:
            raise RuntimeError("No versions found on Modrinth project.")

        version = versions[0]
        files = version.get("files", [])
        if not files:
            raise RuntimeError("No files in selected Modrinth version.")

        file_info = None
        for f in files:
            if f.get("primary"):
                file_info = f
                break
        if file_info is None:
            file_info = files[0]

        file_url = file_info["url"]
        filename = file_info["filename"]

        target = mods_dir / filename
        self.log(f"Downloading Modrinth mod '{slug}' -> {target}", source="LAUNCHER")
        download_to_file(file_url, target)
        self.log(f"Added Modrinth mod '{slug}' as {filename}", source="LAUNCHER")

    # ----- CurseForge API helpers -----

    def _cf_api_request(self, path: str) -> dict:
        api_key = CURSEFORGE_API_KEY.strip()
        if not api_key:
            raise RuntimeError("CURSEFORGE_API_KEY is empty. Set it at the top of the script.")

        url = "https://api.curseforge.com" + path
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        req.add_header("x-api-key", api_key)

        with urllib.request.urlopen(req) as resp:
            data = resp.read().decode("utf-8")
        return json.loads(data)

    def _cf_resolve_project(self, text: str) -> int:
        import re
        import urllib.parse

        text = text.strip()

        if text.isdigit():
            return int(text)

        m = re.search(r"curseforge\.com/minecraft/mc-mods/([^/]+)", text)
        if m:
            slug = m.group(1)
        else:
            slug = text

        params = f"?gameId=432&searchFilter={urllib.parse.quote(slug)}"
        data = self._cf_api_request("/v1/mods/search" + params)
        mods = data.get("data", [])
        if not mods:
            raise RuntimeError(f"No CurseForge mods found for slug '{slug}'.")

        mod = mods[0]
        mod_id = mod["id"]
        name = mod.get("name", "")
        self.log(f"CurseForge project resolved: {name} (id={mod_id})", source="LAUNCHER")
        return mod_id

    def _cf_pick_file_for_mod(
        self,
        mod_id: int,
        target_mc_version: Optional[str],
        target_loader: Optional[str],
    ) -> dict:
        data = self._cf_api_request(f"/v1/mods/{mod_id}/files")
        files = data.get("data", [])
        if not files:
            raise RuntimeError(f"No files found for CurseForge mod id={mod_id}.")

        if not target_mc_version and not target_loader:
            return files[0]

        loader_token = None
        if target_loader:
            norm = normalize_loader_name(target_loader)
            if norm == "forge":
                loader_token = "Forge"
            elif norm == "neoforge":
                loader_token = "NeoForge"
            elif norm == "fabric":
                loader_token = "Fabric"
            elif norm == "quilt":
                loader_token = "Quilt"

        matching = []
        for f in files:
            gv = f.get("gameVersions") or []
            if target_mc_version and target_mc_version not in gv:
                continue
            if loader_token and loader_token not in gv:
                continue
            matching.append(f)

        if matching:
            return matching[0]

        # Fall back: only require MC version
        if target_mc_version:
            for f in files:
                gv = f.get("gameVersions") or []
                if target_mc_version in gv:
                    return f

        return files[0]

    def _add_mod_from_curseforge(
        self,
        text: str,
        mods_dir: Path,
        target_mc_version: Optional[str],
        target_loader: Optional[str],
    ):
        import os
        import urllib.parse
        import re

        text = text.strip()
        parsed = urllib.parse.urlparse(text)
        path = parsed.path or ""
        is_http_url = parsed.scheme in ("http", "https") and parsed.netloc != ""

        if is_http_url and path.lower().endswith(".jar"):
            self.log(f"Downloading CurseForge mod from direct URL '{text}'...", source="LAUNCHER")
            name = os.path.basename(path) or "curseforge_mod.jar"
            target = mods_dir / name
            download_to_file(text, target)
            self.log(f"Added CurseForge mod as {name}", source="LAUNCHER")
            return

        if not CURSEFORGE_API_KEY.strip():
            raise RuntimeError(
                "CURSEFORGE_API_KEY is empty. Set it at the top of the script or use a direct .jar URL."
            )

        if not is_http_url and text.isdigit():
            mod_id = int(text)
        else:
            self.log(f"Resolving CurseForge mod via API from '{text}'...", source="LAUNCHER")
            mod_id = self._cf_resolve_project(text)

        if target_mc_version:
            self.log(
                f"Target MC version from instance/args: {target_mc_version}",
                source="LAUNCHER",
            )
        if target_loader:
            self.log(
                f"Target loader from instance: {normalize_loader_name(target_loader)}",
                source="LAUNCHER",
            )

        file_info = self._cf_pick_file_for_mod(mod_id, target_mc_version, target_loader)
        file_name = file_info.get("fileName") or "curseforge_mod.jar"
        download_url = file_info.get("downloadUrl")
        if not download_url:
            raise RuntimeError("CurseForge file has no downloadUrl.")

        target = mods_dir / file_name
        self.log(f"Downloading CurseForge file id={file_info.get('id')} -> {target}", source="LAUNCHER")
        download_to_file(download_url, target)
        self.log(f"Added CurseForge mod as {file_name}", source="LAUNCHER")

    # ----- Install vanilla version -----

    def install_vanilla_version_dialog(self):
        dialog = Toplevel(self.root)
        dialog.title("Install Vanilla Version")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.resizable(False, False)

        Label(
            dialog,
            text="Minecraft Version ID (e.g. 1.21.11):",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 11),
        ).pack(padx=10, pady=(10, 3), anchor="w")

        version_var = StringVar(value="1.21.11")
        entry = Entry(
            dialog,
            textvariable=version_var,
            bg="#1f2616",
            fg=self.text_color,
            insertbackground=self.text_color,
            highlightthickness=1,
            highlightbackground="#101509",
            highlightcolor=self.accent_color,
        )
        entry.pack(padx=10, pady=3, fill="x")
        entry.focus_set()

        hint = (
            "This will download the official client, libraries and assets\n"
            "for the specified version directly from Mojang,\n"
            "and generate USERDIR/vanilla/java_args_<version>.txt."
        )
        Label(
            dialog,
            text=hint,
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 9),
            justify="left",
        ).pack(padx=10, pady=(0, 8), anchor="w")

        def on_install():
            version_id = version_var.get().strip()
            if not version_id:
                messagebox.showwarning("Invalid version", "Please enter a version ID.")
                return
            dialog.destroy()
            threading.Thread(
                target=self._do_install_vanilla_version,
                args=(version_id,),
                daemon=True,
            ).start()

        btn_frame = Frame(dialog, bg=self.panel_color)
        btn_frame.pack(padx=10, pady=10, fill="x")

        self._mk_main_button(btn_frame, "Install", on_install).pack(
            side="right", padx=5
        )
        self._mk_main_button(btn_frame, "Cancel", dialog.destroy).pack(
            side="right", padx=5
        )

    def _do_install_vanilla_version(self, version_id: str):
        try:
            args_file = download_vanilla_version(version_id, self.config, self.log)
            self.log(
                f"Installed vanilla {version_id}. Args: USERDIR/vanilla/{args_file.name}",
                source="LAUNCHER",
            )
            self._refresh_args_file_options()
            self._on_select_args_file(args_file.name)
        except Exception as e:
            messagebox.showerror(
                "Install error",
                f"Failed to install vanilla {version_id}:\n{e}",
            )
            self.log("Failed to install vanilla version.", source="LAUNCHER")

    # ----- Settings -----

    def choose_minecraft_dir(self):
        directory = filedialog.askdirectory(
            title="Select your .minecraft folder or instance folder",
        )
        if not directory:
            return
        self.config["minecraft_dir"] = directory
        save_config(self.config)
        self.log(f"Minecraft directory set to: {directory}", source="LAUNCHER")

    # ----- Play logic -----

    def play(self):
        name = self.selected_modpack.get()
        if not name:
            messagebox.showinfo("No modpack", "Please select a modpack first.")
            return

        mc_dir = self.config.get("minecraft_dir") or ""
        if not mc_dir or not os.path.isdir(mc_dir):
            messagebox.showerror(
                "Minecraft folder not set",
                "Please set your .minecraft/instance folder in the header first.",
            )
            return

        mp_dir = Path(MODPACKS_DIR) / name
        if not mp_dir.exists():
            messagebox.showerror(
                "Missing modpack",
                f"The folder for '{name}' is missing.\nExpected: {mp_dir}",
            )
            return

        instance = load_instance_json(mp_dir)
        if instance is None:
            instance = create_default_instance_json(mp_dir, name)
            save_instance_json(mp_dir, instance)

        launcher_cfg = instance.get("launcher") or {}
        max_mem = launcher_cfg.get("maximumMemory")
        min_mem = launcher_cfg.get("requiredMemory")
        extra_jvm = launcher_cfg.get("additionalJvmArgs")

        try:
            max_mem = int(max_mem) if max_mem else None
        except (TypeError, ValueError):
            max_mem = None
        try:
            min_mem = int(min_mem) if min_mem else None
        except (TypeError, ValueError):
            min_mem = None
        if min_mem == 0:
            min_mem = None

        if not isinstance(extra_jvm, str):
            extra_jvm = ""

        java_exe = get_java_executable()
        if not java_exe.exists():
            messagebox.showerror(
                "Java not found",
                f"Java runtime not found at:\n{java_exe}\n\n"
                "Ensure the bundled Java was downloaded correctly.",
            )
            return

        args_name = self.args_file_var.get()
        if args_name.startswith("<no args"):
            messagebox.showerror(
                "No args files",
                "No args files found in USERDIR/vanilla.\n"
                "Install a vanilla version first or add a java_args_*.txt there.",
            )
            self.log("No args files found in USERDIR/vanilla.", source="LAUNCHER")
            return

        args_file = VANILLA_DIR / args_name
        if not args_file.exists():
            messagebox.showerror(
                "Args file not found",
                f"Java arguments file not found:\n{args_file}\n\n"
                "Select or generate a valid args file.",
            )
            self.log(f"Args file not found: {args_file}", source="LAUNCHER")
            return

        try:
            self.open_console_window()

            self.log(f"Applying modpack '{name}'...", source="LAUNCHER")
            self.root.update_idletasks()

            mods_src = mp_dir / "mods"
            mods_dst = Path(mc_dir) / "mods"
            os.makedirs(mods_dst, exist_ok=True)
            clean_dir(str(mods_dst))
            copy_tree(str(mods_src), str(mods_dst))

            config_src = mp_dir / "config"
            config_dst = Path(mc_dir) / "config"
            os.makedirs(config_dst, exist_ok=True)
            copy_tree(str(config_src), str(config_dst))

            res_src = mp_dir / "resourcepacks"
            res_dst = Path(mc_dir) / "resourcepacks"
            os.makedirs(res_dst, exist_ok=True)
            copy_tree(str(res_src), str(res_dst))

            mem_note = []
            if max_mem:
                mem_note.append(f"-Xmx{max_mem}M")
            if min_mem:
                mem_note.append(f"-Xms{min_mem}M")

            extra = (" " + " ".join(mem_note)) if mem_note else ""
            self.log(
                f"Modpack '{name}' applied. Launching Minecraft with USERDIR/vanilla/{args_name}{extra}...",
                source="LAUNCHER",
            )
            self._launch_with_argfile(java_exe, args_file, max_mem=max_mem, min_mem=min_mem, extra_jvm=extra_jvm)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to apply modpack or launch: {e}")
            self.log("Error while applying modpack / launching.", source="LAUNCHER")

    def _launch_with_argfile(
        self,
        java_exe: Path,
        args_file: Path,
        max_mem: Optional[int] = None,
        min_mem: Optional[int] = None,
        extra_jvm: str = "",
    ):
        """Launch Java with @<args_file> from USERDIR and stream logs to console."""
        try:
            rel_args_path = args_file.relative_to(INSTALL_DIR)
        except ValueError:
            rel_args_path = Path("vanilla") / args_file.name

        argfile_arg = f"@{rel_args_path.as_posix()}"

        cmd = [str(java_exe)]

        if extra_jvm.strip():
            extra_args = shlex.split(extra_jvm, posix=not sys.platform.startswith("win"))
            cmd.extend(extra_args)

        if max_mem:
            cmd.append(f"-Xmx{max_mem}M")
        if min_mem:
            cmd.append(f"-Xms{min_mem}M")

        cmd.append(argfile_arg)

        try:
            if sys.platform.startswith("win"):
                cmd_str = subprocess.list2cmdline(cmd)
            else:
                cmd_str = shlex.join(cmd)
            self.log(f"Launch command: {cmd_str}", source="LAUNCHER")
        except Exception:
            self.log(f"Launch command: {cmd}", source="LAUNCHER")

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(INSTALL_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as e:
            messagebox.showerror("Launch error", f"Could not launch Minecraft: {e}")
            self.log("Failed to launch Minecraft.", source="LAUNCHER")
            return

        self.log(f"Minecraft launch started ({rel_args_path}).", source="LAUNCHER")

        def reader_thread():
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    line = line.rstrip("\n\r")
                    if line:
                        self.log(line, source="GAME")
            except Exception as e:
                self.log(f"Error reading game output: {e}", source="LAUNCHER")

        threading.Thread(target=reader_thread, daemon=True).start()

    # ----- Misc -----

    def set_status(self, text):
        self.status_var.set(text)


def main():
    root = Tk()
    app = MinecraftLauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
