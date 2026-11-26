"""The home's part of a turn: the static home block of the rules and what the Harness's environment adds.

``static_block`` is what app/prompts.py bridge_rules puts where the workspace block was, for a topic that started in
the home (core/topics.py ``home_start``): the home, the repo map's path, the topic's outputs directory when
``home.json`` names one, and the rules of working from the home. It never changes within a topic, so the rules stay
one cacheable prefix; what changes turn by turn is app/repos_turn.py's. A topic from before the home gets '' and keeps
its workspace block. ``env`` is what every Harness process gets (core/home.py ``env``: ``COVEY_HOME``, ``COVEY_TOPIC``,
``COVEY_STATE``, ``<数据根>/bin`` first on ``PATH``), and the cache variables in the run's directory when ``home.json``
says ``cache_env`` (docs/configuration.md 主目录与仓库地图).
"""
from __future__ import annotations

from covey.core import home, repomap, topic_repos
from covey.core.state import read_json
from covey.core.topics import home_start

RULES = ("主目录的规矩：\n"
         "- 不要在主目录根递归搜索（rg、grep -r、find、ls -R、du），先查仓库地图，只搜具体的仓库或子目录。\n"
         "- 进一个仓库干活之前先读它的 AGENTS.md 或 CLAUDE.md，照它的规矩做。\n"
         "- 要改仓库：covey repo use <仓库> --write，在它打印的目录里改（按话题建 worktree，不动仓库的主检出；"
         "地图里写着原地改的除外）。只读：covey repo use <仓库>；本话题用到的：covey repo status。")


def _topic(ctx) -> dict:
    try:
        data = read_json(ctx.history_path.parent / "topic.json")
    except (OSError, ValueError, AttributeError):
        return {}
    return data if isinstance(data, dict) else {}


def outputs_dir(ctx, data=None) -> str:
    """The topic's outputs directory (core/home.py ``topic_dir``) when ``home.json`` is there; '' else."""
    if not home.configured(ctx.state_dir):
        return ""
    data = _topic(ctx) if data is None else data
    number = data.get("topic_number") if type(data.get("topic_number")) is int else 0
    return home.topic_dir(home.read(ctx.state_dir), home.of(ctx), number=number, topic_id=ctx.topic_id,
                          title=data.get("slug") or "", started=data.get("started_at"))


def static_block(ctx) -> str:
    """The home block of ``ctx``'s rules: '' for a topic that did not start in the home, or one on a device (its
    workspace block, as before; app/prompts.py home_section)."""
    if getattr(ctx, "device", ""):
        return ""
    data = _topic(ctx)
    if not home_start(data):
        return ""
    where = home.of(ctx)
    rendered = repomap.render(ctx.state_dir, where) or repomap.rendered_path(ctx.state_dir, where)
    lines = [f"主目录：{where}（本话题从这里启动，先遵守这里的 AGENTS.md）",
             f"仓库地图：{rendered}（要动的代码先在地图里找仓库）"]
    outputs = outputs_dir(ctx, data)
    if outputs:
        lines.append(f"本话题产物目录：{outputs}（输出、日志、临时文件都放这里，每次运行在它下面另建子目录）")
    return "\n".join(lines) + "\n" + RULES


def env(ctx) -> dict:
    """The variables the Harness process of ``ctx``'s turn gets on top of the Bridge's (core/home.py ``env``), with the
    cache variables of the topic's run directory when ``home.json`` says ``cache_env`` and the directory is writable."""
    found = home.env(ctx)
    if not found or not home.configured(ctx.state_dir):
        return found
    config = home.read(ctx.state_dir)
    if not config.cache_env:
        return found
    data = _topic(ctx)
    if not home_start(data):
        return found
    number = data.get("topic_number") if type(data.get("topic_number")) is int else 0
    task = topic_repos.task_dir_of(ctx.state_dir)
    run = home.run_dir_for(config, home.of(ctx), number=number, topic_id=ctx.topic_id, title=data.get("slug") or "",
                           started=data.get("started_at"), task_key=task.name if task else "")
    return {**found, **home.cache_env(run)}
