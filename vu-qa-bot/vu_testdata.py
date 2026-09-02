#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генератор синтетического датасета ВУ (ТЗ v2.0).

Производит СТРУКТУРИРОВАННЫЕ ЗАПИСИ ПОЛЕЙ (JSON), а не изображения документов.
Каждая запись без исключений помечена как синтетическая:
  * synthetic: true
  * серия из диапазона 00XX (не соответствует ни одному коду региона ГИБДД),
    предикат is_synthetic(series) истинен для всех записей;
  * поля разметки expected_valid / broken_rule / identity_source.
Эти признаки — часть контракта датасета (ТЗ §1.2, критерий приёмки 5).

CLI:
    python vu_testdata.py --valid 500 --mutated 1100 --seed 7 -o dataset.jsonl
    python vu_testdata.py --valid 10 --identity "ЩЕРБАКОВ ДМИТРИЙ ВАЛЕНТИНОВИЧ 14.03.1988"
"""
from __future__ import annotations

import argparse
import json
import random
import re
import secrets
import sys
from dataclasses import dataclass, asdict, field
from datetime import date, timedelta
from typing import Callable, Iterable

# ────────────────────────────── транслитерация (§4.2) ──────────────────────────────

TRANSLIT_MAP = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "E",
    "Ж": "ZH", "З": "Z", "И": "I", "Й": "I", "К": "K", "Л": "L", "М": "M",
    "Н": "N", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U",
    "Ф": "F", "Х": "KH", "Ц": "TS", "Ч": "CH", "Ш": "SH", "Щ": "SHCH",
    "Ъ": "", "Ы": "Y", "Ь": "", "Э": "E", "Ю": "IU", "Я": "IA",
}
# Наивная («поддельная») таблица для мутатора translit_mismatch (§5, R01)
NAIVE_MAP = dict(TRANSLIT_MAP, **{"Х": "H", "Я": "YA", "Ю": "YU", "Й": "Y", "Щ": "SCH", "Ц": "C"})


def _translit_with(table: dict, s: str) -> str:
    out = []
    for ch in s.upper():
        if ch in table:
            out.append(table[ch])
        elif ch in " -.()":
            out.append(ch)
        else:
            out.append(ch)
    return "".join(out)


def translit(s: str) -> str:
    """Транслитерация по приказу МВД / ИКАО Doc 9303."""
    return _translit_with(TRANSLIT_MAP, s)


def naive_translit(s: str) -> str:
    """Типовая ошибка подделки: KH→H, IA→YA, Й→Y."""
    return _translit_with(NAIVE_MAP, s)


# ────────────────────────────── категории (§4.5) ──────────────────────────────

ALL_CATEGORIES = ["A", "A1", "B", "B1", "C", "C1", "D", "D1",
                  "BE", "CE", "C1E", "DE", "D1E", "M", "Tm", "Tb"]

MIN_AGE = {
    "M": 16, "A1": 16,
    "A": 18, "B": 18, "B1": 18, "C": 18, "C1": 18,
    "BE": 19, "C1E": 19, "CE": 19,
    "D": 21, "D1": 21, "Tm": 21, "Tb": 21,
    "DE": 22, "D1E": 22,
}

IMPLIES = {
    "B": ["B1", "M"], "A": ["M"], "A1": ["M"],
    "C": ["C1", "M"], "D": ["D1", "M"],
    "BE": ["B", "B1", "M"], "CE": ["C", "C1", "M"], "C1E": ["C1", "M"],
    "DE": ["D", "D1", "M"], "D1E": ["D1", "M"],
    "B1": ["M"], "C1": ["M"], "D1": ["M"], "Tm": ["M"], "Tb": ["M"],
}

BASE_SETS = [
    (["B"], 45), (["B", "C"], 12), (["A", "B"], 12), (["B", "BE"], 8),
    (["D"], 5), (["B", "C", "CE"], 5), (["A"], 4), (["B", "C", "D"], 3),
    (["A1", "B"], 3), (["B", "C1"], 3),
]

RESTRICTION_CODES = ["AT", "AS", "MS", "ГБО"]


def closure(cats: Iterable[str]) -> set[str]:
    """Транзитивное замыкание набора категорий по таблице зависимостей."""
    out = set(cats)
    changed = True
    while changed:
        changed = False
        for c in list(out):
            for dep in IMPLIES.get(c, []):
                if dep not in out:
                    out.add(dep)
                    changed = True
    return out


def prune_by_age(cats: set[str], age: int) -> set[str]:
    """Отфильтровать по возрасту и повторно проверить замыкание (§4.5)."""
    out = {c for c in cats if MIN_AGE.get(c, 99) <= age}
    changed = True
    while changed:
        changed = False
        for c in list(out):
            for dep in IMPLIES.get(c, []):
                if dep not in out:      # зависимость отпала по возрасту — убираем зависящую
                    out.discard(c)
                    changed = True
                    break
    return out


def sort_categories(cats: Iterable[str]) -> list[str]:
    order = {c: i for i, c in enumerate(ALL_CATEGORIES)}
    return sorted(set(cats), key=lambda c: (order.get(c, 999), c))


# ────────────────────────────── справочники (§4.6) ──────────────────────────────

REGIONS = {
    "01": "РЕСПУБЛИКА АДЫГЕЯ", "02": "РЕСПУБЛИКА БАШКОРТОСТАН", "03": "РЕСПУБЛИКА БУРЯТИЯ",
    "04": "РЕСПУБЛИКА АЛТАЙ", "05": "РЕСПУБЛИКА ДАГЕСТАН", "06": "РЕСПУБЛИКА ИНГУШЕТИЯ",
    "07": "КАБАРДИНО-БАЛКАРСКАЯ РЕСП.", "08": "РЕСПУБЛИКА КАЛМЫКИЯ",
    "09": "КАРАЧАЕВО-ЧЕРКЕССКАЯ РЕСП.", "10": "РЕСПУБЛИКА КАРЕЛИЯ", "11": "РЕСПУБЛИКА КОМИ",
    "12": "РЕСПУБЛИКА МАРИЙ ЭЛ", "13": "РЕСПУБЛИКА МОРДОВИЯ", "14": "РЕСПУБЛИКА САХА (ЯКУТИЯ)",
    "15": "РЕСП. СЕВЕРНАЯ ОСЕТИЯ-АЛАНИЯ", "16": "РЕСПУБЛИКА ТАТАРСТАН", "17": "РЕСПУБЛИКА ТЫВА",
    "18": "УДМУРТСКАЯ РЕСП.", "19": "РЕСПУБЛИКА ХАКАСИЯ", "21": "ЧУВАШСКАЯ РЕСП.",
    "22": "АЛТАЙСКИЙ КР.", "23": "КРАСНОДАРСКИЙ КР.", "24": "КРАСНОЯРСКИЙ КР.",
    "25": "ПРИМОРСКИЙ КР.", "26": "СТАВРОПОЛЬСКИЙ КР.", "27": "ХАБАРОВСКИЙ КР.",
    "28": "АМУРСКАЯ ОБЛ.", "29": "АРХАНГЕЛЬСКАЯ ОБЛ.", "30": "АСТРАХАНСКАЯ ОБЛ.",
    "31": "БЕЛГОРОДСКАЯ ОБЛ.", "32": "БРЯНСКАЯ ОБЛ.", "33": "ВЛАДИМИРСКАЯ ОБЛ.",
    "34": "ВОЛГОГРАДСКАЯ ОБЛ.", "35": "ВОЛОГОДСКАЯ ОБЛ.", "36": "ВОРОНЕЖСКАЯ ОБЛ.",
    "37": "ИВАНОВСКАЯ ОБЛ.", "38": "ИРКУТСКАЯ ОБЛ.", "39": "КАЛИНИНГРАДСКАЯ ОБЛ.",
    "40": "КАЛУЖСКАЯ ОБЛ.", "41": "КАМЧАТСКИЙ КР.", "42": "КЕМЕРОВСКАЯ ОБЛ. - КУЗБАСС",
    "43": "КИРОВСКАЯ ОБЛ.", "44": "КОСТРОМСКАЯ ОБЛ.", "45": "КУРГАНСКАЯ ОБЛ.",
    "46": "КУРСКАЯ ОБЛ.", "47": "ЛЕНИНГРАДСКАЯ ОБЛ.", "48": "ЛИПЕЦКАЯ ОБЛ.",
    "49": "МАГАДАНСКАЯ ОБЛ.", "50": "МОСКОВСКАЯ ОБЛ.", "51": "МУРМАНСКАЯ ОБЛ.",
    "52": "НИЖЕГОРОДСКАЯ ОБЛ.", "53": "НОВГОРОДСКАЯ ОБЛ.", "54": "НОВОСИБИРСКАЯ ОБЛ.",
    "55": "ОМСКАЯ ОБЛ.", "56": "ОРЕНБУРГСКАЯ ОБЛ.", "57": "ОРЛОВСКАЯ ОБЛ.",
    "58": "ПЕНЗЕНСКАЯ ОБЛ.", "59": "ПЕРМСКИЙ КР.", "60": "ПСКОВСКАЯ ОБЛ.",
    "61": "РОСТОВСКАЯ ОБЛ.", "62": "РЯЗАНСКАЯ ОБЛ.", "63": "САМАРСКАЯ ОБЛ.",
    "64": "САРАТОВСКАЯ ОБЛ.", "65": "САХАЛИНСКАЯ ОБЛ.", "66": "СВЕРДЛОВСКАЯ ОБЛ.",
    "67": "СМОЛЕНСКАЯ ОБЛ.", "68": "ТАМБОВСКАЯ ОБЛ.", "69": "ТВЕРСКАЯ ОБЛ.",
    "70": "ТОМСКАЯ ОБЛ.", "71": "ТУЛЬСКАЯ ОБЛ.", "72": "ТЮМЕНСКАЯ ОБЛ.",
    "73": "УЛЬЯНОВСКАЯ ОБЛ.", "74": "ЧЕЛЯБИНСКАЯ ОБЛ.", "75": "ЗАБАЙКАЛЬСКИЙ КР.",
    "76": "ЯРОСЛАВСКАЯ ОБЛ.", "77": "Г. МОСКВА", "78": "Г. САНКТ-ПЕТЕРБУРГ",
    "79": "ЕВРЕЙСКАЯ АОБЛ.", "82": "РЕСПУБЛИКА КРЫМ", "83": "НЕНЕЦКИЙ АО",
    "86": "ХАНТЫ-МАНСИЙСКИЙ АО - ЮГРА", "87": "ЧУКОТСКИЙ АО", "89": "ЯМАЛО-НЕНЕЦКИЙ АО",
    "92": "Г. СЕВАСТОПОЛЬ", "95": "ЧЕЧЕНСКАЯ РЕСП.",
}

# Коды, отсутствующие в справочнике — для мутатора invalid_authority_region (R07)
INVALID_REGION_CODES = [f"{i:02d}" for i in range(100) if f"{i:02d}" not in REGIONS]

BIRTH_PLACES = [
    "Г. МОСКВА", "Г. САНКТ-ПЕТЕРБУРГ", "Г. ЩЁЛКОВО", "Г. ЮЖНО-САХАЛИНСК",
    "Г. ХАБАРОВСК", "Г. ЙОШКАР-ОЛА", "Г. ЖЕЛЕЗНОГОРСК", "Г. ЦИМЛЯНСК",
    "Г. ЧЕБОКСАРЫ", "Г. ШАХТЫ", "Г. ЭНГЕЛЬС", "Г. ЯКУТСК", "Г. ВЛАДИВОСТОК",
    "Г. НИЖНИЙ НОВГОРОД", "Г. РОСТОВ-НА-ДОНУ", "Г. НАБЕРЕЖНЫЕ ЧЕЛНЫ",
    "Г. СЕРГИЕВ ПОСАД", "Г. ПЕТРОПАВЛОВСК-КАМЧАТСКИЙ", "Г. ВЕЛИКИЙ НОВГОРОД",
    "П. ЧЁРНАЯ РЕЧКА", "С. ХОЛМОГОРЫ", "Г. ЮЖА", "Г. МЫТИЩИ", "Г. ТЫНДА",
]

# ────────────────────────────── даты ──────────────────────────────

def fmt_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def parse_date(s: str) -> date:
    d, m, y = s.split(".")
    return date(int(y), int(m), int(d))


def plus_years(d: date, years: int) -> date:
    """Сдвиг на N лет; 29 февраля переносится на 28-е (§4.4)."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def age_on(birth: date, when: date) -> int:
    return when.year - birth.year - ((when.month, when.day) < (birth.month, birth.day))


