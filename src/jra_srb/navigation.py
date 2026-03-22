from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from bs4 import BeautifulSoup

from .provider import PageContent


COURSE_NAMES = {
    "sapporo": "札幌",
    "hakodate": "函館",
    "fukushima": "福島",
    "niigata": "新潟",
    "tokyo": "東京",
    "nakayama": "中山",
    "chukyo": "中京",
    "kyoto": "京都",
    "hanshin": "阪神",
    "kokura": "小倉",
}

KIND_PREFIXES = {
    "card": "pw01drl",
    "odds": "pw15orl",
    "result": "pw01srl",
    "payout": "pw01hde",
}


@dataclass(frozen=True)
class ResolvedTransition:
    label: str
    cname: str


class JraNavigation:
    def resolve_meeting_from_selection(
        self,
        page: PageContent,
        target_date: date,
        course: str,
        kind: str,
    ) -> ResolvedTransition:
        prefix = KIND_PREFIXES[kind]
        course_name = COURSE_NAMES[course]
        target_day = target_date.strftime("%Y%m%d")
        soup = BeautifulSoup(page.content, "html.parser")

        for link in soup.select("a[onclick*='doAction']"):
            onclick = link.get("onclick", "")
            text = self._normalize_label(link.get_text(" ", strip=True))
            match = re.search(r"doAction\(\s*'[^']+'\s*,\s*'([^']+)'", onclick)
            if match is None:
                continue
            cname = match.group(1)
            if prefix in cname and course_name in text and target_day in cname:
                return ResolvedTransition(label=text, cname=cname)

        raise LookupError(f"meeting not found for course={course} date={target_date} kind={kind}")

    @staticmethod
    def _normalize_label(text: str) -> str:
        return text.replace(" 馬番確定", "").strip()
