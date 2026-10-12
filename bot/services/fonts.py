"""Превращает текст в «красивые» ники: юникод-шрифты, диакритика и украшения."""
import random
from string import ascii_lowercase, ascii_uppercase, digits


def _offset_table(upper: int, lower: int, digit: int | None = None,
                  exceptions: dict[str, str] | None = None) -> dict[int, str]:
    table = {ord(c): chr(upper + i) for i, c in enumerate(ascii_uppercase)}
    table.update({ord(c): chr(lower + i) for i, c in enumerate(ascii_lowercase)})
    if digit is not None:
        table.update({ord(c): chr(digit + i) for i, c in enumerate(digits)})
    for src, dst in (exceptions or {}).items():
        table[ord(src)] = dst
    return table


def _letters_table(lower_letters: str) -> dict[int, str]:
    table = {ord(c): lower_letters[i] for i, c in enumerate(ascii_lowercase)}
    table.update({ord(c): lower_letters[i] for i, c in enumerate(ascii_uppercase)})
    return table


# Латинские шрифты (кириллица в них остаётся как есть)
FONTS: dict[str, dict[int, str]] = {
    "Жирный": _offset_table(0x1D400, 0x1D41A, 0x1D7CE),
    "Курсив": _offset_table(0x1D434, 0x1D44E, exceptions={"h": "ℎ"}),
    "Жирный курсив": _offset_table(0x1D468, 0x1D482),
    "Рукописный": _offset_table(0x1D4D0, 0x1D4EA),
    "Готика": _offset_table(0x1D56C, 0x1D586),
    "Двойной": _offset_table(0x1D538, 0x1D552, 0x1D7D8, exceptions={
        "C": "ℂ", "H": "ℍ", "N": "ℕ", "P": "ℙ", "Q": "ℚ", "R": "ℝ", "Z": "ℤ"}),
    "Гротеск": _offset_table(0x1D5D4, 0x1D5EE, 0x1D7EC),
    "Гротеск курсив": _offset_table(0x1D63C, 0x1D656),
    "Моно": _offset_table(0x1D670, 0x1D68A, 0x1D7F6),
    "Широкий": _offset_table(0xFF21, 0xFF41, 0xFF10),
    "Кружки": _offset_table(0x24B6, 0x24D0),
    "Квадраты": _offset_table(0x1F130, 0x1F130),
    "Чёрные квадраты": _offset_table(0x1F170, 0x1F170),
    "Капитель": _letters_table("ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ"),
}

_UPSIDE = _letters_table("ɐqɔpǝɟƃɥᴉɾʞlɯuodbɹsʇnʌʍxʎz")

# Работают с любым алфавитом, в том числе с кириллицей
COMBINING = {
    "Зачёркнутый": "̶",
    "Подчёркнутый": "̲",
    "Косая черта": "̷",
    "Двойная черта": "̳",
    "Искры": "҉",
}

DECORATIONS = [
    "꧁༺ {} ༻꧂", "★彡 {} 彡★", "『{}』", "【{}】", "•°•{}•°•", "ıllıllı {} ıllıllı",
    "▄︻デ{}══━一", "×͜× {} ×͜×", "⚡{}⚡", "♡ {} ♡", "𓆩{}𓆪", "✿ {} ✿", "亗 {} 亗",
    "メ{}メ", "☾ {} ☽", "⋆｡°✩ {} ✩°｡⋆", "▓▒░ {} ░▒▓", "ꗃ {} ꗃ", "†{}†", "◥꧁{}꧂◤",
    "𝕏 {} 𝕏", "°•.✦ {} ✦.•°", "─═≡ {} ≡═─", "➳ {} ❥",
]


def has_latin(text: str) -> bool:
    return any(c in ascii_lowercase or c in ascii_uppercase for c in text)


def apply_font(text: str, name: str) -> str:
    return text.translate(FONTS[name])


def apply_combining(text: str, mark: str) -> str:
    return "".join(c if c.isspace() else c + mark for c in text)


def upside_down(text: str) -> str:
    return text.translate(_UPSIDE)[::-1]


def decorate(text: str, template: str | None = None) -> str:
    return (template or random.choice(DECORATIONS)).format(text)


def stylize(text: str) -> list[tuple[str, str]]:
    """Все варианты оформления: [(название стиля, результат), ...]."""
    out: list[tuple[str, str]] = []
    latin = has_latin(text)
    if latin:
        out += [(name, apply_font(text, name)) for name in FONTS]
        out.append(("Вверх ногами", upside_down(text)))
    out += [(name, apply_combining(text, mark)) for name, mark in COMBINING.items()]
    out.append(("Разрядка", " ".join(text)))

    fonts = list(FONTS)
    for template in random.sample(DECORATIONS, 12):
        base = apply_font(text, random.choice(fonts)) if latin and random.random() < 0.5 else text
        out.append(("Украшение", template.format(base)))
    return out


def random_style(text: str) -> str:
    """Один случайный стиль — для генератора ников."""
    roll = random.random()
    if has_latin(text) and roll < 0.45:
        styled = apply_font(text, random.choice(list(FONTS)))
    else:
        styled = text
    if roll > 0.3:
        styled = decorate(styled)
    return styled
