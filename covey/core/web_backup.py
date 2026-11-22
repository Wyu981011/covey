"""自托管网页的数据库备份与恢复 (docs/web.md 自托管, docs/operations.md 备份): the page's own PGlite database in the daily backup
(core/backup.py) and back out of it.

``snapshot`` asks the page process on the loopback for a ``dumpDataDir('gzip')`` tar.gz (``GET <base_url>/selfhost/backup``, the open
interface's key) and returns it as the member ``MEMBER`` of the backup; with ``COVEY_WEB_SELFHOST`` off, or when the page is not this
machine's loopback one, no request is made. ``unpack`` is the restore side: a safe extraction of such a tar.gz into a folder (no ``..``,
no absolute path, no link or device). The key file and the TLS key are never part of a backup. Standard library and covey.core only."""
from __future__ import annotations

import gzip
import io
import os
import shutil
import tarfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from covey.core import env as cenv
from covey.core import web_sync

WEB_ENV = "COVEY_WEB"
SELFHOST_ENV = "COVEY_WEB_SELFHOST"  # The switch of service/web_selfhost.py (a service may not import it from core).
PREFIX = "selfhost-web/"  # Members of a backup that restore_backup (core/backup.py) leaves to ``unpack``.
MEMBER = PREFIX + "pglite.tar.gz"
WEB_DB_BYTES = 256 * 1024 * 1024  # The most of a database a backup takes (the page answers 413 over its own limit alike).
UNPACK_BYTES = 2 * 1024 ** 3  # The most a restore writes.
MARKER = ".covey-restore-complete"  # The last file of a restored folder: the page swaps the folder in only when it is there.
CHUNK = 1 << 20


def selfhost_on(environ=None) -> bool:
    return str(cenv.get(SELFHOST_ENV, "", environ)).strip() == "1"


def snapshot(environ=None, *, timeout=120, limit=WEB_DB_BYTES):
    """(MEMBER, bytes, info) of the page's database now; (None, None, info) when not applicable or it failed. ``info`` is {} with
    COVEY_WEB_SELFHOST off (nothing asked, nothing recorded), else {"skipped": reason} or {"error": reason} or {"bytes": n}. Takes no
    lock and reads no config but COVEY_WEB_CONFIG's; never raises."""
    if not selfhost_on(environ):
        return None, None, {}
    try:
        if str(cenv.get(WEB_ENV, "", environ)).strip() != "1":
            return None, None, {"skipped": "COVEY_WEB 没开"}
        path = str(cenv.get(web_sync.CONFIG_ENV, "", environ) or "").strip()
        if not path:
            return None, None, {"skipped": "COVEY_WEB_CONFIG 没设"}
        config = web_sync.load_config(path)
        parts = urlsplit(config.base_url)
        if parts.scheme != "http" or parts.hostname not in web_sync.LOOPBACK_HOSTS:
            return None, None, {"skipped": "网页不在本机回环上"}
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # A loopback request never goes through a proxy.
        request = urllib.request.Request(config.base_url + "/selfhost/backup", headers={"Authorization": "Bearer " + config.key})
        try:
            with opener.open(request, timeout=timeout) as response:
                if int(response.headers.get("Content-Length") or 0) > limit:
                    return None, None, {"error": "数据库超过备份上限"}
                data = response.read(limit + 1)
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                return None, None, {"skipped": "外部 Postgres 要用 pg_dump 备份"}
            return None, None, {"error": f"http {exc.code}" + ("：数据库超过备份上限" if exc.code == 413 else "")}
        if len(data) > limit:
            return None, None, {"error": "数据库超过备份上限"}
        if data[:2] != b"\x1f\x8b":
            return None, None, {"error": "网页返回的不是 tar.gz"}
        return MEMBER, data, {"bytes": len(data)}
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return None, None, {"error": type(exc).__name__ if not isinstance(exc, ValueError) else str(exc)[:80]}
    except Exception as exc:  # noqa: BLE001 - the state directory's backup never depends on the page
        return None, None, {"error": type(exc).__name__}


def _safe_name(name):
    """The member ``name`` as a relative path under the folder, or None for the folder itself; ValueError when it is unsafe."""
    parts = [part for part in name.lstrip("/").split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts) or any("\x00" in part for part in parts):
        raise ValueError(f"备份包含不安全路径：{name[:60]}")
    return Path(*parts) if parts else None


def unpack(source, destination, *, limit=UNPACK_BYTES) -> int:
    """Extract the tar.gz ``source`` (a path, or bytes) into the new folder ``destination`` (0700; an existing one is removed
    first), returning the number of files. Leading ``/`` of a member is dropped (PGlite's dump has them); ``..``, links, devices
    and FIFOs are refused (ValueError, the folder removed); more than ``limit`` bytes in all is refused. Writes no MARKER."""
    destination = Path(destination)
    if destination.is_symlink() or destination.is_file():
        destination.unlink()
    elif destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, mode=0o700)
    files, total = 0, 0
    try:
        stream = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else open(source, "rb")
        with stream, tarfile.open(fileobj=stream, mode="r:gz") as tar:
            for member in tar:
                relative = _safe_name(member.name)
                if member.isdir():
                    if relative is not None:
                        (destination / relative).mkdir(parents=True, exist_ok=True, mode=0o700)
                    continue
                if not member.isfile() or relative is None:
                    raise ValueError(f"备份包含链接或设备文件：{member.name[:60]}")
                total += member.size
                if total > limit:
                    raise ValueError("备份解开后太大")
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with tar.extractfile(member) as source_file, open(target, "wb") as out:
                    while chunk := source_file.read(CHUNK):
                        out.write(chunk)
                os.chmod(target, 0o600)
                files += 1
    except (tarfile.TarError, EOFError, gzip.BadGzipFile) as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise ValueError(f"不是有效的 tar.gz：{type(exc).__name__}") from None
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return files
