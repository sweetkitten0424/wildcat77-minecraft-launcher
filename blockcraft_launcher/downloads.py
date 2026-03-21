import shutil
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .constants import MAX_PARALLEL_DOWNLOADS, PARALLEL_DOWNLOADS_ENABLED


def download_to_file(url: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as out_f:
        shutil.copyfileobj(resp, out_f)


def parallel_download_files(download_tasks, logger, max_workers: int = MAX_PARALLEL_DOWNLOADS):
    """Download multiple files in parallel.

    download_tasks: iterable of (url, dest_path, description)
    logger: callable like logger(text, source="LAUNCHER")
    """
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
