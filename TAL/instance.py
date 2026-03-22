import json
import uuid
from pathlib import Path
from typing import Optional

from .constants import DEFAULT_JAVA_PARAMETERS


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
