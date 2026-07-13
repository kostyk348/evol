# EVOL — язык переходов состояний (proof-of-concept)

Экспериментальный язык, оптимизированный под **скорость эволюции инженерных
идей** (не под производительность рантайма и не под типобезопасность как таковую).
Каждая конструкция — это правило перехода абстрактной машины, поэтому семантика
задаётся явно, без «магии».

Проект реализован по цепочке документов `lang-design-spec` → `lang-implementation-roadmap`
→ `lang-scaling-corpus` (phases 0–7 roadmap). Статус: **Этапы 1–6 выполнены**.

---

## Что реализовано

| Этап | Модуль | Суть |
|---|---|---|
| 1 | — (бумага) | EBNF-грамматика + формальная семантика АМ (`δ(S)→S′`) |
| 2 | `lexer.py`, `ast_nodes.py`, `parser.py` | Лексер + AST + рекурсивный спуск |
| 3 | `interpreter.py` | AST-walking интерпретатор (`Σ, Μ, Q`) |
| 4 | `typechecker.py` | Тайпчекер (реально отклоняет ошибки) + доказательщик свойств (M5) |
| 5 | `metrics/run_metrics.py` | Генератор scaling-корпуса + подсчёт M1–M5 |
| Опция A | `parser.py`, `interpreter.py` | `forall x in expr` + встроенные `range`, `len` — O(1) токенов по N |
| Опция B | `metrics/smt_prove.py` | z3-SMT: проверка эксклюзивности + полноты гвардов (M5-SMT) |
| Опция C | `metrics/option_c.py` | Rust-baseline (генераторы + токен-счётчик) + энтропия M3 |
| Опция D | `lexer.py`..`interpreter.py` | `import` внешних модулей + квалифицированный `spawn Lib.Rule` |
| Float | `lexer.py`..`compiler.py` | Тип `FLOAT` (динамический) в лексере/парсере/интерпретере/тийпчекере/компиляторе |
| Error handling | `parser.py`, `interpreter.py` | `try/catch/raise` — ловит InterpreterError + EvalError |
| Corpus #2 | `metrics/corpus2.py` | Held-out корпус (6 задач, seeds зафиксированы, без утечки) |
| Этап 7 | `lexer.py`, `parser.py`, `ast_nodes.py`, `typechecker.py`, `interpreter.py`, `compiler.py` | **Аннотации типов**: статическая проверка (Int/Str/Bool/Float/Sym/List[T]/Top) + опциональная runtime-проверка через `enforce_types=True` |

---

## Быстрый старт

```bash
cd evol
python test_parser.py          # валидное принято, невалидное отклонено
python test_interpreter.py     # семантика, par, forall, квалифицированный spawn
python test_typechecker.py     # ошибки типов/spawn/import, M5
python test_smt.py             # SMT-проверка гвардов (z3)
python test_option_c.py        # Rust-baseline + M3 энтропия
python test_stdlib.py        # модули: console, random, file, sim, math, string, os
python test_repl.py          # REPL: hot reload, checkpoint, time
python test_new_features.py  # FLOAT, try/catch/raise, math/string/os модули
python test_types.py         # Этап 7: аннотации типов, статическая + runtime проверка
python metrics/run_metrics.py  # полная таблица метрик (6 задач, прогон #1)
python metrics/corpus2.py      # held-out корпус #2 (6 задач, без утечки)
python repl.py                 # REPL: интерактивная оболочка
python compiler.py file.evol   # транспиляция EVOL → Python
```

Требуется Python 3.10+ (использовался 3.14). Для опции B нужен `z3-solver` (`pip install z3-solver`).
Остальные зависимости — только стандартная библиотека.

---

## Модель исполнения

Состояние абстрактной машины `S = (Σ, Μ, Q)`:
- `Σ` — store (`name → value`);
- `Μ` — очередь сообщений;
- `Q` — множество установленных правил `when <pat> => <eff>`.

Шаг `δ`: взять головное сообщение, найти подходящее правило (по тегу паттерна,
макс. приоритет), выполнить эффект. Несовпавшие сообщения отбрасываются.

Эффекты:
`assign (x := e)` · `emit (m)` · `spawn Name` · `retract Name` ·
`if c then … else …` · `seq(a,b)` · `par(a,b)` (отказ при конфликте имён) ·
`choice(a,b)` · `loop(guard, body)` · `forall x in expr { … }` · встроенные `range`, `len`, `abs`, `min`, `max`, `str`, `int`, `float`.
`try { … } catch var { … }` · `raise expr` — ловит InterpreterError + EvalError.

Импорт: `import ModuleName` (из файла `modulename.evol`). Квалифицированный спавн:
`spawn Lib.Rule` (проверяется тайпчекером, срабатывает из внешнего модуля).

