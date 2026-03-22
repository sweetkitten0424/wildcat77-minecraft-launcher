import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional
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

APP_NAME = "The Angel Launcher"
LAUNCHER_VERSION = "1.3.1"

INSTALL_DIR = Path(__file__).resolve().parent

MODPACKS_DIR = INSTALL_DIR / "modpacks"
VANILLA_DIR = INSTALL_DIR / "vanilla"
LIBRARIES_DIR = INSTALL_DIR / "libraries"
ASSETS_DIR = INSTALL_DIR / "assets"

# ATLauncher-style configs layout (optional but kept for parity)
CONFIGS_DIR = INSTALL_DIR / "configs"
CONFIGS_COMMON_DIR = CONFIGS_DIR / "common"
CONFIGS_IMAGES_DIR = CONFIGS_DIR / "images"
CONFIGS_SKINS_DIR = CONFIGS_IMAGES_DIR / "skins"
CONFIGS_JSON_DIR = CONFIGS_DIR / "json"
CONFIGS_JSON_MINECRAFT_DIR = CONFIGS_JSON_DIR / "minecraft"
CONFIGS_THEMES_DIR = CONFIGS_DIR / "themes"

CONFIG_FILE = CONFIGS_JSON_DIR / "config.json"
LEGACY_CONFIG_FILE = INSTALL_DIR / "launcher_config.json"

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

# Java runtime (bundled)
JAVA_RUNTIME_DIR_NAME = "runtime"
JAVA_RUNTIME_VERSION = "21.0.7"
JAVA_RUNTIME_VERSION_FILE = "java_runtime_version.txt"
JAVA_RUNTIME_ZIP_URL = "https://download.oracle.com/java/21/latest/jdk-21_windows-x64_bin.zip"

# Mojang endpoints
VERSION_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
ASSET_BASE_URL = "https://resources.download.minecraft.net"

# Parallel downloads
PARALLEL_DOWNLOADS_ENABLED = True
MAX_PARALLEL_DOWNLOADS = 16

# CurseForge
CURSEFORGE_API_KEY = ""
CURSEFORGE_GAME_ID_MINECRAFT = 432
CURSEFORGE_MODLOADER_TYPE_IDS = {
    "forge": 1,
    "fabric": 4,
    "quilt": 5,
    "neoforge": 6,
}

MODRINTH_API_URL = "https://api.modrinth.com/v2"

DEFAULT_JAVA_PARAMETERS = "-XX:+UnlockExperimentalVMOptions -XX:+UseG1GC -XX:G1NewSizePercent=20 -XX:G1ReservePercent=20 -XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M"


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

    write_if_missing(JAVA_RUNTIMES_JSON_FILE, {})
    write_if_missing(LWJGL_JSON_FILE, {})
    write_if_missing(MINECRAFT_VERSIONS_JSON_FILE, {})
    write_if_missing(NEWNEWS_JSON_FILE, {})
    write_if_missing(PACKSNEW_JSON_FILE, {})
    write_if_missing(RUNTIMES_JSON_FILE, {})
    write_if_missing(USERS_JSON_FILE, {})
    write_if_missing(VERSION_JSON_FILE, {})


def load_config() -> dict:
    ensure_configs_layout()

    if not CONFIG_FILE.exists() and LEGACY_CONFIG_FILE.exists():
        try:
            data = json.loads(LEGACY_CONFIG_FILE.read_text(encoding="utf-8"))
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}

    data.setdefault("minecraft_dir", "")
    data.setdefault("last_selected_modpack", "")
    data.setdefault("java_runtime_version", "")
    data.setdefault("auth_player_name", "Player")
    data.setdefault("auth_uuid", "00000000-0000-0000-0000-000000000000")
    data.setdefault("auth_access_token", "0")
    data.setdefault("user_type", "mojang")
    data.setdefault("version_type", "release")

    return data


def save_config(cfg: dict):
    ensure_configs_layout()
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def ensure_modpacks_dir():
    MODPACKS_DIR.mkdir(parents=True, exist_ok=True)


def list_modpacks() -> list[str]:
    ensure_modpacks_dir()
    names = []
    for p in sorted(MODPACKS_DIR.iterdir()):
        if p.is_dir():
            names.append(p.name)
    return names


