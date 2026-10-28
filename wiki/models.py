"""Small data contracts shared by retrieval and extraction."""

from dataclasses import dataclass, field
from urllib.parse import quote, urlencode

from .games import default_source, source_api


class WikiError(Exception):
    """An expected failure with a user-readable description."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def page_url(title: str, anchor: str = "", code: str = "ys", source: str = "") -> str:
    source = source or default_source(code)
    source_api(code, source)  # Reject unknown game/source combinations.
    if source == "akedata":
        kind = (
            "character"
            if title.startswith("chr_")
            else "weapon"
            if title.startswith("wpn_")
            else "item"
        )
        return "https://www.akedata.wiki/?" + urlencode({"plugin": kind, "id": title})
    base = (
        "https://prts.wiki/w/"
        if source == "prts"
        else f"https://wiki.biligame.com/{code}/"
    )
    url = base + quote(title, safe="/")
    return url + ("#" + quote(anchor, safe="") if anchor else "")


@dataclass
class Section:
    title: str
    anchor: str
    blocks: list[str] = field(default_factory=list)


@dataclass
class Page:
    title: str
    page_id: int
    revision_id: int
    fetched_at: str
    sections: list[Section]
    related: list[dict] = field(default_factory=list)
    noise: dict = field(default_factory=dict)
    image_url: str = ""
