"""Text shown on a card from what a task or a tool said: secrets hidden, bounded, escaped. In core/ so that
core/status_line.py and cards/ use the same rule (repo review R3: core no longer imports cards/). Also the words for
a trace step on the status line (step_label, step_event: its coarse kind and purpose, never the command)."""
import html
import re
import shlex
import time
import unicodedata
from urllib.parse import urlsplit, urlunsplit


# Match fullwidth ASCII on a one-codepoint-for-one-codepoint shadow; keep the original spelling
# outside secret values. NFKC would also change ordinary text and can change its length.
_ASCII_WIDTH = str.maketrans({chr(c): chr(c - 0xFEE0) for c in range(0xFF01, 0xFF5F)})
_SECRET = re.compile(
    r"""(?:token|password|secret|api[_-]?key)["']?\s*[=:]\s*|(?P<bearer>Bearer\s+)""", re.I)


def redact(value):
    """``value`` as text with what looks like a secret (a token, password, key or Bearer value) hidden."""
    text = "" if value is None else str(value)
    shadow = text.translate(_ASCII_WIDTH)
    parts, start = [], 0
    for match in _SECRET.finditer(shadow):
        if match.start() < start:
            continue
        end, quote = match.end(), ""
        # Shell/JSON values may contain spaces, escaped quotes or adjacent quoted fragments.
        # An unfinished quote hides through the end rather than exposing the rest of the value.
        while end < len(shadow):
            char = shadow[end]
            if quote:
                if char == "\\" and end + 1 < len(shadow):
                    end += 2
                    continue
                if char == quote:
                    quote = ""
            elif char.isspace() or (not match.group("bearer") and char in ",;"):
                break
            elif char in "\"'":
                quote = char
            end += 1
        if end == match.end():
            continue
        parts.append(text[start:match.start()])
        parts.append("Bearer " if match.group("bearer") else text[match.start():match.end()])
        parts.append("[已隐藏]")
        start = end
    return "".join(parts) + text[start:]


def safe_text(value, limit=220, *, markdown=False):
    """Redact then escape; limit counts codepoints before escaping (plus an ellipsis).

    None preserves layout and length. A cut retreats before combining marks and emoji continuations
    (modifiers, ZWJ, variation selectors, tags and flag pairs), so it does not change their appearance.
    """
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative or None")
    text = redact(value)
    if limit is not None:
        text = " ".join(text.split())
        if len(text) > limit:
            end = limit
            while end > 0 and (unicodedata.category(text[end]).startswith("M")
                               or text[end] == "\u200d" or text[end - 1] == "\u200d"
                               or "\U0001f3fb" <= text[end] <= "\U0001f3ff"
                               or "\U000e0020" <= text[end] <= "\U000e007f"):
                end -= 1
            if end > 0 and "\U0001f1e6" <= text[end] <= "\U0001f1ff":
                start = end
                while start > 0 and "\U0001f1e6" <= text[start - 1] <= "\U0001f1ff":
                    start -= 1
                end -= (end - start) % 2
            text = text[:end] + "…"
    escaped = html.escape(text)
    return escaped if markdown else re.sub(r"([`*_\[\]\\])", r"\\\1", escaped)


# The titles of a step that runs a shell command (core/trace.py, the backends' progress adapters).
COMMAND_TITLES = frozenset({"执行命令", "后台命令", "启动后台命令"})
# Trimming of a command's output at its end, which says nothing of what it does: | tail -1, | head -n 5,
# | cut -c1-80, 2>&1, > /dev/null. Try each whitespace run only once, not from every character in it.
_TRIM_TAIL = re.compile(r"(?<!\s)(?:\s*(?:\|\s*(?:tail|head|cut)(?:\s+[-+\w.,=]+)*|2>&1|>\s*/dev/null))+\s*$")
# An absolute path of four parts or more (not inside a URL); a card keeps its last two.
_LONG_PATH = re.compile(r"(?<![\w.~:/-])/(?:[^\s/'\"|;&<>()`$]+/){3,}[^\s/'\"|;&<>()`$]*")