def effective_expiry(expiry: date) -> date:
    """Автопродление 2022–2025: +3 года (§4.10). Используется генератором и валидатором."""
    if date(2022, 1, 1) <= expiry <= date(2025, 12, 31):
        return plus_years(expiry, 3)
    return expiry


def is_synthetic(rec) -> bool:
    """
    Признак синтетики записи.

    До v2.1 маркер жил в серии (00XX — код, отсутствующий в справочнике ГИБДД).
    С v2.1 серия генерируется из реального кода региона (требование заказчика),
    поэтому маркер перенесён в метаполе `synthetic`, которого не существует
    в реальном потоке данных. Признак остаётся обязательным для всех записей.
    """
    if isinstance(rec, dict):
        return rec.get("synthetic") is True
    return getattr(rec, "synthetic", False) is True


# ────────────────────────────── личные данные (§2) ──────────────────────────────

RU_NAME_RE = re.compile(r"^[А-ЯЁ]+(?:-[А-ЯЁ]+)*$")


@dataclass
class Identity:
    """Личные данные: из профиля пользователя либо сгенерированные случайно."""
    surname: str
    name: str
    patronymic: str
    birth_date: str        # ДД.ММ.ГГГГ
    gender: str            # M | F
    source: str = "user"   # user | random

    @property
    def given(self) -> str:
        return f"{self.name} {self.patronymic}".strip()


