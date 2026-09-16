"""Explicit price-window evidence. Live shop prices always win for current trades."""
from __future__ import annotations

import re
import math
from dataclasses import dataclass, field

from .rules import RESOURCE_ZONE_TYPES


@dataclass(frozen=True, slots=True)
class PriceWindow:
    ore: str
    start_day: int
    end_day: int
    price: int | None = None
    closed: bool = False
    rising: bool = False


@dataclass(slots=True)
class MarketMemory:
    windows: list[PriceWindow] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)

    def observe(self, text: str, day: int) -> None:
        if not text or text in self.seen:
            return
        self.seen.add(text)
        if len(self.seen) > 40:
            self.seen = {text}
        aliases = {"stone": r"stone|石[矿头]", "iron": r"iron|铁", "copper": r"copper|铜"}
        numerals = {c:str(i) for i,c in enumerate("一二三四五六七八九十",1)}
        text = re.sub(r"第([一二三四五六七八九十])[天日]",lambda m:"第"+numerals[m[1]]+"天",text)
        for sentence in re.split(r"[。；;\n]", text[:8000]):
            ores = [ore for ore, pattern in aliases.items() if re.search(pattern, sentence, re.I)]
            if len(ores) != 1:
                continue
            span = re.search(r"第\s*(\d+)\s*[天日]\s*(?:至|到|[-~—])\s*第?\s*(\d+)\s*[天日]", sentence)
            span = span or re.search(r"days?\s+(\d+)\s*[-–~]\s*(\d+)", sentence, re.I)
            one = re.search(r"第\s*(\d+)\s*[天日]|day\s+(\d+)\b", sentence, re.I)
            if span:
                start, end = map(int, span.groups())
            elif "明天" in sentence or "明日" in sentence or re.search(r"\btomorrow\b", sentence, re.I):
                start = end = day + 1
            elif one:
                start = end = int(one[1] or one[2])
            else:
                continue
            duration = re.search(r"(?:持续|为期|维持|lasting|for)\s*(\d+|[一二三四五六七八九十])\s*(?:天|days?)", sentence,re.I)
            if duration and not span:
                days = int(numerals.get(duration[1],duration[1]))
                end = start+days-1
            price_match = re.search(r"(?:价格|售价|卖价|收购价|price)\s*(?:调整为|提高到|涨至|降至|为|[:=]|to|is)?\s*(\d+)(?![\d.])", sentence, re.I)
            closed = bool(re.search(r"关闭|封闭|停采|暂停开采|禁止采集|\bclosed\b", sentence, re.I))
            rising = bool(re.search(r"涨价|上涨|上调|走高|\brise\b|\bincrease\b",sentence,re.I))
            if re.search(r"不会|不再|取消|可能|或许|might|may",sentence,re.I):
                continue
            if not (1 <= start <= end <= 10) or (not price_match and not closed and not rising):
                continue
            price = int(price_match[1]) if price_match else None
            if price is not None and not 0 < price < 10000:
                continue
            previous = next((w for w in self.windows if w.ore == ores[0] and w.start_day == start and w.end_day == end),None)
            window = PriceWindow(ores[0], start, end, price if price is not None else previous.price if previous else None,
                                 closed or bool(previous and previous.closed),rising or bool(previous and previous.rising))
            self.windows = [w for w in self.windows if not (w.ore == window.ore and w.start_day == start and w.end_day == end)]
            self.windows.append(window)
        self.windows = [w for w in self.windows[-40:] if w.end_day >= day]

    def closed(self, ore: str, day: int) -> bool:
        return any(w.ore == ore and w.closed and w.start_day <= day <= w.end_day for w in self.windows)

    def expected_price(self, ore: str, current: int, day: int, *, can_wait: bool) -> int:
        if ore not in RESOURCE_ZONE_TYPES or not can_wait:
            return current
        return max([current] + [w.price for w in self.windows if w.ore == ore and w.price is not None
                                and day < w.start_day <= day + 1])

    def will_rise(self, ore: str, day: int) -> bool:
        return any(w.ore == ore and w.rising and day < w.start_day <= day+1 for w in self.windows)

    def ingest_interpretation(self, data: object, source: str, source_day: int) -> None:
        """Narrative news needs interpretation; require a real source span and bounded dates.

        Interpreted windows affect planning only. They never replace live prices
        in sale valuation, budgets or purchase affordability.
        """
        if not isinstance(data,list) or not source:
            return
        names = {"iron":("iron","铁"),"copper":("copper","铜"),"stone":("stone","石")}
        for entry in data[:6]:
            if not isinstance(entry,dict): continue
            ore=entry.get("ore"); quote=entry.get("evidence")
            if not isinstance(ore,str) or ore not in names or not isinstance(quote,str) or not 8<=len(quote)<=500 or quote not in source:
                continue
            if not any(name in source.lower() for name in names[ore]): continue
            start,end=entry.get("start_day"),entry.get("end_day")
            confidence=entry.get("confidence")
            if type(start) is not int or type(end) is not int or not source_day<=start<=end<=min(10,source_day+4): continue
            if not isinstance(confidence,(int,float)) or not math.isfinite(confidence) or confidence<0.95: continue
            closed,rising=entry.get("closed") is True,entry.get("rising") is True
            price=entry.get("price")
            # Exact price forecasts need the literal number in the cited text.
            if type(price) is not int or not 0<price<10000 or str(price) not in quote: price=None
            if not (closed or rising or price): continue
            self.windows=[w for w in self.windows if not(w.ore==ore and w.start_day==start and w.end_day==end)]
            self.windows.append(PriceWindow(ore,start,end,price,closed,rising))
        self.windows=self.windows[-40:]
