"""Прогон приёмки Этапа 4: тайпчекер отклоняет некорректное + метрика 5.

Запуск: python test_typechecker.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import parse
from typechecker import typecheck, proven_properties

SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")


def load(fn):
    with open(os.path.join(SAMPLES, fn), encoding="utf-8") as f:
        return parse(f.read(), fn)


def check(name, cond, detail=""):
    status = "[OK]  " if cond else "[FAIL]"
    print(f"{status} {name}" + (f" -- {detail}" if detail and not cond else ""))
    return cond


def main():
    fails = []

    # 1) корректная программа принимается
    ast = load("tc_ok.evol")
    errs = typecheck(ast)
    if not check("ok: принята (0 ошибок)", len(errs) == 0, str(errs)):
        fails.append("tc_ok rejected")

    # 2) типовая ошибка отклоняется
    ast = load("tc_bad_type.evol")
    errs = typecheck(ast)
    if not check("bad-type: отклонена", len(errs) > 0, "ошибок нет"):
        fails.append("tc_bad_type accepted")

    # 3) неизвестный spawn отклоняется
    ast = load("tc_bad_spawn.evol")
    errs = typecheck(ast)
    if not check("bad-spawn: отклонена", len(errs) > 0, "ошибок нет"):
        fails.append("tc_bad_spawn accepted")

    # 3b) неизвестный квалифицированный spawn отклоняется
    ast = load("tc_bad_spawn_qual.evol")
    errs = typecheck(ast)
    if not check("bad-spawn-qual: отклонена", len(errs) > 0, "ошибок нет"):
        fails.append("tc_bad_spawn_qual accepted")

    # 4) метрика 5: хорошая программа доказывает >=6 свойств (отлично)
    ast = load("tc_ok.evol")
    ok_proven, ok_failed = proven_properties(ast)
    if not check("metric5 ok: >=6 свойств", len(ok_proven) >= 6,
                 f"proven={len(ok_proven)}: {ok_proven}"):
        fails.append("metric5 ok too low")

    # 5) метрика 5: программа с непокрытым emit теряет свойство покрытия
    ast = load("tc_uncovered.evol")
    proven, failed = proven_properties(ast)
    if not check("metric5 uncovered: покрытие провалено", any("emit" in f or "покрыт" in f for f in failed),
                 f"failed={failed}"):
        fails.append("coverage not detected")

    print("\n--- доказанные свойства (tc_ok) ---")
    for p in ok_proven:
        print("   +", p)
    print("\n" + "=" * 50)
    if fails:
        print(f"ПРОВАЛ: {fails}")
        sys.exit(1)
    print("ЭТАП 4 ПРИНЯТ: тайпчекер реально отклоняет ошибки, метрика 5 считается.")


if __name__ == "__main__":
    main()
