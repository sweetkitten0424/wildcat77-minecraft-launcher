import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
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

APP_NAME = "Wildcat77 Launcher"
LAUNCHER_VERSION = "1.0.0"

CONFIG_FILE = "launcher_config.json"
MODPACKS_DIR = "modpacks"
MODPACK_METADATA_FILE = "modpack.json"  # Per-modpack loader config

# Installation directory (this is USERDIR)
INSTALL_DIR = Path(__file__).resolve().parent

# Java runtime configuration
JAVA_RUNTIME_DIR_NAME = "runtime"
JAVA_RUNTIME_VERSION = "21.0.7"  # version we expect
JAVA_RUNTIME_VERSION_FILE = "java_runtime_version.txt"

# Vanilla args directory and pattern
VANILLA_DIR = INSTALL_DIR / "vanilla"  # all args files live here

# Mojang endpoints
VERSION_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
ASSET_BASE_URL = "https://resources.download.minecraft.net"

# Oracle JDK ZIP
JAVA_RUNTIME_ZIP_URL = (
    "https://download.oracle.com/java/21/latest/jdk-21_windows-x64_bin.zip"
)

# Parallel downloads configuration
PARALLEL_DOWNLOADS_ENABLED = True  # Enable parallel downloads by default
MAX_PARALLEL_DOWNLOADS = 50  # Number of concurrent download threads


def load_config():
    if not os.path.exists(CONFIG_FILE):
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
            "curseforge_api_key": "",
        }
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    data.setdefault("minecraft_dir", "")
    data.setdefault("last_selected_modpack", "")
    data.setdefault("java_runtime_version", "")
    data.setdefault("auth_player_name", "Player")
    data.setdefault("auth_uuid", "00000000-0000-0000-0000-000000000000")
    data.setdefault("auth_access_token", "0")
    data.setdefault("user_type", "mojang")
    data.setdefault("version_type", "release")
    data.setdefault("curseforge_api_key", "")
    return data


def save_config(config):
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


# --------------------------------------------------------------------------------------
# Modpack metadata (loader config)
# --------------------------------------------------------------------------------------

def load_modpack_metadata(modpack_dir: Path) -> dict:
    """Load modpack.json or return default config."""
    metadata_file = modpack_dir / MODPACK_METADATA_FILE
    if metadata_file.exists():
        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    
    return {
        "loader": "vanilla",  # vanilla, forge, fabric, neoforge
        "loader_version": "",
        "minecraft_version": "",
    }


def save_modpack_metadata(modpack_dir: Path, metadata: dict):
    """Save modpack.json."""
    metadata_file = modpack_dir / MODPACK_METADATA_FILE
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4)


# --------------------------------------------------------------------------------------
# Forge/Fabric loader management
# --------------------------------------------------------------------------------------

def get_loaders_dir() -> Path:
    """Directory to cache downloaded loaders."""
    return INSTALL_DIR / "loaders"


def get_available_forge_versions(mc_version: str) -> list:
    """Fetch available Forge versions for a given Minecraft version.
    Returns a list of version strings, sorted newest first."""
    try:
        url = f"https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
        with urllib.request.urlopen(url) as resp:
            promotions = json.loads(resp.read().decode("utf-8"))
        
        promos = promotions.get("promos", {})
        versions = []
        
        # Collect all versions for this MC version
        for key, version in promos.items():
            if key.startswith(f"{mc_version}-"):
                if version not in versions:
                    versions.append(version)
        
        # Sort by version (reverse numeric order)
        try:
            versions.sort(key=lambda x: [int(n) for n in x.split(".")], reverse=True)
        except:
            versions.reverse()
        
        return versions if versions else ["latest"]
    except Exception:
        return ["latest"]


def get_available_neoforge_versions(mc_version: str) -> list:
    """Fetch available NeoForge versions for a given Minecraft version.
    Returns a list of version strings, sorted newest first."""
    try:
        url = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
        with urllib.request.urlopen(url) as resp:
            content = resp.read().decode("utf-8")
        
        # Parse version numbers from maven-metadata.xml
        import xml.etree.ElementTree as ET
        root = ET.fromstring(content)
        
        versions = []
        for version_elem in root.findall(".//version"):
            version = version_elem.text
            if version:
                # NeoForge versions are like "21.0.35-beta", "20.4.109", etc
                # Check if this version supports the target MC version
                parts = version.split(".")
                if parts and parts[0] == mc_version.split(".")[0]:  # Match major version
                    if version not in versions:
                        versions.append(version)
        
        # Sort by version (reverse numeric order)
        try:
            versions.sort(key=lambda x: [int(n) for n in x.split(".")[0:2]], reverse=True)
        except:
            versions.reverse()
        
        return versions[:15] if versions else ["latest"]  # Return top 15 versions
    except Exception:
        return ["latest"]


def get_available_fabric_versions(mc_version: str) -> list:
    """Fetch available Fabric loader versions for a given Minecraft version.
    Returns a list of (loader_version, installer_version) tuples."""
    try:
        # Get available loaders
        url = "https://meta.fabricmc.net/v2/versions/loader"
        with urllib.request.urlopen(url) as resp:
            loaders = json.loads(resp.read().decode("utf-8"))
        
        # Get available installers
        url = "https://meta.fabricmc.net/v2/versions/installer"
        with urllib.request.urlopen(url) as resp:
            installers = json.loads(resp.read().decode("utf-8"))
        
        if not loaders or not installers:
            return [("latest", "latest")]
        
        # Return top 10 loader versions paired with latest installer
        latest_installer = installers[0]["version"]
        versions = []
        for loader in loaders[:10]:
            loader_version = loader.get("version", "")
            if loader_version:
                versions.append((loader_version, latest_installer))
        
        return versions if versions else [("latest", "latest")]
    except Exception:
        return [("latest", "latest")]