class IdentityError(ValueError):
    """Ошибка разбора личных данных с текстом для пользователя."""


def gender_from(patronymic: str, surname: str) -> str:
    """Пол выводится из отчества, при его отсутствии — из окончания фамилии (§2.3)."""
    p = (patronymic or "").upper()
    if p.endswith(("ОВНА", "ЕВНА", "ИНИЧНА", "ИЧНА")):
        return "F"
    if p.endswith(("ОВИЧ", "ЕВИЧ", "ИЧ")):
        return "M"
    s = (surname or "").upper()
    return "F" if s.endswith(("А", "Я")) else "M"


def parse_identity(text: str, today: date | None = None) -> Identity:
    """
    Разбор строки «ФАМИЛИЯ ИМЯ [ОТЧЕСТВО] ДД.ММ.ГГГГ» (§2.1).
    Бросает IdentityError с человекочитаемым текстом.
    """
    today = today or date.today()
    tokens = (text or "").strip().split()
    if len(tokens) < 3:
        raise IdentityError("Нужно минимум: ФАМИЛИЯ ИМЯ ДД.ММ.ГГГГ")
    if len(tokens) > 4:
        raise IdentityError("Слишком много слов. Формат: ФАМИЛИЯ ИМЯ ОТЧЕСТВО ДД.ММ.ГГГГ")

    raw_date = tokens[-1]
    fio = [t.upper() for t in tokens[:-1]]

    if not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", raw_date):
        raise IdentityError(f"Дата «{raw_date}» не в формате ДД.ММ.ГГГГ")
    try:
        birth = parse_date(raw_date)
    except ValueError:
        raise IdentityError(f"Даты «{raw_date}» не существует")

    for token in fio:
        if not RU_NAME_RE.fullmatch(token):
            raise IdentityError(f"«{token}» — допустимы только русские буквы и дефис")

    age = age_on(birth, today)
    if age < 18:
        raise IdentityError(f"Возраст {age} лет — ВУ выдают с 18")
    if age > 100:
        raise IdentityError(f"Возраст {age} лет — проверь год рождения")

    surname, name = fio[0], fio[1]
    patronymic = fio[2] if len(fio) > 2 else ""
    return Identity(surname, name, patronymic, raw_date,
                    gender_from(patronymic, surname), source="user")


