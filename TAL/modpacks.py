from .paths import MODPACKS_DIR


def ensure_modpacks_dir():
    MODPACKS_DIR.mkdir(parents=True, exist_ok=True)


def list_modpacks() -> list[str]:
    ensure_modpacks_dir()
    names = []
    for p in sorted(MODPACKS_DIR.iterdir()):
        if p.is_dir():
            names.append(p.name)
    return names
