"""Replay real source snapshots through command/card production paths.

Usage: python scripts/audit_cards.py research/card-cases.json --output research/card-review
The manifest is a JSON list. Each case declares game, source, title, question,
url, and either html_path or result_path. Optional required_sections and
required_text assert actual selected evidence and rendered text. expect_skip
records sources whose page supplies no suitable aspect section. Input files
and PNG/JSON outputs stay outside the distribution and version control.
"""

import argparse
import asyncio
import io
import json
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki import card  # noqa: E402
from wiki.assistant import CommandAssistant  # noqa: E402
from wiki.extractor import extract_sections  # noqa: E402
from wiki.games import PROFILES  # noqa: E402
from wiki.selection import evidence  # noqa: E402


def load_result(case, root):
    if "result_path" in case:
        return json.loads((root / case["result_path"]).read_text(encoding="utf-8"))
    raw = (root / case["html_path"]).read_text(encoding="utf-8")
    html = (
        json.loads(raw)["parse"]["text"] if case["html_path"].endswith(".json") else raw
    )
    profile = PROFILES[case["game"]]
    sections = extract_sections(
        html, case["title"], prefix=profile.code, source=case["source"]
    )
    snippets, truncated, selection = evidence(
        sections,
        case["question"],
        6000,
        "",
        case["title"],
        profile.intents,
        profile.specifics,
    )
    return dict(
        status="ok",
        title=case["title"],
        source=f"{profile.name} {case['source'].upper()}",
        source_key=case["source"],
        url=case["url"],
        evidence=snippets,
        selection=selection,
        truncated=truncated,
    )


async def audit(case, root, output):
    profile = PROFILES[case["game"]]
    result = load_result(case, root)
    record = {**case, "selected": [s["section"] for s in result.get("evidence", [])]}
    service = SimpleNamespace(aliases={}, search=AsyncMock(return_value=result))
    assistant = CommandAssistant(AsyncMock(return_value="请查看资料中的相关说明。"))
    _, metrics = await assistant.answer(
        f"{case['title']} {case['question']}", profile, service
    )
    payload = metrics.get("card") if not metrics.get("fallback") else None
    if case.get("expect_skip"):
        assert not payload, (
            "unstructured/fallback evidence must not produce an aspect card"
        )
        return {**record, "status": "skipped", "reason": case["expect_skip"]}
    assert payload, f"missing card: {metrics}"
    for text in case.get("required_sections", []):
        assert any(text in s for s in record["selected"]), f"section missing: {text}"
    drawn = []
    original = card.ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        bbox = draw.textbbox(xy, text, font=kwargs["font"])
        drawn.append(dict(text=text, bbox=bbox, xy=xy))
        return original(draw, xy, text, *args, **kwargs)

    start = time.perf_counter()
    with patch.object(card.ImageDraw.ImageDraw, "text", capture):
        png = card.render_card(
            payload["title"], payload["source"], payload["sections"], profile.accent
        )
    elapsed = time.perf_counter() - start
    assert png, "a usable CJK font is required for visual audits"
    image = Image.open(io.BytesIO(png))
    path = output / (case["id"] + ".png")
    path.write_bytes(png)
    footer = image.height - 46
    for entry in drawn:
        left, top, right, bottom = entry["bbox"]
        assert 0 <= left <= right <= card.WIDTH, f"horizontal overflow: {entry}"
        assert 0 <= top <= bottom <= image.height, f"vertical overflow: {entry}"
        if entry["xy"][1] < footer:
            assert bottom < footer, f"body collides with footer: {entry}"
    rendered = "\n".join(e["text"] for e in drawn)
    compact = re.sub(r"\s+", "", rendered)
    for text in case.get("required_text", []):
        assert re.sub(r"\s+", "", text) in compact, f"rendered text missing: {text}"
    for text in ("点击查看技能预览", "文件:.png", "显示算法", "查看逐级数值", "{{{"):
        assert text not in rendered, f"UI/placeholder noise: {text}"
    return {
        **record,
        "status": "passed",
        "png": str(path.resolve()),
        "size": image.size,
        "render_seconds": round(elapsed, 4),
        "drawn": drawn,
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=Path("research/card-review"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = json.loads(args.manifest.read_text(encoding="utf-8"))
    records = []
    for case in cases:
        try:
            record = await audit(case, args.manifest.parent, args.output)
        except Exception as exc:  # noqa: BLE001 - keep every failed case in the report
            record = {**case, "status": "failed", "error": str(exc)}
        records.append(record)
        print(record["status"].upper(), case["id"], record.get("error", ""), flush=True)
    (args.output / "audit.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if any(r["status"] == "failed" for r in records):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