DEMO_IDENTITY_STR = "ТЕСТОВ ТЕСТ ТЕСТОВИЧ 01.01.1990"

# Место рождения (п. 3) задаётся пользователем: населённый пункт печатается на бланке
# в свободной форме, поэтому справочник — только быстрый выбор, а не ограничение.
PLACE_RE = re.compile(r"^[А-ЯЁ0-9 .()\-]{2,60}$")


def parse_place(text: str) -> str:
    """Нормализовать место рождения к бланочному виду. Бросает IdentityError."""
    place = " ".join((text or "").upper().split())
    if not place:
        raise IdentityError("Пустое место рождения")
    if len(place) > 60:
        raise IdentityError(f"Слишком длинно ({len(place)} симв., максимум 60)")
    if not PLACE_RE.fullmatch(place):
        raise IdentityError("Допустимы русские буквы, цифры, пробел, дефис, точка и скобки")
    if not any("А" <= ch <= "Я" or ch == "Ё" for ch in place):
        raise IdentityError("Нужна хотя бы одна русская буква")
    return place


DATE_TOKEN_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")


def parse_me(text: str, today: date | None = None) -> tuple[Identity, str | None]:
    """
    Единый разбор ввода команды /me: «ФАМИЛИЯ ИМЯ [ОТЧЕСТВО] ДД.ММ.ГГГГ [МЕСТО РОЖДЕНИЯ]».

    Дата служит разделителем: всё до неё — ФИО, всё после — место рождения
    (может отсутствовать → None, тогда место берётся случайным из справочника).
    """
    tokens = (text or "").strip().split()
    if not tokens:
        raise IdentityError("Пустой ввод")

    date_at = next((i for i, t in enumerate(tokens) if DATE_TOKEN_RE.fullmatch(t)), None)
    if date_at is None:
        raise IdentityError("Не нашёл дату рождения в формате ДД.ММ.ГГГГ")
    if date_at < 2:
        raise IdentityError("Перед датой нужны минимум ФАМИЛИЯ и ИМЯ")

    ident = parse_identity(" ".join(tokens[:date_at + 1]), today=today)
    tail = tokens[date_at + 1:]
    return ident, (parse_place(" ".join(tail)) if tail else None)


