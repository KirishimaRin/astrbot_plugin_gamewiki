"""Bounded, short-lived command context isolated by session and sender."""

import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field

NUMBER = re.compile(r"[0-9]{1,3}")
FOLLOWUP = re.compile(
    r"^(?:(?:那|那么|再|它|他|她|这个角色|这个条目)(?:的)?[，,\s]*)?"
    r"(?:突破|晋阶|精英化|材料|培养材料|升级材料|获取|获得|来源|在哪|哪里|"
    r"战技|元素战技|爆发|元素爆发|普攻|普通攻击|技能|天赋|行迹|终结技|"
    r"特殊技|模组|属性|倍率|故事|剧情|简介|介绍|用途|效果|语音|分节)"
    r"(?:[0-9一二三四五六七八九十级LVlv\s，,？?。！!]|的|呢|吗|啊|是|什么|怎么|如何|"
    r"需要|哪些|多少|总量|讲了|讲讲|介绍|详细|材料|伤害|倍率|冷却|时间|获取|方式|"
    r"提升|消耗|升级|天赋|故事|剧情|行迹|专精|技能|晋阶|突破)*$"
)


@dataclass
class Conversation:
    game: str
    expires: float
    candidates: list[dict] = field(default_factory=list)
    question: str = ""
    page_id: int | None = None
    title: str = ""
    sections: tuple[str, ...] = ()
    source: str = ""


@dataclass
class Ticket:
    expires: float
    state: Conversation | None = None


def is_followup(text: str, state: Conversation | None) -> bool:
    if state is None or state.page_id is None or not 0 < len(text) <= 100:
        return False
    return bool(FOLLOWUP.match(text)) or text.rstrip("呢？?。 ") in state.sections


def looks_like_followup(text: str) -> bool:
    return 0 < len(text) <= 100 and bool(FOLLOWUP.fullmatch(text))


class Conversations:
    def __init__(self, *, max_entries=256, candidate_ttl=120, topic_ttl=600):
        self.max_entries = max_entries
        self.candidate_ttl = candidate_ttl
        self.topic_ttl = topic_ttl
        self._entries: OrderedDict[tuple[str, str], Ticket] = OrderedDict()

    def _prune(self):
        now = time.monotonic()
        for key, ticket in list(self._entries.items()):
            if ticket.expires <= now:
                del self._entries[key]

    def get(self, key: tuple[str, str]) -> Conversation | None:
        self._prune()
        ticket = self._entries.get(key)
        if ticket and ticket.state and ticket.state.expires > time.monotonic():
            return ticket.state
        return None

    def begin(self, key: tuple[str, str], *, preserve=False) -> Ticket:
        state = self.get(key) if preserve else None
        ticket = Ticket(time.monotonic() + self.topic_ttl, state)
        self._entries[key] = ticket
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return ticket

    def forget(self, key: tuple[str, str]) -> None:
        self._entries.pop(key, None)

    def remember(self, key, ticket: Ticket, game: str, result: dict) -> None:
        # A slower older query must not overwrite a newer command's context.
        if self._entries.get(key) is not ticket:
            return
        state = None
        if result.get("status") == "needs_choice" and result.get("candidates"):
            state = Conversation(
                game,
                time.monotonic() + self.candidate_ttl,
                candidates=[dict(item) for item in result["candidates"][:5]],
                question=result.get("question", ""),
                source=result.get("source_key", ""),
            )
        elif result.get("status") in {"ok", "section_not_found"}:
            page_id = result.get("page_id")
            if (
                isinstance(page_id, int)
                and not isinstance(page_id, bool)
                and page_id > 0
            ):
                state = Conversation(
                    game,
                    time.monotonic() + self.topic_ttl,
                    page_id=page_id,
                    title=result.get("display_title", result.get("title", "")),
                    sections=tuple(result.get("available_sections", [])),
                    source=result.get("source_key", ""),
                )
        if state:
            ticket.state = state
            ticket.expires = state.expires