def _words(text, count):
    """(word, start, end) of the first ``count`` shell words of ``text``'s first command: quotes and escapes kept as
    written, a word ending at a blank, a newline or ``;``, ``&``, ``|``, ``(``, ``)``. Display only, never run."""
    found, i, end = [], 0, len(text)
    while len(found) < count:
        while i < end and text[i] in " \t":
            i += 1
        if i >= end or text[i] in "\n;&|()":
            break
        start, quote = i, ""
        while i < end:
            char = text[i]
            if quote:
                if char == "\\" and quote == '"' and i + 1 < end:
                    i += 2
                    continue
                quote = "" if char == quote else quote
                i += 1
            elif char in "'\"":
                quote, i = char, i + 1
            elif char == "\\" and i + 1 < end:
                i += 2
            elif char in " \t\n;&|()":
                break
            else:
                i += 1
        found.append((text[start:i], start, i))
    return found


def _unquote(word):
    """A shell word's value: its quotes and escapes taken off (``'it'\\''s'`` → ``it's``); the word as written when it
    does not parse."""
    try:
        parts = shlex.split(word, comments=False, posix=True)
    except ValueError:
        return word.strip("'\"")
    return parts[0] if len(parts) == 1 else word


# The words in front of a command that say nothing of what it does: a time limit (timeout and its options and
# duration), an environment (env and its assignments), niceness, buffering, a timer, a detach (``_unwrap``).
_RUNNERS = frozenset({"timeout", "gtimeout", "env", "nice", "ionice", "stdbuf", "time", "nohup", "setsid", "chronic"})
_VALUED = frozenset({"-s", "-k", "--signal", "--kill-after", "-n", "-u", "-C", "-c", "-i", "-o", "-e"})  # Take the next word.
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")
_DURATION = re.compile(r"\d+(?:\.\d+)?[smhd]?")
_SHELL = re.compile(r"(?:/usr)?(?:/bin/)?(?:ba|z|da|k)?sh")
_SHELL_FLAGS = re.compile(r"-[A-Za-z]*c[A-Za-z]*")


def _unwrap(command):
    """``command`` without what it is wrapped in: the words in front that only run it (``_RUNNERS``, assignments) and a
    shell it is handed to as one string (``bash -lc '…'``, ``timeout 10s bash -c "…"``), as often as they nest."""
    text = str(command or "").strip()
    for _ in range(6):
        words = _words(text, 24)
        at, skipped = 0, False
        while at < len(words):
            word = words[at][0]
            if _ASSIGNMENT.match(word):
                at, skipped = at + 1, True
                continue
            if word not in _RUNNERS:
                break
            at, skipped = at + 1, True
            while at < len(words) and words[at][0].startswith("-"):
                at += 2 if words[at][0] in _VALUED and "=" not in words[at][0] else 1
            if word in ("timeout", "gtimeout") and at < len(words) and _DURATION.fullmatch(words[at][0]):
                at += 1
            if word == "env":
                while at < len(words) and _ASSIGNMENT.match(words[at][0]):
                    at += 1
        if at < len(words) and _SHELL.fullmatch(words[at][0]):
            flag = at + 1  # Past the shell's own options (bash -euo pipefail -c '…') to the one that takes the string.
            while flag < len(words) and words[flag][0][:1] in "-+" and not _SHELL_FLAGS.fullmatch(words[flag][0]):
                flag += 2 if words[flag][0].endswith("o") else 1  # -o, -euo: the next word is the option's name.
            if flag + 1 < len(words) and _SHELL_FLAGS.fullmatch(words[flag][0]):
                text = _unquote(words[flag + 1][0]).strip()  # Quoted as one string, or one word (bash -lc pwd).
                continue
        if skipped and at < len(words):
            text = text[words[at][1]:].strip()
            continue
        break
    return text


def _segments(line):
    """(the commands of one line of a script as (text, where it starts in ``line``), split at ``;``, ``&&`` and ``||``
    outside quotes and parentheses; the words of a ``#`` comment that ends it, '' for none)."""
    parts, start, i, end, quote, depth = [], 0, 0, len(line), "", 0
    while i < end:
        char = line[i]
        if quote:
            if char == "\\" and quote == '"' and i + 1 < end:
                i += 2
                continue
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "\\":
            i += 2
            continue
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and char == "#" and (i == 0 or line[i - 1] in " \t;"):
            parts.append((line[start:i], start))
            return _kept(parts), line[i + 1:].strip()
        elif depth == 0 and (char == ";" or line.startswith(("&&", "||"), i)):
            parts.append((line[start:i], start))
            i += 1 if char == ";" else 2
            start = i
            continue
        i += 1
    parts.append((line[start:], start))
    return _kept(parts), ""


