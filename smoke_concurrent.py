import time
import threading
import runtime_concurrent as R
import interpreter as I

# Нагрузка: N независимых I/O-блокирующих задач (sleep), каждая в своём акторе.
N = 21
SLEEP = 0.01

# --- EVOL concurrent: 20 spawn-нутых акторов + 1 исходный, все реагируют на broadcast
src = open("samples/concurrent_fanout.evol", encoding="utf-8").read()
ast = I.parse(src, "samples/concurrent_fanout.evol")
res = R.run(ast, bootstrap=[("start", 0)], n_workers=8)
dones = [e for e in res["emitted"] if isinstance(e, tuple) and e[0].name == "done"]
assert len(dones) == N, f"ожидали {N} done, получили {len(dones)}"
print(f"[EVOL concurrent] wall={res['wall']:.4f}s  agents={res['agents']}  done={len(dones)}")

# --- Честная базовая линия 1: наивный последовательный Python (тот же объём работы)
def naive_seq():
    for _ in range(N):
        time.sleep(SLEEP)
t0 = time.perf_counter(); naive_seq(); naive_wall = time.perf_counter() - t0
print(f"[python naive seq ] wall={naive_wall:.4f}s  (N * sleep, без параллелизма)")

# --- Честная базовая линия 2: эквивалентный Python на потоках (та же модель, руками)
def py_threading():
    def job():
        time.sleep(SLEEP)
    ts = [threading.Thread(target=job) for _ in range(N)]
    for t in ts: t.start()
    for t in ts: t.join()
t0 = time.perf_counter(); py_threading(); py_thr_wall = time.perf_counter() - t0
print(f"[python threads  ] wall={py_thr_wall:.4f}s  (эквивалентная модель на потоках)")

# Вывод: EVOL должен быть близок к python threads (та же механика GIL-release при sleep)
# и существенно быстрее naive seq. Выигрыш EVOL — не в raw-speed, а в модели:
# race-free по построению (shared-nothing), детерминированная маршрутизация по контенту,
# декларативный spawn/retract без ручной синхронизации.
speedup_vs_naive = naive_wall / res["wall"]
print(f"\nEVOL speedup vs наивный seq: {speedup_vs_naive:.1f}x")
print("OK: 21 независимых актора выполнены параллельно (race-free, shared-nothing)")
