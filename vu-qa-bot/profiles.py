#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хранилище профилей пользователей (§7.3 ТЗ)."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vu_testdata import Identity


@dataclass
class UserProfile:
    ident: Identity
    birth_place: str | None = None
    region: str | None = None  # код подразделения; None = «любое»


class ProfileStore:
    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _row(self, user_id: int) -> dict:
        return dict(self._load().get(str(user_id), {}))

    def save_identity(self, user_id: int, ident: Identity, place: str | None) -> None:
        data = self._load()
        row = data.get(str(user_id), {})
        row.update({
            "surname": ident.surname,
            "name": ident.name,
            "patronymic": ident.patronymic,
            "birth_date": ident.birth_date,
            "gender": ident.gender,
            "birth_place": place,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        })
        data[str(user_id)] = row
        self._save(data)

    def save_birth_place(self, user_id: int, place: str | None) -> None:
        data = self._load()
        key = str(user_id)
        if key not in data:
            return
        data[key]["birth_place"] = place
        self._save(data)

    def save_region(self, user_id: int, region: str | None) -> None:
        """None или 'any' — сброс выбора подразделения."""
        data = self._load()
        key = str(user_id)
        if key not in data:
            return
        data[key]["region"] = None if region in (None, "any") else region
        self._save(data)

    def touch(self, user_id: int, *, username: str | None = None, first_name: str | None = None) -> None:
        data = self._load()
        key = str(user_id)
        row = data.get(key, {})
        now = datetime.now().isoformat(timespec="seconds")
        row.setdefault("first_seen", now)
        row["last_seen"] = now
        row["tg_id"] = user_id
        if username is not None:
            row["username"] = username
        if first_name is not None:
            row["first_name"] = first_name
        data[key] = row
        self._save(data)

    def bump(self, user_id: int, field: str, n: int = 1) -> None:
        data = self._load()
        key = str(user_id)
        row = data.get(key, {})
        row[field] = int(row.get(field) or 0) + n
        data[key] = row
        self._save(data)

    def stats(self, user_id: int) -> dict:
        p = self._row(user_id)
        return {
            "tg_id": int(p.get("tg_id") or user_id),
            "username": str(p.get("username") or ""),
            "first_name": str(p.get("first_name") or ""),
            "generations": int(p.get("generations") or 0),
            "renders": int(p.get("renders") or 0),
            "first_seen": str(p.get("first_seen") or ""),
            "last_seen": str(p.get("last_seen") or ""),
        }

    def load(self, user_id: int) -> UserProfile | None:
        p = self._load().get(str(user_id))
        if not p or not p.get("surname"):
            return None
        ident = Identity(
            p["surname"],
            p["name"],
            p.get("patronymic", ""),
            p["birth_date"],
            p.get("gender", "M"),
            source="user",
        )
        return UserProfile(
            ident=ident,
            birth_place=p.get("birth_place"),
            region=p.get("region"),
        )

    def delete(self, user_id: int) -> bool:
        data = self._load()
        key = str(user_id)
        if key not in data:
            return False
        del data[key]
        self._save(data)
        return True

    # совместимость со старым API
    def save(self, user_id: int, ident: Identity, place: str | None) -> None:
        self.save_identity(user_id, ident, place)
