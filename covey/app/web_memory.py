"""The web page's 记忆 tab (data contract v37, COVEY_MEMORY=1): the owner's main memory, 全局 and each workspace's, read and changed
as the 设置 card's 记忆 tab reads and changes it.

``view`` is the ``settings`` item ``memory`` (app/web_sync.py push_memory): the principles (core/principles.py), with
COVEY_KNOWLEDGE=1 the knowledge entries (core/knowledge.py) and with COVEY_MEMORY_LEARN=1 the open candidates
(app/memory_candidates.py), each group with the room it uses of its scope's limit and which entries the next turn carries,
through core/memory.py ``items``, ``fill`` and ``select`` exactly as a turn does (app/memory_turn.py), and the block a new topic's
turn in each workspace would read (app/prompts.py memory_block). Projects' and topics' memory are on their own pages, not here.

``edit`` is the ``memory_edit`` operation (app/web_ops.py): add a principle or a knowledge entry to 全局 or a workspace, change its
words (only when it still reads what the page started from, ``base``), mark a principle 常驻 or not, delete a principle or void a
knowledge entry, keep (记下) or drop (不用) a candidate. Every change goes through the store's own function under its own lock,
the same ones the butler's tools and the 设置 card use, so the card and the page read one memory. No model, no Feishu call.
"""
from __future__ import annotations

import re
from pathlib import Path

from covey.app import memory_candidates
from covey.app.prompts import memory_block
from covey.core import knowledge, memory, memory_usage, principles
from covey.core.jobs import job_path, read_job_record
from covey.core.state import read_object
from covey.core.topics import topic_file
from covey.core.workspaces import config_path, load_config

GLOBAL, WORKSPACE = memory.GLOBAL, memory.WORKSPACE
PRINCIPLE, KNOWLEDGE, CANDIDATE = "principle", "knowledge", "candidate"
ACTIONS = ("add", "edit", "pin", "unpin", "delete", "keep", "drop")
CANDIDATE_ID = re.compile(r"c[0-9a-f]{8}")  # app/memory_candidates.py ids, as app/memory_panel.py CANDIDATE.
PREVIEWS = 24  # Workspaces the next turn is previewed for: the default one and those with entries, the default first.
DROP_REASON = "主人在网页「记忆」里作废"
EDIT_REASON = "主人在网页「记忆」里改了"
SOURCE = {"via": "web"}  # What a principle or an entry written here says of where it came from.
ORIGIN_WORDS = {"web": "网页上记的", "settings_card": "设置卡里升为全局的", "memory_candidates": "晚间候选里记下的",
                "memory_learn": "自动学习记的"}
QUOTE_SHOWN = 200  # Characters of the owner's own words an entry's origin carries.
NOTE_SHOWN = 60  # Characters of a source's note the page shows after where it came from.


def enabled() -> bool:
    return memory.enabled()


def stamps(state_dir) -> tuple:
    """What a change of the memory shows in, read each step of the pass thread: the principles', the candidates', the usage's and the
    workspace list's mtimes, and each knowledge file's."""
    state = Path(state_dir)
    files = [principles.path(state), memory_candidates.path(state), memory_usage.path(state), config_path(state)]
    root = knowledge.root(state)
    try:
        files += sorted(root.iterdir())
    except OSError:
        pass
    out = []
    for file in files:
        try:
            out.append((file.name, file.stat().st_mtime_ns))
        except OSError:
            out.append((file.name, 0))
    return tuple(out)


def workspace_names(state_dir, default_workdir) -> tuple[str, list]:
    """(the default workspace, every workspace's name); ('', []) when the list cannot be read."""
    try:
        config = load_config(state_dir, default_workdir)
    except (OSError, ValueError, TypeError, AttributeError):
        return "", []
    return str(config["default"] or ""), [str(name) for name in config["workspaces"]]


