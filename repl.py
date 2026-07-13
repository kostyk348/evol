"""EVOL REPL — интерактивная оболочка с hot reload.

Поддерживает:
  :load <file>          — загрузить .evol файл
  :reload               — перезагрузить последний файл (hot reload)
  :step [n]             — выполнить n шагов (по умолчанию 1)
  :run [n]              — выполнить до остановки или n шагов
  :store                — показать текущее состояние
  :queue                — показать очередь сообщений
  :rules                — показать установленные правила
  :emit <msg>           — добавить сообщение в очередь
  :spawn <lib>.<rule>   — добавить правило на лету
  :retract <name>       — удалить правило
  :watch <file>         — следить за файлом и перезагружать
  :unwatch              —停止 следить
  :checkpoint <file>    — сохранить состояние в файл
  :restore <file>       — восстановить состояние из файла
  :time                 — показать текущее время симуляции
  :dt <value>           — установить шаг времени
  :help                 — показать справку
  :quit                 — выйти

Интерактивный ввод без : — это EVOL-выражение или эффект.
"""

import sys
import os
import time
import json
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import parse
from interpreter import run, eval_eff, evaluate, collect_rule_table, make_value, Symbol, InterpreterError


class SimState:
    """Инкапсулирует состояние симуляции для REPL."""

    def __init__(self):
        self.sigma = {}
        self.queue = []
        self.rules = []
        self.steps = 0
        self.emit_log = []
        self.time = 0.0
        self.dt = 1.0
        self.max_steps = 100000
        self._rule_id_counter = 0
        self._file_hashes = {}
        self._watched_files = {}

    def load_file(self, path):
        with open(path, encoding="utf-8") as f:
            src = f.read()
        ast = parse(src, path)
        self._load_ast(ast, source=path)
        self._file_hashes[path] = self._file_hash(path)
        return f"Загружено: {path} ({len(self.rules)} правил)"

    def _load_ast(self, ast, source="loaded"):
        table = collect_rule_table(ast)
        for (lib, name), node in table.items():
            self.rules.append({
                "id": self._rule_id_counter,
                "name": name,
                "lib": lib,
                "prio": 0,
                "pat": node.pat,
                "eff": node.body,
                "source": source,
            })
            self._rule_id_counter += 1

    def hot_reload(self, path):
        old_count = len(self.rules)
        self.rules = [r for r in self.rules if r.get("source") != path]
        with open(path, encoding="utf-8") as f:
            src = f.read()
        ast = parse(src, path)
        table = collect_rule_table(ast)
        for (lib, name), node in table.items():
            self.rules.append({
                "id": self._rule_id_counter,
                "name": name,
                "lib": lib,
                "prio": 0,
                "pat": node.pat,
                "eff": node.body,
                "source": path,
            })
            self._rule_id_counter += 1
        new_count = len(self.rules)
        self._file_hashes[path] = self._file_hash(path)
        return f"Hot reload: {path} — правил было {old_count}, стало {new_count}"

    def step(self, n=1):
        result_log = []
        for _ in range(n):
            if not self.queue:
                result_log.append("Очередь пуста, шагов не выполнено.")
                break
            if self.steps >= self.max_steps:
                result_log.append(f"Достигнут лимит {self.max_steps} шагов.")
                break
            self.steps += 1
            self.time += self.dt
            msg = self.queue.pop(0)
            matched = False
            for r in self.rules:
                from interpreter import match as evol_match
                bindings = evol_match(r["pat"], msg)
                if bindings is not None:
                    local = dict(self.sigma)
                    local.update(bindings)
                    new_sigma, emits, spawned, retracted = eval_eff(r["eff"], local)
                    self.sigma = new_sigma
                    for v in emits:
                        self.queue.append(v)
                        self.emit_log.append(v)
                    for sp in spawned:
                        self.rules.append({
                            "id": self._rule_id_counter,
                            "name": sp.name,
                            "lib": sp.lib,
                            "prio": 0,
                            "pat": None,
                            "eff": None,
                            "source": "spawned",
                        })
                        self._rule_id_counter += 1
                    if retracted:
                        self.rules = [x for x in self.rules if x["name"] not in retracted]
                    matched = True
                    break
            if not matched:
                result_log.append(f"Шаг {self.steps}: сообщение {msg} не совпало ни с одним правилом.")
        return "\n".join(result_log) if result_log else f"Выполнено {n} шагов. Время: {self.time:.1f}"

    def run(self, max_steps=None):
        limit = max_steps or self.max_steps
        start = self.steps
        while self.queue and self.steps - start < limit:
            self.step(1)
        return f"Выполнено {self.steps - start} шагов. Время: {self.time:.1f}. Очередь: {len(self.queue)}"

    def emit_msg(self, msg_str):
        parts = msg_str.split(",")
        tag = parts[0].strip()
        if len(parts) == 1:
            self.queue.append(Symbol(tag))
        else:
            vals = []
            for p in parts[1:]:
                p = p.strip()
                try:
                    vals.append(int(p))
                except ValueError:
                    try:
                        vals.append(float(p))
                    except ValueError:
                        vals.append(p.strip('"'))
            self.queue.append(tuple([Symbol(tag)] + vals))
        return f"Добавлено: ^{tag} в очередь ({len(self.queue)} сообщений)"

    def add_rule_interactive(self, lib_name, rule_name, pat_str, eff_code):
        from lexer import tokenize
        pat_ast = parse(f"lib _ {{ rule _ = when {pat_str} => {{ pass }} }}", "<interactive>")
        pat_node = pat_ast[0].decls[0].pat
        eff_ast = parse(f"lib _ {{ rule _ = when boot => {{ {eff_code} }} }}", "<interactive>")
        eff_node = eff_ast[0].decls[0].body
        self.rules.append({
            "id": self._rule_id_counter,
            "name": rule_name,
            "lib": lib_name,
            "prio": 0,
            "pat": pat_node,
            "eff": eff_node,
            "source": "interactive",
        })
        self._rule_id_counter += 1
        return f"Правило добавлено: {lib_name}.{rule_name}"

    def retract_rule(self, name):
        before = len(self.rules)
        self.rules = [r for r in self.rules if r["name"] != name]
        after = len(self.rules)
        return f"Удалено правил: {before - after}"

    def checkpoint(self, path):
        data = {
            "sigma": {k: v for k, v in self.sigma.items()},
            "queue": [self._serialize_msg(m) for m in self.queue],
            "steps": self.steps,
            "time": self.time,
            "dt": self.dt,
            "rule_count": len(self.rules),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        return f"Checkpoint сохранён: {path}"

    def restore(self, path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.sigma = data.get("sigma", {})
        self.queue = [self._deserialize_msg(m) for m in data.get("queue", [])]
        self.steps = data.get("steps", 0)
        self.time = data.get("time", 0.0)
        self.dt = data.get("dt", 1.0)
        return f"Восстановлено: шаг={self.steps}, время={self.time:.1f}, очередь={len(self.queue)}"

    def check_watch(self):
        reloaded = []
        for path, old_hash in list(self._file_hashes.items()):
            if os.path.exists(path):
                new_hash = self._file_hash(path)
                if new_hash != old_hash:
                    reloaded.append(self.hot_reload(path))
        return reloaded

    def _file_hash(self, path):
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    def _serialize_msg(self, msg):
        if isinstance(msg, Symbol):
            return {"type": "sym", "name": msg.name}
        if isinstance(msg, tuple):
            return {"type": "tuple", "items": [self._serialize_msg(m) for m in msg]}
        return {"type": "val", "value": msg}

    def _deserialize_msg(self, d):
        if d["type"] == "sym":
            return Symbol(d["name"])
        if d["type"] == "tuple":
            return tuple(self._deserialize_msg(i) for i in d["items"])
        return d["value"]

    def show_rules(self):
        lines = []
        for r in self.rules:
            pat_str = r["pat"].__repr__() if r["pat"] else "?"
            lines.append(f"  [{r['id']}] {r['lib']}.{r['name']} ({r['source']})")
        return "\n".join(lines) if lines else "  (нет правил)"

    def show_store(self):
        if not self.sigma:
            return "  (пусто)"
        return "\n".join(f"  {k} = {v!r}" for k, v in sorted(self.sigma.items()))

    def show_queue(self):
        if not self.queue:
            return "  (пусто)"
        return "\n".join(f"  [{i}] {m!r}" for i, m in enumerate(self.queue[:20]))


HELP_TEXT = """
EVOL REPL — интерактивная оболочка
===================================

Файлы и загрузка:
  :load <file>          загрузить .evol файл
  :reload               hot reload последнего файла

Выполнение:
  :step [n]             выполнить n шагов (по умолчанию 1)
  :run [n]              выполнить до остановки или n шагов

Инспекция:
  :store                текущее состояние (store)
  :queue                очередь сообщений
  :rules                установленные правила
  :time                 текущее время симуляции

Изменение состояния:
  :emit <tag>           добавить сообщение (tag или tag,val1,val2)
  :spawn <lib>.<rule>   добавить правило на лету
  :retract <name>       удалить правило по имени

Hot reload:
  :watch <file>         следить за файлом
  :unwatch             停止 следить
  Автоматический reload при изменении файла.

Checkpoint:
  :checkpoint <file>    сохранить состояние
  :restore <file>       восстановить состояние

Время:
  :dt <value>           установить шаг времени

Справка:
  :help                 эта справка
  :quit                 выход

Интерактивный ввод:
  Просто введите EVOL-выражение или эффект — он будет выполнен.
"""


def format_msg(msg):
    if isinstance(msg, Symbol):
        return f"^{msg.name}"
    if isinstance(msg, tuple):
        parts = [format_msg(m) for m in msg]
        return f"({', '.join(parts)})"
    return repr(msg)


def repl_main():
    state = SimState()
    last_file = None
    watching = set()

    print("EVOL REPL v1.0 — введите :help для справки")

    while True:
        try:
            prompt = f"evol[{state.steps}|{state.time:.1f}]> "
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nВыход.")
            break

        if not line:
            continue

        if line == ":quit" or line == ":q":
            break

        if line == ":help" or line == ":h":
            print(HELP_TEXT)
            continue

        if line.startswith(":load"):
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                print("Использование: :load <file.evol>")
                continue
            path = parts[1].strip()
            if not os.path.exists(path):
                print(f"Файл не найден: {path}")
                continue
            result = state.load_file(path)
            last_file = path
            watching.add(path)
            print(result)
            continue

        if line == ":reload":
            if last_file:
                result = state.hot_reload(last_file)
                print(result)
            else:
                print("Файл не загружен.")
            continue

        if line.startswith(":step"):
            parts = line.split()
            n = int(parts[1]) if len(parts) > 1 else 1
            print(state.step(n))
            continue

        if line.startswith(":run"):
            parts = line.split()
            n = int(parts[1]) if len(parts) > 1 else None
            print(state.run(n))
            continue

        if line == ":store":
            print(state.show_store())
            continue

        if line == ":queue":
            print(state.show_queue())
            continue

        if line == ":rules":
            print(state.show_rules())
            continue

        if line == ":time":
            print(f"  время: {state.time:.1f}  шаг: {state.steps}  dt: {state.dt}")
            continue

        if line.startswith(":emit"):
            msg_str = line[len(":emit"):].strip()
            if not msg_str:
                print("Использование: :emit tag или :emit tag,val1,val2")
                continue
            print(state.emit_msg(msg_str))
            continue

        if line.startswith(":spawn"):
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                print("Использование: :spawn lib.rule_name")
                continue
            qualified = parts[1].strip()
            if "." not in qualified:
                print("Формат: lib.rule_name")
                continue
            lib_name, rule_name = qualified.split(".", 1)
            pat_str = input("  паттерн (when): ").strip()
            eff_code = input("  эффект: ").strip()
            print(state.add_rule_interactive(lib_name, rule_name, pat_str, eff_code))
            continue

        if line.startswith(":retract"):
            name = line[len(":retract"):].strip()
            print(state.retract_rule(name))
            continue

        if line.startswith(":watch"):
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                print("Использование: :watch <file.evol>")
                continue
            path = parts[1].strip()
            watching.add(path)
            state._file_hashes[path] = state._file_hash(path)
            print(f"Слежу за: {path}")
            continue

        if line == ":unwatch":
            watching.clear()
            print("Слежение отключено.")
            continue

        if line.startswith(":checkpoint"):
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                print("Использование: :checkpoint <file.json>")
                continue
            print(state.checkpoint(parts[1].strip()))
            continue

        if line.startswith(":restore"):
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                print("Использование: :restore <file.json>")
                continue
            print(state.restore(parts[1].strip()))
            continue

        if line.startswith(":dt"):
            parts = line.split()
            if len(parts) < 2:
                print(f"  dt = {state.dt}")
                continue
            state.dt = float(parts[1])
            print(f"  dt = {state.dt}")
            continue

        # EVOL-выражение/эффект
        try:
            wrapped = f"lib _repl {{ rule _ = when boot => {{ {line} }} }}"
            ast = parse(wrapped, "<repl>")
            rule_node = ast[0].decls[0]
            local = dict(state.sigma)
            new_sigma, emits, spawned, retracted = eval_eff(rule_node.body, local)
            state.sigma = new_sigma
            for v in emits:
                state.queue.append(v)
                state.emit_log.append(v)
            if state.sigma != local:
                changed = {k: v for k, v in state.sigma.items() if local.get(k) != v}
                if changed:
                    print(f"  store: {changed}")
            if emits:
                print(f"  emit: {[format_msg(m) for m in emits]}")
        except Exception as e:
            print(f"  Ошибка: {e}")

        # Hot reload check
        if watching:
            reloaded = state.check_watch()
            for msg in reloaded:
                print(f"  [hot-reload] {msg}")


if __name__ == "__main__":
    repl_main()
