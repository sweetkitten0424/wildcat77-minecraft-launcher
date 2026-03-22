import shutil
import sys
import zipfile
from pathlib import Path

from .config import save_config
from .constants import JAVA_RUNTIME_DIR_NAME, JAVA_RUNTIME_VERSION, JAVA_RUNTIME_VERSION_FILE, JAVA_RUNTIME_ZIP_URL
from .downloads import download_to_file
from .paths import INSTALL_DIR


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
