"""A HOME for one more Google account of Antigravity (``agy``) on this machine, and the terminal command ``agy-as``
(bin/agy_as.py; backends/agy/accounts.py uses the HOME).

agy has one login a machine and no flag for another: it finds the login under ``$HOME`` alone
(``~/.gemini/antigravity-cli/antigravity-oauth-token`` without a keyring). So another account is a directory of its own
(``own``, e.g. ``~/.agy-accounts/b``) holding what agy keeps for an account, ``ACCOUNT_PATHS`` under it, and each run
gets a HOME made of links: every entry of the real home links to the real one, but each of ACCOUNT_PATHS links to the
account's (``compose``), so the login, its refreshes and the account's caches and logs stay the account's, while
``.ssh``, ``.gitconfig``, the owner's GEMINI.md, MCP servers, hooks and skills (``~/.gemini/config``) are the real
ones. Of the account's own ``antigravity-cli`` directory, ``SHARED`` are links to the real ones (``prepare``): a
conversation is local files (``conversations/<id>.db``, ``brain/<id>/``), so another account goes on with the main
login's conversations and the other way round (seen on agy 1.5.14: the second account answered from the first's
conversation, its quota charged).

The HOME is a directory under ``parent`` (owner-only), removed on the way out, its links removed and never followed;
a new file agy writes at its top (or of ``.gemini``, ``.config``) goes with it, the way backends/agy/home.py says of the
butler's home. Standard library only: the terminal command runs without the rest of Covey.

``agy-as NAME [agy arguments]`` runs agy as the account ``~/.agy-accounts/NAME`` (``AGY_ACCOUNTS_DIR`` another
directory): the first time it makes the directory and agy asks to sign in (Google OAuth: the link it prints, opened in a
browser signed in to that account, and the code pasted back). ``agy-as --list`` lists the accounts and whether each is
signed in. Plain ``agy`` stays the machine's own login.
"""
from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

GEMINI, CLI, CONFIG, AGY_CONFIG = ".gemini", "antigravity-cli", ".config", "antigravity"
TOKEN = "antigravity-oauth-token"
# What agy keeps for the account it is signed in to: the login and the CLI's own files (cache, logs, its settings, the
# installation id), and the keyring scope beside them.
ACCOUNT_PATHS = ((GEMINI, CLI), (CONFIG, AGY_CONFIG))
# Of antigravity-cli, the directories a conversation lives in: every account reads and writes the real ones.
SHARED = ("conversations", "brain", "implicit", "presence", "persistent_terminals")
ACCOUNTS_ENV, ACCOUNTS_DIR = "AGY_ACCOUNTS_DIR", ".agy-accounts"
HOMES = ".homes"  # Under the accounts directory: the HOMEs of the agy-as runs.
PREFIX = "agy-account-"
LOCK = ".agy-account.lock"


def private_dir(path) -> Path:
    """``path``, made owner-only when missing, and so each missing directory above it."""
    path = Path(path)
    if not path.is_dir():
        if not path.parent.is_dir():
            private_dir(path.parent)
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    return path


def signed_in(own: Path) -> bool:
    return (Path(own) / GEMINI / CLI / TOKEN).is_file()


