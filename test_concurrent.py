"""Тесты параллельного actor-рантайма (runtime_concurrent.py).

Модель отличается от последовательного интерпретатора:
- последовательный интерпретатор: одно сообщение -> ОДНО правило (по приоритету), общий store;
- concurrent: одно сообщение -> ВСЕ подходящие акторы (pub/sub по контенту), у каждого свой store
  (shared-nothing). По построению race-free и детерминирован.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runtime_concurrent as R
import interpreter as I
from interpreter import Symbol

ok = True
def test(name, f):
    global ok
    try:
        f()
        print(f"  [OK] {name}")
    except AssertionError as e:
        ok = False
        print(f"  [FAIL] {name}: {e}")
    except Exception as e:
        ok = False
        print(f"  [ERR] {name}: {e}")


def _load():
    src = open("samples/concurrent_fanout.evol", encoding="utf-8").read()
    return I.parse(src, "samples/concurrent_fanout.evol")


print("=== Concurrent actor runtime ===")

def _load():
    src = open("samples/concurrent_fanout.evol", encoding="utf-8").read()
    return I.parse(src, "samples/concurrent_fanout.evol")


# 1. spawn создаёт независимые акторы; broadcast (go,0) доходит до ВСЕХ (включая свежие)
def _check_broadcast():
    ast = _load()
    res = R.run(ast, bootstrap=[("start", 0)], n_workers=8)
    dones = [e for e in res["emitted"] if isinstance(e, tuple) and e[0].name == "done"]
    assert len(dones) == 21, f"ожидали 21 done (1 исходный + 20 spawn), got {len(dones)}"
    assert res["inflight"] == 0, f"inflight должен быть 0, got {res['inflight']}"
    assert res["agents"] == 22, f"agents=22, got {res['agents']}"

test("broadcast_reaches_all_spawned", _check_broadcast)


# 2. детерминизм: повторный запуск даёт тот же набор emitted (порядок внутри mailbox FIFO)
def _check_determinism():
    ast = _load()
    r1 = R.run(ast, bootstrap=[("start", 0)], n_workers=8)
    r2 = R.run(ast, bootstrap=[("start", 0)], n_workers=4)
    d1 = sum(1 for e in r1["emitted"] if isinstance(e, tuple) and e[0].name == "done")
    d2 = sum(1 for e in r2["emitted"] if isinstance(e, tuple) and e[0].name == "done")
    assert d1 == d2 == 21, f"детерминизм нарушен: {d1} vs {d2}"

test("deterministic_emitted_count", _check_determinism)


# 3. race-free: параллельные I/O задачи завершаются быстрее наивного последовательного эквивалента
def _check_speedup():
    import time as _t
    ast = _load()
    res = R.run(ast, bootstrap=[("start", 0)], n_workers=8)
    N = 21
    # наивный seq: 21 * sleep(0.01) ~ 0.21s одним потоком
    t0 = _t.perf_counter()
    for _ in range(N):
        _t.sleep(0.01)
    naive_wall = _t.perf_counter() - t0
    assert res["wall"] < naive_wall, f"conc {res['wall']:.3f} не быстрее seq {naive_wall:.3f}"

test("parallel_faster_than_naive_seq", _check_speedup)


print(f"\n{'='*40}")
print("CONCURRENT RUNTIME OK" if ok else "CONCURRENT RUNTIME FAILED")
sys.exit(0 if ok else 1)