def _job_topic(state_dir, job_key, cache) -> tuple[str, bool]:
    """(the topic number "T83" or '', whether it is the butler's topic) of the job ``job_key``, '' and False when it cannot be read."""
    if job_key not in cache:
        found = ("", False)
        try:
            record = read_job_record(job_path(Path(state_dir), job_key)) or {}
            topic = read_object(topic_file(Path(state_dir), str(record.get("topic_id") or ""))) if record.get("topic_id") else {}
            number = topic.get("topic_number")
            found = (f"T{number}" if type(number) is int else "", topic.get("main_thread") is True)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        cache[job_key] = found
    return cache[job_key]


def _topic_number(state_dir, topic_id, cache) -> str:
    key = f"topic:{topic_id}"
    if key not in cache:
        try:
            number = read_object(topic_file(Path(state_dir), str(topic_id))).get("topic_number")
        except (OSError, ValueError, TypeError, AttributeError):
            number = None
        cache[key] = f"T{number}" if type(number) is int else ""
    return cache[key]


def origin_of(source, by="", state_dir=None, cache=None) -> dict:
    """Where a principle or an entry came from, by what its ``source`` really says: {origin (a few words, '' when it does not say),
    quote (the owner's own words it was learned from), topic (the topic number "T83" it was written in, or the candidates' topics
    joined)}. ``by``: a knowledge entry's own ``by`` (main: the butler's tool, topic: a topic's turn, import). A ``note`` in the
    source (what a later look at the line found of where it came from) follows the words."""
    found = _origin_bare(source, by, state_dir, cache)
    note = " ".join(str((source if isinstance(source, dict) else {}).get("note") or "").split())[:NOTE_SHOWN]
    if note:
        found["origin"] = f"{found['origin']}；{note}" if found["origin"] else note
    return found


def _origin_bare(source, by="", state_dir=None, cache=None) -> dict:
    source = source if isinstance(source, dict) else {}
    cache = {} if cache is None else cache
    quote = " ".join(str(source.get("quote") or "").split())[:QUOTE_SHOWN]
    for key in ("via", "by"):
        word = ORIGIN_WORDS.get(source.get(key))
        if word is None:
            continue
        topic = ""
        if source.get(key) == "memory_candidates" and state_dir is not None:
            names = [_topic_number(state_dir, tid, cache) for tid in list(source.get("topics") or ())[:6]]
            topic = "、".join(name for name in names if name)
        elif source.get(key) == "memory_learn" and state_dir is not None and source.get("job_key"):
            topic = _job_topic(state_dir, str(source["job_key"]), cache)[0]
        if topic:
            word += f"（话题 {topic}）"
        return {"origin": word, "quote": quote, "topic": topic}
    topic = str(source.get("topic") or "")
    job_key = str(source.get("job_key") or "")
    butler = False
    if not topic and job_key and state_dir is not None:
        topic, butler = _job_topic(state_dir, job_key, cache)
    if source.get("from") and (job_key or topic):  # app/memory_collect.py: a line of a topic's memory raised to 全局.
        return {"origin": f"话题 {topic} 里升为全局的" if topic else "话题里升为全局的", "quote": quote, "topic": topic}
    if by == "topic" or (topic and not butler):
        return {"origin": f"话题 {topic} 里记的" if topic else "话题里记的", "quote": quote, "topic": topic}
    if by == "import":
        return {"origin": "导入的", "quote": quote, "topic": topic}
    if job_key or source.get("job_id"):
        return {"origin": "管家记的", "quote": quote, "topic": ""}
    return {"origin": "", "quote": quote, "topic": ""}


def origin(source, by="", state_dir=None, cache=None) -> str:
    """The words of ``origin_of``."""
    return origin_of(source, by, state_dir, cache)["origin"]


def _origin_facts(source, by, state_dir, cache) -> dict:
    found = origin_of(source, by, state_dir, cache)
    return {"origin": found["origin"], "quote": found["quote"], "topic": found["topic"]}


