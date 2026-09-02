#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты критериев приёмки ТЗ §9 (1–5, 7). Запуск: python test_vu.py"""
from __future__ import annotations

import sys
from datetime import date

from eval_rules import validate
from vu_testdata import (
    ALL_CATEGORIES, IMPLIES, MIN_AGE, MUTATORS, REGIONS, parse_place, parse_me,
    Identity, IdentityError, LicenceRecord,
    age_on, closure, gender_from, is_synthetic, make_mutated, make_valid,
    naive_translit, new_rng, parse_date, parse_identity, plus_years, translit,
)

FAILS: list[str] = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
    return cond


def t_translit_table():
    """Контрольные примеры транслитерации (§4.2)."""
    cases = {
        "ДМИТРИЙ": "DMITRII", "МУРМАНСКАЯ": "MURMANSKAIA",
        "КРАСНОДАРСКИЙ": "KRASNODARSKII", "ЩЕРБАКОВ": "SHCHERBAKOV",
        "ПОДЪЯЧЕВ": "PODIACHEV", "ЖУРАВЛЁВ": "ZHURAVLEV",
    }
    for ru, expected in cases.items():
        check(translit(ru) == expected, f"translit({ru}) = {translit(ru)}, ждали {expected}")


def t_criterion_1_and_2():
    """1: транслитерация всех 4 пар. 2: все правила §4 на валидных записях."""
    rng = new_rng(11)
    ident = parse_identity("ЩЕРБАКОВ ДМИТРИЙ ВАЛЕНТИНОВИЧ 14.03.1988")
    for _ in range(300):
        r = make_valid(rng, identity=ident)
        check(translit(r.surname_ru) == r.surname_lat, "C1 surname")
        check(translit(r.given_ru) == r.given_lat, "C1 given")
        check(translit(r.birth_place_ru) == r.birth_place_lat, "C1 birth_place")
        check(translit(r.residence_ru) == r.residence_lat, "C1 residence")

        issue, expiry = parse_date(r.issue_date), parse_date(r.expiry_date)
        birth = parse_date(r.birth_date)
        check(expiry == plus_years(issue, 10), "C2 срок != выдача+10")
        check(issue <= date.today(), "C2 выдача в будущем")
        check(set(r.categories) == closure(r.categories), "C2 замыкание категорий")
        check(all(c in ALL_CATEGORIES for c in r.categories), "C2 алфавит категорий")
        age = age_on(birth, issue)
        check(all(MIN_AGE[c] <= age for c in r.categories), "C2 возрастной порог")
        check(set(r.back_table) == set(r.categories), "C2 back_table.keys != categories")
        check(r.back_number == f"{r.series} {r.number}", "C2 back_number")
        year14 = int(r.special_marks.split()[-1])
        check(year14 <= issue.year, "C2 поле 14 > года выдачи")
        check(len(r.series) == 4 and len(r.number) == 6, "C2 длина серии/номера")
        check(r.series[:2] in REGIONS, f"C2 серия не из справочника регионов: {r.series}")
        check(r.authority[6:8] == r.series[:2], "C2 код в серии != коду подразделения")
        check(not validate(r.to_dict()), f"C2 валидная запись помечена red: {validate(r.to_dict())}")


def t_criterion_3():
    """Каждый мутатор на 100 прогонах даёт red — 100/100, без ложно-негативных."""
    ident = parse_identity("ЩЕРБАКОВ ДМИТРИЙ ВАЛЕНТИНОВИЧ 14.03.1988")
    for name in MUTATORS:
        rng = new_rng(hash(name) & 0xFFFF)
        red = sum(1 for _ in range(100)
                  if validate(make_mutated(rng, name, identity=ident).to_dict()))
        check(red == 100, f"C3 мутатор {name}: red {red}/100")


def t_criterion_3_single_rule():
    """Мутатор ломает РОВНО ОДНО правило (иначе кейс перестаёт быть точечным)."""
    ident = parse_identity("ЩЕРБАКОВ ДМИТРИЙ ВАЛЕНТИНОВИЧ 14.03.1988")
    for name in MUTATORS:
        rng = new_rng(hash(name) & 0xFFFF)
        for _ in range(50):
            broken = validate(make_mutated(rng, name, identity=ident).to_dict())
            check(len(broken) == 1, f"C3 {name} сломал {len(broken)} правил: {broken}")
            if len(broken) != 1:
                break


def t_criterion_4_profile():
    """В режиме профиля ФИО и ДР фиксированы, уникальны пары (серия, номер)."""
    ident = parse_identity("ЩЕРБАКОВ ДМИТРИЙ ВАЛЕНТИНОВИЧ 14.03.1988")
    rng = new_rng(6)
    recs = [make_valid(rng, identity=ident) for _ in range(50)]
    check(len({(r.surname_ru, r.given_ru, r.birth_date) for r in recs}) == 1, "C4 профиль: ФИО менялось")
    check(len({(r.series, r.number) for r in recs}) == 50,
          f"C4 профиль: уникальных пар серия+номер {len({(r.series, r.number) for r in recs})}/50")