def prepare(own, real) -> list[str]:
    """Make ``own`` an account directory that shares the conversations of ``real`` (a home): ACCOUNT_PATHS made, each of
    SHARED in its antigravity-cli a link to the real one. One the account kept itself (agy run with HOME=own before) is
    renamed ``<name>.own-<time>`` beside it, never removed; an empty one is. Returns what it renamed."""
    own, real = Path(own), Path(real)
    for parts in ACCOUNT_PATHS:
        private_dir(own.joinpath(*parts))
    cli, shared = own / GEMINI / CLI, real / GEMINI / CLI
    moved = []
    with open(own / LOCK, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for name in SHARED:
            link, target = cli / name, shared / name
            if os.path.islink(link) and os.readlink(link) == str(target):
                continue
            private_dir(target)
            if os.path.islink(link):
                os.unlink(link)
            elif link.is_dir():
                try:
                    link.rmdir()
                except OSError as exc:
                    if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                        raise
                    aside = cli / f"{name}.own-{time.strftime('%Y%m%d%H%M%S')}"
                    link.rename(aside)
                    moved.append(str(aside))
            elif os.path.lexists(link):
                aside = cli / f"{name}.own-{time.strftime('%Y%m%d%H%M%S')}"
                link.rename(aside)
                moved.append(str(aside))
            os.symlink(target, link)
    return moved


def compose(target: Path, real: Path, own: Path) -> None:
    """``target`` (made, empty): every entry of ``real`` linked, but each of ACCOUNT_PATHS a link to ``own``'s, its
    parent a directory of links to the real one's other entries."""
    tree = {}
    for first, second in ACCOUNT_PATHS:
        tree.setdefault(first, set()).add(second)
    _links(target, real, set(tree))
    for first, names in tree.items():
        inner = target / first
        inner.mkdir(mode=0o700)
        _links(inner, real / first, names)
        for name in names:
            os.symlink(own / first / name, inner / name)


def _links(target: Path, source: Path, skip) -> None:
    try:
        entries = list(os.scandir(source))
    except OSError:
        return  # No such directory: agy makes what it needs.
    for entry in entries:
        if entry.name not in skip:
            os.symlink(entry.path, target / entry.name)


class AccountHome:
    """``with AccountHome(parent, real, own) as home``: a HOME (a Path under ``parent``) in which agy runs as the
    account of ``own``; ``real`` is the real home. ``moved``: what ``prepare`` renamed."""

    def __init__(self, parent, real, own, *, prefix=PREFIX):
        self.parent, self.real, self.own, self.prefix = Path(parent), Path(real), Path(own), prefix
        self.path, self.moved = None, []

    def __enter__(self) -> Path:
        self.moved = prepare(self.own, self.real)
        private_dir(self.parent)
        self.path = Path(tempfile.mkdtemp(prefix=self.prefix, dir=str(self.parent)))  # mkdtemp is 0700.
        try:
            compose(self.path, self.real, self.own)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self.path

    def __exit__(self, *exc) -> None:
        if self.path is not None:
            shutil.rmtree(self.path, ignore_errors=True)  # Links are removed, never followed.
            self.path = None


def accounts_dir(environ=None) -> Path:
    environ = os.environ if environ is None else environ
    value = str(environ.get("AGY_ACCOUNTS_DIR") or "").strip()  # ACCOUNTS_ENV: not Covey's own, no older spelling.
    return Path(value).expanduser() if value else Path(environ.get("HOME") or Path.home()) / ACCOUNTS_DIR


def sweep(parent: Path) -> None:
    """Remove the HOMEs of agy-as runs that are gone (their pid is in the name)."""
    try:
        entries = list(os.scandir(parent))
    except OSError:
        return
    for entry in entries:
        pid = entry.name.removeprefix(PREFIX).split("-", 1)[0]
        if entry.name.startswith(PREFIX) and pid.isdigit() and not os.path.exists(f"/proc/{pid}"):
            shutil.rmtree(entry.path, ignore_errors=True)


USAGE = """usage: {prog} 账号名 [agy 的参数]   以这个账号运行 agy（第一次运行时建账号目录，在 agy 里登录）
       {prog} --list               列出账号和是否已登录
       {prog} --install [目录]     把 agy-as 装进目录（默认 ~/.local/bin），装的是自带全部代码的一份，升级后不会失效
账号目录是 ~/.agy-accounts/<账号名>（环境变量 AGY_ACCOUNTS_DIR 可以换）；直接运行 agy 仍是本机原来的登录。"""
COMMAND = "agy-as"
SHEBANG = "#!/usr/bin/env python3\n"


def install(folder=None) -> Path:
    """Write this file, as a command of its own (``COMMAND``, executable), into ``folder`` (default ~/.local/bin): it
    needs nothing else, so no upgrade or removed checkout leaves it dangling. A link there (the old way: one into a
    checkout) is replaced."""
    folder = Path(folder).expanduser() if folder else Path.home() / ".local" / "bin"
    if not folder.is_dir():
        private_dir(folder)
    text = Path(__file__).read_text(encoding="utf-8")
    target = folder / COMMAND
    staging = folder / f".{COMMAND}.{os.getpid()}"
    staging.write_text(text if text.startswith("#!") else SHEBANG + text, encoding="utf-8")
    os.chmod(staging, 0o755)
    os.replace(staging, target)  # Over a link too: the link itself is replaced, never what it points at.
    return target


# Where the command was before it moved into the core; joined here, so an installed copy of this file never names it.
OLD_PLACE = "/".join(("covey_internal", "bin", "agy_as.py"))


def link_problem(folder=None) -> str:
    """Why ``agy-as`` in ``folder`` (default ~/.local/bin) needs installing again: a link that no longer leads anywhere,
    one into the extension's old place, or a script of one's own that looks for it there (it runs an older release's
    copy until none is left); '' when it is fine or not there."""
    target = (Path(folder).expanduser() if folder else Path.home() / ".local" / "bin") / COMMAND
    if os.path.islink(target):
        if not target.exists():
            return f"{target} 指向的文件已经没有了"
        if "covey_internal" in os.readlink(target):
            return f"{target} 还指向扩展里的旧文件"
        return ""
    try:
        with open(target, encoding="utf-8", errors="replace") as found:
            head = found.read(4096)
    except OSError:
        return ""
    return f"{target} 还在找扩展里的旧文件" if OLD_PLACE in head else ""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = accounts_dir()
    if not argv or argv[0] in ("-h", "--help"):
        prog = COMMAND if Path(__file__).name == COMMAND else "agy_as.py"  # The installed copy, else bin/agy_as.py.
        print(USAGE.format(prog=prog), file=sys.stderr if not argv else sys.stdout)
        return 0 if argv else 2
    if argv[0] == "--install":
        target = install(argv[1] if len(argv) > 1 else None)
        print(f"已装好 {target}")
        return 0
    if argv[0] == "--list":
        names = sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")) if root.is_dir() else []
        for name in names:
            print(f"{name}\t{'已登录' if signed_in(root / name) else '未登录'}\t{root / name}")
        if not names:
            print(f"{root} 下还没有账号：第一次运行 agy-as 账号名 时创建", file=sys.stderr)
        return 0
    name, args = argv[0], argv[1:]
    if not name or name.startswith((".", "-")) or "/" in name:
        print(f"账号名不能是 {name!r}", file=sys.stderr)
        return 2
    own = root / name
    if not signed_in(own):
        print(f"账号 {name} 还没有登录：在 agy 里选 Google OAuth，用这个账号登录（登录存在 {own}）", file=sys.stderr)
    real = Path(os.environ.get("HOME") or Path.home())
    homes = private_dir(root / HOMES)
    sweep(homes)
    child = None

    def forward(signum, _frame):
        if child is not None:
            child.send_signal(signum)
    signal.signal(signal.SIGINT, lambda *_: None)  # Ctrl+C reaches agy itself, in the terminal's process group.
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, forward)
    with AccountHome(homes, real, own, prefix=f"{PREFIX}{os.getpid()}-") as home:
        try:
            child = subprocess.Popen([os.environ.get("AGY_CMD") or "agy", *args], env={**os.environ, "HOME": str(home)})
        except OSError as exc:
            print(f"agy 不能运行：{exc.strerror or exc}", file=sys.stderr)
            return 127
        return child.wait()


if __name__ == "__main__":
    sys.exit(main())
