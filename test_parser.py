"""Прогон приёмки Этапа 2: парсер принимает валидные и отклоняет невалидные.

Запуск: python test_parser.py
"""

import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import parse
from parser import ParseError
from lexer import LexError

SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")

VALID = [
    "valid1_dispatcher.evol",
    "valid2_statemachine.evol",
    "valid3_pipeline.evol",
    "valid4_di.evol",
]
INVALID = [
    "invalid1_no_arrow.evol",
    "invalid2_unclosed.evol",
    "invalid3_bad_assign.evol",
    "invalid4_bad_token.evol",
]


def main():
    failures = []

    for fn in VALID:
        path = os.path.join(SAMPLES, fn)
        with open(path, encoding="utf-8") as f:
            src = f.read()
        try:
            ast = parse(src, fn)
            print(f"[OK]   {fn}: распознано decls={len(ast)}")
        except (ParseError, LexError) as e:
            failures.append(f"{fn}: должен быть валидным, но упал: {e}")
            print(f"[FAIL] {fn}: {e}")

    for fn in INVALID:
        path = os.path.join(SAMPLES, fn)
        with open(path, encoding="utf-8") as f:
            src = f.read()
        try:
            ast = parse(src, fn)
            failures.append(f"{fn}: должен быть НЕвалидным, но распознан ({len(ast)} decls)")
            print(f"[FAIL] {fn}: не отклонён (распознано {len(ast)} decls)")
        except (ParseError, LexError) as e:
            print(f"[OK]   {fn}: корректно отклонен -> {e}")

    print("\n" + "=" * 50)
    if failures:
        print(f"ПРОВАЛ: {len(failures)} проблем")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    else:
        print("ЭТАП 2 ПРИНЯТ: валидные приняты, невалидные отклонены.")


if __name__ == "__main__":
    main()