def _wait_for_manual_loader(loaders_dir: Path, search_pattern: str, logger) -> Path:
    """
    Wait for user to manually place a loader file in the loaders directory.
    Shows a message box instructing the user, then polls the directory.
    
    Args:
        loaders_dir: Path to the loaders directory
        search_pattern: Partial filename to search for (e.g., "forge-", "fabric-", "neoforge-")
        logger: Logger function
    
    Returns:
        Path to the found loader file
        
    Raises:
        RuntimeError: If user cancels the operation
    """
    loaders_dir.mkdir(parents=True, exist_ok=True)
    
    # Show message asking user to place loader
    result = messagebox.askyesno(
        "Manual Loader Required",
        f"Could not auto-download the modloader.\n\n"
        f"Please place the modloader .jar file in:\n{loaders_dir}\n\n"
        f"Once placed, click 'Yes' to continue.",
    )
    
    if not result:
        raise RuntimeError("User cancelled modloader installation")
    
    # Poll the loaders directory for the file
    logger(f"Waiting for modloader to be placed in {loaders_dir}...", source="LAUNCHER")
    
    max_wait_time = 300  # 5 minutes timeout
    elapsed = 0
    poll_interval = 1  # Check every 1 second
    
    while elapsed < max_wait_time:
        # Look for matching files in loaders directory
        for file in loaders_dir.glob("*.jar"):
            if search_pattern in file.name:
                logger(f"Found modloader: {file.name}", source="LAUNCHER")
                return file
        
        time.sleep(poll_interval)
        elapsed += poll_interval
        
        # Show progress message every 5 seconds
        if elapsed % 5 == 0:
            logger(f"Still waiting for modloader ({elapsed}s)...", source="LAUNCHER")
    
    raise RuntimeError(
        f"Timeout waiting for modloader file in {loaders_dir} (5 minutes)\n"
        f"Please place a .jar file matching '{search_pattern}' in that directory"
    )


def download_forge_installer(mc_version: str, logger, forge_version: str = "") -> Path:
    """Download Forge installer for the given Minecraft version and optional Forge version."""
    loaders_dir = get_loaders_dir()
    loaders_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        logger(f"Fetching Forge releases for MC {mc_version}...")
        
        # Use Forge API to find the right version
        url = f"https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
        with urllib.request.urlopen(url) as resp:
            promotions = json.loads(resp.read().decode("utf-8"))
        
        promos = promotions.get("promos", {})
        
        # If specific version not provided, get latest
        if not forge_version or forge_version == "latest":
            key = f"{mc_version}-latest"
            if key not in promos:
                raise RuntimeError(f"No Forge releases found for MC {mc_version}")
            forge_version = promos[key]
        
        logger(f"Found Forge version {forge_version} for MC {mc_version}")
        
        # Construct download URL
        installer_url = (
            f"https://maven.minecraftforge.net/net/minecraftforge/forge/"
            f"{mc_version}-{forge_version}/forge-{mc_version}-{forge_version}-installer.jar"
        )
        
        installer_name = f"forge-{mc_version}-{forge_version}-installer.jar"
        installer_path = loaders_dir / installer_name
        
        if installer_path.exists():
            logger(f"Forge installer already cached: {installer_name}")
            return installer_path
        
        logger(f"Downloading Forge installer {installer_name}...")
        download_to_file(installer_url, installer_path)
        
        return installer_path
    
    except Exception as e:
        logger(f"Failed to download Forge: {e}", source="LAUNCHER")
        logger(f"Looking for manually placed Forge installer in {loaders_dir}...", source="LAUNCHER")
        
        # Check if a Forge installer already exists in the loaders directory
        for file in loaders_dir.glob("forge-*.jar"):
            logger(f"Found existing Forge installer: {file.name}", source="LAUNCHER")
            return file
        
        # Ask user to manually place the installer
        logger(f"No existing Forge installer found. Asking user to place one...", source="LAUNCHER")
        return _wait_for_manual_loader(loaders_dir, "forge-", logger)


def download_fabric_installer(mc_version: str, logger, loader_version: str = "", installer_version: str = "") -> Path:
    """Download Fabric installer for the given Minecraft version and optional versions.
    
    Args:
        mc_version: Minecraft version
        logger: Logger function
        loader_version: Specific Fabric loader version (empty = latest)
        installer_version: Specific installer version (empty = latest)
    """
    loaders_dir = get_loaders_dir()
    loaders_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        logger(f"Fetching Fabric releases for MC {mc_version}...")
        
        # Get latest Fabric Loader version if not specified
        url = "https://meta.fabricmc.net/v2/versions/loader"
        with urllib.request.urlopen(url) as resp:
            loaders = json.loads(resp.read().decode("utf-8"))
        
        if not loaders:
            raise RuntimeError("No Fabric loaders found")
        
        if not loader_version or loader_version == "latest":
            latest_loader = loaders[0]["version"]
        else:
            latest_loader = loader_version
        logger(f"Found Fabric Loader {latest_loader}")
        
        # Get Installer version
        url = "https://meta.fabricmc.net/v2/versions/installer"
        with urllib.request.urlopen(url) as resp:
            installers = json.loads(resp.read().decode("utf-8"))
        
        if not installers:
            raise RuntimeError("No Fabric installers found")
        
        if not installer_version or installer_version == "latest":
            latest_installer = installers[0]["version"]
        else:
            latest_installer = installer_version
        logger(f"Found Fabric Installer {latest_installer}")
        
        # Download installer
        installer_url = (
            f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}/"
            f"{latest_loader}/installer/{latest_installer}/server.jar"
        )
        
        installer_name = f"fabric-installer-{mc_version}-{latest_loader}.jar"
        installer_path = loaders_dir / installer_name
        
        if installer_path.exists():
            logger(f"Fabric installer already cached: {installer_name}")
            return installer_path
        
        logger(f"Downloading Fabric installer {installer_name}...")
        download_to_file(installer_url, installer_path)
        
        return installer_path
    
    except Exception as e:
        logger(f"Failed to download Fabric: {e}", source="LAUNCHER")
        logger(f"Looking for manually placed Fabric installer in {loaders_dir}...", source="LAUNCHER")
        
        # Check if a Fabric installer already exists in the loaders directory
        for file in loaders_dir.glob("fabric-*.jar"):
            logger(f"Found existing Fabric installer: {file.name}", source="LAUNCHER")
            return file
        
        # Ask user to manually place the installer
        logger(f"No existing Fabric installer found. Asking user to place one...", source="LAUNCHER")
        return _wait_for_manual_loader(loaders_dir, "fabric-", logger)


