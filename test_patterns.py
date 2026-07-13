"""Verify all EVOL patterns needed for corpus2."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parser import parse
from interpreter import run

ok = True
def test(name, src, bootstrap, check):
    global ok
    try:
        ast = parse(src, name)
        r = run(ast, bootstrap)
        passed, msg = check(r)
        status = "OK" if passed else "FAIL"
        print(f"  [{status}] {name}: {msg}")
        if not passed:
            ok = False
    except Exception as e:
        print(f"  [ERR] {name}: {e}")
        ok = False

print("=== Pattern verification ===")

# 1. forall + emit + pattern match (dispatcher core)
test("forall_emit",
    'lib d { rule start = when boot => { forall i in range(0, 5) { emit (req, i) } } rule h = when (req, x) => { y := x } }',
    ["boot"],
    lambda r: (r['steps'] > 0, f"steps={r['steps']}"))

# 2. emit with multiple tuple fields (3-tag patterns)
test("multi_tag",
    'lib t { rule r = when boot => { emit (ev, 1, 2) } rule h = when (ev, a, b) => { x := a + b } }',
    ["boot"],
    lambda r: (r['store'].get('x') == 3, f"x={r['store'].get('x')}"))

# 3. nested if-else chains (FSM guards)
test("nested_if",
    'lib f { rule r = when boot => { x := 2 if x == 0 then { y := 0 } else { if x == 1 then { y := 1 } else { y := 2 } } } }',
    ["boot"],
    lambda r: (r['store'].get('y') == 2, f"y={r['store'].get('y')}"))

# 4. spawn + retract
test("spawn_retract",
    'lib w { rule go = when work => { emit (done) } } lib m { rule start = when boot => { spawn w retract active } }',
    ["boot"],
    lambda r: (r['steps'] >= 1, f"steps={r['steps']}"))

# 5. loop with seq
test("loop_seq",
    'lib l { rule r = when boot => { i := 0 loop(i < 5, seq(i := i + 1, emit (tick))) } }',
    ["boot"],
    lambda r: (r['store'].get('i') == 5, f"i={r['store'].get('i')}"))

# 6. Multiple rules matching (dispatcher pattern with chain)
test("chain_dispatch",
    'lib d { rule s = when boot => { emit (e1, 0) } rule h1 = when (e1, x) => { emit (e2, x + 1) } rule h2 = when (e2, x) => { emit (e3, x + 1) } rule h3 = when (e3, x) => { result := x } }',
    ["boot"],
    lambda r: (r['store'].get('result') == 2, f"result={r['store'].get('result')}"))

# 7. string operations in EVOL
test("string_ops",
    'lib s { rule r = when boot => { a := "hello" b := string.upper(a) c := string.len(a) } }',
    ["boot"],
    lambda r: (r['store'].get('b') == "HELLO" and r['store'].get('c') == 5, f"b={r['store'].get('b')}, c={r['store'].get('c')}"))

# 8. math operations
test("math_ops",
    'lib m { rule r = when boot => { x := math.sqrt(100) y := math.floor(3.7) z := math.pow(2, 3) } }',
    ["boot"],
    lambda r: (r['store']['x'] == 10 and r['store']['y'] == 3 and r['store']['z'] == 8, f"{r['store']}"))

# 9. list creation and indexing
test("list_index",
    'lib l { rule r = when boot => { items := [10, 20, 30, 40, 50] x := items[2] } }',
    ["boot"],
    lambda r: (r['store'].get('x') == 30, f"x={r['store'].get('x')}"))

# 10. Tuple creation
test("tuple_create",
    'lib t { rule r = when boot => { t := (1, 2, 3) x := t[0] } }',
    ["boot"],
    lambda r: (r['store'].get('x') == 1, f"x={r['store'].get('x')}"))

# 11. emit chain — FSM pattern: state transitions
test("fsm_chain",
    'lib sm { rule init = when boot => { emit (s, 0) } rule step = when (s, x) => { if x < 5 then { emit (s, x + 1) } else { emit (halt, x) } } }',
    ["boot"],
    lambda r: (r['store'].get('x') == 5, f"x={r['store'].get('x')}"))

# 12. Pipeline: sequential stages via emit chain
test("pipeline_chain",
    'lib p { rule init = when boot => { emit (stage, 0, data) } rule run = when (stage, i, d) => { if i < 4 then { emit (stage, i + 1, d) } else { result := d } } }',
    ["boot"],
    lambda r: (r['store'].get('result') == 'data', f"result={r['store'].get('result')}"))

# 13. Guard with && (and)
test("guard_and",
    'lib g { rule r = when boot => { x := 5 y := 10 if x > 0 and y > 5 then { z := 1 } else { z := 0 } } }',
    ["boot"],
    lambda r: (r['store'].get('z') == 1, f"z={r['store'].get('z')}"))

# 14. try/catch
test("try_catch",
    'lib t { rule r = when boot => { try { raise "err" x := 1 } catch e { x := -1 } } }',
    ["boot"],
    lambda r: (r['store'].get('x') == -1, f"x={r['store'].get('x')}"))

# 15. emit + retract pattern (for cache invalidation)
test("emit_retract",
    'lib c { rule init = when boot => { emit (cache, key1, 100) } rule inv = when (cache, k, v) => { retract cache emit (cache, k, v + 1) } }',
    ["boot"],
    lambda r: (r['steps'] >= 1, f"steps={r['steps']}"))

# 16. Multiple emit in one rule
test("multi_emit",
    'lib m { rule r = when boot => { emit (a, 1) emit (b, 2) emit (c, 3) } rule ha = when (a, x) => { ax := x } rule hb = when (b, x) => { bx := x } rule hc = when (c, x) => { cx := x } }',
    ["boot"],
    lambda r: (r['store'].get('ax') == 1 and r['store'].get('bx') == 2 and r['store'].get('cx') == 3, f"{r['store']}"))

# 17. Complex DAG dispatcher (multiple depends)
test("dag_dispatch",
    'lib d { rule s = when boot => { emit (req, 1) } rule h = when (req, x) => { emit (down1, x) emit (down2, x) } rule d1 = when (down1, x) => { a := x * 2 emit (merge, a) } rule d2 = when (down2, x) => { b := x * 3 emit (merge, b) } rule m = when (merge, v) => { final := v } }',
    ["boot"],
    lambda r: (r['store'].get('final') is not None, f"final={r['store'].get('final')}"))

# 18. Nested loop via recursive rules (simulating backpressure)
test("backpressure",
    'lib bp { rule init = when boot => { emit (check, 0) } rule step = when (check, n) => { if n < 3 then { emit (pressure, n) emit (check, n + 1) } else { emit (bp_done) } } rule p = when (pressure, n) => { val := n * 10 } }',
    ["boot"],
    lambda r: (r['store'].get('val') == 20, f"val={r['store'].get('val')}"))

print(f"\n{'='*40}")
print("ALL PATTERNS VERIFIED" if ok else "SOME PATTERNS FAILED")
