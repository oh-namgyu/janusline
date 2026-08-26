"""Deterministic offline collector for demos and browser tests.

It builds the same RSS documents a Google News edition would return and hands
them to the real parser, so dedupe, the scheme guard and the period filter are
exercised for real — only the network is fake.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape, quoteattr

from .collect import GoogleNewsCollector

# title, source, link, days_ago (None = no pubDate), snippet
Entry = Tuple[str, str, str, Optional[int], str]

KO_ENTRIES: List[Entry] = [
    ("반도체 수출 3분기 연속 증가", "연합뉴스",
     "https://example.com/ko/exports-up?utm_source=news", 2,
     "<a href='#'>수출</a> 증가세가 이어지고 있다."),
    ("Factory fire halts production - Korea Herald", "Korea Herald",
     "https://example.com/ko/fire", 5,
     "생산 라인 일부가 멈췄다."),
    ("신규 파운드리 투자 발표", "매일경제",
     "https://example.com/ko/foundry-investment", 9,
     "대규모 설비 투자를 예고했다."),
    ("<script>alert('xss')</script> 주가 급등", "머니투데이",
     "https://example.com/ko/hostile-headline", 12,
     "제목에 스크립트가 섞인 기사."),
    ("법원, 하청 소송 심리 시작", "뉴시스",
     "javascript:alert(1)", 3,
     "스킴이 잘못된 링크는 기사째 버린다."),
    ("날짜 없는 속보", "뉴스1",
     "https://example.com/ko/no-date", None,
     "pubDate 가 없는 기사."),
]

EN_ENTRIES: List[Entry] = [
    ("Chip exports rise for a third quarter", "Reuters",
     "https://example.com/ko/exports-up?utm_campaign=en", 2,
     "Same story, different tracking parameters."),
    ("Regulator opens antitrust review", "Bloomberg",
     "https://example.com/en/antitrust", 4,
     "The watchdog wants documents by June."),
    ("Analysts raise price target after strong quarter", "Financial Times",
     "https://example.com/en/price-target", 7,
     "Two banks lifted their targets."),
    ("Factory fire halts production! - Korea Herald", "Korea Herald",
     "https://example.com/en/fire-duplicate", 5,
     "A punctuation-only variant of the other edition's headline."),
    ("Supplier dispute heads to arbitration", "Nikkei",
     "https://example.com/en/arbitration", 21,
     "Both sides confirmed the filing."),
    ("Old profile piece from two years ago", "Wired",
     "https://example.com/en/ancient", 730,
     "Outside every supported period window."),
]


def _item(entry: Entry, now: datetime) -> str:
    title, source, link, days_ago, snippet = entry
    parts = [
        f"    <title>{escape(title)}</title>",
        f"    <link>{escape(link)}</link>",
        f"    <guid isPermaLink=\"false\">{escape(link)}</guid>",
        f"    <description>{escape(snippet)}</description>",
        f"    <source url={quoteattr('https://example.com')}>{escape(source)}</source>",
    ]
    if days_ago is not None:
        stamp = format_datetime(now - timedelta(days=days_ago))
        parts.insert(3, f"    <pubDate>{stamp}</pubDate>")
    body = "\n".join(parts)
    return f"  <item>\n{body}\n  </item>"


def build_feed(query: str, entries: Sequence[Entry], now: datetime) -> str:
    items = "\n".join(_item(entry, now) for entry in entries)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n<channel>\n'
        f"  <title>{escape(query)} - janusline demo</title>\n"
        "  <link>https://example.com/</link>\n"
        f"{items}\n"
        "</channel>\n</rss>\n"
    )


class FakeCollector(GoogleNewsCollector):
    """Same pipeline, canned feeds. Enabled by JANUSLINE_FAKE=1.

    Publication dates are relative to the current time, so the fixtures stay
    inside the period window forever; everything else is fixed.
    """

    def fetch(self, url: str) -> bytes:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        entries = KO_ENTRIES if "hl=ko" in url else EN_ENTRIES
        return build_feed("janusline demo", entries, now).encode("utf-8")
