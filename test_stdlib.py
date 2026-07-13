"""Тесты модулей стандартной библиотеки."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import parse
from interpreter import run
import random as _random


def test(name, src, bootstrap, check=None):
    ast = parse(src, name)
    result = run(ast, bootstrap)
    ok = True
    msg = ""
    if check:
        ok, msg = check(result)
    status = "OK" if ok else "FAIL"
    print(f"  [{status}] {name}")
    if not ok:
        print(f"    store: {result['store']}")
        print(f"    {msg}")
    return ok


def main():
    all_ok = True
    print("\n=== Builtin functions ===")
    all_ok &= test("range", 'lib t { rule r = when boot => { x := range(0, 5) } }', ["boot"])
    all_ok &= test("len", 'lib t { rule r = when boot => { x := len([1,2,3]) } }', ["boot"])
    all_ok &= test("abs", 'lib t { rule r = when boot => { x := abs(-5) } }', ["boot"])
    all_ok &= test("min/max", 'lib t { rule r = when boot => { a := min(3,7) b := max(3,7) } }', ["boot"])
    all_ok &= test("str", 'lib t { rule r = when boot => { x := str(42) } }', ["boot"])

    print("\n=== console module ===")
    all_ok &= test("console.print", 'lib t { rule r = when boot => { console.print("hello") } }', ["boot"])

    print("\n=== random module ===")
    all_ok &= test("random.int",
        'lib t { rule r = when boot => { x := random.int(1, 100) } }', ["boot"],
        lambda r: (1 <= r['store']['x'] <= 100, f"x={r['store']['x']} outside [1,100]"))

    all_ok &= test("random.pick",
        'lib t { rule r = when boot => { x := random.pick([10,20,30]) } }', ["boot"],
        lambda r: (r['store']['x'] in [10,20,30], f"x={r['store']['x']} not in [10,20,30]"))

    _random.seed(42)
    all_ok &= test("random.shuffle",
        'lib t { rule r = when boot => { x := random.shuffle([1,2,3,4,5]) } }', ["boot"],
        lambda r: (isinstance(r['store']['x'], list) and len(r['store']['x']) == 5,
                   f"x={r['store']['x']} not a list of 5"))

    print("\n=== sim module ===")
    all_ok &= test("sim.step", 'lib t { rule r = when boot => { s := sim.step() } }', ["boot"])

    print("\n=== file module ===")
    test_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_test_stdlib.txt")
    safe_path = test_path.replace("\\", "/")
    all_ok &= test("file.write",
        f'lib t {{ rule r = when boot => {{ file.write("{safe_path}", "EVOL TEST") }} }}', ["boot"])
    all_ok &= test("file.read",
        f'lib t {{ rule r = when boot => {{ x := file.read("{safe_path}") }} }}', ["boot"],
        lambda r: (r['store']['x'] == "EVOL TEST", f"x={r['store']['x']!r}"))
    all_ok &= test("file.exists",
        f'lib t {{ rule r = when boot => {{ x := file.exists("{safe_path}") }} }}', ["boot"],
        lambda r: (r['store']['x'] == 1, f"x={r['store']['x']}"))
    if os.path.exists(test_path):
        os.remove(test_path)

    print(f"\n{'='*40}")
    if all_ok:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
