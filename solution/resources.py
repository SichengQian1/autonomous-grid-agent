from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re

from .rules import RESOURCE_ZONE_TYPES, ROUNDS_PER_DAY


_NAMES = {
    'iron': re.compile(r'\biron\b|铁矿|铁资源', re.I),
    'copper': re.compile(r'\bcopper\b|铜矿|铜资源', re.I),
    'stone': re.compile(r'\bstone\b|石矿|石料', re.I),
}
_STOP = re.compile(r'停工|停采|暂停(?:开采|采集)|停止(?:开采|采集)|无法(?:开采|采集)|不能(?:开采|采集)|\bsuspend(?:ed)?\b|\bclosed\b|\bunavailable\b', re.I)
_OPEN = re.compile(r'恢复(?:正常)?(?:开采|采集)|复工|复采|\breopen(?:ed|s)?\b|\bresum(?:e|ed|es)\b', re.I)
_RELATIVE = re.compile(r'day after tomorrow|大后天|后天|明天|明日|次日|今天|今日|当天|tomorrow|today', re.I)
_OFFSETS = {'today': 0, '今天': 0, '今日': 0, '当天': 0,
            'tomorrow': 1, '明天': 1, '明日': 1, '次日': 1,
            'day after tomorrow': 2, '后天': 2, '大后天': 3}
_NUMBERS = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
            '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
            'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}
_NUMBER_PATTERN = r'\d{1,2}|[一二两三四五六七八九十]|one|two|three|four|five'
_DURATION = re.compile(r'(?<![第0-9])(' + _NUMBER_PATTERN + r')\s*(?:天|days?\b)', re.I)
_EXPLICIT = re.compile(r'第(' + _NUMBER_PATTERN + r')天', re.I)
_NEGATION = re.compile(r'未|不会|并未|不能|无法|not\s+(?:be\s+)?|never\s+', re.I)


def _number(value: str) -> int:
    return int(value) if value.isdigit() else _NUMBERS[value.lower()]


def _positive_event(pattern: re.Pattern, text: str) -> re.Match | None:
    event = pattern.search(text)
    if event and not _NEGATION.search(text[max(0, event.start() - 8):event.start()]):
        return event
    return None


def _event_day(text: str, event_start: int, event_end: int, publication_day: int) -> tuple[int, list[int]]:
    # Only a nearby temporal phrase can qualify this event. A later reopening
    # phrase must not accidentally move the start of an earlier closure.
    before = [m for m in _RELATIVE.finditer(text[:event_start]) if event_start - m.end() <= 80]
    after_text = re.split(r'[。.;；]', text[event_end:])[0][:80]
    after_text = _OPEN.split(after_text)[0]
    after = list(_RELATIVE.finditer(after_text))
    explicit = list(_EXPLICIT.finditer(text[:event_start]))
    if explicit and event_start - explicit[-1].end() <= 40:
        day = _number(explicit[-1].group(1))
    elif before:
        day = publication_day + _OFFSETS[before[-1].group().lower()]
    elif after:
        day = publication_day + _OFFSETS[after[0].group().lower()]
    else:
        day = publication_day
    end_days = [publication_day + _OFFSETS[m.group().lower()] for m in after]
    return day, end_days


@dataclass(frozen=True, slots=True)
class MiningWindow:
    starts: int
    ends: int | None


@dataclass(slots=True)
class MiningCalendar:
    windows: dict[str, list[MiningWindow]] = field(default_factory=dict)
    seen: set[str] = field(default_factory=set)

    def available(self, mineral: str, round_no: int) -> bool:
        return not any(w.starts <= round_no and (w.ends is None or round_no <= w.ends)
                       for w in self.windows.get(mineral, ()))

    def close(self, mineral: str, starts: int, ends: int | None) -> None:
        window = MiningWindow(starts, ends)
        entries = self.windows.setdefault(mineral, [])
        if window not in entries:
            entries.append(window)

    def reopen(self, mineral: str, starts: int) -> None:
        self.windows[mineral] = [MiningWindow(w.starts, min(w.ends or 1300, starts - 1))
                                for w in self.windows.get(mineral, ()) if w.starts < starts]

    def observe(self, round_no: int, news: str) -> None:
        if not news:
            return
        news = news[:16000]
        digest = hashlib.sha256(news.encode()).hexdigest()
        if digest in self.seen:
            return
        self.seen.add(digest)
        publication_day = (max(1, round_no) - 1) // ROUNDS_PER_DAY + 1
        # Keep a single-mineral narrative together, including later duration
        # estimates. Split mixed-mineral statements rather than borrowing dates.
        minerals = [name for name, pattern in _NAMES.items() if pattern.search(news)]
        chunks = [news] if len(minerals) <= 1 else re.split(r'[。;；，\n]', news)
        for text in chunks:
            ores = [name for name, pattern in _NAMES.items() if pattern.search(text)]
            if not ores:
                continue
            stop = _positive_event(_STOP, text)
            opened = _positive_event(_OPEN, text)
            if stop:
                day, last_days = _event_day(text, stop.start(), stop.end(), publication_day)
                duration = _DURATION.search(text[stop.end():]) or _DURATION.search(text[:stop.start()])
                # Unknown end remains closed until an explicit reopening or a
                # validated structured interpretation supplies the missing bound.
                end_day = day + _number(duration.group(1)) - 1 if duration else (max(last_days) if last_days else None)
                for ore in ores:
                    self.close(ore, (day - 1) * ROUNDS_PER_DAY + 1,
                               end_day * ROUNDS_PER_DAY if end_day is not None else None)
            if opened and (stop is None or _RELATIVE.search(text[stop.end():opened.start()])
                           or _EXPLICIT.search(text[stop.end():opened.start()])):
                day, _ = _event_day(text, opened.start(), opened.end(), publication_day)
                for ore in ores:
                    self.reopen(ore, (day - 1) * ROUNDS_PER_DAY + 1)

    def apply_structured(self, data: object, history: list[tuple[int, str]]) -> None:
        if not isinstance(data, list) or len(data) > 12:
            return
        for event in data:
            if not isinstance(event, dict):
                continue
            ore, starts, ends = event.get('resource'), event.get('startsRound'), event.get('endsRound')
            evidence, status = event.get('evidence'), event.get('status')
            confidence = event.get('confidence')
            if (not isinstance(ore, str) or ore not in RESOURCE_ZONE_TYPES or type(starts) is not int or not 1 <= starts <= 1300
                    or type(confidence) not in (float, int) or not .9 <= confidence <= 1
                    or not isinstance(evidence, str) or len(evidence) < 8 or not _NAMES[ore].search(evidence)
                    or not any(evidence in text for _, text in history)):
                continue
            if status == 'open' and _positive_event(_OPEN, evidence):
                self.reopen(ore, starts)
            elif status == 'closed' and _positive_event(_STOP, evidence) and type(ends) is int and starts <= ends <= 1300:
                # Refine a conservative interval with the same start, rather than
                # leaving its previous unknown end in force forever.
                self.windows[ore] = [w for w in self.windows.get(ore, ()) if w.starts != starts]
                self.close(ore, starts, ends)
