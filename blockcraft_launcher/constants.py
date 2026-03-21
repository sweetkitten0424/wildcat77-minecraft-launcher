APP_NAME = "BlockCraft Launcher"
LAUNCHER_VERSION = "1.3.1"

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

# Modrinth
MODRINTH_API_URL = "https://api.modrinth.com/v2"

DEFAULT_JAVA_PARAMETERS = "-XX:+UnlockExperimentalVMOptions -XX:+UseG1GC -XX:G1NewSizePercent=20 -XX:G1ReservePercent=20 -XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M"
