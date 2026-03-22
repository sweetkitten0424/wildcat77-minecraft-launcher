import json

from .constants import APP_NAME, LAUNCHER_VERSION
from .paths import (
    ACCOUNTS_JSON_FILE,
    ATLAUNCHER_JSON_FILE,
    CONFIGS_COMMON_DIR,
    CONFIGS_JSON_DIR,
    CONFIGS_JSON_MINECRAFT_DIR,
    CONFIGS_SKINS_DIR,
    CONFIGS_THEMES_DIR,
    CONFIG_FILE,
    JAVA_RUNTIMES_JSON_FILE,
    LEGACY_CONFIG_FILE,
    LWJGL_JSON_FILE,
    MINECRAFT_VERSIONS_JSON_FILE,
    NEWNEWS_JSON_FILE,
    PACKSNEW_JSON_FILE,
    RUNTIMES_JSON_FILE,
    USERS_JSON_FILE,
    VERSION_JSON_FILE,
 )


def ensure_configs_layout():
    CONFIGS_COMMON_DIR.mkdir(parents=True, exist_ok=True)
    CONFIGS_SKINS_DIR.mkdir(parents=True, exist_ok=True)
    CONFIGS_JSON_MINECRAFT_DIR.mkdir(parents=True, exist_ok=True)
    CONFIGS_THEMES_DIR.mkdir(parents=True, exist_ok=True)

    def write_if_missing(path, obj):
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
