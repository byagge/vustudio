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

    def test_stamp_does_not_draw_new_dates(self):
        """Python не рисует новый текст — только чистит призраки, PS-даты не трогает."""
        im = _synth_back()
        draw = ImageDraw.Draw(im)
        card = find_card_rect(im)
        draw.rectangle(
            [card.x + int(card.w * 0.52), card.y + int(card.h * 0.25), card.x + int(card.w * 0.62), card.y + int(card.h * 0.28)],
            fill=(180, 180, 185),
        )
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
            card2 = find_card_rect(out)
            self.assertIsNotNone(card2)
            # маркер «PS-дата» в ячейке B не закрашен плоским серым
            sample = out.getpixel((card2.x + int(card2.w * 0.56), card2.y + int(card2.h * 0.26)))
            self.assertGreaterEqual(sample[0], 170)

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

    def test_scrubs_ghost_zone_not_full_column(self):
        """Призраки убираются точечно, без закрашивания всей колонки."""
        from back_jpg_dates import DEFAULT_GEOM, DEFAULT_ROW_FRAC, _ghost_scrub_boxes, _scrub_ghost_zones

        im = _synth_back()
        card = find_card_rect(im)
        self.assertIsNotNone(card)
        g = {
            **DEFAULT_GEOM,
            "row_step_px": float(card.h * 0.045),
            "font_h_px": 14.0,
        }
        draw = ImageDraw.Draw(im)
        ghost_boxes = _ghost_scrub_boxes(card, g, DEFAULT_ROW_FRAC, "B")
        self.assertGreaterEqual(len(ghost_boxes), 2)
        box = ghost_boxes[0]
        draw.rectangle([box.x0 + 2, box.y0 + 2, box.x1 - 2, box.y1 - 2], fill=(20, 20, 22))
        # линия сетки на краю ячейки — не должна исчезнуть полностью
        grid_y = card.y + int(card.h * 0.30)
        draw.line(
            [(card.x + int(card.w * 0.37), grid_y), (card.x + int(card.w * 0.65), grid_y)],
            fill=(40, 40, 45),
            width=1,
        )
        before_ghost = im.getpixel((box.x0 + 4, box.y0 + 4))
        self.assertLess(sum(before_ghost) / 3, 80)
        _scrub_ghost_zones(im, card, g, DEFAULT_ROW_FRAC, cats=("B",))
        after_ghost = im.getpixel((box.x0 + 4, box.y0 + 4))
        self.assertGreater(sum(after_ghost) / 3, 100)
        grid_px = im.getpixel((card.x + int(card.w * 0.50), grid_y))
        self.assertLess(sum(grid_px) / 3, 120)

    def test_stamp_ghosts_only_no_draw(self):
        im = _synth_back()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "back.jpg"
            im.save(path, format="JPEG", quality=92)
            before = Image.open(path).convert("RGB")
            card = find_card_rect(before)
            mid = before.getpixel((card.x + card.w // 2, card.y + card.h // 2))
            self.assertTrue(
                stamp_back_jpg(
                    path,
                    table={"B": {"open": "08.09.2023", "expiry": "08.09.2033"}},
                    draw_dates=False,
                )
            )
            after = Image.open(path).convert("RGB")
            mid2 = after.getpixel((card.x + card.w // 2, card.y + card.h // 2))
            # JPEG re-encode may nudge ±2; dates must not appear (no big darkening)
            self.assertLessEqual(sum(abs(a - b) for a, b in zip(mid, mid2)), 12)

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
