"""The doctor's report (service/doctor.py ``diagnose``) said in plain Chinese for a person at a terminal, with the next step.

``covey_doctor.py`` prints these lines instead of its JSON when its output is a terminal (or with ``--summary``); a pipe, a
script and ``--json`` get the JSON as before. ``lines(report, ...)``: a title, the conclusion (都正常, or how many parts need a
look), one row a part (the Manager, each service of the root, its switches, how long Claude Code keeps sessions, what it
set up that this release no longer uses, its devices, the self-hosted page, 等主人的账 and its 补发, start at boot, each Harness's last probe), each fault or warning followed by ``下一步：`` and a command to run, and
where the full report is. A row's mark: ``✓`` fine, ``✗`` a fault, ``!`` to know, ``·`` only said.

Only the report's fields are read: nothing is asked of a process, a model or Feishu here, and no value of an environment
variable is shown but the switches' (core/switches.py ``shown`` already hides what may be a secret). The 设置 card's 诊断 tab
(app/doctor_panel.py, cards/doctor_card.py) says the same parts for one bot in the same words. Standard library only.
"""
from __future__ import annotations

import time

OK, FAULT, NOTE, INFO = "✓", "✗", "!", "·"
ENTRY = "python3 -B bin/covey_doctor.py"
SERVICE = "python3 -B bin/covey_service.py"
HARNESS_NAMES = {"claude": "Claude Code", "codex": "Codex"}
BOOT_MODES = {"systemd-user": "systemd 用户服务", "launchd": "launchd 用户代理", "cron": "crontab 的 @reboot 一行"}
LOST = {"stalled": "卡住了", "disconnected": "断开了", "unresponsive": "没有回应"}
REQUIRED = ("im.message.receive_v1", "card.action.trigger")
# What to do about a Harness probe that did not get through, by core/harness_probe.py's reason.
LOGIN = {"claude": "在这台机器的终端里运行 claude，按提示登录（用 API key 的写进 ~/.claude/settings.json 的 env）",
         "codex": "在这台机器的终端里运行 codex login"}
PROBE_NEXT = {
    "not_installed": "装法见 docs/harnesses.md「安装和登录 Harness」",
    "network": "设好代理再试：export HTTPS_PROXY=http://主机:端口，服务里也要有，见 docs/troubleshooting.md「机器要代理才能连模型」",
    "timeout": "多半是网络或代理：见 docs/troubleshooting.md「机器要代理才能连模型」",
}


def clock(stamp) -> str:
    """HH:MM today, MM-DD HH:MM before; '' without a time."""
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or stamp <= 0:
        return ""
    today = time.localtime(stamp)[:3] == time.localtime()[:3]
    return time.strftime("%H:%M" if today else "%m-%d %H:%M", time.localtime(stamp))


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def manager_row(manager, root_arg, state="") -> tuple:
    lag = _dict(manager).get("lag")
    if isinstance(lag, (int, float)) and not isinstance(lag, bool) and lag < 120:
        return OK, f"服务管理器在运行（巡检延迟 {round(lag, 1)} 秒）", ""
    return (FAULT, "服务管理器没有回应：机器人退出了没人拉起",
            f"{SERVICE}{root_arg} start --state-dir {state or '<状态目录>'}（顺带拉起服务管理器）")


def bridge_problems(row) -> list:
    """What is wrong with a running service, in words, from its row of the report."""
    problems = []
    bridge = row.get("bridge") if isinstance(row.get("bridge"), dict) else None
    if not row.get("alive"):
        problems.append("进程不在")
    elif bridge is None:
        problems.append("进程在，但没有回应健康检查")
    if bridge:
        lost = _dict(bridge.get("remote_connection")).get("status")
        if lost in LOST:
            problems.append(f"和飞书的连接{LOST[lost]}")
        consumers = _dict(bridge.get("consumers"))
        down = [key for key in REQUIRED if consumers and not _dict(consumers.get(key)).get("ready")]
        if down:
            problems.append("收" + "和".join("消息" if key == REQUIRED[0] else "卡片点击" for key in down) + "的连接没就绪")
        stopped = sorted(name for name, alive in _dict(bridge.get("workers")).items() if alive is False)
        if stopped:
            problems.append("后台部件停了：" + "、".join(stopped))
    events = _dict(row.get("events"))
    if events.get("status") == "unavailable":
        problems.append("读不到 lark-cli 的事件状态" + (f"（退出码 {events['exit_code']}）" if events.get("exit_code") else ""))
    elif events.get("owned_required_consumers") is False and not any("连接没就绪" in p for p in problems):
        problems.append("收消息或卡片点击的连接没就绪")
    if events.get("dropped"):
        problems.append(f"丢了 {events['dropped']} 个事件")
    if row.get("permission_env"):
        problems.append("清单里留着已不生效的权限变量")
    if not problems and _dict(bridge).get("status") == "degraded":
        problems.append("有部件不正常")
    if not problems and bridge and _dict(bridge).get("status") == "ready":
        problems.append("新的一代还没接上（刚改过设置或升级过时会这样）")
    return problems