# ────────────────────────────── модель записи (§3) ──────────────────────────────

@dataclass
class LicenceRecord:
    surname_ru: str = ""
    surname_lat: str = ""
    given_ru: str = ""
    given_lat: str = ""
    birth_date: str = ""
    birth_place_ru: str = ""
    birth_place_lat: str = ""
    issue_date: str = ""
    expiry_date: str = ""
    authority: str = ""
    series: str = ""
    number: str = ""
    residence_ru: str = ""
    residence_lat: str = ""
    categories: list[str] = field(default_factory=list)
    back_table: dict[str, dict[str, str]] = field(default_factory=dict)
    back_number: str = ""
    special_marks: str = ""
    # разметка датасета — в реальном потоке таких полей не существует
    synthetic: bool = True
    expected_valid: bool = True
    broken_rule: str | None = None
    identity_source: str = "random"

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def new_rng(seed: int | None = None) -> random.Random:
    """Энтропия на каждый запрос (§6), либо детерминированный seed для CI."""
    return random.Random(seed if seed is not None else secrets.randbits(64))


# ────────────────────────────── генерация валидной записи (§4) ──────────────────────────────

def make_valid(rng: random.Random, identity: Identity,
               region_code: str | None = None,
               birth_place: str | None = None,
               valid_now: bool = False,
               today: date | None = None) -> LicenceRecord:
    """
    Валидная запись. Личные данные обязательны (§2): случайных ФИО больше нет.
    region_code — код подразделения ГИБДД; None → случайный из справочника.
    birth_place — место рождения (п. 3); None → случайное из справочника.
    valid_now   — выдача в пределах последних 10 лет, т.е. срок действия ещё НЕ истёк.
                  По умолчанию False: выдача равномерна на всём допустимом интервале,
                  поэтому большинство записей оказывается просроченными.
    """
    today = today or date.today()
    if identity is None:
        raise ValueError("identity обязателен: генерация без личных данных не поддерживается")
    if region_code is not None and region_code not in REGIONS:
        raise ValueError(f"код региона {region_code} отсутствует в справочнике")
    ident = identity
    birth = parse_date(ident.birth_date)

    # 4.4 — выдача в интервале [ДР+18 ; min(сегодня, ДР+60)], никогда не в будущем
    lo = plus_years(birth, 18)
    hi = min(today, plus_years(birth, 60))
    if valid_now:
        # чтобы срок (выдача+10) не истёк, выдача должна быть не раньше «сегодня минус 10 лет»
        lo = max(lo, plus_years(today, -10) + timedelta(days=1))
        hi = today
    if hi < lo:
        hi = lo
    issue = lo + timedelta(days=rng.randint(0, max((hi - lo).days, 0)))
    expiry = plus_years(issue, 10)
    age_at_issue = age_on(birth, issue)

    # 4.5 — категории
    base = rng.choices([b for b, _ in BASE_SETS], weights=[w for _, w in BASE_SETS])[0]
    cats = prune_by_age(closure(base), age_at_issue)
    cats.add("M")                                   # гарантируем M
    categories = sort_categories(cats)

    # 4.6 — подразделение и регион проживания
    auth_code = region_code or rng.choice(list(REGIONS))
    # в 85% случаев регион проживания совпадает с регионом выдачи, в 15% — нет
    res_code = auth_code if rng.random() < 0.85 else rng.choice(list(REGIONS))
    authority = f"ГИБДД {auth_code}{rng.randint(0, 99):02d}"
    residence_ru = REGIONS[res_code]
    # пустая/пробельная строка трактуется как «не задано» — так же, как None
    birth_place_ru = (parse_place(birth_place) if (birth_place or "").strip()
                      else rng.choice(BIRTH_PLACES))

    # 4.7 — серия и номер: первые две цифры серии — код региона подразделения
    series = f"{auth_code}{rng.randint(0, 99):02d}"
    number = f"{rng.randint(0, 999999):06d}"

    # 4.8 — оборотная таблица
    back: dict[str, dict[str, str]] = {}
    for cat in categories:
        open_d = issue
        if cat in ("A", "A1", "M") and rng.random() < 0.25:
            cand = plus_years(issue, -3)
            earliest = plus_years(birth, MIN_AGE.get(cat, 18))
            if cand >= earliest:
                open_d = cand
        restriction = rng.choice(RESTRICTION_CODES) if rng.random() < 0.12 else ""
        back[cat] = {"open": fmt_date(open_d), "expiry": fmt_date(expiry),
                     "restriction": restriction}

    # 4.9 — поле 14: год первого получения прав
    first_year = min(parse_date(r["open"]).year for r in back.values())

    return LicenceRecord(
        surname_ru=ident.surname, surname_lat=translit(ident.surname),
        given_ru=ident.given, given_lat=translit(ident.given),
        birth_date=ident.birth_date,
        birth_place_ru=birth_place_ru, birth_place_lat=translit(birth_place_ru),
        issue_date=fmt_date(issue), expiry_date=fmt_date(expiry),
        authority=authority, series=series, number=number,
        residence_ru=residence_ru, residence_lat=translit(residence_ru),
        categories=categories, back_table=back,
        back_number=f"{series} {number}",
        special_marks=f"СТАЖ С {first_year}",
        synthetic=True, expected_valid=True, broken_rule=None,
        identity_source=ident.source,
    )