def download_neoforge_installer(mc_version: str, logger, neoforge_version: str = "") -> Path:
    """Download NeoForge installer for the given Minecraft version and optional NeoForge version.
    
    Args:
        mc_version: Minecraft version
        logger: Logger function
        neoforge_version: Specific NeoForge version (empty = latest)
    """
    loaders_dir = get_loaders_dir()
    loaders_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        logger(f"Fetching NeoForge releases for MC {mc_version}...")
        
        # If specific version not provided, get latest
        if not neoforge_version or neoforge_version == "latest":
            versions = get_available_neoforge_versions(mc_version)
            if not versions or versions == ["latest"]:
                raise RuntimeError(f"No NeoForge releases found for MC {mc_version}")
            neoforge_version = versions[0]
        
        logger(f"Found NeoForge version {neoforge_version} for MC {mc_version}")
        
        # Construct download URL
        installer_url = (
            f"https://maven.neoforged.net/releases/net/neoforged/neoforge/"
            f"{neoforge_version}/neoforge-{neoforge_version}-installer.jar"
        )
        
        installer_name = f"neoforge-{neoforge_version}-installer.jar"
        installer_path = loaders_dir / installer_name
        
        if installer_path.exists():
            logger(f"NeoForge installer already cached: {installer_name}")
            return installer_path
        
        logger(f"Downloading NeoForge installer {installer_name}...")
        download_to_file(installer_url, installer_path)
        
        return installer_path
    
    except Exception as e:
        logger(f"Failed to download NeoForge: {e}", source="LAUNCHER")
        logger(f"Looking for manually placed NeoForge installer in {loaders_dir}...", source="LAUNCHER")
        
        # Check if a NeoForge installer already exists in the loaders directory
        for file in loaders_dir.glob("neoforge-*.jar"):
            logger(f"Found existing NeoForge installer: {file.name}", source="LAUNCHER")
            return file
        
        # Ask user to manually place the installer
        logger(f"No existing NeoForge installer found. Asking user to place one...", source="LAUNCHER")
        return _wait_for_manual_loader(loaders_dir, "neoforge-", logger)


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
    """
    Download multiple files in parallel.
    
    Args:
        download_tasks: List of tuples (url, dest_path, description)
        logger: Logger function
        max_workers: Number of parallel threads
    """
    if not PARALLEL_DOWNLOADS_ENABLED or len(download_tasks) <= 1:
        # Fall back to sequential downloads
        for url, dest, desc in download_tasks:
            try:
                logger(f"Downloading {desc}...", source="LAUNCHER")
                download_to_file(url, dest)
            except Exception as e:
                logger(f"Failed to download {desc}: {e}", source="LAUNCHER")
                raise
        return
    
    # Parallel downloads
    def download_task(task):
        url, dest, desc = task
        try:
            download_to_file(url, dest)
            return (True, desc, None)
        except Exception as e:
            return (False, desc, str(e))
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(download_task, task) for task in download_tasks]
        
        completed = 0
        for future in futures:
            success, desc, error = future.result()
            completed += 1
            if success:
                logger(f"Downloaded {desc} ({completed}/{len(download_tasks)})", source="LAUNCHER")
            else:
                logger(f"Failed to download {desc}: {error}", source="LAUNCHER")
                raise RuntimeError(f"Failed to download {desc}: {error}")


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

def get_curseforge_file_download_url(project_id: int, file_id: int, api_key: str = "") -> str:
    """Get download URL for a CurseForge file using the API.
    Returns empty string if not available.
    api_key is optional but recommended for better reliability."""
    try:
        # Try the API endpoint
        url = f"https://api.curseforge.com/v1/mods/{project_id}/files/{file_id}"
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        
        # Add API key if provided
        if api_key.strip():
            req.add_header("x-api-key", api_key)
        
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        
        if data.get("data"):
            file_data = data.get("data", {})
            download_url = file_data.get("downloadUrl")
            return download_url or ""
        return ""
    except Exception as e:
        # API might require authentication or have changed - return empty string
        return ""


