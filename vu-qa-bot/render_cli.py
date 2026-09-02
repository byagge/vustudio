#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI: подстановка текста в Photoshop."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from photoshop_text import (
    list_mockups,
    prepare_substitute_job,
    substitute_text,
    substitute_text_queued,
    validate_text_block,
    wait_substitute,
)
from photoshop_server import is_server_mode


def main() -> int:
    p = argparse.ArgumentParser(
        description="Подстановка текста в Photoshop-мокап (PSB/PSD + JPG)",
    )
    p.add_argument("input", nargs="?", help="Файл с блоком или — для stdin")
    p.add_argument(
        "--text",
        dest="text_inline",
        default=None,
        help="Текстовый блок inline (task2 §9: render_cli.py --text \"...\")",
    )
    p.add_argument("--text-file", type=Path, default=None, help="Файл с блоком (task3 §12)")
    p.add_argument("--mockup", choices=list(list_mockups()), default="blank")
    p.add_argument("--background", type=int, default=1)
    p.add_argument("--dry-run", action="store_true", help="Только job JSON, без Photoshop")
    p.add_argument("--queue", action="store_true", help="Через render-worker")
    p.add_argument("--wait", action="store_true", help="Ждать worker (--queue)")
    p.add_argument("--validate", action="store_true", help="Только проверка блока")
    p.add_argument("--verify-scene", action="store_true", help="Проверка scene vs PSB (task4)")
    p.add_argument("--generate-portrait", action="store_true", help="ИИ-портрет (PORTRAIT_API_URL)")
    p.add_argument("--portrait", type=Path, default=None, help="Путь к JPG портрета")
    p.add_argument("-o", "--output-dir", type=Path, default=None)
    args = p.parse_args()

    if args.text_inline:
        text = args.text_inline
    elif args.text_file:
        text = args.text_file.read_text(encoding="utf-8")
    elif args.input and args.input != "-":
        text = Path(args.input).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    if args.validate:
        errors = validate_text_block(text)
        if errors:
            print("; ".join(errors), file=sys.stderr)
            return 1
        print("OK")
        return 0

    if args.verify_scene:
        import json
        from mockup_scene import verify_all_scenes

        report = verify_all_scenes()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1

    if args.dry_run:
        job, path = prepare_substitute_job(
            text,
            mockup=args.mockup,
            background=args.background,
            output_dir=args.output_dir,
            portrait_path=str(args.portrait) if args.portrait else None,
            generate_portrait=args.generate_portrait,
        )
        print(path)
        print(json.dumps(job["layers_by_field"], ensure_ascii=False, indent=2))
        return 0

    if args.queue or is_server_mode():
        if not args.queue and is_server_mode():
            print(
                "RENDER_MODE=server: используйте --queue --wait",
                file=sys.stderr,
            )
        queued = substitute_text_queued(
            text,
            mockup=args.mockup,
            background=args.background,
            portrait_path=str(args.portrait) if args.portrait else None,
            generate_portrait=args.generate_portrait,
        )
        if not queued.ok:
            print(queued.message, file=sys.stderr)
            return 1
        print(f"queued:{queued.job_id}")
        if args.wait or is_server_mode():
            done = wait_substitute(queued.job_id)
            if not done.ok:
                print(done.message, file=sys.stderr)
                return 2
            for path in done.output_paths:
                print(path)
        return 0

    result = substitute_text(
        text,
        mockup=args.mockup,
        background=args.background,
        output_dir=args.output_dir,
        portrait_path=str(args.portrait) if args.portrait else None,
        generate_portrait=args.generate_portrait,
    )
    if not result.ok:
        print(result.message, file=sys.stderr)
        return 2
    for path in result.output_paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