def service_rows(row, state, root_arg) -> list:
    """The rows of one service of the report: itself, then what it has (switches, Claude Code's sessions, devices)."""
    state_arg = f" --state-dir {state}" if state else " --state-dir <状态目录>"
    log = f"{state}/bridge.log" if state else "<状态目录>/bridge.log"
    name = state.rstrip("/").rsplit("/", 1)[-1] if state else str(row.get("id") or "?")[:12]
    generation = f"第 {row['generation']} 代，" if row.get("generation") is not None else ""
    permission = "；".join(str(line) for line in row.get("permission_env") or ())
    fix_permission = "按 docs/troubleshooting.md「权限变量让诊断或部署失败」去掉它们，再重新注册服务"
    rows = []
    if row.get("status") == "stopped":
        if permission:
            rows.append((NOTE, f"机器人 {name} 已停用，清单里留着已不生效的权限变量：{permission}", fix_permission))
        else:
            rows.append((INFO, f"机器人 {name} 已停用", f"要启用：{SERVICE}{root_arg} start{state_arg}"))
    elif row.get("status") == "ready":
        rows.append((OK, f"机器人 {name} 正常：{generation}收消息和卡片点击都连着", ""))
    else:
        problems = bridge_problems(row)
        if permission:
            next_step = fix_permission + f"（{permission}）"
        elif any(p.startswith("新的一代") for p in problems):
            next_step = f"半分钟后再运行一次 {ENTRY}"
        else:
            next_step = (f"看日志最后几行：tail -n 50 {log}；一直不好就 {SERVICE}{root_arg} restart{state_arg}"
                         "（见 docs/troubleshooting.md）")
        rows.append((FAULT, f"机器人 {name} 有问题：{generation}{'；'.join(problems)}", next_step))
    rows += storage_rows(_dict(_dict(row.get("bridge")).get("storage")), state, log)
    pairs = [pair for pair in row.get("switches") or () if isinstance(pair, (list, tuple)) and len(pair) == 2]
    if pairs:
        rows.append((INFO, f"设了 {len(pairs)} 个可选开关：" + "、".join(f"{key}={value}" for key, value in pairs),
                     ""))
    else:
        rows.append((INFO, "没设可选开关，功能都按代码默认", ""))
    cleanup = _dict(row.get("claude_cleanup"))
    if cleanup.get("state") in ("low", "missing"):
        hint = str(cleanup.get("hint") or "")
        rows.append((NOTE, f"Claude Code 只保留最近 {cleanup.get('days')} 天的会话：更早的话题接不上、回退不了",
                     hint.split("；", 1)[-1]))
    elif cleanup.get("state") == "ok":
        rows.append((OK, f"Claude Code 会话保留 {cleanup.get('days')} 天", ""))
    elif cleanup:
        rows.append((INFO, "没读出 Claude Code 保留会话几天（它默认只留 30 天）", ""))
    dropped = [str(line) for line in row.get("dropped_config") or ()]
    if dropped:
        rows.append((NOTE, f"有 {len(dropped)} 项配置新版本不再用：" + "；".join(dropped),
                     "照每项后面说的改掉；升级前 scripts/upgrade.sh --dry-run 会先列出新版本要丢的配置"))
    devices = _dict(row.get("devices"))
    if devices:
        found = _dict(devices.get("devices"))
        failed = sorted(alias for alias, one in found.items() if not _dict(_dict(one).get("check")).get("ok"))
        if devices.get("status") == "ready":
            rows.append((OK, f"设备自检都通过（{len(found)} 台）", ""))
        elif failed:
            rows.append((NOTE, "设备自检没通过：" + "、".join(failed),
                         f"python3 -B bin/covey_devices.py{state_arg} check {failed[0]}"))
        else:
            rows.append((NOTE, "设备读不出来", "看 docs/operations.md「多设备」"))
    rows += web_rows(_dict(row.get("web_selfhost")))
    rows += ledger_rows(_dict(row.get("owner_ledger")), state_arg)
    return rows


