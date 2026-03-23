from __future__ import annotations

from dataclasses import dataclass

APP_NAME = "The Angel Launcher"
LAUNCHER_VERSION = "1.3.1"

# --------------------------------------------------------------------------------------
# CurseForge domains, endpoints, config, etc
# --------------------------------------------------------------------------------------

CURSEFORGE_CORE_API_URL = "https://api.curseforge.com/v1"
CURSEFORGE_CORE_API_HOST = "api.curseforge.com"

# If you fork or modify this launcher, you must not use ATLauncher's key and must apply for your own.
# This project uses CURSEFORGE_API_KEY (below) as a user-supplied key.
CURSEFORGE_CORE_API_KEY = ""

# User-supplied CurseForge API key used by TAL.
CURSEFORGE_API_KEY = ""

CURSEFORGE_FORGE_MODLOADER_ID = 1
CURSEFORGE_FABRIC_MODLOADER_ID = 4
CURSEFORGE_QUILT_MODLOADER_ID = 5
CURSEFORGE_NEOFORGE_MODLOADER_ID = 6

CURSEFORGE_PAGINATION_SIZE = 20

CURSEFORGE_FABRIC_MOD_ID = 306612
CURSEFORGE_LEGACY_FABRIC_MOD_ID = 400281
CURSEFORGE_JUMPLOADER_MOD_ID = 361988
CURSEFORGE_SINYTRA_CONNECTOR_MOD_ID = 890127
CURSEFORGE_FORGIFIED_FABRIC_API_MOD_ID = 889079

CURSEFORGE_PLUGINS_SECTION_ID = 5
CURSEFORGE_MODS_SECTION_ID = 6
CURSEFORGE_MODPACKS_SECTION_ID = 4471
CURSEFORGE_RESOURCE_PACKS_SECTION_ID = 12
CURSEFORGE_WORLDS_SECTION_ID = 17
CURSEFORGE_SHADER_PACKS_SECTION_ID = 6552

# Minecraft is gameId 432 on CurseForge
CURSEFORGE_GAME_ID_MINECRAFT = 432

CURSEFORGE_MODLOADER_TYPE_IDS = {
    "forge": CURSEFORGE_FORGE_MODLOADER_ID,
    "fabric": CURSEFORGE_FABRIC_MODLOADER_ID,
    "quilt": CURSEFORGE_QUILT_MODLOADER_ID,
    "neoforge": CURSEFORGE_NEOFORGE_MODLOADER_ID,
}

# --------------------------------------------------------------------------------------
# Modrinth domains, endpoints, config, etc
# --------------------------------------------------------------------------------------

MODRINTH_API_URL = "https://api.modrinth.com/v2"
MODRINTH_HOST = "api.modrinth.com"
MODRINTH_FABRIC_MOD_ID = "P7dR8mSH"
MODRINTH_LEGACY_FABRIC_MOD_ID = "9CJED7xi"
MODRINTH_QSL_MOD_ID = "qvIfYCYJ"
MODRINTH_SINYTRA_CONNECTOR_MOD_ID = "u58R1TMW"
MODRINTH_FORGIFIED_FABRIC_API_MOD_ID = "Aqlf1Shp"
MODRINTH_PAGINATION_SIZE = 20

# --------------------------------------------------------------------------------------
# FTB domains, endpoints, config, etc
# --------------------------------------------------------------------------------------

FTB_API_URL = "https://api.feed-the-beast.com/v1/modpacks/public"
FTB_HOST = "api.feed-the-beast.com"
FTB_PAGINATION_SIZE = 20

# --------------------------------------------------------------------------------------
# Technic domains, endpoints, config, etc
# --------------------------------------------------------------------------------------

TECHNIC_API_URL = "https://api.technicpack.net"
TECHNIC_HOST = "api.technicpack.net"
TECHNIC_PAGINATION_SIZE = 20

# --------------------------------------------------------------------------------------
# Forge domains, endpoints, etc
# --------------------------------------------------------------------------------------

FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"
FORGE_PROMOTIONS_FILE = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
FORGE_MAVEN_BASE = "https://maven.minecraftforge.net/"
FORGE_HOST = "maven.minecraftforge.net"
FORGE_OLD_MAVEN_BASE = "https://files.minecraftforge.net/maven/"

# --------------------------------------------------------------------------------------
# Fabric domains, endpoints, etc
# --------------------------------------------------------------------------------------

FABRIC_MAVEN = "https://maven.fabricmc.net/"
FABRIC_HOST = "maven.fabricmc.net"

# Legacy Fabric domains, endpoints, etc
LEGACY_FABRIC_MAVEN = "https://maven.legacyfabric.net/"
LEGACY_FABRIC_HOST = "maven.legacyfabric.net"

# --------------------------------------------------------------------------------------
# NeoForge domains, endpoints, etc
# --------------------------------------------------------------------------------------

NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/"
NEOFORGE_HOST = "maven.neoforged.net"

# --------------------------------------------------------------------------------------
# Quilt domains, endpoints, etc
# --------------------------------------------------------------------------------------

QUILT_MAVEN = "https://maven.quiltmc.org/repository/release/"
QUILT_HOST = "maven.quiltmc.org"

