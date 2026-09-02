#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты хранилища профилей (§7.3 ТЗ)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from profiles import ProfileStore
from vu_testdata import Identity, parse_identity


def test_profile_region_persistence():
    with tempfile.TemporaryDirectory() as tmp:
        store = ProfileStore(Path(tmp) / "profiles.json")
        ident = parse_identity("ЩЕРБАКОВ ДМИТРИЙ ВАЛЕНТИНОВИЧ 14.03.1988")
        store.save_identity(1, ident, "Г. ВОРОНЕЖ")
        store.save_region(1, "77")

        p = store.load(1)
        assert p is not None
        assert p.region == "77"
        assert p.birth_place == "Г. ВОРОНЕЖ"
        assert p.ident.surname == "ЩЕРБАКОВ"

        # смена ФИО не затирает region
        ident2 = parse_identity("ИВАНОВ ИВАН ИВАНОВИЧ 01.01.1990")
        store.save_identity(1, ident2, "Г. МОСКВА")
        p2 = store.load(1)
        assert p2.region == "77"
        assert p2.ident.surname == "ИВАНОВ"

        store.save_region(1, "any")
        assert store.load(1).region is None

        assert store.delete(1)
        assert store.load(1) is None


if __name__ == "__main__":
    test_profile_region_persistence()
    print("test_profiles OK")