LEDGER_WORDS = (("waiting", "等你"), ("stopped", "停住了"), ("stuck", "可能卡住"), ("result", "有结果"))


def ledger_rows(ledger, state_arg="") -> list:
    """等主人的账's rows (service/doctor.py ledger_row): what it counted at the last 对账, the cards not in the chat, and the
    tries at sending them again; [] before any 对账."""
    if not ledger:
        return []
    counts = _dict(ledger.get("counts"))
    said = "、".join(f"{words} {int(counts.get(key) or 0)}" for key, words in LEDGER_WORDS if counts.get(key))
    at = clock(ledger.get("checked_at"))
    rows = [(INFO, f"等你的事：{said or '没有'}" + (f"（{at} 对的账）" if at else ""), "")]
    missing = list(ledger.get("missing") or ())
    if missing:
        rows.append((NOTE, f"有 {len(missing)} 张卡没到聊天里，对账会补发",
                     f"python3 -B bin/covey_ledger.py{state_arg}"))
    tries = int(ledger.get("tries") or 0)
    if tries:
        failed = int(ledger.get("failed") or 0)
        rows.append((NOTE if failed else INFO,
                     f"对账补发过 {tries} 次卡：发出 {int(ledger.get('ok') or 0)} 次" + (f"，没发出 {failed} 次" if failed else ""),
                     f"python3 -B bin/covey_ledger.py{state_arg}" if failed else ""))
    return rows


def storage_rows(storage, state, log) -> list:
    """What the Bridge saw of its state directory's disk lately (core/storage_watch.py snapshot): a write refused for
    want of space, and locks and reads that took more than two seconds."""
    rows = []
    full = _dict(storage.get("full"))
    if full:
        count = int(full.get("count") or 0)
        rows.append((FAULT, f"状态目录的磁盘写不进：{full.get('error') or '空间不足'}（最近一次 {clock(full.get('at'))}"
                            + (f"，共 {count} 次" if count > 1 else "") + "）：任务记录和卡片进度可能存不下",
                     f"清出空间或扩大配额：df -h {state or '<状态目录>'}；恢复后不用重启"))
    slow = [one for one in storage.get("slow") or () if isinstance(one, dict)]
    if slow:
        worst = max(slow, key=lambda one: one.get("seconds") or 0)
        rows.append((NOTE, f"最近 {len(slow)} 次持锁或读盘超过 2 秒，最长 {worst.get('seconds')} 秒：{worst.get('what')}"
                           f"（{clock(worst.get('at'))}）", f"调用栈在日志里：grep 'slow ' {log}"))
    return rows


def web_rows(web) -> list:
    """The self-hosted page's rows (service/web_selfhost.py ``check``): one line when all is well, else one a problem; [] when the
    service does not run one."""
    if not web:
        return []
    problems = [p for p in web.get("problems") or () if isinstance(p, dict)]
    rows = [(NOTE if p.get("level") == "note" else FAULT, str(p.get("what") or "自托管网页有问题"), str(p.get("next") or "")) for p in problems]
    if any(mark == FAULT for mark, _, _ in rows):
        return rows
    public = _dict(web.get("public"))
    text = f"自托管网页在运行：本机 {web.get('url')}"
    if public:
        names = public.get("names") or ["?"]
        host = f"[{names[0]}]" if ":" in str(names[0]) else names[0]
        until = str(public.get("not_after") or "")[:10]
        text += f"，公网 https://{host}:{public.get('port')}/（{'自签证书' if public.get('tls') == 'self-signed' else '自己的证书'}"
        text += f"到 {until}）" if until else "）"
    return [(OK, text, ""), *rows]