# ────────────────────────────── мутаторы (§5) ──────────────────────────────

MUTATORS: dict[str, Callable[[random.Random, LicenceRecord], LicenceRecord]] = {}
MUTATOR_RULES: dict[str, str] = {}


def mutator(name: str, rule: str):
    """Регистрация мутатора: добавление нового не требует правок в других местах."""
    def deco(fn):
        MUTATORS[name] = fn
        MUTATOR_RULES[name] = rule
        return fn
    return deco


def _mark(rec: LicenceRecord, name: str) -> LicenceRecord:
    rec.expected_valid = False
    rec.broken_rule = name
    return rec


def _recalc_marks(rec: LicenceRecord) -> None:
    if rec.back_table:
        first = min(parse_date(r["open"]).year for r in rec.back_table.values())
        rec.special_marks = f"СТАЖ С {first}"


@mutator("translit_mismatch", "R01")
def m_translit(rng: random.Random, rec: LicenceRecord) -> LicenceRecord:
    pairs = [("surname_ru", "surname_lat"), ("given_ru", "given_lat"),
             ("birth_place_ru", "birth_place_lat"), ("residence_ru", "residence_lat")]
    cands = [(ru, lat) for ru, lat in pairs
             if naive_translit(getattr(rec, ru)) != getattr(rec, lat)]
    if cands:
        ru, lat = rng.choice(cands)
        setattr(rec, lat, naive_translit(getattr(rec, ru)))
    else:
        # ФИО без «сложных» букв — типовая ошибка V→W, гарантирует расхождение
        ru, lat = pairs[0]
        cur = getattr(rec, lat)
        setattr(rec, lat, cur.replace("V", "W", 1) if "V" in cur else cur + "X")
    return _mark(rec, "translit_mismatch")


@mutator("expiry_not_plus_10y", "R02")
def m_expiry(rng: random.Random, rec: LicenceRecord) -> LicenceRecord:
    issue = parse_date(rec.issue_date)
    wrong = plus_years(issue, rng.choice([5, 9, 11, 15]))
    rec.expiry_date = fmt_date(wrong)
    for row in rec.back_table.values():          # синхронно, чтобы не сломать второе правило
        row["expiry"] = rec.expiry_date
    return _mark(rec, "expiry_not_plus_10y")


