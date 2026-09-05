#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты парсера текстового блока."""
from __future__ import annotations

import unittest

from formatter import format_client_block
from text_parser import parse_client_block
from vu_testdata import make_valid, new_rng, parse_me


SAMPLE = """1  Фамилия      АБСАЛЯМОВ / ABSALIAMOV
2  Имя, отч.    ВЛАДИСЛАВ НАИЛЕВИЧ / VLADISLAV NAILEVICH
3  Дата рожд.   08.09.1983
   Место рожд.  Г. ХАБАРОВСК / G. KHABAROVSK
4a Выдано       27.02.2009
4b Действ. до   27.02.2019
4c Кем выдано   ГИБДД 0469
5  Номер        0476 656492
8  Регион       РЕСПУБЛИКА АЛТАЙ / RESPUBLIKA ALTAI
9  Категории    B, B1, M
────────────────────────────────────────────
кат   открыто     до          огр.
B     27.02.2009  27.02.2019  —
B1    27.02.2009  27.02.2019  —
M     27.02.2009  27.02.2019  —
────────────────────────────────────────────
14 СТАЖ С 2009
номер (оборот) 0476 656492"""


class TestTextParser(unittest.TestCase):
    def test_sample_from_tz(self):
        b = parse_client_block(SAMPLE)
        self.assertEqual(b.surname_ru, "АБСАЛЯМОВ")
        self.assertEqual(b.surname_lat, "ABSALIAMOV")
        self.assertEqual(b.series, "0476")
        self.assertEqual(b.number, "656492")
        self.assertEqual(b.categories, ["B", "B1", "M"])
        self.assertEqual(b.back_table["B"].open_date, "27.02.2009")
        self.assertEqual(b.special_marks, "СТАЖ С 2009")
        self.assertEqual(b.birth_place_ru, "Г. ХАБАРОВСК")
        self.assertEqual(b.birth_place_lat, "G. KHABAROVSK")

    def test_roundtrip_with_generator(self):
        ident, place = parse_me("АБСАЛЯМОВ ВЛАДИСЛАВ НАИЛЕВИЧ 08.09.1983 Г. ХАБАРОВСК")
        rec = make_valid(new_rng(7), identity=ident, region_code="04", birth_place=place)
        text = format_client_block(rec)
        b = parse_client_block(text)
        self.assertEqual(b.surname_ru, rec.surname_ru)
        self.assertEqual(b.issue_date, rec.issue_date)
        self.assertEqual(len(b.back_table), len(rec.back_table))


if __name__ == "__main__":
    unittest.main()
