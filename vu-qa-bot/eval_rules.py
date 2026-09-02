#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Эталонный валидатор правил оформления ВУ (R01–R11) и замер метрик. Точка входа CI (ТЗ §10).

Проверяет ФОРМАЛЬНУЮ КОНСИСТЕНТНОСТЬ записи, а не факт действительности документа:
истёкший срок сам по себе не делает запись red (для этого есть effective_expiry).

    python eval_rules.py --valid 500 --mutated 1100
    python eval_rules.py --in dataset.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date

from vu_testdata import (
    ALL_CATEGORIES, IMPLIES, MIN_AGE, REGIONS,
    age_on, effective_expiry, generate_dataset, is_synthetic,
    parse_date, plus_years, translit,
)

AUTHORITY_RE = re.compile(r"^ГИБДД (\d{2})(\d{2})$")
YEAR_RE = re.compile(r"(\d{4})")


def validate(rec: dict) -> list[str]:
    """Вернуть список нарушенных правил. Пустой список = green."""
    v: list[str] = []

    # R01 — транслитерация
    for ru, lat in (("surname_ru", "surname_lat"), ("given_ru", "given_lat"),
                    ("birth_place_ru", "birth_place_lat"), ("residence_ru", "residence_lat")):
        if translit(rec.get(ru, "")) != rec.get(lat, ""):
            v.append("R01")
            break

    try:
        issue = parse_date(rec["issue_date"])
        expiry = parse_date(rec["expiry_date"])
        birth = parse_date(rec["birth_date"])
    except Exception:
        return v + ["R00_bad_date"]

    # R02 — срок = выдача + ровно 10 лет
    if expiry != plus_years(issue, 10):
        v.append("R02")

    # R03 — номер на обороте совпадает с полем 5
    if rec.get("back_number") != f"{rec.get('series')} {rec.get('number')}":
        v.append("R03")

    cats = list(rec.get("categories") or [])
    known = [c for c in cats if c in MIN_AGE]

    # R04 — замыкание зависимостей категорий
    if any(dep not in cats for c in known for dep in IMPLIES.get(c, [])):
        v.append("R04")

    # R05 — множество строк оборота равно множеству категорий
    if set((rec.get("back_table") or {}).keys()) != set(cats):
        v.append("R05")

    # R06 — возраст на дату выдачи не ниже порога строжайшей категории
    if known and age_on(birth, issue) < max(MIN_AGE[c] for c in known):
        v.append("R06")

    # R07 — код региона подразделения из справочника
    m = AUTHORITY_RE.match(rec.get("authority", "") or "")
    if not m or m.group(1) not in REGIONS:
        v.append("R07")

    # R08 — только допустимый алфавит категорий
    if any(c not in ALL_CATEGORIES for c in cats):
        v.append("R08")

    # R09 — дата выдачи не в будущем
    if issue > date.today():
        v.append("R09")

    # R10 — год в поле 14 не позже года выдачи
    ym = YEAR_RE.search(rec.get("special_marks", "") or "")
    if ym and int(ym.group(1)) > issue.year:
        v.append("R10")

    # R11 — дата открытия категории не позже срока действия
    for row in (rec.get("back_table") or {}).values():
        try:
            if parse_date(row["open"]) > expiry:
                v.append("R11")
                break
        except Exception:
            v.append("R11")
            break

    return v


def status(rec: dict) -> str:
    return "green" if not validate(rec) else "red"


def evaluate(records: list[dict], verbose: bool = True) -> dict:
    tp = fp = tn = fn = 0
    per_rule = Counter()
    misses = Counter()
    not_synth = 0

    for rec in records:
        if not is_synthetic(rec):
            not_synth += 1
        red = bool(validate(rec))
        expected_valid = rec.get("expected_valid", True)
        if expected_valid:
            if red:
                fp += 1                       # валидную ошибочно отбраковали
                per_rule[f"FP:{'/'.join(validate(rec))}"] += 1
            else:
                tn += 1
        else:
            if red:
                tp += 1                       # битую поймали
            else:
                fn += 1                       # ЛОЖНО-НЕГАТИВНАЯ: мутатор не сработал
                misses[rec.get("broken_rule") or "?"] += 1

    total_bad = tp + fn
    total_ok = tn + fp
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / total_bad if total_bad else 1.0

    res = {
        "records": len(records), "valid": total_ok, "mutated": total_bad,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": precision, "recall": recall,
        "false_negatives_by_rule": dict(misses),
        "false_positives": dict(per_rule),
        "non_synthetic": not_synth,
    }

    if verbose:
        print(f"записей:      {len(records)}  (валидных {total_ok}, битых {total_bad})")
        print(f"precision:    {precision:.4f}")
        print(f"recall:       {recall:.4f}")
        print(f"поймано битых:{tp}/{total_bad}   ложно-негативных: {fn}")
        print(f"валидных пропущено как green: {tn}/{total_ok}   ложно-положительных: {fp}")
        print(f"is_synthetic() ложь у записей: {not_synth}")
        if misses:
            print("НЕ СРАБОТАВШИЕ МУТАТОРЫ:", dict(misses))
        if per_rule:
            print("ЛОЖНО-ПОЛОЖИТЕЛЬНЫЕ:", dict(per_rule))
        auto = sum(1 for r in records
                   if r.get("expected_valid")
                   and effective_expiry(parse_date(r["expiry_date"])) != parse_date(r["expiry_date"]))
        print(f"записей под автопродлением 2022–2025: {auto}")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Замер метрик валидатора ВУ (точка входа CI)")
    ap.add_argument("--valid", type=int, default=500)
    ap.add_argument("--mutated", type=int, default=1100)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--in", dest="infile", type=str, default=None,
                    help="готовый .jsonl вместо генерации")
    args = ap.parse_args(argv)

    if args.infile:
        with open(args.infile, encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
    else:
        records = [r.to_dict() for r in generate_dataset(args.valid, args.mutated, seed=args.seed)]

    res = evaluate(records)
    ok = (res["fn"] == 0 and res["fp"] == 0 and res["non_synthetic"] == 0)
    print("РЕЗУЛЬТАТ:", "OK" if ok else "ПРОВАЛ")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