@mutator("front_back_number_mismatch", "R03")
def m_number(rng: random.Random, rec: LicenceRecord) -> LicenceRecord:
    chars = list(rec.back_number)
    idxs = [i for i, c in enumerate(chars) if c.isdigit()]
    i = rng.choice(idxs)
    chars[i] = str((int(chars[i]) + 1) % 10)
    rec.back_number = "".join(chars)
    return _mark(rec, "front_back_number_mismatch")


@mutator("category_dependency_broken", "R04")
def m_dependency(rng: random.Random, rec: LicenceRecord) -> LicenceRecord:
    cats = set(rec.categories)
    # удалять только то, от чего зависит другая открытая категория (§5, критично)
    needed = {dep for c in cats for dep in IMPLIES.get(c, []) if dep in cats}
    if needed:
        victim = rng.choice(sorted(needed))
        cats.discard(victim)
        rec.categories = sort_categories(cats)
        rec.back_table.pop(victim, None)
        _recalc_marks(rec)
    else:
        # Фолбэк: категория без своей базовой. BE (порог 19 лет) годится не всегда —
        # у 18-летнего он сломал бы ещё и R06, и кейс перестал бы быть точечным.
        age = age_on(parse_date(rec.birth_date), parse_date(rec.issue_date))
        victim = "BE" if age >= MIN_AGE["BE"] else "B"   # BE без B либо B без B1/M
        rec.categories = [victim]
        row = next(iter(rec.back_table.values()), None) or {
            "open": rec.issue_date, "expiry": rec.expiry_date, "restriction": ""}
        rec.back_table = {victim: dict(row)}
        _recalc_marks(rec)
    return _mark(rec, "category_dependency_broken")


@mutator("front_back_category_mismatch", "R05")
def m_front_back_cat(rng: random.Random, rec: LicenceRecord) -> LicenceRecord:
    birth = parse_date(rec.birth_date)
    age = age_on(birth, parse_date(rec.issue_date))
    cur = set(rec.categories)
    # кандидат: алфавитный, по возрасту проходит, зависимости уже открыты
    cands = [c for c in ALL_CATEGORIES
             if c not in cur and MIN_AGE.get(c, 99) <= age
             and set(IMPLIES.get(c, [])) <= cur]
    add = rng.choice(cands) if cands else "A1"
    rec.categories = sort_categories(cur | {add})   # строку на оборот НЕ добавляем
    return _mark(rec, "front_back_category_mismatch")


@mutator("underage_at_issue", "R06")
def m_underage(rng: random.Random, rec: LicenceRecord) -> LicenceRecord:
    issue = parse_date(rec.issue_date)
    threshold = max(MIN_AGE.get(c, 18) for c in rec.categories)
    target_age = threshold - rng.randint(1, 3)
    new_birth = plus_years(issue, -target_age) + timedelta(days=rng.randint(0, 200))
    rec.birth_date = fmt_date(new_birth)
    return _mark(rec, "underage_at_issue")


@mutator("invalid_authority_region", "R07")
def m_authority(rng: random.Random, rec: LicenceRecord) -> LicenceRecord:
    rec.authority = f"ГИБДД {rng.choice(INVALID_REGION_CODES)}{rng.randint(0, 99):02d}"
    return _mark(rec, "invalid_authority_region")


@mutator("unknown_category_symbol", "R08")
def m_unknown_cat(rng: random.Random, rec: LicenceRecord) -> LicenceRecord:
    bogus = rng.choice(["E", "B2", "CD", "A2"])
    rec.categories = rec.categories + [bogus]
    rec.back_table[bogus] = {"open": rec.issue_date, "expiry": rec.expiry_date,
                             "restriction": ""}   # и на обороте — иначе сломаем R05 тоже
    return _mark(rec, "unknown_category_symbol")


@mutator("issue_date_in_future", "R09")
def m_future(rng: random.Random, rec: LicenceRecord) -> LicenceRecord:
    # отсчёт от сегодня, а не от исходной выдачи: у «старых» записей выдача может быть
    # настолько в прошлом, что +900 дней не выведет её в будущее и правило не сломается
    issue = date.today() + timedelta(days=rng.randint(30, 900))
    expiry = plus_years(issue, 10)               # срок держим = выдача+10, ломаем ровно одно
    rec.issue_date, rec.expiry_date = fmt_date(issue), fmt_date(expiry)
    for row in rec.back_table.values():
        row["expiry"] = rec.expiry_date
    return _mark(rec, "issue_date_in_future")


