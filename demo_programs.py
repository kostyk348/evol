"""Демо: запуск программ на EVOL — симуляции и утилиты."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import parse
from interpreter import run


def demo(name, src, bootstrap):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    ast = parse(src, name)
    result = run(ast, bootstrap)
    print(f"Store: {result['store']}")
    print(f"Шагов АМ: {result['steps']}")
    for e in result['emitted']:
        tag = e[0] if isinstance(e, tuple) else e
        if tag == "msg":
            print(f"  > {e}")
    if result['stopped_by_max_steps']:
        print("  ОСТАНОВЛЕН по max_steps!")
    print()


if __name__ == "__main__":
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")

    demos = [
        ("server_farm_sim.evol", "Server Farm (3 сервера, 9 задач)", ["boot"]),
        ("dice_game.evol", "Dice Game (random + console, 5 раундов)", ["boot"]),
        ("data_pipeline.evol", "Data Pipeline (random + file I/O)", ["boot"]),
    ]
    for fname, title, boot in demos:
        with open(os.path.join(base, fname), encoding="utf-8") as f:
            demo(title, f.read().strip(), boot)
