from pathlib import Path


# Installation directory (this is USERDIR). The package lives in USERDIR/blockcraft_launcher.
INSTALL_DIR = Path(__file__).resolve().parent.parent

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
