import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
import urllib.error
import zipfile
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
LAUNCHER_VERSION = "1.3.0"

CONFIG_FILE = "launcher_config.json"
MODPACKS_DIR = "modpacks"

# Installation directory (this is USERDIR)
INSTALL_DIR = Path(__file__).resolve().parent

# Java runtime configuration
JAVA_RUNTIME_DIR_NAME = "java-runtime"
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

# CurseForge API key (hard-coded).
# WARNING: Anyone who can read this file can see your key.
# Replace the placeholder with your real key string.
CURSEFORGE_API_KEY = "$2a$10$5R7Sc1GxclJVk3tiNEVytexYE599JRnSncKGANk7JdYMErAq3xDgy"


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

def import_curseforge_modpack(zip_path: Path, dest_modpack_dir: Path):
    """Import a CurseForge modpack zip: extract overrides/ into the modpack."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()

        manifest_name = None
        for name in namelist:
            if name.endswith("manifest.json"):
                manifest_name = name
                break

        if manifest_name:
            with zf.open(manifest_name) as mf:
                _manifest = json.loads(mf.read().decode("utf-8"))
            # manifest currently unused

        overrides_prefix = "overrides/"
        for name in namelist:
            if name.startswith(overrides_prefix) and not name.endswith("/"):
                rel = name[len(overrides_prefix):]
                target = dest_modpack_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as out_f:
                    shutil.copyfileobj(src, out_f)


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
        for i, file_info in enumerate(files, start=1):
            path = file_info.get("path")
            downloads = file_info.get("downloads") or []
            if not path or not downloads:
                continue
            url = downloads[0]
            target = dest_modpack_dir / path
            target.parent.mkdir(parents=True, exist_ok=True)
            logger(f"Downloading Modrinth file {i}/{len(files)}...", source="LAUNCHER")
            try:
                download_to_file(url, target)
            except Exception as e:
                logger(f"Failed to download {url}: {e}", source="LAUNCHER")

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

    libraries = version_data.get("libraries", [])
    total_libs = len(libraries)
    for i, lib in enumerate(libraries, start=1):
        downloads = lib.get("downloads", {})
        artifact = downloads.get("artifact")
        if not artifact:
            continue
        path = artifact.get("path")
        url = artifact.get("url")
        if not path or not url:
            continue
        target = libraries_dir / Path(path)
        logger(f"Downloading library {i}/{total_libs}...")
        download_to_file(url, target)

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
        total_objects = len(objects)
        for i, (name, obj) in enumerate(objects.items(), start=1):
            hash_ = obj["hash"]
            prefix = hash_[:2]
            url = f"{ASSET_BASE_URL}/{prefix}/{hash_}"
            target = objects_dir / prefix / hash_
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if i % 50 == 0:
                logger(f"Downloading assets {i}/{total_objects}...")
            try:
                download_to_file(url, target)
            except Exception as e:
                logger(f"Failed to download asset {name} ({url}): {e}")

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

        info = [
            f"Folder: {mp_dir}",
            "",
            f"Mods: {mods_count}",
            f"Config files: {config_count}",
            f"Resource packs: {resource_count}",
            "",
            f"Java: {java_exec} (expected {JAVA_RUNTIME_VERSION})",
            f"Args file: USERDIR/vanilla/{args_file}",
            "",
            "Tip: Drop files into this modpack's mods/config/resourcepacks folders.",
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
            else:
                import_curseforge_modpack(src, dest_dir)

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

            if source == "modrinth":
                self._add_mod_from_modrinth(text, mods_dir)
            else:
                self._add_mod_from_curseforge(text, mods_dir)

        except Exception as e:
            messagebox.showerror(
                "Add mod error",
                f"Failed to add mod:\n{e}",
            )
            self.log("Failed to add mod.", source="LAUNCHER")

    def _add_mod_from_modrinth(self, text: str, mods_dir: Path):
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

        url_versions = f"https://api.modrinth.com/v2/project/{project_id}/version"
        with urllib.request.urlopen(url_versions) as resp:
            versions = json.loads(resp.read().decode("utf-8"))

        if not versions:
            raise RuntimeError("No versions found on Modrinth project.")

        version = versions[0]
        files = version.get("files", [])
        if not files:
            raise RuntimeError("No files in latest Modrinth version.")

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

    def _cf_pick_file_for_mod(self, mod_id: int, target_mc_version: str | None) -> dict:
        data = self._cf_api_request(f"/v1/mods/{mod_id}/files")
        files = data.get("data", [])
        if not files:
            raise RuntimeError(f"No files found for CurseForge mod id={mod_id}.")

        if not target_mc_version:
            return files[0]

        matching = []
        for f in files:
            gv = f.get("gameVersions") or []
            if target_mc_version in gv:
                matching.append(f)

        if matching:
            return matching[0]
        return files[0]

    def _add_mod_from_curseforge(self, text: str, mods_dir: Path):
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

        target_mc_version = None
        args_name = self.args_file_var.get()
        m = re.search(r"java_args_(\d+\.\d+(?:\.\d+)?).txt", args_name)
        if m:
            target_mc_version = m.group(1)
            self.log(
                f"Target MC version inferred as {target_mc_version} from args file.",
                source="LAUNCHER",
            )

        file_info = self._cf_pick_file_for_mod(mod_id, target_mc_version)
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

            self.log(
                f"Modpack '{name}' applied. Launching Minecraft with USERDIR/vanilla/{args_name}...",
                source="LAUNCHER",
            )
            self._launch_with_argfile(java_exe, args_file)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to apply modpack or launch: {e}")
            self.log("Error while applying modpack / launching.", source="LAUNCHER")

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