def import_curseforge_modpack(zip_path: Path, dest_modpack_dir: Path, logger, api_key: str = "") -> tuple:
    """Import a CurseForge modpack zip: extract mods and overrides.
    Returns (mc_version, loader, loader_version) tuple."""
    mc_version = ""
    loader = "vanilla"
    loader_version = ""
    mods_dir = dest_modpack_dir / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    
    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()

        manifest_name = None
        for name in namelist:
            if name.endswith("manifest.json"):
                manifest_name = name
                break

        download_tasks = []
        mods_extracted = 0
        
        if manifest_name:
            with zf.open(manifest_name) as mf:
                manifest = json.loads(mf.read().decode("utf-8"))
                # Extract Minecraft version
                mc_version = manifest.get("minecraft", {}).get("version", "")
                logger(f"Detected Minecraft version: {mc_version}", source="LAUNCHER")
                
                # Try to detect loader from modLoaders
                loader_info = manifest.get("minecraft", {}).get("modLoaders", [])
                if loader_info:
                    loader_entry = loader_info[0]
                    loader_id = loader_entry.get("id", "")
                    if "neoforge" in loader_id.lower():
                        loader = "neoforge"
                        loader_version = loader_id.split("-")[-1] if "-" in loader_id else ""
                        logger(f"Detected NeoForge loader: {loader_version}", source="LAUNCHER")
                    elif "forge" in loader_id.lower():
                        loader = "forge"
                        loader_version = loader_id.split("-")[-1] if "-" in loader_id else ""
                        logger(f"Detected Forge loader: {loader_version}", source="LAUNCHER")
                    elif "fabric" in loader_id.lower():
                        loader = "fabric"
                        loader_version = loader_id.split("-")[-1] if "-" in loader_id else ""
                        logger(f"Detected Fabric loader: {loader_version}", source="LAUNCHER")
                
                # Collect mod download tasks from manifest
                files = manifest.get("files", [])
                for file_info in files:
                    project_id = file_info.get("projectID")
                    file_id = file_info.get("fileID")
                    required = file_info.get("required", True)
                    
                    if not project_id or not file_id:
                        continue
                    
                    # Try to get download URL from API
                    download_url = get_curseforge_file_download_url(project_id, file_id, api_key)
                    if download_url:
                        # Extract filename from URL
                        filename = download_url.split("/")[-1] or f"mod_{project_id}_{file_id}.jar"
                        target = mods_dir / filename
                        download_tasks.append((download_url, target, f"{filename} (proj:{project_id})"))
                    else:
                        # Log warning but don't fail - mod might be optional
                        if required:
                            logger(f"Warning: Could not get download URL for mod {project_id}/{file_id}", source="LAUNCHER")

        # First, try to extract mods from the ZIP if they exist
        mods_prefix = "mods/"
        for name in namelist:
            if name.startswith(mods_prefix) and name.endswith(".jar"):
                rel = name[len(mods_prefix):]
                target = mods_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                logger(f"Extracting mod from archive: {rel}", source="LAUNCHER")
                with zf.open(name) as src, open(target, "wb") as out_f:
                    shutil.copyfileobj(src, out_f)
                mods_extracted += 1

        # Download any additional mods from manifest
        if download_tasks:
            logger(f"Downloading {len(download_tasks)} mods from CurseForge (extracted {mods_extracted} from archive)...", source="LAUNCHER")
            parallel_download_files(download_tasks, logger)
        else:
            if mods_extracted > 0:
                logger(f"Extracted {mods_extracted} mods from modpack archive.", source="LAUNCHER")
            else:
                logger(f"No mods found in modpack.", source="LAUNCHER")

        # Extract overrides
        overrides_prefix = "overrides/"
        for name in namelist:
            if name.startswith(overrides_prefix) and not name.endswith("/"):
                rel = name[len(overrides_prefix):]
                target = dest_modpack_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as out_f:
                    shutil.copyfileobj(src, out_f)
    
    return mc_version, loader, loader_version


def import_modrinth_modpack(zip_path: Path, dest_modpack_dir: Path, logger) -> tuple:
    """Import a Modrinth .mrpack into the modpack folder.
    Returns (mc_version, loader, loader_version) tuple."""
    mc_version = ""
    loader = "vanilla"
    loader_version = ""
    
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
            # Extract Minecraft version
            mc_version = index.get("gameVersion", "")
            logger(f"Detected Minecraft version: {mc_version}", source="LAUNCHER")
            
            # Detect loader from loaders array
            loaders = index.get("loaders", [])
            if loaders:
                loader_entry = loaders[0]
                loader_id = loader_entry.get("id", "")
                loader_ver = loader_entry.get("version", "")
                
                if "neoforge" in loader_id.lower():
                    loader = "neoforge"
                    loader_version = loader_ver
                    logger(f"Detected NeoForge loader: {loader_version}", source="LAUNCHER")
                elif "forge" in loader_id.lower():
                    loader = "forge"
                    loader_version = loader_ver
                    logger(f"Detected Forge loader: {loader_version}", source="LAUNCHER")
                elif "fabric" in loader_id.lower():
                    loader = "fabric"
                    loader_version = loader_ver
                    logger(f"Detected Fabric loader: {loader_version}", source="LAUNCHER")

        # Create mods directory and prepare download tasks
        mods_dir = dest_modpack_dir / "mods"
        mods_dir.mkdir(parents=True, exist_ok=True)
        
        files = index.get("files", [])
        download_tasks = []
        
        for file_info in files:
            path = file_info.get("path")
            downloads = file_info.get("downloads") or []
            if not path or not downloads:
                continue
            url = downloads[0]
            target = dest_modpack_dir / path
            target.parent.mkdir(parents=True, exist_ok=True)
            download_tasks.append((url, target, path))
        
        # Download all files in parallel
        if download_tasks:
            logger(f"Starting parallel download of {len(download_tasks)} files...", source="LAUNCHER")
            parallel_download_files(download_tasks, logger)

        # Extract overrides (configs, resourcepacks, etc)
        overrides_prefix = "overrides/"
        for name in namelist:
            if name.startswith(overrides_prefix) and not name.endswith("/"):
                rel = name[len(overrides_prefix):]
                target = dest_modpack_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as out_f:
                    shutil.copyfileobj(src, out_f)
    
    return mc_version, loader, loader_version


# --------------------------------------------------------------------------------------
# Vanilla version download via Mojang (generic)
# --------------------------------------------------------------------------------------

def fetch_version_manifest():
    with urllib.request.urlopen(VERSION_MANIFEST_URL) as resp:
        return json.loads(resp.read().decode("utf-8"))


def find_version_in_manifest(manifest, version_id: str):
    versions = manifest.get("versions", [])
    for v in versions:
        if v.get("id") == version_id:
            return v
    return None