def _kept(parts):
    """The non-blank of ``parts`` ((text, start)), each stripped, its start moved past the blanks it lost."""
    return [(text.strip(), start + len(text) - len(text.lstrip())) for text, start in parts if text.strip()]


# What a line of a script does before the work starts, never what it is for (``_setup``): strict mode, the proxy
# variables unset, exports and assignments, a directory to work in, a file sourced, a heading echoed, a loop's keywords.
_SETUP_WORDS = frozenset({"set", "unset", "export", "cd", "pushd", "popd", "source", ".", "umask", "ulimit", "trap",
                          "shopt", ":", "true", "local", "readonly", "declare", "typeset", "echo", "printf", "mkdir",
                          "chmod", "done", "fi", "esac", "{", "}", "wait"})
_KEYWORDS = ("do", "then", "else")
_PROXY_LOOP = re.compile(r"for\s+\w+\s+in\s+[^;]*proxy", re.I)


def _setup(segment):
    """Whether one command of a script (``_segments``) only sets the script up (``_SETUP_WORDS``, a loop over the proxy
    variables, assignments alone), so the command it runs is elsewhere."""
    text = segment.strip()
    words = _words(text, 2)
    if words and words[0][0] in _KEYWORDS:
        text = text[words[0][2]:].strip()
        words = _words(text, 2)
    if text.startswith("("):
        return False  # A subshell: what it runs is in it.
    if not words or _PROXY_LOOP.match(text):
        return True
    first = words[0][0]
    return first in _SETUP_WORDS or all(_ASSIGNMENT.match(word) for word, _, _ in _words(text, 64))


def command_purpose(command):
    """The model's own words for what a shell ``command`` is for when it wrote them in it as a comment: the first
    ``# …`` line before the first line that does something (the wrappers and the setup lines before it skipped,
    ``_unwrap``, ``_setup``), else a ``# …`` at the end of that line; '' when it wrote none. The bridge rules ask a
    model whose command has no field for it (Codex, an Antigravity call without toolSummary) to begin each command so
    (app/prompts.py LANGUAGE_RULE)."""
    for line in _unwrap(command).splitlines()[:60]:
        line = line.strip()
        if not line or line.startswith("#!"):
            continue
        if line.startswith("#"):
            words = line.lstrip("#").strip()
            if re.search(r"\w", words):
                return words[:120]
            continue
        segments, comment = _segments(line)
        if segments and all(_setup(segment) for segment, _ in segments):
            continue
        return comment[:120] if re.search(r"\w", comment) else ""
    return ""


def command_core(command):
    """What a shell ``command`` runs, for a card that has no purpose to show: from the first command that does
    something to the end, past its wrappers (``timeout …``, ``bash -lc '…'``) and the lines and commands before it
    that only set it up (strict mode, the proxy variables unset in a loop, assignments, ``cd``, an echoed heading:
    ``_setup``), its own runner words off; the command without its wrappers when every line only sets it up.
    2026-11-24 T738: Antigravity's and Codex's steps read "set -euo pipefail for v in http_proxy https_proxy…" one under
    another."""
    body = _unwrap(command)
    lines = body.splitlines()
    for index, line in enumerate(lines[:400]):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        segments, _ = _segments(stripped)
        for segment, start in segments:
            if _setup(segment):
                continue
            rest = stripped[start:]
            words = _words(rest, 1)
            if words and words[0][0] in _KEYWORDS:  # "do make" of a loop over the proxies: what it runs is make.
                rest = rest[words[0][2]:].strip()
            return "\n".join((_unwrap(rest), *lines[index + 1:])).strip()
    return body


