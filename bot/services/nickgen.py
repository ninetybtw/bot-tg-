"""Генератор идей для ников по темам."""
import random

from bot.services.fonts import random_style

THEMES: dict[str, dict] = {
    "game": {
        "title": "🎮 Игровые",
        "a": ["Dark", "Shadow", "Ghost", "Toxic", "Silent", "Mad", "Frost", "Night", "Cyber",
              "Iron", "Blood", "Storm", "Neon", "Wild", "Lucky", "Rage", "Void", "Hyper"],
        "b": ["Sniper", "Killer", "Wolf", "Reaper", "Hunter", "Ninja", "Demon", "Viper", "Rider",
              "Slayer", "Fox", "Dragon", "Joker", "Phantom", "Raven", "Blade", "Titan", "King"],
        "patterns": ["{a}{b}", "{a}_{b}", "xX{b}Xx", "{b}{n}", "{a}{b}{n}", "i{b}", "{b}Pro"],
    },
    "cute": {
        "title": "🌸 Милые",
        "a": ["Sweet", "Little", "Baby", "Soft", "Pink", "Honey", "Sugar", "Tiny", "Cozy",
              "Peachy", "Sunny", "Lovely", "Fluffy", "Bubble", "Candy"],
        "b": ["Bunny", "Kitty", "Cherry", "Mochi", "Panda", "Peach", "Bear", "Star", "Bun",
              "Cookie", "Muffin", "Daisy", "Berry", "Angel", "Cloud"],
        "patterns": ["{a}{b}", "{a}_{b}", "{b}ie", "{l}{b}", "{b}{n}", "its{b}", "{a}{b}xo"],
    },
    "dark": {
        "title": "🖤 Дерзкие",
        "a": ["Black", "Dead", "Cold", "Lost", "Broken", "Savage", "Evil", "Sad", "Wicked",
              "Grim", "Toxic", "Hollow", "Crazy", "Lonely", "Bad"],
        "b": ["Soul", "Heart", "Boy", "Girl", "Angel", "Devil", "Rose", "Smoke", "Crown",
              "Mask", "Moon", "Sin", "Ghost", "Vibe", "Queen"],
        "patterns": ["{a}{b}", "{a}_{b}", "{l}{a}{b}", "{b}666", "notyour{b}", "{a}.{b}"],
    },
    "aesthetic": {
        "title": "☁️ Эстетика",
        "a": ["lunar", "velvet", "misty", "dreamy", "golden", "pastel", "silent", "ocean",
              "cosmic", "faded", "hazy", "stardust", "vintage", "moonlit", "lavender"],
        "b": ["haze", "bloom", "petal", "wave", "glow", "aura", "dawn", "dusk", "echo", "rain",
              "sky", "mist", "light", "soul", "breeze"],
        "patterns": ["{a}{b}", "{a}.{b}", "{a}_{b}", "{b}{a}", "{l}{b}", "{a}{b}{s}"],
    },
    "ru": {
        "title": "🇷🇺 Русские",
        "a": ["Тёмный", "Злой", "Тихий", "Дикий", "Ночной", "Лунный", "Снежный", "Безумный",
              "Хитрый", "Ледяной", "Огненный", "Грустный", "Добрый", "Мятный", "Бархатный"],
        "b": ["Волк", "Кот", "Лис", "Призрак", "Ворон", "Тигр", "Демон", "Ангел", "Барон",
              "Шторм", "Ёж", "Медведь", "Самурай", "Дракон", "Странник"],
        "patterns": ["{a} {b}", "{a}_{b}", "{b}{n}", "{a}{b}", "Мистер {b}", "{b} {a}"],
    },
}


def _one(theme: dict) -> str:
    return random.choice(theme["patterns"]).format(
        a=random.choice(theme["a"]),
        b=random.choice(theme["b"]),
        n=random.choice(["", "7", "13", "69", "77", "99", "228", "666", "777", "2k",
                         str(random.randint(10, 99))]),
        l=random.choice(["the", "mr", "lil", "im", "x"]),
        s=random.choice(["", ".", "_", "x"]),
    )


def generate(theme_key: str, count: int = 8) -> list[tuple[str, str]]:
    """[(простой ник, стилизованный ник), ...]"""
    theme = THEMES[theme_key]
    seen: set[str] = set()
    result = []
    for _ in range(count * 5):
        nick = _one(theme)
        if nick in seen:
            continue
        seen.add(nick)
        result.append((nick, random_style(nick)))
        if len(result) == count:
            break
    return result