def download_vanilla_version(version_id: str, config, logger) -> Path:
    """Download vanilla client + libs + assets; generate java_args_<version>.txt."""
    logger(f"Fetching manifest for version {version_id}...")
    manifest = fetch_version_manifest()
    v_entry = find_version_in_manifest(manifest, version_id)
    if not v_entry:
        raise RuntimeError(f"Version {version_id} not found in Mojang manifest.")

    version_url = v_entry["url"]
    logger(f"Downloading version JSON for {version_id}...")
    with urllib.request.urlopen(version_url) as resp:
        version_data = json.loads(resp.read().decode("utf-8"))

    version_root = VANILLA_DIR / version_id
    libraries_dir = version_root / "libraries"
    versions_dir = version_root / "versions" / version_id
    assets_dir = version_root / "assets"
    objects_dir = assets_dir / "objects"

    version_root.mkdir(parents=True, exist_ok=True)
    libraries_dir.mkdir(parents=True, exist_ok=True)
    versions_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    objects_dir.mkdir(parents=True, exist_ok=True)

    version_json_path = version_root / f"{version_id}.json"
    version_json_path.write_text(json.dumps(version_data, indent=2), encoding="utf-8")

    client_download = version_data["downloads"]["client"]
    client_url = client_download["url"]
    client_jar_path = versions_dir / f"{version_id}.jar"
    logger(f"Downloading client JAR for {version_id}...")
    download_to_file(client_url, client_jar_path)

    # Download libraries in parallel
    libraries = version_data.get("libraries", [])
    lib_tasks = []
    for lib in libraries:
        downloads = lib.get("downloads", {})
        artifact = downloads.get("artifact")
        if not artifact:
            continue
        path = artifact.get("path")
        url = artifact.get("url")
        if not path or not url:
            continue
        target = libraries_dir / Path(path)
        lib_tasks.append((url, target, path))
    
    if lib_tasks:
        logger(f"Downloading {len(lib_tasks)} libraries in parallel...")
        parallel_download_files(lib_tasks, logger)

    # Download assets in parallel
    asset_index_info = version_data.get("assetIndex")
    if asset_index_info:
        asset_index_url = asset_index_info["url"]
        logger(f"Downloading asset index for {version_id}...")
        with urllib.request.urlopen(asset_index_url) as resp:
            asset_index = json.loads(resp.read().decode("utf-8"))
        (assets_dir / "indexes").mkdir(parents=True, exist_ok=True)
        (assets_dir / "indexes" / f"{asset_index_info['id']}.json").write_text(
            json.dumps(asset_index, indent=2), encoding="utf-8"
        )

        objects = asset_index.get("objects", {})
        asset_tasks = []
        for name, obj in objects.items():
            hash_ = obj["hash"]
            prefix = hash_[:2]
            url = f"{ASSET_BASE_URL}/{prefix}/{hash_}"
            target = objects_dir / prefix / hash_
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            asset_tasks.append((url, target, name))
        
        if asset_tasks:
            logger(f"Downloading {len(asset_tasks)} assets in parallel...")
            parallel_download_files(asset_tasks, logger)

    args_file = generate_java_args_from_version_json(
        version_id, version_data, version_root, libraries_dir, versions_dir, assets_dir, config
    )

    logger(f"Downloaded vanilla {version_id}. Args file: {args_file}")
    return args_file


