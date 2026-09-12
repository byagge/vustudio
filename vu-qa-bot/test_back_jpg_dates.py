#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from back_jpg_dates import fallback_card_rect, find_card_rect, stamp_back_from_text, stamp_back_jpg


def _synth_back(w=768, h=1024) -> Image.Image:
    im = Image.new("RGB", (w, h), (70, 55, 50))
    draw = ImageDraw.Draw(im)
    cw, ch = 400, 252
    x = (w - cw) // 2
    y = 280
    draw.rectangle([x, y, x + cw, y + ch], fill=(228, 228, 230))
    for i in range(17):
        yy = y + int(ch * (0.115 + 0.735 * i / 16))
        draw.line([(x + 20, yy), (x + cw - 12, yy)], fill=(200, 200, 205), width=1)
    for fx in (0.50, 0.67, 0.86):
        xx = x + int(cw * fx)
        draw.line(
            [(xx, y + int(ch * 0.10)), (xx, y + int(ch * 0.88))],
            fill=(200, 200, 205),
            width=1,
        )
    return im


class TestBackJpgDates(unittest.TestCase):
    def test_find_synth_card(self):
        card = find_card_rect(_synth_back())
        self.assertIsNotNone(card)
        self.assertGreater(card.w / card.h, 1.35)
        self.assertLess(card.w / card.h, 1.85)

    def test_stamp_writes_on_card_not_below(self):
        im = _synth_back()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "back.jpg"
            im.save(path, format="JPEG", quality=92)
            ok = stamp_back_jpg(
                path,
                table={
                    "B": {"open": "08.09.2023", "expiry": "08.09.2033"},
                    "B1": {"open": "08.09.2023", "expiry": "08.09.2033"},
                    "M": {"open": "08.09.2023", "expiry": "08.09.2033"},
                },
            )
            self.assertTrue(ok)
            out = Image.open(path).convert("RGB")
            card = find_card_rect(out)
            self.assertIsNotNone(card)
            below_y = min(out.size[1] - 1, card.y + card.h + 30)
            below = out.getpixel((card.x + card.w // 2, below_y))
            self.assertGreater(sum(below) / 3, 40)
            dark = 0
            for xx in range(card.x + int(card.w * 0.50), card.x + int(card.w * 0.84), 2):
                for yy in range(card.y + int(card.h * 0.20), card.y + int(card.h * 0.88), 2):
                    if sum(out.getpixel((xx, yy))) / 3 < 150:
                        dark += 1
            self.assertGreater(dark, 5)

    def test_stamp_preserves_guilloche_not_gray_bar(self):
        """После штампа колонки 10/11 не должны быть закрашены плоским серым."""
        im = _synth_back()
        draw = ImageDraw.Draw(im)
        card = find_card_rect(im)
        for i in range(40):
            y = card.y + int(card.h * (0.15 + 0.7 * i / 40))
            draw.line(
                [
                    (card.x + int(card.w * 0.52), y),
                    (card.x + int(card.w * 0.84), y + 1),
                ],
                fill=(210, 180, 190),
                width=1,
            )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "back.jpg"
            im.save(path, format="JPEG", quality=92)
            self.assertTrue(
                stamp_back_jpg(
                    path,
                    table={"B": {"open": "01.02.2020", "expiry": "01.02.2030"}},
                )
            )
            out = Image.open(path).convert("RGB")
            card2 = find_card_rect(out)
            samples = []
            yy = card2.y + int(card2.h * 0.15)
            for xx in range(card2.x + int(card2.w * 0.52), card2.x + int(card2.w * 0.64), 3):
                samples.append(out.getpixel((xx, yy)))
            uniq = len({s for s in samples})
            self.assertGreaterEqual(uniq, 2)

    def test_fallback_card_is_id1(self):
        card = fallback_card_rect(Image.new("RGB", (768, 1024), (40, 30, 28)))
        self.assertGreater(card.w / card.h, 1.4)
        self.assertLess(card.w / card.h, 1.8)

    def test_ensure_from_job_json(self):
        from back_jpg_dates import ensure_back_jpg_stamped

        im = _synth_back()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "vu_job_back.jpg"
            im.save(path, format="JPEG", quality=92)
            (root / "vu_job.job.json").write_text(
                '{"back_table_map":{"B":{"open":"01.01.2020","expiry":"01.01.2030"}}}',
                encoding="utf-8",
            )
            self.assertTrue(ensure_back_jpg_stamped(path))

    def test_stamp_from_text_block(self):
        from test_text_parser import SAMPLE

        im = _synth_back()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "back.jpg"
            im.save(path, format="JPEG", quality=92)
            self.assertTrue(stamp_back_from_text(path, SAMPLE))


if __name__ == "__main__":
    unittest.main()
