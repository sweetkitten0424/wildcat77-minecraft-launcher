import json
import sys
import urllib.request
from pathlib import Path
from typing import Optional

from .config import ensure_configs_layout
from .constants import ASSET_BASE_URL, VERSION_MANIFEST_URL
from .downloads import download_to_file, parallel_download_files
from .paths import ASSETS_DIR, CONFIGS_JSON_MINECRAFT_DIR, INSTALL_DIR, LIBRARIES_DIR, MINECRAFT_VERSIONS_JSON_FILE, VANILLA_DIR


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