def shown_command(detail):
    """A command step's ``detail`` (escaped by ``safe_text``) as a card shows it: the model's own purpose when
    it gave one (Claude's "<purpose> · <command>", backends/claude/events.py; a comment it began the command with,
    ``command_purpose``), else what the command runs (``command_core``: not its wrappers and setup lines) without
    the trimming of its output and the heads of long paths. Not "R=/data/…/03-shot.png | tail -1 | cut -c1-60",
    "/bin/bash -lc 'timeout …" and "set -euo pipefail for v in http_proxy…" on running cards. Display only: the
    step keeps the whole command, which command_kind reads for its kind."""
    purpose, separated, _ = detail.partition(" · ")
    if separated and purpose.strip():
        return purpose.strip()
    text = html.unescape(re.sub(r"\\([`*_\[\]\\])", r"\1", detail)).strip()
    said = command_purpose(text)
    if said:
        return safe_text(said, None)
    text = command_core(text)  # Its lines as they are: each caller puts a step on one line.
    text = _TRIM_TAIL.sub("", text) or text
    text = _LONG_PATH.sub(lambda match: "…/" + "/".join(match.group(0).rstrip("/").split("/")[-2:]), text)
    return safe_text(text, None)


def tool_detail(inputs, keys, fallback="", said=""):
    """A tool step's one-line detail: the first of ``keys`` that ``inputs`` has (each backend keeps its own
    order: Claude shows Grep's pattern, dsh and Pi its path), else ``fallback``. ``said``: what the model said
    the call is for beside its parameters (Antigravity's toolSummary, backends/agy/bridge.py), which leads the
    detail ("<purpose> · <parameter>"). A command leads with the model's own one-line purpose: ``said``, its
    description (Claude Code's), else a comment it began the command with (``command_purpose``); a URL loses its
    query and fragment, which may carry a token (dsh and Pi showed ``?token=…`` on the card and in traces/)."""
    if not isinstance(inputs, dict):
        return fallback
    key = next((k for k in keys if inputs.get(k)), None)
    if key is None:
        return fallback
    if key == "command":
        purpose = said or inputs.get("description") or command_purpose(inputs[key])
        return f"{purpose} · {inputs[key]}" if purpose else str(inputs[key])
    value = str(inputs[key])
    if key == "url":
        try:
            url = urlsplit(value)
            value = urlunsplit((url.scheme, url.hostname or "", url.path, "", ""))
        except ValueError:
            value = "网页地址"
    return f"{said} · {value}" if said else value


def short_count(value):
    """A token count to three figures in 万 or 亿 (141,137,149 → 1.41 亿, 329,638 → 33.0 万); under
    10,000 as it is. 任务详情 keeps the exact count."""
    if value < 10000:
        return f"{value:,}"
    unit, size = ("亿", 10 ** 8) if value >= 99995000 else ("万", 10 ** 4)  # 9999.5 万 rounds to 1.00 亿.
    amount = value / size
    return f"{amount:.{2 if amount < 9.995 else 1 if amount < 99.95 else 0}f} {unit}"


def share(part, whole):
    """``part`` of ``whole`` in whole percent; under 1 % reads "<1%"; from 99 % one decimal, cut rather than
    rounded, so only all of it reads 100% (repo review S1: 99.6 % read 100%)."""
    percent = part * 100 / whole if whole else 0
    if part and part < whole and percent >= 99:
        return f"{part * 1000 // whole / 10:.1f}%"  # From the counts: 99.6 * 10 is 995.99… in floats.
    return f"{percent:.0f}%" if percent >= 1 or not part else "<1%"