def _found(state_dir, workspace, knowledge_on, learn, used):
    """The items a new topic's turn in ``workspace`` reads ('' : 全局 alone)."""
    mine, space = principles.for_turn(state_dir, workspace)
    entries = knowledge.for_turn(state_dir, workspace) if knowledge_on else ((), ())
    drafts = memory_candidates.carried(state_dir, workspace) if learn else ((), ())
    return memory.items(principles=(mine, space), entries=entries, drafts=drafts, used=used)


def _row(item, carried, facts) -> dict:
    """An entry of a group: what the item says, and of its store what the page shows besides (kind, origin, knowledge's kind and why).
    ``text`` is what the store holds (a knowledge entry's own words, not the line a turn reads, which adds its kind and why), the
    ``base`` of an edit; ``size`` is its characters as the editor counts them, ``chars`` what the line uses of the group's room
    (the number and the speaker around it count too)."""
    kind, _, rid = item["ref"].partition(":")
    extra = facts.get(item["ref"], {})
    text = extra.get("text", item["text"])
    row = {"key": item["ref"], "kind": kind, "text": text, "by": item["by"], "pinned": bool(item.get("pinned")),
           "pinnable": kind == PRINCIPLE, "editable": kind in (PRINCIPLE, KNOWLEDGE), "carried": item["ref"] in carried,
           "chars": memory.line_size(item), "size": len(text), "at": item["at"], "origin": extra.get("origin", ""),
           "edited": extra.get("edited", ""), "quote": extra.get("quote", ""), "topic": extra.get("topic", "")}
    if kind == KNOWLEDGE:
        row["knowledge_kind"], row["why"] = extra.get("kind", ""), extra.get("why", "")
    return row


def _group(scope, workspace, found, scopes, carried, facts) -> dict:
    info = scopes[scope]
    rows = [_row(item, carried, facts) for item in found if item["scope"] == scope]
    rows.sort(key=lambda row: (not row["pinned"], -row["at"], row["key"]))
    return {"scope": scope, "workspace": workspace, "title": "全局" if scope == GLOBAL else f"工作区 {workspace}",
            "used": info["used"], "limit": info["limit"], "left": len(info["left"]), "entries": rows}


def view(state_dir, default_workdir=None) -> dict:
    """The ``memory`` item's data (docs/web.md 设置条目): {on, knowledge, learn, limits, kinds, default, workspaces, groups,
    candidates, previews}. ``groups``: 全局 first, then each workspace that has entries, by name (an empty one the page adds to
    is listed once it has one). ``previews``: per workspace, the block a new topic's turn there reads (``text``), how many entries
    and characters it carries and how many it leaves out."""
    knowledge_on, learn = knowledge.enabled(), memory.learning()
    used = memory_usage.last_used(state_dir) if learn else None
    default, names = workspace_names(state_dir, default_workdir)
    loaded = principles.load(state_dir)
    facts, cache = {}, {}
    for row in principles.entries(state_dir):
        facts[f"principle:{row['id']}"] = {**_origin_facts(row.get("source"), "", state_dir, cache), "edited": row.get("edited", "")}
    spaces = set(loaded["workspaces"])
    if knowledge_on:
        for scope, name, group in knowledge.groups(state_dir):
            for entry in group.values():
                if entry["state"] == knowledge.CURRENT:
                    facts[f"knowledge:{entry['id']}"] = {**_origin_facts(entry.get("source"), entry.get("by"), state_dir, cache),
                                                          "text": entry["text"], "kind": entry.get("kind", ""), "why": entry.get("why", "")}
                    if scope == knowledge.WORKSPACE and name:
                        spaces.add(name)
    open_rows = [row for row in memory_candidates.load(state_dir)["rows"] if row.get("state") == memory_candidates.OPEN
                 and isinstance(row.get("text"), str) and row["text"].strip()] if learn else []
    spaces |= {str(row.get("workspace") or "") for row in open_rows if row.get("carried") and row.get("workspace")}
    groups, previews = [], {}
    order = list(dict.fromkeys([default, *sorted(spaces)])) if default else sorted(spaces)
    for index, name in enumerate(order or [""]):
        found = _found(state_dir, name, knowledge_on, learn, used)
        scopes = memory.fill(found)
        kept, left = memory.select([dict(item) for item in found])
        carried = {item["ref"] for item in kept}
        if index == 0:  # 全局 reads the same whatever the workspace: its group once, from the first.
            groups.append(_group(GLOBAL, "", found, scopes, carried, facts))
        if name and name in spaces:
            groups.append(_group(WORKSPACE, name, found, scopes, carried, facts))
        if name and len(previews) < PREVIEWS:
            previews[name] = {"count": len(kept), "chars": sum(memory.line_size(item) for item in kept), "left": left,
                              "text": memory_block(kept, left, learn={"search": ""} if learn else None)}
    globals_ = groups[:1]
    groups = globals_ + sorted(groups[1:], key=lambda group: group["workspace"])
    candidates = [{"key": f"candidate:{row['id']}", "text": " ".join(row["text"].split()), "workspace": str(row.get("workspace") or ""),
                   "carried": bool(row.get("carried")), "at": float(row.get("at") or 0), "error": str(row.get("error") or ""),
                   "from": memory_candidates.SOURCE_WORDS.get(str(row.get("source") or ""), "")}
                  for row in sorted(open_rows, key=lambda row: -float(row.get("at") or 0))]
    return {"on": True, "knowledge": knowledge_on, "learn": learn,
            "limits": {"text": principles.TEXT_LIMIT, "group": principles.GROUP_LIMIT, "pinned": principles.PINNED_LIMIT,
                       GLOBAL: memory.LIMITS[GLOBAL], WORKSPACE: memory.LIMITS[WORKSPACE]},
            "kinds": [{"value": key, "text": word} for key, word in knowledge.KINDS.items()],
            "default": default, "workspaces": names, "groups": groups, "candidates": candidates, "previews": previews}


