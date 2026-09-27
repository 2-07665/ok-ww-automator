"""Parse echo substats without importing the game runtime or opening sockets."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
import unicodedata
from typing import Iterable, Protocol


BUFF_VALUE_OPTIONS = {
    "Crit_Rate": {63, 69, 75, 81, 87, 93, 99, 105},
    "Crit_Damage": {126, 138, 150, 162, 174, 186, 198, 210},
    "Attack": {64, 71, 79, 86, 94, 101, 109, 116},
    "Defence": {81, 90, 100, 109, 118, 128, 138, 147},
    "HP": {64, 71, 79, 86, 94, 101, 109, 116},
    "Attack_Flat": {30, 40, 50, 60},
    "Defence_Flat": {40, 50, 60, 70},
    "HP_Flat": {320, 360, 390, 430, 470, 510, 540, 580},
    "ER": {68, 76, 84, 92, 100, 108, 116, 124},
    "Basic_Attack_Damage": {64, 71, 79, 86, 94, 101, 109, 116},
    "Heavy_Attack_Damage": {64, 71, 79, 86, 94, 101, 109, 116},
    "Skill_Damage": {64, 71, 79, 86, 94, 101, 109, 116},
    "Ult_Damage": {64, 71, 79, 86, 94, 101, 109, 116},
}

# A comma is accepted only as a single decimal separator, not as a thousands separator.
VALUE_PATTERN = re.compile(r"\+?\d+(?:[.,]\d+)?%?")
ROW_PATTERN = re.compile(r"([^\d+%.,]+?)(\+?\d+(?:[.,]\d+)?%?)")


class TextBox(Protocol):
    name: str
    x: float
    y: float
    width: float
    height: float


def normalize_text(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", str(text)).split())


def to_buff_value(raw: str) -> int | None:
    text = normalize_text(raw)
    if not VALUE_PATTERN.fullmatch(text):
        return None
    # Flat values do not have a decimal or thousands separator in this protocol.
    percent = text.endswith("%")
    if not percent and ("." in text or "," in text):
        return None
    try:
        value = Decimal(text.rstrip("%").replace(",", ".")) * (10 if percent else 1)
    except InvalidOperation:
        return None
    # Never round an OCR error into a valid discrete stat tier.
    if value != value.to_integral_value():
        return None
    return int(value)


def to_buff_name(raw: str, raw_value: str) -> str | None:
    text = normalize_text(raw).rstrip(":：")
    percent = normalize_text(raw_value).endswith("%")
    # Damage names precede generic attack names (e.g. 普通攻击伤害加成).
    for labels, name in (
        (("暴击伤害",), "Crit_Damage"),
        (("暴击",), "Crit_Rate"),
        (("普攻", "普通攻击"), "Basic_Attack_Damage"),
        (("重击",), "Heavy_Attack_Damage"),
        (("技能",), "Skill_Damage"),
        (("解放",), "Ult_Damage"),
        (("效率",), "ER"),
    ):
        if any(label in text for label in labels):
            return name if percent else None
    for label, name in (("攻击", "Attack"), ("生命", "HP"), ("防御", "Defence")):
        if label in text:
            return name if percent else name + "_Flat"
    return None


def _entry(label: str, raw_value: str) -> dict | None:
    name = to_buff_name(label, raw_value)
    value = to_buff_value(raw_value)
    if name is None or value not in BUFF_VALUE_OPTIONS[name]:
        return None
    return {"buffName": name, "buffValue": value}


def parse_echo_stats(boxes: Iterable[TextBox]) -> list[dict]:
    """Pair valid values with labels by row geometry, allowing one-box rows too."""
    boxes = sorted(boxes, key=lambda b: (b.y + b.height / 2, b.x))
    values = [(index, box) for index, box in enumerate(boxes)
              if VALUE_PATTERN.fullmatch(normalize_text(box.name))]
    consumed: set[int] = set()
    entries: list[dict] = []
    names: set[str] = set()
    for box in boxes:
        text = normalize_text(box.name)
        value_index = None
        joined = ROW_PATTERN.fullmatch(text)
        if joined:
            entry = _entry(*joined.groups())
        else:
            if any(char.isdigit() for char in text):
                continue
            candidates = []
            for index, value in values:
                if index in consumed or value.x < box.x + box.width:
                    continue
                delta = abs(box.y + box.height / 2 - value.y - value.height / 2)
                tolerance = max(1.0, min(box.height, value.height) * 0.6)
                if delta <= tolerance and (entry := _entry(text, value.name)):
                    candidates.append((delta, value.x - box.x, index, entry))
            if not candidates:
                continue
            _, _, value_index, entry = min(candidates, key=lambda c: c[:3])
        if entry is None or entry["buffName"] in names:
            continue
        if value_index is not None:
            consumed.add(value_index)
        names.add(entry["buffName"])
        entries.append(entry)
        if len(entries) == 5:
            break
    return entries