# --------------------------------------------------------------------------------------
# Minecraft domains, endpoints, etc
# --------------------------------------------------------------------------------------

LAUNCHER_META_MINECRAFT = "https://launchermeta.mojang.com"
MINECRAFT_LIBRARIES = "https://libraries.minecraft.net/"
MINECRAFT_RESOURCES = "https://resources.download.minecraft.net"

# Note: Mojang's original manifest URL. TAL currently uses piston-meta's v2 manifest for installs.
MINECRAFT_VERSION_MANIFEST_URL = LAUNCHER_META_MINECRAFT + "/mc/game/version_manifest.json"

# Mojang java runtime product manifest (not currently used by TAL's Oracle ZIP runtime download).
MINECRAFT_JAVA_RUNTIME_URL = (
    LAUNCHER_META_MINECRAFT
    + "/v1/products/java-runtime/2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json"
)

MINECRAFT_DEFAULT_SERVER_PORT = 25565

# TAL currently uses these endpoints for vanilla installs
VERSION_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
ASSET_BASE_URL = MINECRAFT_RESOURCES

# --------------------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------------------

LEGACY_JAVA_FIXER_URL = "https://cdn.atlcdn.net/legacyjavafixer-1.0.jar"
LEGACY_JAVA_FIXER_MD5 = "12c337cb2445b56b097e7c25a5642710"

DATE_FORMATS = [
    "dd/MM/yyyy",
    "MM/dd/yyyy",
    "yyyy/MM/dd",
    "dd MMMM yyyy",
    "dd-MM-yyyy",
    "MM-dd-yyyy",
    "yyyy-MM-dd",
]

# instance name, pack name, pack version, minecraft version
INSTANCE_TITLE_FORMATS = [
    "%1$s (%2$s %3$s)",
    "%1$s",
    "%1$s (%4$s)",
    "%1$s (%3$s)",
]


@dataclass(frozen=True)
class ScreenResolution:
    width: int
    height: int


SCREEN_RESOLUTIONS = [
    ScreenResolution(854, 480),
    ScreenResolution(1280, 720),
    ScreenResolution(1366, 768),
    ScreenResolution(1600, 900),
    ScreenResolution(1920, 1080),
    ScreenResolution(2560, 1440),
    ScreenResolution(3440, 1440),
    ScreenResolution(3840, 2160),
]

DEFAULT_JAVA_PARAMETERS = "-XX:+UnlockExperimentalVMOptions -XX:+UseG1GC -XX:G1NewSizePercent=20 -XX:G1ReservePercent=20 -XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M"

# --------------------------------------------------------------------------------------
# Microsoft login constants
# --------------------------------------------------------------------------------------

# If you fork or modify this launcher, you must not use ATLauncher's client ID.
MICROSOFT_LOGIN_CLIENT_ID = ""

MICROSOFT_LOGIN_REDIRECT_PORT = 28562
MICROSOFT_LOGIN_REDIRECT_URL = f"http://127.0.0.1:{MICROSOFT_LOGIN_REDIRECT_PORT}"
MICROSOFT_LOGIN_REDIRECT_URL_ENCODED = (
    "http%3A%2F%2F127.0.0.1%3A" + str(MICROSOFT_LOGIN_REDIRECT_PORT)
)

MICROSOFT_LOGIN_SCOPES = ["XboxLive.signin", "offline_access"]

MICROSOFT_LOGIN_URL = (
    "https://login.live.com/oauth20_authorize.srf"
    + "?client_id="
    + MICROSOFT_LOGIN_CLIENT_ID
    + "&prompt=select_account&cobrandid=8058f65d-ce06-4c30-9559-473c9275a65d"
    + "&response_type=code"
    + "&scope="
    + "%20".join(MICROSOFT_LOGIN_SCOPES)
    + "&redirect_uri="
    + MICROSOFT_LOGIN_REDIRECT_URL_ENCODED
)

MICROSOFT_DEVICE_CODE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
MICROSOFT_AUTH_TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
MICROSOFT_XBL_AUTH_TOKEN_URL = "https://user.auth.xboxlive.com/user/authenticate"
MICROSOFT_XSTS_AUTH_TOKEN_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MICROSOFT_MINECRAFT_LOGIN_URL = "https://api.minecraftservices.com/launcher/login"
MICROSOFT_MINECRAFT_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"
MICROSOFT_MINECRAFT_ENTITLEMENTS_URL = "https://api.minecraftservices.com/entitlements/license"

# --------------------------------------------------------------------------------------
# Java runtime (bundled)
# --------------------------------------------------------------------------------------

JAVA_RUNTIME_DIR_NAME = "runtime"
JAVA_RUNTIME_VERSION = "21.0.7"
JAVA_RUNTIME_VERSION_FILE = "java_runtime_version.txt"
JAVA_RUNTIME_ZIP_URL = "https://download.oracle.com/java/21/latest/jdk-21_windows-x64_bin.zip"

# --------------------------------------------------------------------------------------
# Parallel downloads
# --------------------------------------------------------------------------------------

PARALLEL_DOWNLOADS_ENABLED = True
MAX_PARALLEL_DOWNLOADS = 16
