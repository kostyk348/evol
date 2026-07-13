"""Прогон приёмки Этапа 3: интерпретатор корректно исполняет семантику.

Запуск: python test_interpreter.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from interpreter import run_file, InterpreterError

SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")


def check(name, cond, detail=""):
    status = "[OK]  " if cond else "[FAIL]"
    print(f"{status} {name}" + (f" -- {detail}" if detail and not cond else ""))
    return cond


def main():
    fails = []

    # 1) счётчик через рекурсивный emit
    r = run_file(os.path.join(SAMPLES, "demo_counter.evol"), ["boot"])
    ticks = [m for m in r["emitted"] if m == "tick" or (isinstance(m, str) and m == "tick")]
    # emitted хранит Symbol; сравниваем по .name
    tick_names = [m.name for m in r["emitted"] if hasattr(m, "name") and m.name == "tick"]
    done = any(hasattr(m, "name") and m.name == "done" for m in r["emitted"])
    n = r["store"].get("n")
    if not check("counter: 5 ticks", len(tick_names) == 5, f"got {len(tick_names)}"):
        fails.append("counter ticks")
    if not check("counter: emit done", done):
        fails.append("counter done")
    if not check("counter: store n == 5", n == 5, f"n={n}"):
        fails.append("counter n")

    # 2) par без конфликта
    r = run_file(os.path.join(SAMPLES, "demo_par.evol"), ["boot"])
    if not check("par: x==1", r["store"].get("x") == 1, f"x={r['store'].get('x')}"):
        fails.append("par x")
    if not check("par: y==2", r["store"].get("y") == 2, f"y={r['store'].get('y')}"):
        fails.append("par y")

    # 3) par с конфликтом имён -> ошибка (не тихая перезапись)
    try:
        r = run_file(os.path.join(SAMPLES, "demo_par_conflict.evol"), ["boot"])
        check("par-conflict: отклонён", False, "проглочен конфликт")
        fails.append("par conflict not raised")
    except InterpreterError as e:
        check("par-conflict: отклонён", True)

    # 4) несовпавшее сообщение не падает (drop)
    r = run_file(os.path.join(SAMPLES, "demo_counter.evol"), ["noboot"])
    if not check("unmatched: без падения", not r["stopped_by_max_steps"]):
        fails.append("unmatched crash")

    # 5) forall: итерация по коллекции без ручного развёртывания
    r = run_file(os.path.join(SAMPLES, "demo_forall.evol"), ["boot"])
    ticks = [m for m in r["emitted"]
             if isinstance(m, tuple) and len(m) == 2 and m[0].name == "tick"]
    if not check("forall: 5 тиков (range 0..5)", len(ticks) == 5, f"ticks={len(ticks)}"):
        fails.append("forall count")
    if not check("forall: store y == 4 (последний элемент)", r["store"].get("y") == 4,
                 f"y={r['store'].get('y')}"):
        fails.append("forall y")

    print("\n" + "=" * 50)
    if fails:
        print(f"ПРОВАЛ: {fails}")
        sys.exit(1)
    print("ЭТАП 3 ПРИНЯТ: семантика исполняется корректно.")


if __name__ == "__main__":
    main()