def cut(text, limit, *, beyond=False, strip=False):
    """``text`` on one line (its whitespace runs one space), cut to ``limit`` characters with "…" at the end.
    ``beyond``: keep ``limit`` characters and put the "…" after them (so the result may be ``limit`` + 1 long).
    ``strip``: drop the trailing blanks the cut leaves before the "…"."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    kept = text[:limit if beyond else limit - 1]
    return (kept.rstrip() if strip else kept) + "…"


def last_line(text):
    """The last non-blank line of ``text``, stripped ("" when there is none)."""
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def stamp(seconds, fmt="%m-%d %H:%M", empty="—", *, lenient=False):
    """``seconds`` (an epoch) as local time in ``fmt``; ``empty`` when it is 0 or missing.
    ``lenient``: 0 is a time (the epoch), and whatever is not a number a time can be made of gives ``empty``."""
    if lenient:
        try:
            return time.strftime(fmt, time.localtime(float(seconds)))
        except (TypeError, ValueError, OverflowError, OSError):
            return empty
    return time.strftime(fmt, time.localtime(seconds)) if seconds else empty


def literal(value):
    """``value`` shown as written on a card: every Markdown and Feishu tag character escaped, newlines and tabs
    as their escapes (a file name, the owner's words)."""
    text = str(value).replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return "".join(f"&#{ord(c)};" if c in "&<>\\`*_{}[]()#+.!|~-" else c for c in text)


def step_label(step):
    title = "调用工具" if step.get("title") == "tool" else str(step.get("title") or "执行步骤")
    # The trace stores details already escaped for Markdown; cut without leaving a dangling escape.
    if title == "更新检查点":  # core/trace.py CHECKPOINT_STEP: its command is in 执行过程, not on this line.
        return title
    detail = str(step.get("detail") or "")
    # A command is read with its lines (its setup lines and comments are lines of their own) before it is one line.
    detail = " ".join((shown_command(detail) if title in COMMAND_TITLES and detail.strip() else detail).split())
    if detail and detail != title:
        title += " · " + clip(detail, 60)
    return title


def clip(text, limit):
    """Cut trace text that is already escaped for Markdown without a dangling escape or entity."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else re.sub(r"\\+$|&[#\w]*$", "", text[:limit]) + "…"


_SEGMENTS = re.compile(r"&&|\|\||[;|\n]")
_PREFIX = re.compile(r"^(?:(?:[A-Za-z_]\w*=\S*|timeout(?:\s+-\S+)*\s+\S+|env|nice|time)\s+)*")
_SETUP = re.compile(r"^(?:cd|export|source|set|echo|printf|true|\.)(?:\s|$)")
_GIT = r"git\s+(?:-C\s+\S+\s+)?"
_COMMIT = re.compile(_GIT + r"(?:commit|merge|rebase|cherry-pick|push|am)\b")
_LOOK = re.compile(r"(?:cat|sed|head|tail|less|ls|grep|rg|find|wc|tree|" + _GIT + r"(?:diff|log|show|status|grep|blame|branch))\b")
_TEST = re.compile(r"\b(?:unittest|pytest|tox|nox)\b|\btest_\w*\.py\b|\b(?:make|npm|yarn|pnpm|go|cargo)(?:\s+run)?\s+test\b")


def command_kind(command):
    """A coarse public kind for a shell command; the command itself is never shown."""
    segments = [_PREFIX.sub("", part.strip()) for part in _SEGMENTS.split(command)]
    segments = [part for part in segments if part and not _SETUP.match(part)]
    if any(_COMMIT.match(part) for part in segments):
        return "提交代码"
    if any(_TEST.search(part) and not _LOOK.match(part) for part in segments):
        return "运行测试"
    if segments and all(_LOOK.match(part) for part in segments):
        return "查看代码"
    return "运行命令"


_STEP_KINDS = {"读取文件": "查看代码", "查找文件": "查看代码", "搜索文件": "查看代码", "浏览目录": "查看代码",
               "修改文件": "编辑文件", "写入文件": "编辑文件", "edit": "编辑文件", "读取网页": "查阅网页",
               "搜索网页": "查阅网页", "等待回答": "等待回答", "分配子任务": "分配子任务", "更新计划": "更新计划",
               "更新检查点": "更新检查点"}


def step_action(step):
    """(kind, purpose) of a trace step: a coarse kind plus the model's own stated purpose or a file name."""
    title = str(step.get("title") or "")
    detail = " ".join(str(step.get("detail") or "").split())
    if title in {"执行命令", "后台命令"}:
        # Claude commands are "<description> · <command>"; a bare command only yields its kind.
        purpose, separated, command = detail.partition(" · ")
        plain = html.unescape(re.sub(r"\\([`*_\[\]\\])", r"\1", command if separated else detail))
        return command_kind(plain), ("：" + clip(purpose, 48) if separated and purpose else "")
    kind = _STEP_KINDS.get(title, "调用工具")
    if detail and title in {"读取文件", "修改文件", "写入文件", "edit"}:
        return kind, " " + clip(detail.split(", ")[0].rstrip("/").rsplit("/", 1)[-1], 40)
    return kind, ""


def step_event(step):
    if step.get("status") == "note":
        return "更新了" + str(step.get("title") or "进展说明")
    kind, purpose = step_action(step)
    if step.get("status") == "running":
        return "正在" + kind + purpose
    return kind + ("出错" if step.get("status") == "failed" else "结束") + purpose