def download_to_file(url: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as out_f:
        shutil.copyfileobj(resp, out_f)


def parallel_download_files(download_tasks, logger, max_workers: int = MAX_PARALLEL_DOWNLOADS):
    if not download_tasks:
        return

    if not PARALLEL_DOWNLOADS_ENABLED or len(download_tasks) == 1:
        total = len(download_tasks)
        for i, (url, dest, desc) in enumerate(download_tasks, start=1):
            logger(f"Downloading {desc} ({i}/{total})...", source="LAUNCHER")
            download_to_file(url, dest)
        return

    total = len(download_tasks)
    log_every = 1 if total <= 200 else 50

    def worker(url: str, dest: Path):
        download_to_file(url, dest)

    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for url, dest, desc in download_tasks:
            futures[pool.submit(worker, url, dest)] = desc

        for f in as_completed(futures):
            desc = futures[f]
            f.result()
            done += 1
            if log_every == 1:
                logger(f"Downloaded {desc} ({done}/{total})", source="LAUNCHER")
            elif done % log_every == 0 or done == total:
                logger(f"Downloaded {done}/{total} files...", source="LAUNCHER")


def copy_tree(src: str, dst: str):
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

    # best-effort cleanup
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


def get_java_runtime_dir() -> Path:
    return INSTALL_DIR / JAVA_RUNTIME_DIR_NAME


def get_java_executable() -> Path:
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
    if not sys.platform.startswith("win"):
        return

    current_local = read_local_java_runtime_version(config)
    desired = JAVA_RUNTIME_VERSION

    java_exe = get_java_executable()
    if current_local == desired and java_exe.exists():
        return

    logger(f"Downloading Java runtime {desired}...", source="LAUNCHER")
    java_dir = get_java_runtime_dir()
    if java_dir.exists():
        shutil.rmtree(java_dir)

    java_dir.mkdir(parents=True, exist_ok=True)
    zip_path = INSTALL_DIR / "java-runtime-download.zip"

    download_to_file(JAVA_RUNTIME_ZIP_URL, zip_path)
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
    logger(f"Java runtime {desired} ready.", source="LAUNCHER")


def fetch_version_manifest(logger=None) -> dict:
    ensure_configs_layout()

    if MINECRAFT_VERSIONS_JSON_FILE.exists():
        try:
            return json.loads(MINECRAFT_VERSIONS_JSON_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    if logger:
        logger("Fetching Mojang version manifest...", source="LAUNCHER")
    with urllib.request.urlopen(VERSION_MANIFEST_URL) as resp:
        manifest = json.loads(resp.read().decode("utf-8"))

    try:
        MINECRAFT_VERSIONS_JSON_FILE.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except OSError:
        pass

    return manifest


def find_version_in_manifest(manifest: dict, version_id: str) -> Optional[dict]:
    for v in manifest.get("versions", []):
        if v.get("id") == version_id:
            return v
    return None


def download_vanilla_version(version_id: str, config: dict, logger) -> Path:
    manifest = fetch_version_manifest(logger)
    v_entry = find_version_in_manifest(manifest, version_id)
    if not v_entry:
        raise RuntimeError(f"Version {version_id} not found in Mojang manifest.")

    with urllib.request.urlopen(v_entry["url"]) as resp:
        version_data = json.loads(resp.read().decode("utf-8"))

    ensure_configs_layout()
    mc_json_path = CONFIGS_JSON_MINECRAFT_DIR / f"{version_id}.json"
    try:
        mc_json_path.write_text(json.dumps(version_data, indent=2), encoding="utf-8")
    except OSError:
        pass

    version_root = VANILLA_DIR / version_id
    versions_dir = version_root / "versions" / version_id
    versions_dir.mkdir(parents=True, exist_ok=True)

    LIBRARIES_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    client_url = version_data["downloads"]["client"]["url"]
    client_jar_path = versions_dir / f"{version_id}.jar"
    if not client_jar_path.exists():
        logger(f"Downloading client JAR for {version_id}...", source="LAUNCHER")
        download_to_file(client_url, client_jar_path)

    download_tasks = []
    for lib in version_data.get("libraries", []):
        artifact = (lib.get("downloads") or {}).get("artifact")
        if not artifact:
            continue
        rel_path = artifact.get("path")
        url = artifact.get("url")
        if not rel_path or not url:
            continue
        target = LIBRARIES_DIR / Path(rel_path)
        if target.exists():
            continue
        download_tasks.append((url, target, f"library {Path(rel_path).name}"))

    if download_tasks:
        parallel_download_files(download_tasks, logger)

    asset_index_info = version_data.get("assetIndex")
    if asset_index_info:
        asset_index_url = asset_index_info["url"]
        logger(f"Downloading asset index for {version_id}...", source="LAUNCHER")
        with urllib.request.urlopen(asset_index_url) as resp:
            asset_index = json.loads(resp.read().decode("utf-8"))

        (ASSETS_DIR / "indexes").mkdir(parents=True, exist_ok=True)
        (ASSETS_DIR / "indexes" / f"{asset_index_info['id']}.json").write_text(
            json.dumps(asset_index, indent=2), encoding="utf-8"
        )

        objects_dir = ASSETS_DIR / "objects"
        objects_dir.mkdir(parents=True, exist_ok=True)

        download_tasks = []
        for name, obj in (asset_index.get("objects") or {}).items():
            hash_ = obj["hash"]
            prefix = hash_[:2]
            url = f"{ASSET_BASE_URL}/{prefix}/{hash_}"
            target = objects_dir / prefix / hash_
            if target.exists():
                continue
            download_tasks.append((url, target, f"asset {name}"))

        if download_tasks:
            parallel_download_files(download_tasks, logger)

    args_file = generate_java_args_from_version_json(version_id, version_data, config)
    logger(f"Downloaded vanilla {version_id}. Args file: {args_file.name}", source="LAUNCHER")
    return args_file


def generate_java_args_from_version_json(version_id: str, version_data: dict, config: dict) -> Path:
    jvm_args = []
    game_args = []

    arguments = version_data.get("arguments")
    if arguments:
        for item in arguments.get("jvm", []):
            if isinstance(item, str):
                jvm_args.append(item)
        for item in arguments.get("game", []):
            if isinstance(item, str):
                game_args.append(item)
    else:
        legacy_args = version_data.get("minecraftArguments", "")
        if legacy_args:
            game_args.extend(legacy_args.split())

    cp_entries = []
    seen = set()

    for lib in version_data.get("libraries", []):
        artifact = (lib.get("downloads") or {}).get("artifact")
        if not artifact:
            continue
        rel_path = artifact.get("path")
        if not rel_path:
            continue
        jar_path = str((LIBRARIES_DIR / Path(rel_path)).resolve())
        if jar_path in seen:
            continue
        seen.add(jar_path)
        cp_entries.append(jar_path)

    client_jar = VANILLA_DIR / version_id / "versions" / version_id / f"{version_id}.jar"
    if client_jar.exists():
        cp_entries.append(str(client_jar.resolve()))

    classpath = ";".join(cp_entries) if sys.platform.startswith("win") else ":".join(cp_entries)
    jvm_args.extend(["-cp", classpath])

    main_class = version_data.get("mainClass", "net.minecraft.client.main.Main")

    game_dir = config.get("minecraft_dir") or str((INSTALL_DIR / "instances" / version_id).resolve())
    assets_root = str(ASSETS_DIR.resolve())
    assets_index_name = (version_data.get("assetIndex") or {}).get("id", "assets")

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
            arg = arg.replace(key, str(value))
        return arg

    game_args = [apply_substitutions(a) for a in game_args]

    args_lines = []
    args_lines.extend(jvm_args)
    args_lines.append(main_class)
    args_lines.extend(game_args)

    VANILLA_DIR.mkdir(parents=True, exist_ok=True)
    args_file = VANILLA_DIR / f"java_args_{version_id}.txt"
    args_file.write_text("\n".join(args_lines), encoding="utf-8")
    return args_file


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


def create_default_instance_json(name: str) -> dict:
    return {
        "uuid": str(uuid.uuid4()),
        "launcher": {
            "name": name,
            "pack": name,
            "description": "",
            "loaderVersion": {
                "type": "",
                "version": "",
                "rawVersion": "",
            },
            "maximumMemory": 4096,
            "requiredMemory": 0,
            "additionalJvmArgs": DEFAULT_JAVA_PARAMETERS,
        },
    }


def get_instance_minecraft_version(instance: Optional[dict]) -> Optional[str]:
    if not instance:
        return None
    launcher = instance.get("launcher") or {}

    curse_file = launcher.get("curseForgeFile") or {}
    for v in (curse_file.get("gameVersions") or []):
        if isinstance(v, str) and v and v[0].isdigit():
            return v

    lv = launcher.get("loaderVersion") or {}
    raw = lv.get("rawVersion")
    if isinstance(raw, str) and raw:
        return raw.split("-")[0]

    return None


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
        VANILLA_DIR.mkdir(parents=True, exist_ok=True)
        LIBRARIES_DIR.mkdir(parents=True, exist_ok=True)
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)

        self.selected_modpack = StringVar()
        self.status_var = StringVar(value="Starting...")
        self.args_file_var = StringVar(value="")

        self.console_window = None
        self.console_text = None
        self.console_scroll_lock = False
        self.scroll_lock_btn = None

        self._build_ui()
        self._load_modpacks_into_list()
        self._restore_last_selection()
        self._refresh_args_file_options()

        threading.Thread(target=self._background_startup_tasks, daemon=True).start()

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

    def _background_startup_tasks(self):
        migrate_legacy_global_resources(self.log)
        ensure_java_runtime(self.config, self.log)
        self.log("Ready.", source="LAUNCHER")

    def _mk_main_button(self, parent, text, command):
        btn = Button(
            parent,
            text=text,
            command=command,
            bg=self.button_color,
            fg=self.text_color,
            activebackground=self.button_hover_color,
            activeforeground=self.text_color,
            relief="flat",
            padx=10,
            pady=3,
        )
        return btn

    def _build_ui(self):
        header = Frame(self.root, bg=self.panel_color, height=60)
        header.pack(fill="x", side="top")

        title_label = Label(
            header,
            text=f"{APP_NAME} v{LAUNCHER_VERSION}",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 16, "bold"),
        )
        title_label.pack(side="left", padx=10)

        self._mk_main_button(header, "Set Minecraft Folder", self.choose_minecraft_dir).pack(
            side="right", padx=10, pady=10
        )

        main_frame = Frame(self.root, bg=self.bg_color)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        left_frame = Frame(main_frame, bg=self.panel_color, width=260, bd=2)
        left_frame.pack(side="left", fill="y", padx=(0, 10), pady=0)

        right_frame = Frame(main_frame, bg=self.panel_color, bd=2)
        right_frame.pack(side="right", fill="both", expand=True, pady=0)

        Label(
            left_frame,
            text="Modpacks",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 14, "bold"),
        ).pack(anchor="w", padx=10, pady=(10, 5))

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
        self._mk_main_button(mp_button_frame, "Imp", self.import_modpack_dialog).pack(
            side="left", expand=True, fill="x", padx=2
        )
        self._mk_main_button(mp_button_frame, "Del", self.delete_modpack).pack(
            side="left", expand=True, fill="x", padx=2
        )

        details = Frame(right_frame, bg=self.panel_color)
        details.pack(fill="both", expand=True, padx=10, pady=10)

        self.details_label = Label(
            details,
            text="Select a modpack",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 13, "bold"),
            justify="left",
        )
        self.details_label.pack(anchor="w")

        Label(
            details,
            text="Vanilla args file:",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 10),
        ).pack(anchor="w", pady=(15, 2))

        self.args_option_menu = OptionMenu(details, self.args_file_var, "")
        self.args_option_menu.config(
            bg="#1f2616",
            fg=self.text_color,
            activebackground=self.button_hover_color,
            activeforeground=self.text_color,
            highlightthickness=0,
            borderwidth=0,
        )
        self.args_option_menu.pack(anchor="w")

        action_row = Frame(details, bg=self.panel_color)
        action_row.pack(fill="x", pady=(15, 10))

        self._mk_main_button(action_row, "Install Vanilla", self.install_vanilla_version_dialog).pack(
            side="left", padx=3
        )
        self._mk_main_button(action_row, "Console", self.open_console_window).pack(
            side="left", padx=3
        )
        self._mk_main_button(action_row, "Play", self.play).pack(side="right", padx=3)

        footer = Frame(self.root, bg=self.panel_color)
        footer.pack(fill="x", side="bottom")

        self.status_label = Label(
            footer,
            textvariable=self.status_var,
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 10),
            anchor="w",
        )
        self.status_label.pack(fill="x", padx=10, pady=6)

    def open_console_window(self):
        if self.console_window is not None and self.console_window.winfo_exists():
            self.console_window.lift()
            return

        self.console_window = Toplevel(self.root)
        self.console_window.title("The Angel Launcher Console")

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
        default_name = f"TAL_Console_{datetime.now().now().strftime('%Y%m%d_%H%M%S')}.log"
        path = filedialog.asksaveasfilename(
            title="Save console log",
            defaultextension=".log",
            initialfile=default_name,
            filetypes=[("Log files", "*.log"), ("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        self.log(f"Console log saved to {path}.", source="LAUNCHER")

    def console_toggle_scroll_lock(self):
        self.console_scroll_lock = not self.console_scroll_lock
        state = "ON" if self.console_scroll_lock else "OFF"
        if self.scroll_lock_btn:
            self.scroll_lock_btn.config(text=f"Scroll Lock: {state}")

    def _load_modpacks_into_list(self):
        self.modpack_listbox.delete(0, END)
        for name in list_modpacks():
            self.modpack_listbox.insert(END, name)

    def _restore_last_selection(self):
        last = self.config.get("last_selected_modpack") or ""
        if not last:
            return
        names = list_modpacks()
        if last not in names:
            return
        idx = names.index(last)
        self.modpack_listbox.selection_set(idx)
        self.modpack_listbox.see(idx)
        self.selected_modpack.set(last)
        self._update_details()

    def _on_modpack_selected(self, _evt=None):
        sel = self.modpack_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        name = self.modpack_listbox.get(idx)
        self.selected_modpack.set(name)
        self.config["last_selected_modpack"] = name
        save_config(self.config)
        self._update_details()

    def _update_details(self):
        name = self.selected_modpack.get() or ""
        if not name:
            self.details_label.config(text="Select a modpack")
            return

        mp_dir = MODPACKS_DIR / name
        inst = load_instance_json(mp_dir)
        mc_ver = get_instance_minecraft_version(inst)
        loader = get_instance_loader(inst)

        extra = []
        if mc_ver:
            extra.append(f"Minecraft: {mc_ver}")
        if loader:
            extra.append(f"Loader: {loader}")

        suffix = ("\n" + "\n".join(extra)) if extra else ""
        self.details_label.config(text=f"{name}{suffix}")

    def _refresh_args_file_options(self):
        VANILLA_DIR.mkdir(parents=True, exist_ok=True)
        args_files = sorted([p.name for p in VANILLA_DIR.glob("java_args_*.txt")])

        menu = self.args_option_menu["menu"]
        menu.delete(0, "end")

        if not args_files:
            self.args_file_var.set("<no args files>")
            menu.add_command(label="<no args files>", command=lambda: self._on_select_args_file("<no args files>"))
            return

        current = self.args_file_var.get()
        if current not in args_files:
            self.args_file_var.set(args_files[0])

        for name in args_files:
            menu.add_command(label=name, command=lambda v=name: self._on_select_args_file(v))

    def _on_select_args_file(self, name: str):
        self.args_file_var.set(name)

    def choose_minecraft_dir(self):
        directory = filedialog.askdirectory(
            title="Select your .minecraft folder or instance folder",
        )
        if not directory:
            return
        self.config["minecraft_dir"] = directory
        save_config(self.config)
        self.log(f"Minecraft directory set to: {directory}", source="LAUNCHER")

    def create_modpack_dialog(self):
        dialog = Toplevel(self.root)
        dialog.title("Create Modpack")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.resizable(False, False)

        Label(dialog, text="Modpack name:", bg=self.panel_color, fg=self.text_color).pack(
            padx=10, pady=(10, 3), anchor="w"
        )

        name_var = StringVar(value="")
        Entry(
            dialog,
            textvariable=name_var,
            bg="#1f2616",
            fg=self.text_color,
            insertbackground=self.text_color,
        ).pack(padx=10, pady=3, fill="x")

        def on_create():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("Invalid name", "Please enter a modpack name.")
                return
            mp_dir = MODPACKS_DIR / name
            if mp_dir.exists():
                messagebox.showerror("Exists", "A modpack with that name already exists.")
                return

            (mp_dir / "mods").mkdir(parents=True, exist_ok=True)
            (mp_dir / "config").mkdir(parents=True, exist_ok=True)
            (mp_dir / "resourcepacks").mkdir(parents=True, exist_ok=True)

            save_instance_json(mp_dir, create_default_instance_json(name))

            dialog.destroy()
            self._load_modpacks_into_list()

        row = Frame(dialog, bg=self.panel_color)
        row.pack(fill="x", padx=10, pady=10)
        self._mk_main_button(row, "Create", on_create).pack(side="right", padx=5)
        self._mk_main_button(row, "Cancel", dialog.destroy).pack(side="right", padx=5)

    def import_modpack_dialog(self):
        archive = filedialog.askopenfilename(
            title="Import modpack",
            filetypes=[
                ("Modrinth modpack", "*.mrpack"),
                ("CurseForge modpack", "*.zip"),
                ("All files", "*.*"),
            ],
        )
        if not archive:
            return

        archive_path = Path(archive)
        default_name = archive_path.stem

        dialog = Toplevel(self.root)
        dialog.title("Import Modpack")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.resizable(False, False)

        Label(dialog, text="Modpack name:", bg=self.panel_color, fg=self.text_color).pack(
            padx=10, pady=(10, 3), anchor="w"
        )

        name_var = StringVar(value=default_name)
        Entry(
            dialog,
            textvariable=name_var,
            bg="#1f2616",
            fg=self.text_color,
            insertbackground=self.text_color,
        ).pack(padx=10, pady=3, fill="x")

        def on_import():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("Invalid name", "Please enter a modpack name.")
                return
            dialog.destroy()

            def worker():
                try:
                    self._do_import_modpack(archive_path, name)
                except Exception as e:
                    self.log(str(e), source="LAUNCHER")
                    self.root.after(0, lambda: messagebox.showerror("Import failed", str(e)))

            threading.Thread(target=worker, daemon=True).start()

        row = Frame(dialog, bg=self.panel_color)
        row.pack(fill="x", padx=10, pady=10)
        self._mk_main_button(row, "Import", on_import).pack(side="right", padx=5)
        self._mk_main_button(row, "Cancel", dialog.destroy).pack(side="right", padx=5)

    def _do_import_modpack(self, archive_path: Path, name: str):
        mp_dir = MODPACKS_DIR / name
        if mp_dir.exists():
            raise RuntimeError("A modpack with that name already exists.")

        mp_dir.mkdir(parents=True, exist_ok=True)
        (mp_dir / "mods").mkdir(parents=True, exist_ok=True)
        (mp_dir / "config").mkdir(parents=True, exist_ok=True)
        (mp_dir / "resourcepacks").mkdir(parents=True, exist_ok=True)

        instance = create_default_instance_json(name)
        launcher = instance.get("launcher") or {}
        lv = launcher.get("loaderVersion") or {}

        suffix = archive_path.suffix.lower()
        if suffix == ".mrpack":
            self.log(f"Importing Modrinth modpack: {archive_path.name}", source="LAUNCHER")
            index = import_modrinth_modpack(archive_path, mp_dir, self.log)

            deps = (index or {}).get("dependencies") or {}
            mc = deps.get("minecraft")
            if isinstance(mc, str) and mc:
                lv["rawVersion"] = mc

            if "neoforge" in deps:
                lv["type"] = "neoforge"
                if mc:
                    lv["rawVersion"] = f"{mc}-{deps['neoforge']}"
            elif "forge" in deps:
                lv["type"] = "forge"
                if mc:
                    lv["rawVersion"] = f"{mc}-{deps['forge']}"
            elif "fabric-loader" in deps:
                lv["type"] = "fabric"
                if mc:
                    lv["rawVersion"] = f"{mc}-{deps['fabric-loader']}"
            elif "quilt-loader" in deps:
                lv["type"] = "quilt"
                if mc:
                    lv["rawVersion"] = f"{mc}-{deps['quilt-loader']}"

        elif suffix == ".zip":
            self.log(f"Importing CurseForge modpack: {archive_path.name}", source="LAUNCHER")
            manifest = import_curseforge_modpack(archive_path, mp_dir)

            mc = ((manifest or {}).get("minecraft") or {}).get("version")
            if isinstance(mc, str) and mc:
                lv["rawVersion"] = mc

            modloaders = ((manifest or {}).get("minecraft") or {}).get("modLoaders") or []
            if modloaders:
                mid = (modloaders[0] or {}).get("id")
                if isinstance(mid, str) and "-" in mid:
                    loader_name, loader_ver = mid.split("-", 1)
                    lv["type"] = normalize_loader_name(loader_name)
                    if mc:
                        lv["rawVersion"] = f"{mc}-{loader_ver}"
        else:
            raise RuntimeError("Unsupported modpack format. Use .mrpack or .zip")

        launcher["loaderVersion"] = lv
        instance["launcher"] = launcher
        save_instance_json(mp_dir, instance)

        def update_ui():
            self._load_modpacks_into_list()
            names = list_modpacks()
            if name in names:
                idx = names.index(name)
                self.modpack_listbox.selection_clear(0, END)
                self.modpack_listbox.selection_set(idx)
                self.modpack_listbox.see(idx)
                self.selected_modpack.set(name)
                self.config["last_selected_modpack"] = name
                save_config(self.config)
                self._update_details()

        self.root.after(0, update_ui)

    def edit_modpack_dialog(self):
        name = self.selected_modpack.get()
        if not name:
            messagebox.showinfo("No modpack", "Select a modpack first.")
            return

        mp_dir = MODPACKS_DIR / name
        if not mp_dir.exists():
            messagebox.showerror("Missing", f"Modpack folder missing: {mp_dir}")
            return

        inst = load_instance_json(mp_dir)
        if inst is None:
            inst = create_default_instance_json(name)
            save_instance_json(mp_dir, inst)

        launcher = inst.get("launcher") or {}
        lv = launcher.get("loaderVersion") or {}

        dialog = Toplevel(self.root)
        dialog.title(f"Edit Modpack: {name}")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.geometry("720x460")

        top = Frame(dialog, bg=self.panel_color)
        top.pack(fill="x", padx=10, pady=10)

        Label(top, text="Minecraft version:", bg=self.panel_color, fg=self.text_color).grid(row=0, column=0, sticky="w")
        mc_var = StringVar(value=get_instance_minecraft_version(inst) or "")
        Entry(top, textvariable=mc_var, bg="#1f2616", fg=self.text_color, insertbackground=self.text_color).grid(
            row=0, column=1, sticky="we", padx=(8, 0)
        )

        Label(top, text="Loader:", bg=self.panel_color, fg=self.text_color).grid(row=1, column=0, sticky="w", pady=(6, 0))
        loader_choices = ["", "forge", "fabric", "quilt", "neoforge"]
        loader_var = StringVar(value=normalize_loader_name(lv.get("type") or ""))
        OptionMenu(top, loader_var, *loader_choices).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(6, 0))

        Label(top, text="Max memory (MB):", bg=self.panel_color, fg=self.text_color).grid(row=2, column=0, sticky="w", pady=(6, 0))
        max_mem_var = StringVar(value=str((launcher.get("maximumMemory") or 4096)))
        Entry(top, textvariable=max_mem_var, bg="#1f2616", fg=self.text_color, insertbackground=self.text_color).grid(
            row=2, column=1, sticky="we", padx=(8, 0), pady=(6, 0)
        )

        Label(top, text="Min memory (MB):", bg=self.panel_color, fg=self.text_color).grid(row=3, column=0, sticky="w", pady=(6, 0))
        min_mem_var = StringVar(value=str((launcher.get("requiredMemory") or 0)))
        Entry(top, textvariable=min_mem_var, bg="#1f2616", fg=self.text_color, insertbackground=self.text_color).grid(
            row=3, column=1, sticky="we", padx=(8, 0), pady=(6, 0)
        )

        Label(top, text="Extra JVM args:", bg=self.panel_color, fg=self.text_color).grid(row=4, column=0, sticky="w", pady=(6, 0))
        extra_var = StringVar(value=str(launcher.get("additionalJvmArgs") or ""))
        Entry(top, textvariable=extra_var, bg="#1f2616", fg=self.text_color, insertbackground=self.text_color).grid(
            row=4, column=1, sticky="we", padx=(8, 0), pady=(6, 0)
        )

        top.columnconfigure(1, weight=1)

        mid = Frame(dialog, bg=self.panel_color)
        mid.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        Label(mid, text="Mods:", bg=self.panel_color, fg=self.text_color, font=("Helvetica", 11, "bold")).pack(anchor="w")

        mods_list = Listbox(
            mid,
            bg="#1f2616",
            fg=self.text_color,
            selectbackground=self.button_color,
            selectforeground=self.text_color,
            highlightthickness=0,
            borderwidth=0,
            activestyle="none",
            font=("Helvetica", 10),
        )
        mods_list.pack(fill="both", expand=True, pady=5)

        mods_dir = mp_dir / "mods"
        mods_dir.mkdir(parents=True, exist_ok=True)
        for p in sorted(mods_dir.glob("*.jar")):
            mods_list.insert(END, p.name)

        btn_row = Frame(mid, bg=self.panel_color)
        btn_row.pack(fill="x")

        def on_remove_selected():
            sel = mods_list.curselection()
            if not sel:
                return
            fname = mods_list.get(sel[0])
            try:
                (mods_dir / fname).unlink()
            except OSError:
                pass
            mods_list.delete(sel[0])

        self._mk_main_button(btn_row, "Add Mod", lambda: self.add_mod_dialog(mp_dir, mods_list)).pack(side="left", padx=3)
        self._mk_main_button(btn_row, "Remove", on_remove_selected).pack(side="left", padx=3)

        bottom = Frame(dialog, bg=self.panel_color)
        bottom.pack(fill="x", padx=10, pady=(0, 10))

        def on_save():
            launcher = inst.get("launcher") or {}
            lv = launcher.get("loaderVersion") or {}

            mc = mc_var.get().strip()
            loader = loader_var.get().strip()

            try:
                max_mem = int(max_mem_var.get().strip())
            except ValueError:
                max_mem = 4096

            try:
                min_mem = int(min_mem_var.get().strip())
            except ValueError:
                min_mem = 0

            lv["type"] = loader
            launcher["loaderVersion"] = lv
            launcher["maximumMemory"] = max_mem
            launcher["requiredMemory"] = min_mem
            launcher["additionalJvmArgs"] = extra_var.get()

            # store mc version on rawVersion for now
            if mc:
                lv["rawVersion"] = mc

            inst["launcher"] = launcher
            save_instance_json(mp_dir, inst)

            dialog.destroy()
            self._update_details()

        self._mk_main_button(bottom, "Save", on_save).pack(side="right", padx=5)
        self._mk_main_button(bottom, "Close", dialog.destroy).pack(side="right", padx=5)

    def delete_modpack(self):
        name = self.selected_modpack.get()
        if not name:
            messagebox.showinfo("No modpack", "Select a modpack first.")
            return
        mp_dir = MODPACKS_DIR / name
        if not mp_dir.exists():
            return
        if not messagebox.askyesno("Delete", f"Delete modpack '{name}'? This removes {mp_dir}."):
            return
        shutil.rmtree(mp_dir)
        self.selected_modpack.set("")
        self._load_modpacks_into_list()
        self._update_details()

    def install_vanilla_version_dialog(self):
        dialog = Toplevel(self.root)
        dialog.title("Install Vanilla Version")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.resizable(False, False)

        Label(
            dialog,
            text="Minecraft Version ID (e.g. 1.21.1):",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 11),
        ).pack(padx=10, pady=(10, 3), anchor="w")

        version_var = StringVar(value="1.21.1")
        entry = Entry(
            dialog,
            textvariable=version_var,
            bg="#1f2616",
            fg=self.text_color,
            insertbackground=self.text_color,
        )
        entry.pack(padx=10, pady=3, fill="x")
        entry.focus_set()

        def on_install():
            version_id = version_var.get().strip()
            if not version_id:
                messagebox.showwarning("Invalid version", "Please enter a version ID.")
                return
            dialog.destroy()
            threading.Thread(target=self._do_install_vanilla_version, args=(version_id,), daemon=True).start()

        btn_frame = Frame(dialog, bg=self.panel_color)
        btn_frame.pack(padx=10, pady=10, fill="x")

        self._mk_main_button(btn_frame, "Install", on_install).pack(side="right", padx=5)
        self._mk_main_button(btn_frame, "Cancel", dialog.destroy).pack(side="right", padx=5)

    def _do_install_vanilla_version(self, version_id: str):
        try:
            args_file = download_vanilla_version(version_id, self.config, self.log)
            self._refresh_args_file_options()
            self._on_select_args_file(args_file.name)
        except Exception as e:
            messagebox.showerror("Install error", f"Failed to install vanilla {version_id}:\n{e}")
            self.log("Failed to install vanilla version.", source="LAUNCHER")

    def add_mod_dialog(self, mp_dir: Path, mods_list: Listbox):
        inst = load_instance_json(mp_dir)
        target_mc_version = get_instance_minecraft_version(inst) or infer_minecraft_version_from_args_filename(self.args_file_var.get())
        target_loader = get_instance_loader(inst)

        dialog = Toplevel(self.root)
        dialog.title("Add Mod")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.resizable(False, False)

        Label(dialog, text="Source:", bg=self.panel_color, fg=self.text_color).pack(padx=10, pady=(10, 3), anchor="w")
        source_var = StringVar(value="Modrinth")
        OptionMenu(dialog, source_var, "Modrinth", "CurseForge").pack(padx=10, pady=3, anchor="w")

        Label(dialog, text="Project URL / slug / id:", bg=self.panel_color, fg=self.text_color).pack(
            padx=10, pady=(8, 3), anchor="w"
        )
        text_var = StringVar(value="")
        Entry(dialog, textvariable=text_var, bg="#1f2616", fg=self.text_color, insertbackground=self.text_color).pack(
            padx=10, pady=3, fill="x"
        )

        hint = f"Target MC: {target_mc_version or 'unknown'} | Loader: {target_loader or 'any'}"
        Label(dialog, text=hint, bg=self.panel_color, fg=self.text_color, font=("Helvetica", 9)).pack(
            padx=10, pady=(0, 8), anchor="w"
        )

        def on_add():
            txt = text_var.get().strip()
            if not txt:
                messagebox.showwarning("Missing", "Enter a URL/slug/id.")
                return
            dialog.destroy()

            def worker():
                try:
                    mods_dir = mp_dir / "mods"
                    mods_dir.mkdir(parents=True, exist_ok=True)

                    if source_var.get() == "Modrinth":
                        self._add_mod_from_modrinth(txt, mods_dir, target_mc_version, target_loader)
                    else:
                        self._add_mod_from_curseforge(txt, mods_dir, target_mc_version, target_loader)

                    self.root.after(0, lambda: self._reload_mods_list(mods_list, mods_dir))
                except Exception as e:
                    self.log(str(e), source="LAUNCHER")
                    self.root.after(0, lambda: messagebox.showerror("Add mod failed", str(e)))

            threading.Thread(target=worker, daemon=True).start()

        btn = Frame(dialog, bg=self.panel_color)
        btn.pack(fill="x", padx=10, pady=10)
        self._mk_main_button(btn, "Add", on_add).pack(side="right", padx=5)
        self._mk_main_button(btn, "Cancel", dialog.destroy).pack(side="right", padx=5)

    def _reload_mods_list(self, mods_list: Listbox, mods_dir: Path):
        mods_list.delete(0, END)
        for p in sorted(mods_dir.glob("*.jar")):
            mods_list.insert(END, p.name)

    def _mr_resolve_project_id(self, text: str) -> str:
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

    def _add_mod_from_modrinth(self, text: str, mods_dir: Path, target_mc_version: Optional[str], target_loader: Optional[str]):
        project_id = self._mr_resolve_project_id(text)

        # project slug/id resolves here
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
        self.log(f"Downloading Modrinth mod '{title}' -> {filename}", source="LAUNCHER")
        download_to_file(file_url, target)

    def _cf_api_request(self, path: str) -> dict:
        api_key = CURSEFORGE_API_KEY.strip()
        if not api_key:
            raise RuntimeError("CURSEFORGE_API_KEY is empty.")

        url = "https://api.curseforge.com" + path
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        req.add_header("x-api-key", api_key)

        with urllib.request.urlopen(req) as resp:
            data = resp.read().decode("utf-8")
        return json.loads(data)

    def _cf_resolve_project(self, text: str) -> int:
        parsed = urllib.parse.urlparse(text)
        slug = text.strip()
        if parsed.scheme in ("http", "https") and parsed.netloc:
            parts = [p for p in parsed.path.split("/") if p]
            # /minecraft/mc-mods/<slug>
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
        data = self._cf_api_request(f"/v1/mods/search?{q}")
        mods = data.get("data") or []
        if not mods:
            raise RuntimeError(f"CurseForge project not found for '{text}'.")
        return int(mods[0]["id"])

    def _cf_pick_file_for_mod(self, mod_id: int, target_mc_version: Optional[str], target_loader: Optional[str]) -> dict:
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
                data = self._cf_api_request(f"/v1/mods/{mod_id}/files?{urllib.parse.urlencode(query)}")
                files = data.get("data", [])
                if files:
                    return files[0]
            except urllib.error.HTTPError:
                pass

        data = self._cf_api_request(f"/v1/mods/{mod_id}/files")
        files = data.get("data", [])
        if not files:
            raise RuntimeError(f"No files found for CurseForge mod id={mod_id}.")

        return files[0]

    def _add_mod_from_curseforge(self, text: str, mods_dir: Path, target_mc_version: Optional[str], target_loader: Optional[str]):
        text = text.strip()
        parsed = urllib.parse.urlparse(text)
        path = parsed.path or ""
        is_http_url = parsed.scheme in ("http", "https") and parsed.netloc != ""

        if is_http_url and path.lower().endswith(".jar"):
            self.log(f"Downloading CurseForge mod from direct URL '{text}'...", source="LAUNCHER")
            name = os.path.basename(path) or "curseforge_mod.jar"
            download_to_file(text, mods_dir / name)
            return

        if not CURSEFORGE_API_KEY.strip():
            raise RuntimeError("CURSEFORGE_API_KEY is empty. Set it or use a direct .jar URL.")

        if not is_http_url and text.isdigit():
            mod_id = int(text)
        else:
            mod_id = self._cf_resolve_project(text)

        file_info = self._cf_pick_file_for_mod(mod_id, target_mc_version, target_loader)
        file_name = file_info.get("fileName") or "curseforge_mod.jar"
        download_url = file_info.get("downloadUrl")
        if not download_url:
            raise RuntimeError("CurseForge file has no downloadUrl.")

        target = mods_dir / file_name
        self.log(f"Downloading CurseForge mod id={mod_id} -> {file_name}", source="LAUNCHER")
        download_to_file(download_url, target)

    def play(self):
        name = self.selected_modpack.get()
        if not name:
            messagebox.showinfo("No modpack", "Please select a modpack first.")
            return

        mc_dir = self.config.get("minecraft_dir") or ""
        if not mc_dir or not os.path.isdir(mc_dir):
            messagebox.showerror("Minecraft folder not set", "Please set your .minecraft folder first.")
            return

        mp_dir = MODPACKS_DIR / name
        if not mp_dir.exists():
            messagebox.showerror("Missing modpack", f"Modpack folder missing: {mp_dir}")
            return

        inst = load_instance_json(mp_dir)
        if inst is None:
            inst = create_default_instance_json(name)
            save_instance_json(mp_dir, inst)

        launcher_cfg = inst.get("launcher") or {}
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
        if sys.platform.startswith("win") and not java_exe.exists():
            messagebox.showerror("Java not found", f"Bundled Java not found at:\n{java_exe}")
            return

        args_name = self.args_file_var.get()
        if args_name.startswith("<no args"):
            messagebox.showerror("No args", "No vanilla args files found. Install vanilla first.")
            return

        args_file = VANILLA_DIR / args_name
        if not args_file.exists():
            messagebox.showerror("Args missing", f"Args file not found:\n{args_file}")
            return

        self.open_console_window()
        self.log(f"Applying modpack '{name}'...", source="LAUNCHER")

        mods_src = mp_dir / "mods"
        mods_dst = Path(mc_dir) / "mods"
        mods_dst.mkdir(parents=True, exist_ok=True)
        clean_dir(str(mods_dst))
        copy_tree(str(mods_src), str(mods_dst))

        config_src = mp_dir / "config"
        config_dst = Path(mc_dir) / "config"
        config_dst.mkdir(parents=True, exist_ok=True)
        copy_tree(str(config_src), str(config_dst))

        res_src = mp_dir / "resourcepacks"
        res_dst = Path(mc_dir) / "resourcepacks"
        res_dst.mkdir(parents=True, exist_ok=True)
        copy_tree(str(res_src), str(res_dst))

        self._launch_with_argfile(java_exe, args_file, max_mem=max_mem, min_mem=min_mem, extra_jvm=extra_jvm)

    def _launch_with_argfile(self, java_exe: Path, args_file: Path, max_mem: Optional[int] = None, min_mem: Optional[int] = None, extra_jvm: str = ""):
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

        proc = subprocess.Popen(
            cmd,
            cwd=str(INSTALL_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        def reader_thread():
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n\r")
                if line:
                    self.log(line, source="GAME")

        threading.Thread(target=reader_thread, daemon=True).start()


def main():
    root = Tk()
    app = MinecraftLauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
