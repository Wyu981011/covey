"""The home's part of a turn (FINAL-SPEC 修订 9): the static home block of the rules and what the Harness's environment adds.

``static_block`` is what app/prompts.py bridge_rules puts where the workspace block was: the home, the repo map's path
and the rules of working from the home; it never changes within a topic, so the rules stay one cacheable prefix (修订 4).
``env`` is what the Harness process gets (``COVEY_HOME``, ``COVEY_TOPIC``, ``COVEY_STATE`` and ``<数据根>/bin`` on its
``PATH``). A0: both empty, so the rules and the environment are as before (package W1).
"""
from __future__ import annotations


def static_block(ctx) -> str:
    """The home block of ``ctx``'s rules; '' keeps the workspace block (app/prompts.py home_section)."""
    return ""


def env(ctx) -> dict:
    """The variables the Harness process of ``ctx``'s turn gets on top of the Bridge's: none yet."""
    return {}
