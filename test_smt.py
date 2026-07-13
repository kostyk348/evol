"""Прогон приёмки опции B: SMT-доказательство свойств state machine.

Запуск: python test_smt.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "metrics"))

from parser import parse
from metrics import smt_prove as SMT


def check(name, cond, detail=""):
    status = "[OK]  " if cond else "[FAIL]"
    print(f"{status} {name}" + (f" -- {detail}" if detail and not cond else ""))
    return cond


def main():
    fails = []
    correct = """
lib sm {
  rule init = when boot => { emit (s, 0) }
  rule st = when (s, x) => {
    if x < 1000 then { emit (s, x + 1) } else { emit (halt) }
  }
}
"""
    ast = parse(correct, "correct")
    p, d = SMT.smt_properties(ast)
    if not check("корректный SM: доказано exclusive+exhaustive (>=2)", p >= 2, f"proven={p}"):
        fails.append("correct SM not proven")

    flawed = """
lib sm {
  rule init = when boot => { emit (s, 0) }
  rule a = when (s, x) => { if x < 500 then { emit (ok) } else { emit (skip) } }
  rule b = when (s, x) => { if x < 1000 then { emit (ok2) } else { emit (skip2) } }
}
"""
    ast2 = parse(flawed, "flawed")
    p2, d2 = SMT.smt_properties(ast2)
    conflict_found = any("КОНФЛИКТ" in x for x in d2)
    if not check("неисправный SM: конфликт охран обнаружен", conflict_found, str(d2)):
        fails.append("conflict not detected")

    print("\n" + "=" * 50)
    if fails:
        print(f"ПРОВАЛ: {fails}")
        sys.exit(1)
    print("ОПЦИЯ B ПРИНЯТА: SMT доказывает свойства и ловит конфликты охран.")


if __name__ == "__main__":
    main()
