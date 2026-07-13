"""Прогон приёмки опции C: Rust-baseline (M1) + M3 (энтропия).

Запуск: python test_option_c.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "metrics"))

from metrics import option_c as C


def check(name, cond, detail=""):
    status = "[OK]  " if cond else "[FAIL]"
    print(f"{status} {name}" + (f" -- {detail}" if detail and not cond else ""))
    return cond


def main():
    fails = []
    # Rust-токенизатор работает
    rt = C.rust_tokens(C.rust_dispatcher(10))
    if not check("rust_tokens: >0", rt > 0, f"tokens={rt}"):
        fails.append("rust_tokens")

    # M1 EVOL/Rust: dispatcher — EVOL компактнее (отлично <0.5)
    from metrics import run_metrics as R
    e_src, _ = R.gen_dispatcher(100)
    r_src = C.rust_dispatcher(100)
    t_e = R.evol_tokens(e_src)
    t_r = C.rust_tokens(r_src)
    ratio = t_e / t_r
    if not check("M1 EVOL/Rust dispatcher < 0.5 (отлично)", ratio < 0.5, f"ratio={ratio:.3f}"):
        fails.append("M1 dispatcher vs rust")

    # M3: энтропия кандидата не выше baseline (<1.0)
    hc, hb, m3 = C.metric3(
        [R.gen_dispatcher(50)[0], C.evol_dispatcher_explicit(50)],
        [R.gen_dispatcher(50)[1], C.py_dispatcher_explicit(50)],
    )
    if not check("M3: Hc/Hb < 1.0 (кандидат не энтропийнее baseline)", m3 < 1.0, f"ratio={m3:.3f}"):
        fails.append("M3 ratio")

    print("\n" + "=" * 50)
    if fails:
        print(f"ПРОВАЛ: {fails}")
        sys.exit(1)
    print("ОПЦИЯ C ПРИНЯТА: второй baseline (Rust) + M3 посчитаны.")


if __name__ == "__main__":
    main()