@mutator("special_marks_after_issue", "R10")
def m_marks(rng: random.Random, rec: LicenceRecord) -> LicenceRecord:
    year = parse_date(rec.issue_date).year + rng.randint(1, 5)
    rec.special_marks = f"СТАЖ С {year}"
    return _mark(rec, "special_marks_after_issue")


@mutator("back_open_after_expiry", "R11")
def m_open_after_expiry(rng: random.Random, rec: LicenceRecord) -> LicenceRecord:
    cat = rng.choice(list(rec.back_table))
    late = parse_date(rec.expiry_date) + timedelta(days=rng.randint(10, 400))
    rec.back_table[cat]["open"] = fmt_date(late)
    return _mark(rec, "back_open_after_expiry")


def make_mutated(rng: random.Random, name: str | None = None,
                 identity: Identity | None = None, region_code: str | None = None,
                 birth_place: str | None = None, valid_now: bool = False,
                 today: date | None = None) -> LicenceRecord:
    """Валидная запись со сломанным ровно одним правилом."""
    rec = make_valid(rng, identity=identity, region_code=region_code,
                     birth_place=birth_place, valid_now=valid_now, today=today)
    key = name or rng.choice(list(MUTATORS))
    if key not in MUTATORS:
        raise KeyError(key)
    return MUTATORS[key](rng, rec)


def generate_dataset(n_valid: int, n_mutated: int, seed: int | None = None,
                     identity: Identity | None = None,
                     region_code: str | None = None,
                     birth_place: str | None = None,
                     valid_now: bool = False) -> list[LicenceRecord]:
    """Пакет: n_valid валидных + n_mutated битых (мутаторы циклом для равномерного покрытия)."""
    rng = new_rng(seed)
    ident = identity or parse_identity(DEMO_IDENTITY_STR)
    out = [make_valid(rng, identity=ident, region_code=region_code, birth_place=birth_place,
                      valid_now=valid_now) for _ in range(n_valid)]
    names = list(MUTATORS)
    for i in range(n_mutated):
        out.append(make_mutated(rng, names[i % len(names)], identity=ident,
                                region_code=region_code, birth_place=birth_place,
                                valid_now=valid_now))
    return out


# ────────────────────────────── CLI (§8) ──────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Генератор синтетического датасета ВУ (ТЗ v2.0)")
    ap.add_argument("--valid", type=int, default=1, help="сколько валидных записей")
    ap.add_argument("--mutated", type=int, default=0, help="сколько битых записей")
    ap.add_argument("--seed", type=int, default=None, help="seed для воспроизводимости в CI")
    ap.add_argument("--identity", type=str, default=None,
                    help=f'личные данные: "ФАМИЛИЯ ИМЯ ОТЧЕСТВО ДД.ММ.ГГГГ" '
                         f'(по умолчанию плейсхолдер "{DEMO_IDENTITY_STR}")')
    ap.add_argument("--region", type=str, default=None,
                    help="код подразделения ГИБДД (2 цифры), например 77; по умолчанию случайный")
    ap.add_argument("--birthplace", type=str, default=None,
                    help='место рождения, например "Г. ВОРОНЕЖ"; по умолчанию случайное')
    ap.add_argument("--valid-now", action="store_true", dest="valid_now",
                    help="только действующие права: срок действия ещё не истёк")
    ap.add_argument("-o", "--out", type=str, default=None, help="файл .jsonl (по умолчанию stdout)")
    args = ap.parse_args(argv)

    ident = None
    if args.identity:
        try:
            ident = parse_identity(args.identity)
        except IdentityError as e:
            print(f"Ошибка в --identity: {e}", file=sys.stderr)
            return 2

    if args.region and args.region not in REGIONS:
        print(f"Код региона {args.region} отсутствует в справочнике. "
              f"Доступно {len(REGIONS)} кодов.", file=sys.stderr)
        return 2

    if args.birthplace:
        try:
            parse_place(args.birthplace)
        except IdentityError as e:
            print(f"Ошибка в --birthplace: {e}", file=sys.stderr)
            return 2

    records = generate_dataset(args.valid, args.mutated, seed=args.seed,
                               identity=ident, region_code=args.region,
                               birth_place=args.birthplace, valid_now=args.valid_now)
    lines = [r.to_json() for r in records]
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"{len(records)} записей → {args.out} "
              f"(валидных {args.valid}, битых {args.mutated})", file=sys.stderr)
    else:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
