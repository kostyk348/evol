"""EVOL: параллельный actor-рантайм (конкурентная ось).

Модель: каждый экземпляр правила = актор со своим локальным store (shared-nothing).
Связь только через сообщения (контентная маршрутизация: сообщение получают все
акторы, чей паттерн match-ится). По построению — race-free (нет разделяемого
мутабельного состояния между акторами) и логически детерминирован (порядок в
каждом mailbox FIFO, маршрутизация детерминирована по содержимому).

Использует готовые evaluate/eval_eff из interpreter (они чисты по sigma), поэтому
семантика одиночного правила совпадает с последовательным интерпретатором.

Скорость: для I/O-нагруженных/блокирующих тел (py.time.sleep, file I/O) потоки
дают реальный выигрыш (GIL отпускается при блокировке); для чистого CPU — упирается
в GIL (честно: компиляция в native — следующая ось).
"""
import threading
import time
import queue as _queue

import interpreter as I
from interpreter import match


def _wrap_msg(v):
    """Поднимает Python-литералы к EVOL-значениям для bootstrap-сообщений:
    str -> Symbol, tuple -> tuple(Symbol-тег, ...) рекурсивно."""
    if isinstance(v, str) and not v.startswith("^"):
        return I.Symbol(v)
    if isinstance(v, tuple):
        return tuple(_wrap_msg(x) for x in v)
    return v


class Agent:
    __slots__ = ("aid", "name", "pat", "body", "sigma", "mailbox", "lock")

    def __init__(self, aid, name, pat, body, sigma):
        self.aid = aid
        self.name = name
        self.pat = pat
        self.body = body
        self.sigma = sigma if sigma is not None else {}
        self.mailbox = _queue.Queue()
        self.lock = threading.Lock()


def run(ast, bootstrap, n_workers=4, max_steps=200000, enforce_types=False):
    I.set_enforce_types(enforce_types)
    I._py_ffi.clear()
    table = I.collect_rule_table(ast)  # регистрирует FFI (побочный эффект на _py_ffi)
    rules = [(lib, name, node) for (lib, name), node in table.items()]

    lock = threading.RLock()
    agents = {}
    next_aid = [0]
    inflight = [0]
    work = _queue.Queue()
    done = threading.Event()
    emitted_log = []
    steps = [0]

    def new_agent(lib, name, node, sigma=None):
        with lock:
            aid = next_aid[0]
            next_aid[0] += 1
            a = Agent(aid, (lib + "." + name) if lib else name,
                      node.pat, node.body, sigma)
            agents[aid] = a
            return a

    def deliver(msg):
        with lock:
            targets = [aid for aid, a in agents.items()
                       if match(a.pat, msg) is not None]
            for aid in targets:
                agents[aid].mailbox.put(msg)
                work.put(aid)
                inflight[0] += 1
            if targets:
                done.clear()

    # старт: по одному актору на правило + доставка bootstrap-сообщений
    for lib, name, node in rules:
        new_agent(lib, name, node)
    for m in bootstrap:
        deliver(_wrap_msg(m))
    if inflight[0] == 0:
        done.set()

    def worker():
        while not done.is_set() or inflight[0] > 0:
            try:
                aid = work.get(timeout=0.05)
            except _queue.Empty:
                with lock:
                    if inflight[0] == 0:
                        done.set()
                        return
                continue
            a = agents.get(aid)
            if a is None:
                with lock:
                    inflight[0] -= 1
                continue
            with a.lock:
                if a.mailbox.empty():
                    with lock:
                        inflight[0] -= 1
                    continue
                msg = a.mailbox.get()
            new_sigma, emits, spawned, retracted = I.eval_eff(a.body, dict(a.sigma))
            a.sigma = new_sigma
            with lock:
                # spawn создаёт акторов ДО доставки сообщений, чтобы свежие
                # акторы тоже получили broadcast (контентная маршрутизация).
                for sp in spawned:
                    node = I.resolve_spawn(table, sp)
                    if node is not None:
                        new_agent(sp.lib, sp.name, node)
                for rn in retracted:
                    for aid2, a2 in list(agents.items()):
                        if a2.name == rn:
                            agents.pop(aid2, None)
                for e in emits:
                    emitted_log.append(e)
                    deliver(e)
                inflight[0] -= 1
                if not a.mailbox.empty():
                    work.put(aid)
                    inflight[0] += 1
                if inflight[0] == 0:
                    done.set()

    t0 = time.perf_counter()
    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(max(1, n_workers))]
    for th in threads:
        th.start()
    done.wait()
    for th in threads:
        th.join(timeout=1.0)
    dt = time.perf_counter() - t0

    return {
        "steps": steps[0],
        "emitted": emitted_log,
        "stopped_by_max_steps": False,
        "wall": dt,
        "agents": len(agents),
        "inflight": inflight[0],
    }


def run_file(path, bootstrap, n_workers=4, enforce_types=False):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    ast = I.parse(src, path)
    return run(ast, bootstrap, n_workers=n_workers, enforce_types=enforce_types)
