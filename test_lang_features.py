"""Тесты новых фич языка: ADT + match, FFI в Python, модули .evol, M5(P7/P8)."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parser import parse
from interpreter import run, run_file, InterpreterError, EvalError
from typechecker import proven_properties


def test(name, src=None, bootstrap=None, check=None, path=None, expect_error=False):
    ok = True
    msg = ""
    try:
        if src is None and path is None:
            if check:
                ok, msg = check(None)
            result = None
        else:
            result = run(parse(src, name), bootstrap) if path is None else run_file(path, bootstrap)
            if expect_error:
                ok = False
                msg = "ожидалось исключение, но программа выполнилась"
            elif check:
                ok, msg = check(result)
    except (InterpreterError, EvalError) as e:
        if expect_error:
            ok = True
        else:
            ok = False
            msg = f"неожиданное исключение: {e}"
    print(f"  [{'OK' if ok else 'FAIL'}] {name}")
    if not ok:
        print(f"    {msg}")
    return ok


all_ok = True

print("=== ADT + match ===")
all_ok &= test("adt_constructor_tuple",
    'lib t { rule r = when boot => { x := Circle(3.0); emit (tag, x) } }',
    ["boot"],
    lambda r: (isinstance(r['store']['x'], tuple) and r['store']['x'][0].name == "Circle"
               and r['store']['x'][1] == 3.0, f"x={r['store']['x']}"))

all_ok &= test("adt_match_circle",
    '''
    type Shape = Circle(r: Float) | Rect(w: Float, h: Float) | None;
    rule start = when boot => {
      x := Circle(3.0);
      y := match x { Circle(r) => r; Rect(w, h) => w * h; None => 0; };
      emit (res, y);
    };
    ''',
    ["boot"],
    lambda r: (r['store']['y'] == 3.0, f"y={r['store']['y']}"))

all_ok &= test("adt_match_rect",
    '''
    type Shape = Circle(r: Float) | Rect(w: Float, h: Float) | None;
    rule start = when boot => {
      x := Rect(2.0, 3.0);
      y := match x { Circle(r) => r; Rect(w, h) => w * h; None => 0; };
      emit (res, y);
    };
    ''',
    ["boot"],
    lambda r: (r['store']['y'] == 6.0, f"y={r['store']['y']}"))

print("\n=== FFI в Python ===")
all_ok &= test("ffi_math",
    '''
    import py "math": sqrt, pi;
    rule start = when boot => {
      a := py.sqrt(144.0);
      b := py.pi;
      emit (a, a);
      emit (b, b);
    };
    ''',
    ["boot"],
    lambda r: (r['store']['a'] == 12.0 and abs(r['store']['b'] - 3.14159) < 1e-4,
               f"a={r['store']['a']} b={r['store']['b']}"))

all_ok &= test("ffi_banned_eval",  # eval запрещён sandbox-ом -> ожидаем ошибку
    '''
    import py "builtins": eval;
    rule start = when boot => { x := py.eval("1+1"); emit (r, x); };
    ''',
    ["boot"], expect_error=True)

print("\n=== Модули .evol ===")
_tmp = tempfile.mkdtemp()
with open(os.path.join(_tmp, "mymod.evol"), "w") as f:
    f.write('lib counter { rule inc = when (inc, n) => { emit (val, n + 1); }; }')
with open(os.path.join(_tmp, "main.evol"), "w") as f:
    f.write('import "mymod.evol";\n'
            'rule start = when boot => { spawn counter.inc; emit (inc, 41); };\n'
            'rule show = when (val, n) => { console.print("v=", n); };')
all_ok &= test("module_import", None, ["boot"],
    check=lambda r: (any(isinstance(m, tuple) and len(m) == 2 and m[0].name == "val" and m[1] == 42
                         for m in r['emitted']),
                     f"emitted={r['emitted']}"),
    path=os.path.join(_tmp, "main.evol"))

print("\n=== M5: исчерпывающий match (P7) и арность (P8) ===")
prov, fail = proven_properties(parse('''
type Shape = Circle(r: Float) | Rect(w: Float, h: Float) | None;
rule start = when boot => {
  x := Rect(2.0, 3.0);
  y := match x { Circle(r) => r; Rect(w, h) => w * h; None => 0; };
  emit (ok, y);
};
''', "exh"))
all_ok &= test("m5_exhaustive_ok", None, None,
    check=lambda r: ("исчерпывающий match по enum 'Shape'" in prov
                     and "все ADT-конструкторы согласованы по арности с объявлением" in prov,
                     f"prov={prov}"))

prov2, fail2 = proven_properties(parse('''
type Shape = Circle(r: Float) | Rect(w: Float, h: Float) | None;
rule start = when boot => {
  x := Circle(3.0);
  y := match x { Circle(r) => r; Rect(w, h) => w * h; };
  bad := Rect(1.0);
  emit (ok, y);
};
''', "non_exh"))
all_ok &= test("m5_exhaustive_fail", None, None,
    check=lambda r: (any("непокрыты варианты" in f for f in fail2)
                     and any("конструктор Rect" in f for f in fail2),
                     f"fail={fail2}"))

print("\n" + ("ALL TESTS PASSED" if all_ok else "SOME TESTS FAILED"))
sys.exit(0 if all_ok else 1)
