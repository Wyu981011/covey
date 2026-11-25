"""The self-hosted web page brought along when scripts/upgrade.sh upgrades the Bridge (docs/deploy.md 日常升级): the page is a
deployment of its own, so a new Bridge would otherwise run with the old page. A page web/deploy/selfhost/build.sh built
(``COVEY_WEB_SELFHOST=1``, the folder holds its mark) is built again from the new release's web/ with ``--restart``, and the Manager
brings it up; a page made some other way is said and left alone (an extension's installer brings its own kinds along).

``plan`` is what would be done, ``current`` whether the page is the release's already, ``update`` does it. Standard library only."""
from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path

MARK = ".covey-selfhost-build"  # What web/deploy/selfhost/build.sh writes in a folder it built: "...; source <its web/>".
SECONDS = 2400  # npm ci and the build take minutes on a slow disk.
WORDS = "自托管网页"
DONE, CURRENT, PLANNED, MANUAL, FAILED = "done", "current", "planned", "manual", "failed"
# Names the page's build must not get from the upgrade's own environment: what the test or deploy tools set for themselves.
DROPPED = ("COVEY_EXTENSIONS", "COVEY_EXTENSION_PATH", "LARK_BRIDGE_EXTENSIONS", "LARK_BRIDGE_EXTENSION_PATH")


def value(env, name) -> str:
    """The service's setting ``name`` (without its prefix) under either spelling, stripped; '' unset."""
    for key in ("COVEY_" + name, "LARK_BRIDGE_" + name):
        found = str((env or {}).get(key) or "").strip()
        if found:
            return found
    return ""


def plan(manifest, release) -> dict | None:
    """How the service of ``manifest`` gets ``release``'s page: {"kind", "target", "argv"} for a self-hosted page build.sh built,
    {"kind", "note"} for a page made another way (not touched), None for a service without a page of its own here."""
    env = manifest.get("environment") if isinstance(manifest.get("environment"), dict) else {}
    if value(env, "WEB_SELFHOST") != "1":
        if value(env, "WEB") == "1" and value(env, "WEB_CONFIG"):
            return {"kind": "app", "note": "网页不是在这台机器上自托管的（另外部署的网页应用），没有替你更新：照你部署它时的办法把新的 web/ 发上去"}
        return None
    folder = value(env, "WEB_SELFHOST_DIR")
    target = Path(folder).parent if folder and Path(folder).is_absolute() else None
    if target is None or not (target / MARK).is_file():
        return {"kind": "selfhost", "note": f"自托管网页的目录（COVEY_WEB_SELFHOST_DIR={folder or '空'}）不是 "
                                            "web/deploy/selfhost/build.sh 建的，没有替你更新：照你建它时的办法重建"}
    return {"kind": "selfhost", "target": str(target),
            "argv": ["bash", str(Path(release) / "web" / "deploy" / "selfhost" / "build.sh"), str(target), "--restart"]}


def current(found, release) -> bool:
    """Whether the page of ``found`` (a plan with a target) is built from ``release``'s web/ already (build.sh's mark says so)."""
    try:
        return f"source {Path(release) / 'web'}" in (Path(found["target"]) / MARK).read_text()
    except (OSError, KeyError, TypeError):
        return False


def view(manifest, release) -> dict | None:
    """The ``web`` of an upgrader's status (app/self_upgrade.py clean_status): {kind, current, manual}, None without a page."""
    found = plan(manifest, release)
    if found is None:
        return None
    if found.get("note"):
        return {"kind": found["kind"], "current": False, "manual": True}
    return {"kind": found["kind"], "current": current(found, release), "manual": False}


def update(data, manifest, release, say, check_only=False, run=subprocess.run) -> str | None:
    """Bring the page to ``release``'s web/, each outcome said with ``say`` (the line app/self_upgrade.py outcome reads starts
    "[网页]"): DONE, CURRENT, PLANNED (``check_only``), MANUAL (made another way, not touched), FAILED, None without a page."""
    found = plan(manifest, release)
    if found is None:
        return None
    if found.get("note"):
        say(f"[网页] {found['note']}")
        return MANUAL
    release = Path(release)
    if current(found, release):
        say(f"[网页] {WORDS}已经是 {release.name} 的版本")
        return CURRENT
    command = shlex.join(found["argv"])
    if check_only:
        say(f"[网页] 升级时会把{WORDS}（{found['target']}）换成 {release.name} 的 web/：\n    {command}")
        return PLANNED
    folder = Path(data) / "deploy-runs" / f"{time.strftime('%Y%m%d-%H%M%S')}-web"
    (folder / "tmp").mkdir(parents=True, exist_ok=True)
    log = folder / "web.log"
    say(f"[网页] 把{WORDS}（{found['target']}）换成 {release.name} 的 web/，要几分钟；进度看 {log}")
    env = {key: item for key, item in os.environ.items() if key not in DROPPED}
    env["TMPDIR"] = str(folder / "tmp")
    error = ""
    try:
        with log.open("w") as out:
            out.write(f"$ {command}\n")
            out.flush()
            code = run(found["argv"], cwd=str(release), env=env, stdin=subprocess.DEVNULL, stdout=out,
                       stderr=subprocess.STDOUT, timeout=SECONDS).returncode
    except subprocess.TimeoutExpired:
        code = None
    except OSError as exc:
        code, error = 127, f"{type(exc).__name__}: {exc}"
    lines = [line.strip() for line in log.read_text(errors="replace").splitlines()[1:] if line.strip()]
    tail = error or " / ".join(lines[-3:])[-400:] or "没有输出"
    if code == 0:
        say(f"[网页] 更新好了（日志 {log}）：网页刷新一下就是新版")
        return DONE
    why = f"超过 {SECONDS} 秒没结束" if code is None else f"退出码 {code}：{tail}"
    say(f"[网页] 没更新上（Bridge 已经是新版，不用回滚）：{why}\n    日志 {log}\n    单独重跑网页这一步：{command}")
    return FAILED