def t_criterion_5_synthetic():
    """is_synthetic(rec) истинен для ВСЕХ записей (маркер в метаполе synthetic, §1.2)."""
    rng = new_rng(9)
    ident = parse_identity("ИВАНОВ ИВАН ИВАНОВИЧ 01.02.1990")
    pool: list[LicenceRecord] = [make_valid(rng, identity=ident) for _ in range(100)]
    pool += [make_valid(rng, identity=ident, region_code="77") for _ in range(50)]
    pool += [make_mutated(rng, n, identity=ident) for n in MUTATORS]
    bad = [r.series for r in pool if not is_synthetic(r)]
    check(not bad, f"C5 несинтетические записи: {bad[:5]}")
    check(all(is_synthetic(r.to_dict()) for r in pool), "C5 is_synthetic по dict")
    check(all(r.synthetic is True for r in pool), "C5 synthetic != True")


def t_criterion_7_profile_fields():
    """Записи из профиля: поля 1,2,3 совпадают посимвольно, identity_source == user."""
    ident = parse_identity("ПОДЪЯЧЕВ ЮРИЙ ЩЕРБАНОВИЧ 07.11.1975")
    rng = new_rng(3)
    for _ in range(50):
        r = make_valid(rng, identity=ident)
        check(r.surname_ru == "ПОДЪЯЧЕВ", "C7 фамилия")
        check(r.given_ru == "ЮРИЙ ЩЕРБАНОВИЧ", "C7 имя+отчество")
        check(r.birth_date == "07.11.1975", "C7 ДР")
        check(r.identity_source == "user", "C7 identity_source")
        check(r.surname_lat == "PODIACHEV", f"C7 транслит фамилии: {r.surname_lat}")
        check(not validate(r.to_dict()), "C7 запись из профиля помечена red")


def t_region_choice():
    """Выбранное подразделение управляет и полем 4c, и первыми цифрами серии (§4.6-4.7)."""
    ident = parse_identity("ЩЕРБАКОВ ДМИТРИЙ ВАЛЕНТИНОВИЧ 14.03.1988")
    rng = new_rng(21)
    for code in ("77", "51", "95", "01"):
        for _ in range(20):
            r = make_valid(rng, identity=ident, region_code=code)
            check(r.series.startswith(code), f"C-reg серия {r.series} не с {code}")
            check(r.authority.startswith(f"ГИБДД {code}"), f"C-reg подразделение {r.authority}")
            check(not validate(r.to_dict()), "C-reg запись помечена red")
    try:
        make_valid(rng, identity=ident, region_code="88")
        check(False, "C-reg код вне справочника должен падать")
    except ValueError:
        pass
    try:
        make_valid(rng, identity=None)
        check(False, "C-reg генерация без личных данных должна падать")
    except ValueError:
        pass


def t_birth_place_choice():
    """Место рождения задаётся пользователем и попадает в п. 3 без искажений."""
    ident = parse_identity("ЩЕРБАКОВ ДМИТРИЙ ВАЛЕНТИНОВИЧ 14.03.1988")
    rng = new_rng(31)
    for raw, expected in [("г. воронеж", "Г. ВОРОНЕЖ"),
                          ("  С.  Щёлково-3 ", "С. ЩЁЛКОВО-3"),
                          ("П. ЮЖНЫЙ", "П. ЮЖНЫЙ")]:
        for _ in range(10):
            r = make_valid(rng, identity=ident, birth_place=raw)
            check(r.birth_place_ru == expected, f"C-bp {r.birth_place_ru} != {expected}")
            check(r.birth_place_lat == translit(expected), "C-bp транслит места рождения")
            check(not validate(r.to_dict()), "C-bp запись помечена red")

    # без указания — случайное из справочника, запись остаётся валидной
    r = make_valid(rng, identity=ident)
    check(bool(r.birth_place_ru), "C-bp пустое место рождения по умолчанию")

    # пустое и пробельное — это «не задано», а не ошибка: берётся случайное из справочника
    for blank in ["", "   "]:
        r = make_valid(rng, identity=ident, birth_place=blank)
        check(r.birth_place_ru in __import__("vu_testdata").BIRTH_PLACES,
              f"C-bp пустое значение не дало фолбэк: {r.birth_place_ru}")

    for bad in ["Voronezh", "###", "Г. " + "Я" * 70]:
        try:
            make_valid(rng, identity=ident, birth_place=bad)
            check(False, f"C-bp должно было упасть: {bad[:12]!r}")
        except IdentityError:
            pass


