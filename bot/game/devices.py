"""Кейс «Телефоны»: 50 популярных моделей с розничными ценами в рублях (как в магазинах РФ),
ступень по цене. Коллекционные телефоны — Мифические и Секретный: их цена — цена у коллекционеров.

Внутри ступени модель выбирается по весу (weight), по умолчанию 1: так Nokia 3310 — самый
редкий из Мифических. Шансы ступеней кейса — в settings.DEFAULTS["device_cases"], возврат ≈80%.
"""
import random
from dataclasses import dataclass

from bot.game.tiers import COMMON, EPIC, LEGENDARY, MYTHIC, RARE, SECRET, UNCOMMON


@dataclass(frozen=True)
class Model:
    key: str
    brand: str
    name: str
    year: int
    price_rub: int
    tier: int
    form: str = "smart"   # smart | keypad | flip | fold — силуэт на карточке
    weight: float = 1.0
    note: str = ""


M = Model
MODELS: list[Model] = [
    # Обычные: до 12 000 ₽
    M("nokia105", "Nokia", "105 (2023)", 2023, 1_990, COMMON, "keypad"),
    M("itel_a70", "itel", "A70", 2024, 6_490, COMMON),
    M("infinix_smart8", "Infinix", "Smart 8", 2024, 7_490, COMMON),
    M("tecno_spark_go", "Tecno", "Spark Go 2024", 2024, 7_990, COMMON),
    M("redmi_a3", "Xiaomi", "Redmi A3", 2024, 7_990, COMMON),
    M("galaxy_a05", "Samsung", "Galaxy A05", 2023, 9_990, COMMON),
    M("realme_c61", "realme", "C61", 2024, 9_990, COMMON),
    M("honor_x5plus", "Honor", "X5 Plus", 2023, 9_990, COMMON),
    M("poco_c65", "POCO", "C65", 2024, 10_990, COMMON),
    M("nokia_g22", "Nokia", "G22", 2023, 11_490, COMMON),
    # Необычные: 12 000–25 000 ₽
    M("redmi13", "Xiaomi", "Redmi 13", 2024, 12_990, UNCOMMON),
    M("galaxy_a15", "Samsung", "Galaxy A15", 2023, 14_990, UNCOMMON),
    M("honor_x7b", "Honor", "X7b", 2024, 15_990, UNCOMMON),
    M("tecno_pova6", "Tecno", "Pova 6", 2024, 16_990, UNCOMMON),
    M("redmi_note13", "Xiaomi", "Redmi Note 13", 2024, 17_990, UNCOMMON),
    M("realme12", "realme", "12", 2024, 19_990, UNCOMMON),
    M("galaxy_a25", "Samsung", "Galaxy A25", 2023, 21_990, UNCOMMON),
    M("infinix_note40pro", "Infinix", "Note 40 Pro", 2024, 22_990, UNCOMMON),
    M("poco_x6", "POCO", "X6", 2024, 24_990, UNCOMMON),
    # Редкие: 25 000–55 000 ₽
    M("galaxy_a35", "Samsung", "Galaxy A35", 2024, 32_990, RARE),
    M("nothing2a", "Nothing", "Phone (2a)", 2024, 32_990, RARE),
    M("redmi_note13proplus", "Xiaomi", "Redmi Note 13 Pro+", 2024, 34_990, RARE),
    M("poco_f6", "POCO", "F6", 2024, 36_990, RARE),
    M("iphone11", "Apple", "iPhone 11", 2019, 39_990, RARE),
    M("galaxy_a55", "Samsung", "Galaxy A55", 2024, 39_990, RARE),
    M("oneplus_nord4", "OnePlus", "Nord 4", 2024, 41_990, RARE),
    M("honor200", "Honor", "200", 2024, 42_990, RARE),
    M("pixel8a", "Google", "Pixel 8a", 2024, 44_990, RARE),
    M("iphone13", "Apple", "iPhone 13", 2021, 54_990, RARE),
    # Эпические: 55 000–100 000 ₽
    M("galaxy_s24fe", "Samsung", "Galaxy S24 FE", 2024, 59_990, EPIC),
    M("galaxy_s24", "Samsung", "Galaxy S24", 2024, 69_990, EPIC),
    M("xiaomi14", "Xiaomi", "14", 2024, 69_990, EPIC),
    M("oneplus12", "OnePlus", "12", 2024, 69_990, EPIC),
    M("iphone15", "Apple", "iPhone 15", 2023, 74_990, EPIC),
    M("pixel9", "Google", "Pixel 9", 2024, 79_990, EPIC),
    M("huawei_pura70", "Huawei", "Pura 70", 2024, 79_990, EPIC),
    M("nothing3", "Nothing", "Phone (3)", 2025, 79_990, EPIC),
    M("iphone16", "Apple", "iPhone 16", 2024, 84_990, EPIC),
    M("galaxy_zflip6", "Samsung", "Galaxy Z Flip6", 2024, 89_990, EPIC, "flip"),
    # Легендарные: 100 000–200 000 ₽
    M("xiaomi14ultra", "Xiaomi", "14 Ultra", 2024, 109_990, LEGENDARY),
    M("iphone16pro", "Apple", "iPhone 16 Pro", 2024, 119_990, LEGENDARY),
    M("galaxy_s24ultra", "Samsung", "Galaxy S24 Ultra", 2024, 129_990, LEGENDARY),
    M("pixel9profold", "Google", "Pixel 9 Pro Fold", 2024, 169_990, LEGENDARY, "fold"),
    M("galaxy_zfold6", "Samsung", "Galaxy Z Fold6", 2024, 179_990, LEGENDARY, "fold"),
    M("huawei_matex5", "Huawei", "Mate X5", 2023, 189_990, LEGENDARY, "fold"),
    M("iphone16promax1tb", "Apple", "iPhone 16 Pro Max 1 ТБ", 2024, 199_990, LEGENDARY),
    # Мифические: коллекционные
    M("nokia8800", "Nokia", "8800 Sirocco", 2006, 350_000, MYTHIC, "keypad", 5, "коллекционный, стальной корпус"),
    M("vertu_signature", "Vertu", "Signature S", 2008, 900_000, MYTHIC, "keypad", 3, "сапфировое стекло, ручная сборка"),
    M("nokia3310", "Nokia", "3310", 2000, 2_000_000, MYTHIC, "keypad", 1, "легенда: «неубиваемый» и «Змейка»"),
    # Секретный
    M("iphone2g_sealed", "Apple", "iPhone 2G 4 ГБ, запечатанный", 2007, 15_000_000, SECRET, "smart", 1,
      "первый iPhone в заводской плёнке, лот аукциона"),
]

BY_KEY: dict[str, Model] = {m.key: m for m in MODELS}
assert len(BY_KEY) == len(MODELS) == 50


def tier_mean_cents(tier: int) -> float:
    ms = [m for m in MODELS if m.tier == tier]
    w = sum(m.weight for m in ms)
    return sum(m.price_rub * 100 * m.weight for m in ms) / w if w else 0.0


def case_return(odds: dict[int, float], price_cents: int) -> float:
    return sum(p * tier_mean_cents(t) for t, p in odds.items()) / price_cents


def pick_model(tier: int, rng: random.Random) -> Model:
    ms = [m for m in MODELS if m.tier == tier]
    x = rng.random() * sum(m.weight for m in ms)
    for m in ms:
        x -= m.weight
        if x < 0:
            return m
    return ms[-1]


def model_dict(m: Model) -> dict:
    return {"key": m.key, "brand": m.brand, "name": m.name, "year": m.year, "price_cents": m.price_rub * 100,
            "tier": m.tier, "form": m.form, "note": m.note}