Пример (`samples/demo_counter.evol`):
```evol
lib demo {
  rule start = when boot => {
    n := 0
    emit (run)
  }
  rule step = when run => {
    if n < 5 then { emit (tick); n := n + 1; emit (run) }
             else { emit (done) }
  }
}
```

---

## Статическая типизация (Этап 7)

Аннотации типов **опциональны** и не меняют динамическую семантику исполнения —
они управляют статическим тайпчекером (`typechecker.py`) и, при желании,
runtime-проверкой (`run(..., enforce_types=True)`).

Типы: `Int`, `Str`, `Bool`, `Float`, `Sym`, `List[T]`, `Top` (верхний тип).
Числовая совместимость: `Int <: Float` (целое можно присвоить вещественному).
Система **постепенная** (gradual): неаннотированный код типизируется как `Top` и
проходит проверку; проверяются только те места, где тип известен с обеих сторон.

Синтаксис:

```evol
lib t {
  rule start = when boot => {
    n : Int := 0                       # аннотация переменной
    xs : List[Int] := [1, 2, 3]        # список с элементом типа
    add := fun (a : Int, b : Int) -> Int => a + b   # типы параметров + результата
    total := add(n, 3)
    emit (go, total)
  }
  rule process = when (go, value : Int) => {   # аннотация поля входящего сообщения
    emit (done)
  }
}
```

Что отклоняется:
- присваивание значения несовместимого типа (`x : Int := "s"`);
- аргумент вызова, не совпадающий с аннотированным параметром (`f("s")` при `f(x:Int)`);
- тип результата функции, не совпадающий с `-> T`;
- несовместимые операнды арифметики/сравнения.

Runtime-проверка (`enforce_types=True`) ловит те же несовпадения во время исполнения
(включая аннотированные поля сообщений из `match`). По умолчанию выключена — язык
остаётся динамическим, как и задумано для proof-of-concept.

Транспилятор (`compiler.py`) сохраняет аннотации как комментарии и теперь компилирует
closure-присваивания (`x := fun (...) => ...`) в тела Python-функций.

## Результаты метрик

### Прогон #1 (scaling-корпус, с утечкой)

