"""Тесты новых фич: try/catch, raise, math, string, os."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parser import parse
from interpreter import run


def test_evolution(name, src, bootstrap, check=None):
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


all_ok = True

print("=== try/catch + raise ===")
all_ok &= test_evolution("try_catch_basic",
    'lib t { rule r = when boot => { try { raise \"err\" x := 1 } catch e { x := -1 } } }',
    ["boot"],
    lambda r: (r['store'].get('x') == -1, f"x={r['store'].get('x')}"))

all_ok &= test_evolution("try_catch_no_error",
    'lib t { rule r = when boot => { try { x := 42 } catch e { x := -1 } } }',
    ["boot"],
    lambda r: (r['store'].get('x') == 42, f"x={r['store'].get('x')}"))

all_ok &= test_evolution("try_div_zero",
    'lib t { rule r = when boot => { try { x := 10 / 0 } catch e { x := 0 } } }',
    ["boot"],
    lambda r: (r['store'].get('x') == 0, f"x={r['store'].get('x')}"))

print("\n=== math module ===")
all_ok &= test_evolution("math_sqrt",
    'lib t { rule r = when boot => { x := math.sqrt(144) } }',
    ["boot"],
    lambda r: (r['store']['x'] == 12, f"x={r['store']['x']}"))

all_ok &= test_evolution("math_pow",
    'lib t { rule r = when boot => { x := math.pow(2, 10) } }',
    ["boot"],
    lambda r: (r['store']['x'] == 1024, f"x={r['store']['x']}"))

all_ok &= test_evolution("math_floor_ceil",
    'lib t { rule r = when boot => { a := math.floor(3.7) b := math.ceil(3.2) } }',
    ["boot"],
    lambda r: (r['store']['a'] == 3 and r['store']['b'] == 4, f"{r['store']}"))

print("\n=== string module ===")
all_ok &= test_evolution("string_upper",
    'lib t { rule r = when boot => { x := string.upper("hello") } }',
    ["boot"],
    lambda r: (r['store']['x'] == "HELLO", f"x={r['store']['x']}"))

all_ok &= test_evolution("string_split",
    'lib t { rule r = when boot => { x := string.split("a,b,c", ",") } }',
    ["boot"],
    lambda r: (r['store']['x'] == ["a","b","c"], f"x={r['store']['x']}"))

all_ok &= test_evolution("string_join",
    'lib t { rule r = when boot => { x := string.join(["a","b"], "-") } }',
    ["boot"],
    lambda r: (r['store']['x'] == "a-b", f"x={r['store']['x']}"))

all_ok &= test_evolution("string_len",
    'lib t { rule r = when boot => { x := string.len("hello") } }',
    ["boot"],
    lambda r: (r['store']['x'] == 5, f"x={r['store']['x']}"))

all_ok &= test_evolution("string_contains",
    'lib t { rule r = when boot => { x := string.contains("hello world", "world") } }',
    ["boot"],
    lambda r: (r['store']['x'] == 1, f"x={r['store']['x']}"))

all_ok &= test_evolution("string_replace",
    'lib t { rule r = when boot => { x := string.replace("hello world", "world", "evol") } }',
    ["boot"],
    lambda r: (r['store']['x'] == "hello evol", f"x={r['store']['x']}"))

print("\n=== os module ===")
all_ok &= test_evolution("os_getcwd",
    'lib t { rule r = when boot => { x := os.getcwd() } }',
    ["boot"],
    lambda r: (isinstance(r['store']['x'], str) and len(r['store']['x']) > 0, f"x={r['store']['x']}"))

all_ok &= test_evolution("os_path_exists",
    'lib t { rule r = when boot => { x := os.path_exists("README.md") } }',
    ["boot"],
    lambda r: (r['store']['x'] == 1, f"x={r['store']['x']}"))

print(f"\n{'='*40}")
print("ALL TESTS PASSED" if all_ok else "SOME TESTS FAILED")
