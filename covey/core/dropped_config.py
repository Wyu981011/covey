"""What a deployment configured that this release no longer uses (T786: an upgrade retired the Claude gateway profiles a
colleague had set up, the Bridge logged one line, and he found out from a launch card with a provider fewer).

``dropped(config, argv=(), environ=None)`` lists, for the harnesses.json ``config`` (its parsed object; {} without one), the
service's own command line ``argv`` (its options are the default Harness's, core/ignored_env.py ``where``) and its
environment, each thing this release reads no more:

- an option of RETIRED_OPTIONS that carries a value: on the command line for the default Harness, in harnesses.json's
  ``harnesses.<name>.args`` for the others (the default Harness's entry there is never read, and is not looked at);
- a Harness core/roster.py retired that harnesses.json still has an entry for or enables;
- a gateway of harnesses.json (core/gateways.py) whose Harnesses are all retired, so it serves none;
- a variable of core/ignored_env.py IGNORED_ENV set in the environment.

Each is ``{"key", "what", "instead"}``: ``key`` stays the same from release to release, so scripts/deploy_bridge.sh compares
what the live release lists with what this one does (a key only this one lists is configuration the upgrade would drop, and
the deploy stops on it unless ``--allow-dropped-config``); ``what`` and ``instead`` are said to the deployer. The doctor
reports them too (service/doctor.py ``dropped_config``), never as a fault: the service runs, without them.

Adding to a retirement: put the option here (RETIRED_OPTIONS) when its value stops being read, or the roster's RETIRED, the
gateways' RETIRED_GATEWAY_HARNESSES or IGNORED_ENV, as the removal already does. Standard library only: the deploy script
runs it from the checkout.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# option -> (its Harness, what its value set up, what the deployer does instead).
RETIRED_OPTIONS = {
    "--claude-profiles": ("claude", "Claude 网关档位：profile/<id>/<模型> 的模型和包装命令",
                          "本机 Claude Code 自己的登录照常可用；停在档位模型上的话题要换配置（可让管家批量换）"),
    "--codex-magpie-url": ("codex", "Codex 的 Magpie 供应商", "改用 harnesses.json 的 gateways 配一个模型网关（docs/harnesses.md 模型网关）"),
    "--traex-ppe-env": ("claude", "Claude Code 的 TRAE 供应商环境", "TRAE 已下线，删掉这个参数"),
    "--traex-site": ("claude", "Claude Code 的 TRAE 供应商站点", "TRAE 已下线，删掉这个参数"),
}


def option_value(argv, option) -> str:
    """The value ``option`` has in ``argv`` (``--x v`` or ``--x=v``), '' when it is not there or empty."""
    argv = [str(part) for part in argv or ()]
    for index, part in enumerate(argv):
        if part == option and index + 1 < len(argv) and not argv[index + 1].startswith("--"):
            return argv[index + 1].strip()
        if part.startswith(option + "="):
            return part.split("=", 1)[1].strip()
    return ""


def read_config(path) -> dict:
    """harnesses.json at ``path`` as an object; {} when it is not there or not one."""
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _item(key, what, instead) -> dict:
    return {"key": key, "what": what, "instead": instead}


def dropped(config, argv=(), environ=None) -> list[dict]:
    """The module docstring's list, in the order it says."""
    from covey.core import env as cenv
    from covey.core.gateways import GATEWAY_HARNESSES
    from covey.core.ignored_env import IGNORED_ENV, where
    from covey.core.roster import NAMES, RETIRED

    environ = os.environ if environ is None else environ
    config = config if isinstance(config, dict) else {}
    harnesses = config.get("harnesses") if isinstance(config.get("harnesses"), dict) else {}
    found = []
    for option, (harness, what, instead) in RETIRED_OPTIONS.items():
        if harness == NAMES[0]:
            value, place = option_value(argv, option), "服务的启动命令"
        else:
            entry = harnesses.get(harness) if isinstance(harnesses.get(harness), dict) else {}
            value, place = option_value(entry.get("args") or (), option), f"harnesses.json 里 {harness} 的参数"
        if value:
            found.append(_item(f"option:{harness}:{option}", f"{place}有 {option}（{what}），新版本不再读", instead))
    enabled = config.get("enabled_harnesses") if isinstance(config.get("enabled_harnesses"), list) else []
    for name in sorted({*(name for name in harnesses if name in RETIRED),
                        *(name for name in enabled if isinstance(name, str) and name in RETIRED)}):
        found.append(_item(f"harness:{name}", f"harnesses.json 里还写着已下线的 Harness「{RETIRED[name]}」，不再启动",
                           "删掉它的条目；停在它上面的话题发消息只得到一句已下线的提示，要换配置"))
    gateways = config.get("gateways") if isinstance(config.get("gateways"), dict) else {}
    for name, fields in sorted(gateways.items()):
        served = fields.get("harnesses") if isinstance(fields, dict) else None
        if isinstance(served, list) and served and not any(h in GATEWAY_HARNESSES for h in served):
            found.append(_item(f"gateway:{name}", f"harnesses.json 的模型网关 {name} 只给已下线的 Harness 用，不再有用处",
                               "删掉它，或在 harnesses 里写上 codex、dsh"))
    for name, (harness, option) in IGNORED_ENV.items():
        if not cenv.has(name, environ):
            continue
        if harness in RETIRED or not option:
            instead = "删掉这个变量"
        else:
            if isinstance(option, tuple):
                option = next((each for each in option if each), "")
            instead = f"删掉它，在{'服务的启动命令' if where(harness) == 'the service command line' else ' harnesses.json'}里写 {option}"
        found.append(_item(f"env:{name}", f"服务环境里的 {name}，新版本不再读", instead))
    return found


def words(items) -> list[str]:
    """One line each: what, then what to do instead."""
    return [f"{item['what']}；{item['instead']}" for item in items]


def newly(items, live_keys) -> list[dict]:
    """``items`` a release lists that the live release's ``live_keys`` do not: what the upgrade drops. ``live_keys`` None (the live
    release has no such list): none, as what the module listed when it came in had been dropped by releases before it."""
    if live_keys is None:
        return []
    known = set(live_keys)
    return [item for item in items if item["key"] not in known]
