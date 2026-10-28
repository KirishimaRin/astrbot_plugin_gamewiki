from unittest.mock import patch

from wiki.conversation import (
    Conversation,
    Conversations,
    is_followup,
    looks_like_followup,
)


def test_context_is_isolated_expires_and_has_a_capacity_bound():
    store = Conversations(max_entries=2, candidate_ttl=120, topic_ttl=600)
    key = ("group1", "alice")
    with patch("wiki.conversation.time.monotonic", return_value=100):
        ticket = store.begin(key)
        store.remember(
            key,
            ticket,
            "ys",
            {
                "status": "needs_choice",
                "question": "技能",
                "candidates": [{"title": "角色", "page_id": 1}],
            },
        )
        assert store.get(key).question == "技能"
        assert store.get(("group1", "bob")) is None
        assert store.get(("group2", "alice")) is None
    with patch("wiki.conversation.time.monotonic", return_value=220):
        assert store.get(key) is None
        for index in range(3):
            store.begin(("group", str(index)))
        assert len(store._entries) == 2
        assert store.get(("group", "0")) is None


def test_confirmed_topic_expires_and_slow_results_cannot_replace_newer_query():
    store = Conversations()
    key = ("group", "alice")
    with patch("wiki.conversation.time.monotonic", return_value=10):
        old = store.begin(key)
        new = store.begin(key)
        store.remember(key, new, "sr", {"status": "ok", "title": "流萤", "page_id": 2})
        store.remember(
            key, old, "ys", {"status": "ok", "title": "纳西妲", "page_id": 1}
        )
        assert store.get(key).title == "流萤"
    with patch("wiki.conversation.time.monotonic", return_value=610):
        assert store.get(key) is None


def test_followup_detection_keeps_new_entities_and_commands_separate():
    state = Conversation("ys", 600, page_id=1, sections=("所闻遍计",))
    for text in ("突破材料呢", "战技10级呢", "那技能倍率是多少？", "所闻遍计呢"):
        assert is_followup(text, state), text
    for text in ("流萤突破材料", "材料图鉴", "/ys 1", "1", "天气怎么样", "技能书"):
        assert not is_followup(text, state), text
    assert not is_followup("突破材料呢", None)
    assert looks_like_followup("战技10级呢")