def short(text, limit=30) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _key(payload) -> tuple[str, str]:
    kind, _, rid = str(payload.get("key") or "").partition(":")
    ok = {PRINCIPLE: principles.ID, KNOWLEDGE: knowledge.ID, CANDIDATE: CANDIDATE_ID}.get(kind)
    if ok is None or not ok.fullmatch(rid):
        raise ValueError("不认识这条记忆，页面会按最新的重画")
    return kind, rid


def _gone(what="这条记忆") -> ValueError:
    return ValueError(f"{what}已经不在了（可能刚在别处删掉），页面会按最新的重画")


def edit(state_dir, payload) -> str:
    """One ``memory_edit`` operation (``payload["action"]``, ACTIONS); the receipt the page shows. ValueError says why nothing changed."""
    action = str(payload.get("action") or "")
    if action not in ACTIONS:
        raise ValueError("不认识的记忆操作")
    if action == "add":
        return _add(state_dir, payload)
    kind, rid = _key(payload)
    if action == "edit":
        try:
            return _edit(state_dir, kind, rid, payload)
        except ValueError as exc:
            raise _owner_words(exc) from None
    if action in ("pin", "unpin"):
        if kind != PRINCIPLE:
            raise ValueError("只有原则能标常驻")
        found = principles.pin(state_dir, rid, action == "pin")
        if found is None:
            raise _gone()
        return ("已标常驻：" if action == "pin" else "已取消常驻：") + short(found["text"])
    if action == "delete":
        if kind == PRINCIPLE:
            found = principles.delete(state_dir, rid)
            if found is None:
                raise _gone()
            return "已删除：" + short(found["text"])
        if kind == KNOWLEDGE:
            old = knowledge.find(state_dir, rid)
            if old is None or old["state"] != knowledge.CURRENT:
                raise _gone()
            found = knowledge.drop(state_dir, rid, DROP_REASON, source=SOURCE, by="main")
            return "已作废：" + short(found["text"])
        raise ValueError("候选用「不用」，不用删")
    if kind != CANDIDATE:
        raise ValueError("记下、不用只对候选")
    before = next((row for row in memory_candidates.load(state_dir)["rows"] if row.get("id") == rid), None)
    if before is None:
        raise _gone("这条候选")
    if before.get("state") != memory_candidates.OPEN:
        raise ValueError("这条候选已经处理过了")
    row = memory_candidates.decide(state_dir, rid, "save" if action == "keep" else "drop")
    if row is None:
        raise _gone("这条候选")
    if row.get("state") == memory_candidates.SAVED:
        where = f"工作区 {row['workspace']}" if row.get("workspace") else "全局"
        return f"已记下，记到{where}：" + short(row.get("text"))
    if row.get("state") == memory_candidates.DECLINED:
        return "不用了：" + short(row.get("text"))
    raise ValueError(str(row.get("error") or "这条候选已经处理过了"))