> Честность метрик (см. оговорку #2): baseline Python бывает двух видов.
> **naive** — явное развёртывание N веток dispatch (как писал бы студент на экзамене);
> **idiomatic** — `dict`/функция-диспетчер за O(1) токенов (как пишет питонист на практике).
> M1 против naive занижает Python и завышает EVOL — это меряет «glue-рост», а НЕ
> выразительность. **M1_fair** (против idiomatic) — честное сравнение.

| Метрика | Зона | Сырое число | Форма M(N) |
|---|---|---|---|
| M1 vs naive-Py (unrolled) | отлично* | dispatcher=0.61, FSM=0.11, pipeline=0.18, fanout=0.19, router=0.18 | плоская |
| **M1_fair vs idiomatic-Py (O(1))** | хорошо (паритет) | dispatcher=0.61, FSM=0.69, pipeline=0.69, fanout=**1.83**, router=0.69 | плоская |
| M1 компрессия vs Rust | отлично | dispatcher=0.49, FSM=0.12, pipeline=0.24, fanout=0.21, router=0.23 | плоская |
| M2 рекомбинация | отлично | 100% пар компонуются | плоская |
| M3 энтропия | терпимо/хорошо | ratio=0.70–0.80 к Python | плоская |
| M4 сем. компрессия | стабильно | 2–17 токенов/шаг АМ | плоская |
| M5 стат. глубина вывода | хорошо | 2–6 свойств/прогон | плоская |
| M5-SMT (z3) | отлично | 0–2 по задачам | н/д |

\* M1 против naive завышен искусственно (см. оговорку #2) — не читать как «EVOL в 5–9 раз компактнее Python».

### Прогон #2 (held-out corpus, без утечки)

Seeds зафиксированы ДО замера: `20260713-1`..`20260713-5`. Грамматика LOCKED.

| Задача | N=10 M1_naive | N=100 M1_naive | N=1000 M1_naive | N=10000 M1_naive | **M1_fair** | M2 | M3 | M5 | M5-SMT |
|--------|---------------|----------------|-----------------|------------------|-------------|-----|-----|-----|--------|
| dispatcher (DAG) | 0.324 | 0.041 | 0.004 | 0.000 | **0.94** | 100% | 0.682 | 3 | 2 |
| FSM (2 shared vars) | 0.109 | 0.012 | 0.001 | — | **0.66** | 100% | 0.800 | 4 | 2 |
| pipeline (parallel) | 0.182 | 0.021 | 0.002 | — | **0.66** | 100% | 0.706 | 4 | 2 |
| **ratelimiter** (NEW) | 0.277 | 0.030 | 0.003 | — | **0.67** | 100% | 0.819 | 4 | 3 |
| **cache** (NEW) | 0.339 | 0.040 | 0.004 | — | **0.62** | 100% | 0.666 | 4 | 2 |
| **httprouter** (control) | 0.231 | — | — | — | **0.94** | 100% | — | 4 | 2 |

Форма M1_naive(N): монотонно ↓ (artifact развёртывания Python, НЕ заслуга EVOL).
Форма **M1_fair(N): плоская** (~0.6–0.9) — честный результат: EVOL с `forall`
достигает **паритета** с idiomatic Python на dispatch-задачах, а на fanout (прогон #1)
**превосходит** (1.83) за счёт компактного `spawn`+`forall`.

**Сравнение прогонов:** FSM и pipeline — стабильно по M1_fair (0.66–0.69). Dispatcher
в прогоне #2 компактнее за счёт другого шаблона (M1_fair=0.94). **Первый прогон не был
эффектом утечки — результаты воспроизводятся.** Новые задачи (ratelimiter, cache)
показывают ту же плоскую форму M1_fair — грамматика généralise beyond 3 паттерна.

Честный вывод: гипотеза «EVOL масштабируется без ручного развёртывания» **подтверждена**
(M1_fair плоский, ни одна кривая не суперлинейна, включая N=10000). Но заявление
«EVOL в разы компактнее Python» **неверно** против idiomatic baseline — там паритет.
Ценность EVOL — в детерминированной АМ-семантике и M5-выводе, а не в токенах.

---

## Важные оговорки

1. **Anti-Goodhart.** Прогон #1 использовал корпус, известный агенту-дизайнеру.
   Прогон #2 (corpus #2) — held-out, seeds зафиксированы, грамматика LOCKED.
   Результаты воспроизводятся, нет признаков утечки.
2. **Baseline — два вида, честно.** `naive`-baseline разворачивает N веток dispatch
   (явный glue-рост) — поэтому M1_naive занижает Python и Artifактно завышает EVOL.
   Рядом всегда считается **M1_fair** против idiomatic `dict`-диспетчера (O(1) токенов) —
   это честное сравнение выразительности. ВСЕГДА смотрите на M1_fair, а не только на M1_naive.
3. **M3 энтропия — НЕ независимая мера.** Варианты `forall`/`EXPLICIT` генерируются
   **одним и тем же генератором** (это разные проходы машины, а не разные авторы).
   Значение ~0.67–0.82 не доказывает «независимую читаемость» — оно лишь показывает,
   что компактная форма беднее вариантами. Трактовать как слабое косвенное свидетельство.
4. **M3/M5 на малых N.** M3 считается только для N≤100 (в прогоне #1) и N≤100 (прогон #2);
   M5-SMT — только для N≤1000 из-за прогона z3. N=10000 замеряется ТОЛЬКО для dispatcher
   (прогон #2), остальные — ns_small=[10,100,1000]. Обобщение на N=10000 для FSM/pipeline
   опирается на плоскую форму на малых N, не на прямом замере.
5. **M6 обучаемость** не измерима агентом — требует живых людей.
6. **Нет основного held-out корпуса 15–20 задач** (roadmap Этап 0) — работали только
   на scaling-корпусе. Это следующий приоритет.

---

## Структура

```
evol/
  lexer.py            # токенизация (forall, import, try, raise, FLOAT)
  ast_nodes.py        # узлы AST (Import, ForEach, TryCatch, Raise, Float, Spawn(lib=…))
  parser.py           # рекурсивный спуск -> AST (import, кв.спавн, Call как eff, try/catch, raise)
  interpreter.py      # δ(S)->S′ + модули stdlib (console, random, file, sim, math, string, os)
  typechecker.py      # проверки + proven_properties() для M5 + TryCatch/Raise
  compiler.py         # транспиляция EVOL → Python (+ try/catch/raise)
  repl.py             # REPL с hot reload, checkpoint, watch
  metrics/
    run_metrics.py    # генератор задач + подсчёт M1/M2/M3/M4/M5/SMT (прогон #1)
    corpus2.py        # held-out corpus #2 (6 задач, seeds зафиксированы)
    smt_prove.py      # z3-SMT: проверка гвардов
    option_c.py       # Rust-базовый вариант + M3 энтропия
  samples/            # .evol файлы (симуляции, протоколы, игры, DI, typed_demo)
  test_*.py           # тесты (suites, все зелёные кроме зависящих от z3/Rust)
```

---

## Дальше

Реализовано:
- [x] Стандартная библиотека (console, random, file, sim, math, string, os)
- [x] REPL с hot reload (как Lisp)
- [x] Checkpoint save/restore
- [x] Транспиляция EVOL → Python
- [x] Непрерывное время (dt)
- [x] Error handling (try/catch/raise)
- [x] FLOAT тип (динамический)
- [x] Held-out корпус #2 (6 задач, seeds зафиксированы, без утечки)
- [x] **Типы (аннотации + статическая проверка, опциональная runtime-проверка)** — Этап 7

Осталось:
- [ ] FFI (системные вызовы, сеть)
- [ ] Основной корпус 15–20 задач