def generate_java_args_from_version_json(
    version_id: str,
    version_data: dict,
    version_root: Path,
    libraries_dir: Path,
    versions_dir: Path,
    assets_dir: Path,
    config: dict,
) -> Path:
    """Build a java_args_<version>.txt based on Mojang's version JSON."""
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

    cp_entries = []
    for root, _, files in os.walk(libraries_dir):
        for f in files:
            if f.endswith(".jar"):
                cp_entries.append(str(Path(root) / f))

    client_jar = versions_dir / f"{version_id}.jar"
    cp_entries.append(str(client_jar))

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
            if self.console_window is not None:
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
        if self.console_text is None or self.console_window is None:
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

        self._mk_header_button(
            settings_frame,
            "Settings",
            self.settings_dialog,
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

        # Load loader metadata
        metadata = load_modpack_metadata(mp_dir)
        loader = metadata.get("loader", "vanilla")
        mc_version = metadata.get("minecraft_version", "")

        java_exec = get_java_executable()
        args_file = self.args_file_var.get()

        info = [
            f"Folder: {mp_dir}",
            "",
            f"Loader: {loader.upper()}",
            f"MC Version: {mc_version}" if mc_version else "MC Version: (not set)",
            "",
            f"Mods: {mods_count}",
            f"Config files: {config_count}",
            f"Resource packs: {resource_count}",
            "",
            f"Java: {java_exec} (expected {JAVA_RUNTIME_VERSION})",
            f"Args file: USERDIR/vanilla/{args_file}",
            "",
            "Note: Manually copy/paste mods, configs, and resourcepacks into the folders above.",
        ]
        self.detail_title.config(text=modpack_name)
        self.detail_info.config(text="\n".join(info))

    def create_modpack_dialog(self):
        dialog = Toplevel(self.root)
        dialog.title("Create Modpack")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.resizable(False, True)

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

        Label(
            dialog,
            text="Loader:",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 11),
        ).pack(padx=10, pady=(10, 3), anchor="w")

        loader_var = StringVar(value="vanilla")
        loader_frame = Frame(dialog, bg=self.panel_color)
        loader_frame.pack(padx=10, pady=3, fill="x")

        self._mk_main_button(
            loader_frame,
            "Vanilla",
            lambda: loader_var.set("vanilla"),
        ).pack(side="left", padx=3)
        self._mk_main_button(
            loader_frame,
            "Forge",
            lambda: loader_var.set("forge"),
        ).pack(side="left", padx=3)
        self._mk_main_button(
            loader_frame,
            "Fabric",
            lambda: loader_var.set("fabric"),
        ).pack(side="left", padx=3)
        self._mk_main_button(
            loader_frame,
            "NeoForge",
            lambda: loader_var.set("neoforge"),
        ).pack(side="left", padx=3)

        Label(
            dialog,
            text="Minecraft Version:",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 10),
        ).pack(padx=10, pady=(8, 3), anchor="w")

        mc_ver_var = StringVar(value="1.21.1")
        mc_entry = Entry(
            dialog,
            textvariable=mc_ver_var,
            bg="#1f2616",
            fg=self.text_color,
            insertbackground=self.text_color,
            highlightthickness=1,
            highlightbackground="#101509",
            highlightcolor=self.accent_color,
        )
        mc_entry.pack(padx=10, pady=3, fill="x")

        # Loader version section (initially hidden)
        loader_version_label = Label(
            dialog,
            text="Loader Version:",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 10),
        )
        
        loader_version_var = StringVar(value="latest")
        loader_version_menu = None
        
        def update_loader_versions():
            """Update available loader versions based on selected loader and MC version."""
            nonlocal loader_version_menu
            
            loader = loader_var.get()
            mc_version = mc_ver_var.get().strip()
            
            # Show/hide loader version section
            if loader == "vanilla":
                loader_version_label.pack_forget()
                if loader_version_menu:
                    loader_version_menu.pack_forget()
                return
            
            # Show loader version section
            loader_version_label.pack(padx=10, pady=(8, 3), anchor="w")
            
            # Destroy old menu if exists
            if loader_version_menu:
                loader_version_menu.pack_forget()
            
            try:
                self.log(f"Fetching {loader.upper()} versions for MC {mc_version}...", source="LAUNCHER")
                dialog.update_idletasks()
                
                if not mc_version:
                    versions = ["latest"]
                elif loader == "forge":
                    versions = get_available_forge_versions(mc_version)
                    if not versions:
                        versions = ["latest"]
                elif loader == "neoforge":
                    versions = get_available_neoforge_versions(mc_version)
                    if not versions:
                        versions = ["latest"]
                elif loader == "fabric":
                    fabric_versions = get_available_fabric_versions(mc_version)
                    versions = [v[0] for v in fabric_versions] if fabric_versions else ["latest"]
                else:
                    versions = ["latest"]
                
                # Create new menu
                loader_version_var.set(versions[0])
                loader_version_menu = OptionMenu(dialog, loader_version_var, *versions)
                loader_version_menu.config(
                    bg="#4d5c32",
                    fg=self.text_color,
                    activebackground=self.button_hover_color,
                    activeforeground=self.text_color,
                    relief="flat",
                    highlightthickness=0,
                )
                loader_version_menu["menu"].config(bg="#4d5c32", fg=self.text_color)
                loader_version_menu.pack(padx=10, pady=3, fill="x")
                
                self.log(f"Loaded {len(versions)} {loader.upper()} versions", source="LAUNCHER")
            except Exception as e:
                self.log(f"Error loading loader versions: {e}", source="LAUNCHER")
                loader_version_var.set("latest")
                loader_version_menu = OptionMenu(dialog, loader_version_var, "latest")
                loader_version_menu.config(
                    bg="#4d5c32",
                    fg=self.text_color,
                    activebackground=self.button_hover_color,
                    activeforeground=self.text_color,
                    relief="flat",
                    highlightthickness=0,
                )
                loader_version_menu["menu"].config(bg="#4d5c32", fg=self.text_color)
                loader_version_menu.pack(padx=10, pady=3, fill="x")

        # Bind loader and MC version changes
        loader_var.trace("w", lambda *_: update_loader_versions())
        mc_ver_var.trace("w", lambda *_: update_loader_versions())

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

            # Save loader metadata
            mc_version = mc_ver_var.get().strip()
            loader = loader_var.get()
            loader_version = loader_version_var.get() if loader != "vanilla" else ""
            metadata = {
                "loader": loader,
                "loader_version": loader_version,
                "minecraft_version": mc_version,
            }
            save_modpack_metadata(mp_dir, metadata)

            self._load_modpacks_into_list()
            for idx in range(self.modpack_listbox.size()):
                if self.modpack_listbox.get(idx) == safe_name:
                    self.modpack_listbox.selection_clear(0, END)
                    self.modpack_listbox.selection_set(idx)
                    self.modpack_listbox.activate(idx)
                    self._on_modpack_selected()
                    break
            dialog.destroy()
            self.log(f"Created modpack '{safe_name}' (loader: {loader}, MC: {mc_version}).")
            
            # Auto-download vanilla version for this MC version
            if mc_version:
                self.log(f"Auto-downloading vanilla {mc_version}...", source="LAUNCHER")
                threading.Thread(
                    target=self._auto_download_vanilla_version,
                    args=(mc_version,),
                    daemon=True,
                ).start()
            
            # Auto-download modloader if not vanilla
            if loader != "vanilla" and mc_version:
                threading.Thread(
                    target=self._auto_download_modloader,
                    args=(loader, mc_version, loader_version),
                    daemon=True,
                ).start()

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

        # Load and display current loader settings
        metadata = load_modpack_metadata(mp_dir)
        current_loader = metadata.get("loader", "vanilla")
        current_mc_version = metadata.get("minecraft_version", "")

        Label(
            dialog,
            text="Loader:",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 11),
        ).pack(padx=10, pady=(10, 3), anchor="w")

        loader_var = StringVar(value=current_loader)
        loader_frame = Frame(dialog, bg=self.panel_color)
        loader_frame.pack(padx=10, pady=3, fill="x")

        self._mk_main_button(
            loader_frame,
            "Vanilla",
            lambda: loader_var.set("vanilla"),
        ).pack(side="left", padx=3)
        self._mk_main_button(
            loader_frame,
            "Forge",
            lambda: loader_var.set("forge"),
        ).pack(side="left", padx=3)
        self._mk_main_button(
            loader_frame,
            "Fabric",
            lambda: loader_var.set("fabric"),
        ).pack(side="left", padx=3)
        self._mk_main_button(
            loader_frame,
            "NeoForge",
            lambda: loader_var.set("neoforge"),
        ).pack(side="left", padx=3)

        Label(
            dialog,
            text="Minecraft Version (for Forge/Fabric/NeoForge):",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 10),
        ).pack(padx=10, pady=(8, 3), anchor="w")

        mc_ver_var = StringVar(value=current_mc_version or "1.21.1")
        mc_entry = Entry(
            dialog,
            textvariable=mc_ver_var,
            bg="#1f2616",
            fg=self.text_color,
            insertbackground=self.text_color,
            highlightthickness=1,
            highlightbackground="#101509",
            highlightcolor=self.accent_color,
        )
        mc_entry.pack(padx=10, pady=3, fill="x")

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

            if safe_name != old_name:
                new_dir = Path(MODPACKS_DIR) / safe_name
                if new_dir.exists():
                    messagebox.showerror(
                        "Already exists",
                        f"A modpack named '{safe_name}' already exists.",
                    )
                    return
                mp_dir.rename(new_dir)
                if self.config.get("last_selected_modpack") == old_name:
                    self.config["last_selected_modpack"] = safe_name
                self.selected_modpack.set(safe_name)
                current_dir = new_dir
            else:
                current_dir = mp_dir

            # Save loader metadata
            new_loader = loader_var.get()
            new_mc_version = mc_ver_var.get().strip()
            metadata = {
                "loader": new_loader,
                "loader_version": "",
                "minecraft_version": new_mc_version,
            }
            save_modpack_metadata(current_dir, metadata)

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
            self.log(f"Updated modpack '{self.selected_modpack.get()}' (loader: {new_loader}).")
            
            # Auto-download new modloader if changed to non-vanilla
            if new_loader != "vanilla" and new_mc_version and new_loader != current_loader:
                threading.Thread(
                    target=self._auto_download_modloader,
                    args=(new_loader, new_mc_version, ""),
                    daemon=True,
                ).start()

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

            # Import and get detected MC version, loader, and loader_version
            api_key = self.config.get("curseforge_api_key", "")
            if ext == ".mrpack":
                mc_version, loader, loader_version = import_modrinth_modpack(src, dest_dir, self.log)
            else:
                mc_version, loader, loader_version = import_curseforge_modpack(src, dest_dir, self.log, api_key)

            # Initialize modpack metadata
            metadata = load_modpack_metadata(dest_dir)
            metadata["loader"] = loader
            metadata["loader_version"] = loader_version
            if mc_version:
                metadata["minecraft_version"] = mc_version
                self.log(f"Stored MC version {mc_version} for modpack.", source="LAUNCHER")
            if loader != "vanilla":
                self.log(f"Stored {loader.upper()} loader (v{loader_version}) for modpack.", source="LAUNCHER")
            save_modpack_metadata(dest_dir, metadata)

            # Auto-download vanilla version if MC version was detected
            if mc_version:
                self.log(f"Auto-downloading vanilla {mc_version}...", source="LAUNCHER")
                try:
                    download_vanilla_version(mc_version, self.config, self.log)
                    self._refresh_args_file_options()
                    self.log(f"Downloaded vanilla {mc_version}.", source="LAUNCHER")
                except Exception as e:
                    self.log(f"Warning: Could not auto-download vanilla {mc_version}: {e}", source="LAUNCHER")
                    # Don't fail the import if vanilla download fails
            
            # Auto-download modloader if detected
            if loader != "vanilla" and mc_version:
                self._auto_download_modloader(loader, mc_version, loader_version)

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

    def _auto_download_vanilla_version(self, version_id: str):
        """Auto-download vanilla version without blocking UI or showing errors."""
        try:
            args_file = download_vanilla_version(version_id, self.config, self.log)
            self.log(
                f"Downloaded vanilla {version_id}. Args: USERDIR/vanilla/{args_file.name}",
                source="LAUNCHER",
            )
            self._refresh_args_file_options()
        except Exception as e:
            self.log(f"Warning: Could not auto-download vanilla {version_id}: {e}", source="LAUNCHER")

    def _auto_download_modloader(self, loader: str, mc_version: str, loader_version: str = ""):
        """Auto-download modloader (Forge/Fabric/NeoForge) without blocking UI.
        
        Args:
            loader: "forge", "fabric", or "neoforge"
            mc_version: Minecraft version
            loader_version: Specific loader version (empty = latest)
        """
        try:
            self.log(f"Auto-downloading {loader.upper()} for MC {mc_version}...", source="LAUNCHER")
            if loader == "forge":
                installer_path = download_forge_installer(mc_version, self.log, loader_version)
                self.log(f"Forge installer cached: {installer_path.name}", source="LAUNCHER")
            elif loader == "neoforge":
                installer_path = download_neoforge_installer(mc_version, self.log, loader_version)
                self.log(f"NeoForge installer cached: {installer_path.name}", source="LAUNCHER")
            elif loader == "fabric":
                installer_path = download_fabric_installer(mc_version, self.log, loader_version)
                self.log(f"Fabric installer cached: {installer_path.name}", source="LAUNCHER")
        except Exception as e:
            self.log(f"Warning: Could not auto-download {loader} for {mc_version}: {e}", source="LAUNCHER")

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

    def settings_dialog(self):
        """Open settings dialog for API keys and launcher configuration."""
        dialog = Toplevel(self.root)
        dialog.title("Launcher Settings")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.geometry("600x300")

        # CurseForge API Key section
        Label(
            dialog,
            text="CurseForge API Key (optional)",
            bg=self.panel_color,
            fg=self.accent_color,
            font=("Helvetica", 12, "bold"),
        ).pack(padx=10, pady=(15, 3), anchor="w")

        hint_text = (
            "Get a free API key from: https://console.curseforge.com/\n"
            "Optional but recommended for better mod download reliability.\n"
            "Your key is stored locally in launcher_config.json"
        )
        Label(
            dialog,
            text=hint_text,
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 9),
            justify="left",
        ).pack(padx=10, pady=(0, 5), anchor="w")

        api_key_var = StringVar(value=self.config.get("curseforge_api_key", ""))
        api_key_entry = Entry(
            dialog,
            textvariable=api_key_var,
            bg="#1f2616",
            fg=self.text_color,
            insertbackground=self.text_color,
            highlightthickness=1,
            highlightbackground="#101509",
            highlightcolor=self.accent_color,
            show="*",  # Hide the API key characters
        )
        api_key_entry.pack(padx=10, pady=5, fill="x")

        # Info section
        info_frame = Frame(dialog, bg=self.panel_color)
        info_frame.pack(padx=10, pady=10, fill="both", expand=True)

        info_text = (
            "Settings are automatically saved when you click OK.\n\n"
            "The CurseForge API key is used when importing modpacks\n"
            "to download mod files that aren't bundled in the archive.\n\n"
            "Note: API keys are stored in plain text locally.\n"
            "Keep your key secret - don't share launchers or configs."
        )
        Label(
            info_frame,
            text=info_text,
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 9),
            justify="left",
        ).pack(anchor="w", fill="both", expand=True)

        # Buttons
        btn_frame = Frame(dialog, bg=self.panel_color)
        btn_frame.pack(padx=10, pady=10, fill="x")

        def on_save():
            api_key = api_key_var.get().strip()
            self.config["curseforge_api_key"] = api_key
            save_config(self.config)
            if api_key:
                self.log("CurseForge API key saved.", source="LAUNCHER")
            else:
                self.log("CurseForge API key cleared.", source="LAUNCHER")
            dialog.destroy()

        self._mk_main_button(btn_frame, "OK", on_save).pack(side="right", padx=5)
        self._mk_main_button(btn_frame, "Cancel", dialog.destroy).pack(
            side="right", padx=5
        )

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

        # Load modpack loader metadata
        metadata = load_modpack_metadata(mp_dir)
        loader = metadata.get("loader", "vanilla")
        mc_version = metadata.get("minecraft_version", "")

        try:
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

            if loader != "vanilla":
                self.log(f"Setting up {loader.upper()} loader...", source="LAUNCHER")
                threading.Thread(
                    target=self._setup_and_launch_with_loader,
                    args=(name, loader, mc_version, java_exe, args_file, mc_dir),
                    daemon=True,
                ).start()
            else:
                self.log(
                    f"Modpack '{name}' applied. Launching Minecraft with USERDIR/vanilla/{args_name}...",
                    source="LAUNCHER",
                )
                self._launch_with_argfile(java_exe, args_file)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to apply modpack or launch: {e}")
            self.log("Error while applying modpack / launching.", source="LAUNCHER")

    def _setup_and_launch_with_loader(self, name: str, loader: str, mc_version: str, java_exe: Path, args_file: Path, mc_dir: str):
        """Setup Forge/Fabric/NeoForge and launch with modified arguments."""
        try:
            if not mc_version:
                raise RuntimeError(f"Minecraft version not set for {loader} modpack.")

            if loader == "forge":
                installer_path = download_forge_installer(mc_version, self.log)
                self.log(f"Installing Forge to {mc_dir}...", source="LAUNCHER")
                # Run forge installer in install client mode
                # Forge installer JAR can be run with --installClient
                subprocess.run(
                    [
                        str(java_exe),
                        "-jar",
                        str(installer_path),
                        "--installClient",
                        mc_dir,
                    ],
                    cwd=str(INSTALL_DIR),
                    capture_output=True,
                    timeout=300,
                )
                self.log(f"Forge installed. Launching...", source="LAUNCHER")

            elif loader == "neoforge":
                installer_path = download_neoforge_installer(mc_version, self.log)
                self.log(f"Installing NeoForge to {mc_dir}...", source="LAUNCHER")
                # Run neoforge installer in install client mode (similar to Forge)
                subprocess.run(
                    [
                        str(java_exe),
                        "-jar",
                        str(installer_path),
                        "--installClient",
                        mc_dir,
                    ],
                    cwd=str(INSTALL_DIR),
                    capture_output=True,
                    timeout=300,
                )
                self.log(f"NeoForge installed. Launching...", source="LAUNCHER")

            elif loader == "fabric":
                installer_path = download_fabric_installer(mc_version, self.log)
                self.log(f"Installing Fabric to {mc_dir}...", source="LAUNCHER")
                # Run fabric installer
                subprocess.run(
                    [
                        str(java_exe),
                        "-jar",
                        str(installer_path),
                        "client",
                        "-dir",
                        mc_dir,
                        "-profile",
                        "fabric",
                        "-loader",
                        "0.15.0",  # or latest
                        "-game",
                        mc_version,
                    ],
                    cwd=str(INSTALL_DIR),
                    capture_output=True,
                    timeout=300,
                )
                self.log(f"Fabric installed. Launching...", source="LAUNCHER")

            # Launch using the modified args file or vanilla args
            self._launch_with_argfile(java_exe, args_file)

        except Exception as e:
            messagebox.showerror(
                "Loader setup error",
                f"Failed to setup {loader}:\n{e}",
            )
            self.log(f"Failed to setup {loader}.", source="LAUNCHER")

    def _launch_with_argfile(self, java_exe: Path, args_file: Path):
        """Launch Java with @<args_file> from USERDIR and stream logs to console."""
        try:
            rel_args_path = args_file.relative_to(INSTALL_DIR)
        except ValueError:
            rel_args_path = Path("vanilla") / args_file.name

        argfile_arg = f"@{rel_args_path.as_posix()}"

        try:
            proc = subprocess.Popen(
                [str(java_exe), argfile_arg],
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