def _scope(payload) -> tuple[str, str]:
    scope, workspace = str(payload.get("scope") or ""), principles.clean_text(payload.get("workspace"))
    if scope not in (GLOBAL, WORKSPACE):
        raise ValueError("要选记在全局还是某个工作区")
    if scope == WORKSPACE and not workspace:
        raise ValueError("要选记在哪个工作区")
    return scope, workspace if scope == WORKSPACE else ""


def _owner_words(exc) -> ValueError:
    """A store's refusal in the owner's words: the stores speak to the butler (its tools' names in them)."""
    text = re.sub(r"：先问主人删掉哪条（principle_delete），再记新的", "：先删掉用不着的再记", str(exc))
    return ValueError(re.sub(r"（[a-z_]+ 里的名字）|：用 knowledge_search 找|，用 knowledge_search 重新找", "", text))


def _add(state_dir, payload) -> str:
    try:
        return _add_one(state_dir, payload)
    except ValueError as exc:
        raise _owner_words(exc) from None


def _add_one(state_dir, payload) -> str:
    scope, workspace = _scope(payload)
    what, text = str(payload.get("what") or ""), payload.get("text")
    if what == PRINCIPLE:
        item, new = principles.save(state_dir, principles.OWNER if scope == GLOBAL else principles.WORKSPACE, text,
                                    workspace=workspace, source=SOURCE)
        return ("已记下：" if new else "已有说同样意思的一条，没再记：") + short(item["text"])
    if what == KNOWLEDGE:
        if not knowledge.enabled():
            raise ValueError("知识条目没开（COVEY_KNOWLEDGE）")
        entry, new = knowledge.save(state_dir, knowledge.OWNER if scope == GLOBAL else knowledge.WORKSPACE,
                                    str(payload.get("knowledge_kind") or "fact"), text, workspace=workspace,
                                    why=str(payload.get("why") or ""), source=SOURCE, by="main")
        return ("已记下：" if new else "已有同样的一条，没再记：") + short(entry["text"])
    raise ValueError("要选记成原则还是知识条目")


def _edit(state_dir, kind, rid, payload) -> str:
    text, base = payload.get("text"), payload.get("base")
    base = None if base is None else str(base)
    if kind == PRINCIPLE:
        found = principles.edit(state_dir, rid, text, base=base)
        if found is None:
            raise _gone()
        return "已保存：" + short(found["text"])
    if kind == KNOWLEDGE:
        old = knowledge.find(state_dir, rid)
        if old is None or old["state"] != knowledge.CURRENT:
            raise _gone()
        if base is not None and knowledge.clean_text(base) != old["text"]:
            raise ValueError("这条刚在别处改过，先看看现在的内容再改")
        kind_ = str(payload.get("knowledge_kind") or "") or None
        why = payload.get("why")
        if knowledge.clean_text(text) == old["text"] and (kind_ in (None, old["kind"])) and (why is None or knowledge.clean_text(why) == old["why"]):
            return "没有变化"
        entry = knowledge.update(state_dir, rid, text, kind=kind_, why=None if why is None else str(why), reason=EDIT_REASON,
                                 source={**old["source"], "edited_via": "web"}, by=old["by"])  # Where it came from stays.
        return "已保存：" + short(entry["text"])
    raise ValueError("候选不能改，记下以后再改")