def t_valid_now():
    """valid_now=True даёт только действующие права: срок ещё не истёк (§4.4)."""
    ident = parse_identity("АБСАЛЯМОВ ВЛАДИСЛАВ НАИЛЕВИЧ 08.09.1983")
    rng = new_rng(77)
    today = date.today()
    for _ in range(200):
        r = make_valid(rng, identity=ident, valid_now=True)
        issue, expiry = parse_date(r.issue_date), parse_date(r.expiry_date)
        check(expiry > today, f"C-vn просрочено: {r.expiry_date}")
        check(issue <= today, f"C-vn выдача в будущем: {r.issue_date}")
        check(expiry == plus_years(issue, 10), "C-vn срок != выдача+10")
        check(not validate(r.to_dict()), "C-vn запись помечена red")
    # без флага просроченные встречаются — это ожидаемое поведение по умолчанию
    expired = sum(parse_date(make_valid(rng, identity=ident).expiry_date) <= today
                  for _ in range(200))
    check(expired > 0, "C-vn без флага не встретилось ни одной просроченной")


def t_parse_me():
    """Единый разбор /me: дата — разделитель ФИО и места рождения (§2.1)."""
    i, p = parse_me("АБСАЛЯМОВ ВЛАДИСЛАВ НАИЛЕВИЧ 08.09.1983 Г. ХАБАРОВСК")
    check((i.surname, i.name, i.patronymic) == ("АБСАЛЯМОВ", "ВЛАДИСЛАВ", "НАИЛЕВИЧ"), "C-me ФИО")
    check(i.birth_date == "08.09.1983" and p == "Г. ХАБАРОВСК", "C-me ДР/место")

    i, p = parse_me("сидоров пётр 01.01.1990")
    check(i.patronymic == "" and p is None, "C-me без отчества и места")

    i, p = parse_me("  ИВАНОВ  ИВАН  ИВАНОВИЧ  05.05.1995   с.  щёлково-3 ")
    check(p == "С. ЩЁЛКОВО-3", f"C-me нормализация места: {p}")

    for bad in ["ИВАНОВ ИВАН ИВАНОВИЧ", "ИВАНОВ 01.01.1990", "",
                "ИВАНОВ ИВАН 01.01.1990 Voronezh", "ИВАНОВ ИВАН ИВАНОВИЧ 31.02.1990"]:
        try:
            parse_me(bad)
            check(False, f"C-me должно было упасть: {bad[:24]!r}")
        except IdentityError:
            pass


def t_identity_parsing():
    """Разбор и валидация личных данных (§2.1)."""
    i = parse_identity("щербаков дмитрий валентинович 14.03.1988")
    check(i.surname == "ЩЕРБАКОВ" and i.name == "ДМИТРИЙ", "регистр не приведён")
    check(i.gender == "M", "пол по отчеству -ОВИЧ")
    check(parse_identity("ИВАНОВА АННА ПЕТРОВНА 01.01.1990").gender == "F", "пол по -ОВНА")
    check(parse_identity("СИДОРОВ ПЁТР 01.01.1990").patronymic == "", "отчество необязательно")

    for bad, why in [
        ("ИВАНОВ 01.01.1990", "мало токенов"),
        ("IVANOV IVAN IVANOVICH 01.01.1990", "латиница"),
        ("ИВАНОВ ИВАН ИВАНОВИЧ 31.02.1990", "несуществующая дата"),
        ("ИВАНОВ ИВАН ИВАНОВИЧ 1990-01-01", "формат даты"),
        ("ИВАНОВ ИВАН ИВАНОВИЧ 01.01.2020", "младше 18"),
        ("ИВАНОВ ИВАН ИВАНОВИЧ 01.01.1890", "старше 100"),
    ]:
        try:
            parse_identity(bad)
            check(False, f"должно было упасть: {why}")
        except IdentityError:
            pass

    check(gender_from("", "ЩЕРБАКОВА") == "F", "пол по фамилии на -А")
    check(gender_from("", "ЩЕРБАКОВ") == "M", "пол по фамилии на согласную")


def t_naive_translit_differs():
    """Наивная транслитерация действительно отличается на «сложных» буквах."""
    check(naive_translit("ХМЕЛЬНИЦКИЙ") != translit("ХМЕЛЬНИЦКИЙ"), "Х/Й не ломается")
    check(naive_translit("ЯКОВЛЕВ") != translit("ЯКОВЛЕВ"), "Я не ломается")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("t_")]
    for fn in tests:
        before = len(FAILS)
        fn()
        status = "OK " if len(FAILS) == before else "FAIL"
        print(f"[{status}] {fn.__name__}")
    print("-" * 60)
    if FAILS:
        print(f"ПРОВАЛЕНО: {len(FAILS)}")
        for f in FAILS[:20]:
            print("  -", f)
        return 1
    print(f"ВСЕ ТЕСТЫ ПРОЙДЕНЫ ({len(tests)} групп)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