def boot_row(boot, root_arg) -> tuple:
    status, mode = boot.get("status"), boot.get("mode")
    hint = boot.get("hint") if isinstance(boot.get("hint"), str) else ""
    linger = hint.rsplit(": ", 1)[-1] if "enable-linger" in hint else ""  # service/install.py linger_hint's command
    if status == "ready" and boot.get("autostart") is False:
        return NOTE, "开机不会自动拉起：这台机器没有可用的托管方式", "重启机器后要重新运行 ./install"
    if status == "ready" and linger:
        return NOTE, "开机自启注册好了，但退出登录后用户服务会停、开机也不起", f"运行 {linger}"
    if status == "ready":
        return OK, "开机会自动拉起（" + BOOT_MODES.get(mode, "扩展提供的托管") + "）", ""
    if status == "degraded":
        more = f"；还要运行 {linger}" if linger else ""
        return FAULT, "开机自启没装好", f"重新运行 ./install 装好它{more}（docs/operations.md「服务托管」）"
    return (NOTE, "开机自启没核实：没找到托管的回执",
            f"./install 会注册；或 python3 -B bin/covey_service_install.py{root_arg} --mode auto --activate")


def harness_rows(probes, probed) -> list:
    rows = []
    for name, probe in sorted(_dict(probes).items()):
        probe = _dict(probe)
        shown, when = HARNESS_NAMES.get(name, name), clock(probe.get("checked_at"))
        at = f"（{when} 测的）" if when else ""
        if probe.get("ok"):
            rows.append((OK, f"{shown} 能调通{at}", ""))
            continue
        reason = probe.get("reason")
        detail = f"：{probe['detail']}" if probe.get("detail") else ""
        advice = probe.get("advice") or "调用失败"
        if reason == "not_logged_in":
            next_step = LOGIN.get(name, f"在这台机器上登录 {shown}")
        else:
            next_step = PROBE_NEXT.get(reason, "看上面它说了什么")
        rows.append((FAULT, f"{shown} 调不通{at}：{advice}{detail}", f"{next_step}；好了再运行 {ENTRY} --probe-harnesses"))
    if not rows:
        rows.append((INFO, "还没测过模型能不能调通", f"{ENTRY} --probe-harnesses（各真实调用一次，花一点点额度）"))
    elif not probed:
        rows.append((INFO, "上面是上次测的结果", f"现在再测：{ENTRY} --probe-harnesses"))
    return rows


def lines(report, *, root="", states=None, root_arg="") -> list:
    """The summary of ``report`` (service/doctor.py ``diagnose``) as lines to print. ``root``: the service root it read;
    ``states``: {service id: its state directory} (the manifests', so the commands name the real directory); ``root_arg``:
    ' --root <root>' when the root is not the default one, for the commands."""
    states = states or {}
    services = [row for row in report.get("services") or () if isinstance(row, dict)]
    only = states.get(services[0].get("id"), "") if len(services) == 1 else ""
    rows = [manager_row(report.get("manager"), root_arg, only)]
    if not services:
        rows.append((FAULT, "这个服务根下没有注册的机器人",
                     "还没装就运行 ./install；装在别处的，用 --root <数据根>/bridge-services 指过去"))
    for row in services:
        rows += service_rows(row, states.get(row.get("id"), ""), root_arg)
    rows.append(boot_row(_dict(report.get("boot")), root_arg))
    rows += harness_rows(report.get("harness_probe"), report.get("model_access") == "probed")
    if report.get("events_checked") is False:
        rows.append((INFO, "这次没查事件连接（--skip-events）", ""))
    faults = sum(1 for mark, _, _ in rows if mark == FAULT)
    notes = sum(1 for mark, _, _ in rows if mark == NOTE)
    if not faults:
        verdict = "都正常" + (f"，有 {notes} 条提示" if notes else "")
    elif report.get("runtime_status") == "ready":
        verdict = f"机器人在运行；有 {faults} 项要看"
    else:
        verdict = f"有 {faults} 项要看"
    out = [f"Covey 诊断（服务根 {root}）" if root else "Covey 诊断", f"结论：{verdict}", ""]
    for mark, what, next_step in rows:
        out.append(f"{mark} {what}")
        if next_step:
            out.append(f"    下一步：{next_step}")
    out += ["", f"完整报告（JSON）：{ENTRY}{root_arg} --json"]
    return out


def unavailable_lines(root, root_arg="") -> list:
    """What the summary says when the service configuration could not be read at all (the report's 'unavailable')."""
    return [f"Covey 诊断（服务根 {root}）", "结论：没查成", "",
            f"{FAULT} 读服务配置时出错：清单或状态文件读不出来",
            "    下一步：确认 --root 指向 <数据根>/bridge-services（不给时用 COVEY_SERVICE_ROOT，或数据根下的 bridge-services）；"
            f"{ENTRY}{root_arg} --json 看原始结果"]
