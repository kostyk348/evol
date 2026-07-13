"""Приёмка Этапа 7: аннотации типов + статическая проверка.

Запуск: python test_types.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import parse
from typechecker import typecheck
from interpreter import run, set_enforce_types


SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")


def check(name, cond, detail=""):
    status = "[OK]  " if cond else "[FAIL]"
    print(f"{status} {name}" + (f" -- {detail}" if detail and not cond else ""))
    return cond


def parse_ok(src, fn="<inline>"):
    return parse(src, fn)


def main():
    fails = []

    # 1) корректная аннотированная программа проходит тайпчек
    good = '''
    lib t {
      rule start = when boot => {
        n : Int := 0
        s : Str := "hi"
        f : Float := 1.5
        inc := fun (x : Int) -> Int => x + 1
        m := inc(n)
        xs : List[Int] := [1, 2, 3]
        emit (done)
      }
    }
    '''
    errs = typecheck(parse_ok(good))
    if not check("аннотации: корректная программа принята", len(errs) == 0, str(errs)):
        fails.append("good rejected")

    # 2) несовпадение типа в присваивании отклоняется
    bad_assign = '''
    lib t {
      rule start = when boot => {
        n : Int := "строка"
        emit (done)
      }
    }
    '''
    errs = typecheck(parse_ok(bad_assign))
    if not check("аннотации: несовпадение в присваивании отклонено",
                 any("присваивание" in e for e in errs), str(errs)):
        fails.append("bad_assign accepted")

    # 3) несовпадение типа аргумента функции отклоняется
    bad_arg = '''
    lib t {
      rule start = when boot => {
        inc := fun (x : Int) -> Int => x + 1
        m := inc("нет")
        emit (done)
      }
    }
    '''
    errs = typecheck(parse_ok(bad_arg))
    if not check("аннотации: несовпадение аргумента отклонено",
                 any("параметром" in e for e in errs), str(errs)):
        fails.append("bad_arg accepted")

    # 4) несовпадение типа результата функции отклоняется
    bad_ret = '''
    lib t {
      rule start = when boot => {
        f := fun (x : Int) -> Int => x > 0
        emit (done)
      }
    }
    '''
    errs = typecheck(parse_ok(bad_ret))
    if not check("аннотации: тип результата отклонён",
                 any("результата" in e for e in errs), str(errs)):
        fails.append("bad_ret accepted")

    # 5) числовая совместимость: Int <: Float (присваивание Int в Float)
    num = '''
    lib t {
      rule start = when boot => {
        x : Float := 5
        emit (done)
      }
    }
    '''
    errs = typecheck(parse_ok(num))
    if not check("аннотации: Int присваиваем в Float", len(errs) == 0, str(errs)):
        fails.append("numeric rejected")

    # 6) аннотации полей сообщения (паттерн)
    pat = '''
    lib t {
      rule start = when boot => { emit (msg, "hello", 3) }
      rule handler = when (msg, text : Str, count : Int) => {
        n : Int := count + 1
        emit (done)
      }
    }
    '''
    errs = typecheck(parse_ok(pat))
    if not check("аннотации: поля сообщения приняты", len(errs) == 0, str(errs)):
        fails.append("pattern rejected")

    # 7) unannotated программы по-прежнему проходят (постепенная типизация)
    plain = '''
    lib t {
      rule start = when boot => {
        x := 1 + 2
        emit (done)
      }
    }
    '''
    errs = typecheck(parse_ok(plain))
    if not check("аннотации: неаннотированная программа принята", len(errs) == 0, str(errs)):
        fails.append("plain rejected")

    # 8) runtime-проверка аннотаций (enforce_types=True) ловит несовпадение
    set_enforce_types(True)
    try:
        run(parse_ok(bad_assign), ["boot"], enforce_types=True)
        caught = False
        detail = "исключение не брошено"
    except Exception as e:
        caught = True
        detail = str(e)
    if not check("аннотации: runtime ловит несовпадение присваивания",
                 caught, detail):
        fails.append("runtime assign not enforced")

    # 9) runtime-проверка аннотаций ловит несовпадение поля сообщения
    bad_field = '''
    lib t {
      rule start = when boot => { emit (msg, "hello", "не-int") }
      rule handler = when (msg, text : Str, count : Int) => {
        n : Int := count + 1
        emit (done)
      }
    }
    '''
    try:
        run(parse_ok(bad_field), ["boot"], enforce_types=True)
        caught = False
        detail = "исключение не брошено"
    except Exception as e:
        caught = True
        detail = str(e)
    if not check("аннотации: runtime ловит несовпадение поля сообщения",
                 caught, detail):
        fails.append("runtime field not enforced")

    # 10) корректная программа исполняется и с enforce_types=True
    res = run(parse_ok(pat), ["boot"], enforce_types=True)
    if not check("аннотации: корректная программа исполняется (enforce)",
                 res["emitted"][-1] == "done" or
                 (hasattr(res["emitted"][-1], "name") and res["emitted"][-1].name == "done"),
                 str(res["emitted"])):
        fails.append("good did not run")

    print("\n" + "=" * 50)
    if fails:
        print(f"ПРОВАЛ: {fails}")
        sys.exit(1)
    print("ЭТАП 7 ПРИНЯТ: аннотации типов парсятся, статически проверяются и "
          "опционально проверяются на runtime.")


if __name__ == "__main__":
    main()
