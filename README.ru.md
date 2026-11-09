<div align="center">

# EVOL — язык переходов состояний (proof-of-concept)

**Экспериментальный язык, оптимизированный под скорость эволюции инженерных идей:
каждая конструкция — правило перехода абстрактной машины δ(S) → S′, семантика
задаётся явно, без «магии».**

[![Release](https://img.shields.io/github/v/release/kostyk348/evol?sort=semver&color=0ea5e9&label=release)](https://github.com/kostyk348/evol/releases)
[![CI](https://img.shields.io/github/actions/workflow/status/kostyk348/evol/ci.yml?branch=master&label=CI)](https://github.com/kostyk348/evol/actions/workflows/ci.yml)
[![tests](https://img.shields.io/badge/tests-51%20passing%2C%20golden--%20%2B%20property--verified-22c55e)](#порт-на-rust-v03)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![Rust](https://img.shields.io/badge/rust-1.80%2B-orange)](https://www.rust-lang.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](CONTRIBUTING.md)

[English](README.md) · Русский

</div>

---

Проект реализован по цепочке документов `lang-design-spec` → `lang-implementation-roadmap`
→ `lang-scaling-corpus` (phases 0–7 roadmap). Статус: **Этапы 1–6 выполнены**, ядро
языка перенесено на Rust (v0.3, golden-verified против Python-прототипа).

## Что такое EVOL (и чем он не является)

EVOL — **DSL для процессов с состояниями**: модель, а не универсальный язык.
Одна спецификация проходит всю цепочку: *описано → скомпилировано →
протестировано → визуализировано → экспортировано в документацию*.
Формальная операционная семантика абстрактной машины — конфигурации
`(Σ, μ, Q, κ)`, отношение перехода δ, терминация (нормальная / по лимиту
шагов / по ошибке / отклонение сообщения), условное завершение,
детерминизм и чистота — записана в
**[docs/semantics.md](docs/semantics.md)** (выведена из реальной
реализации, честно об ограничениях) и закреплена тестами, включая
рандомизированные property-тесты детерминизма, чистоты и терминации на
сгенерированных корректных программах.

## Что реализовано

| Этап | Модуль (Rust) | Суть |
|---|---|---|
| 1 | — (бумага) | EBNF-грамматика + формальная семантика АМ (`δ(S)→S′`) |
| 2 | `src/lexer.rs`, `src/ast.rs`, `src/parser.rs` | Лексер + AST + рекурсивный спуск |
| 3 | `src/interp.rs`, `src/value.rs` | AST-walking интерпретатор (`Σ, Μ, Q`) |
| 4 | `src/types.rs` | Тайпчекер (реально отклоняет ошибки) + доказательщик свойств (M5) |
| Опция A | `parser.rs`, `interp.rs` | `forall x in expr` + встроенные `range`, `len` — O(1) токенов по N |
| Опция D | `interp.rs` | `import` внешних модулей + квалифицированный `spawn Lib.Rule` |
| Float | `lexer.rs`..`compiler.rs` | Тип `FLOAT` (динамический) во всём стеке |
| Error handling | `parser.rs`, `interp.rs` | `try/catch/raise` — ловит InterpreterError + EvalError |
| Этап 7 | все модули | **Аннотации типов**: статическая проверка (Int/Str/Bool/Float/Sym/List[T]/Top) + опциональная runtime-проверка через `--enforce-types` |
| ADT | `ast.rs`, `parser.rs`, `interp.rs`, `types.rs` | `type Name = A(x:T) \| B \| …`, конструкторы `Circle(3.0)`, match по тегу |
| Транспилятор | `src/compiler.rs` | EVOL → Python (тот же вывод, что у прототипа — golden-verified) |

## Порт на Rust (v0.3)

Прототип был на Python 3.10+ (ядро ~2700 строк + REPL/метрики). Ядро языка —
лексер, парсер, интерпретатор, тайпчекер, транспилятор — перенесено на Rust
без зависимостей. **Корректность доказана golden-тестами против оригинала**:
`tests/golden.rs` запускает детерминированный корпус из `samples/` через оба
интерпретатора и требует побитового совпадения (шаги АМ, store, лог emitted,
вывод console), плюс ошибки парсера, свойства тайпчекера и вывод транспилятора.

| | Python-прототип | Rust 0.3 |
|---|---|---|
| зависимости | Python 3.10+ | Rust 1.80+, ноль crates |
| тесты | suites (z3-зависимые падали) | 18, все зелёные, golden-verified |
| FFI `import py` | Python-callables, sandbox | недоступен (нет Python-хоста) — та же ошибка «не зарегистрирован» |
| `random.*` | Mersenne (CPython) | свой SplitMix64 — тот же контракт (seed → детерминированная последовательность), но числа не совпадают с CPython |
| REPL / актор-рантайм / метрики | `repl.py`, `runtime_concurrent.py`, `metrics/` | **не портированы** — следующий шаг (см. CHANGELOG) |

Сборка и запуск:

```bash
cargo build --release
evol run samples/demo_counter.evol boot     # исполнить (13 шагов, n=5)
evol check samples/tc_ok.evol               # тайпчекер + доказанные свойства
evol compile samples/valid1_dispatcher.evol # EVOL → Python
```

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

Модули стандартной библиотеки: `console` (print), `random` (int/pick/shuffle),
`file` (read/write/exists), `sim` (step/set_seed), `math` (sqrt/pow/sin/cos/pi/floor/ceil/log),
`string` (split/join/upper/lower/contains/replace/len/at/substr), `os` (listdir/getcwd/path_exists/mkdir).

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
они управляют статическим тайпчекером (`src/types.rs`) и, при желании,
runtime-проверкой (`evol run --enforce-types`).

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

Runtime-проверка (`--enforce-types`) ловит те же несовпадения во время исполнения
(включая аннотированные поля сообщений из `match`). По умолчанию выключена — язык
остаётся динамическим, как и задумано для proof-of-concept.

## Доказательщик свойств (M5)

`evol check` печатает свойства, автоматически доказуемые из одного определения
программы (P1–P8): валидность spawn/retract, типобезопасность, достижимость всех
правил из `boot` (нет dead-кода), покрытие emit-тегов обработчиками, детерминизм
выбора правила (нет конфликта when-тегов), исчерпывающий match по ADT, арность
ADT-конструкторов.

## Результаты метрик (прогоны Python-прототипа)

> Метрики M1–M5 и corpus #2 измерены на Python-прототипе (`metrics/`, не портирован).
> Языковая семантика не менялась (golden-verified), поэтому результаты остаются
> релевантными для грамматики; переномеровка рантайма их не касается.

### Прогон #1 (scaling-корпус, с утечкой)

> Честность метрик (см. оговорку #2): baseline Python бывает двух видов.
> **naive** — явное развёртывание N веток dispatch; **idiomatic** — `dict`/функция-диспетчер
> за O(1) токенов. M1 против naive занижает Python — смотреть **M1_fair**.

| Метрика | Зона | Сырое число | Форма M(N) |
|---|---|---|---|
| M1 vs naive-Py (unrolled) | отлично* | dispatcher=0.61, FSM=0.11, pipeline=0.18, fanout=0.19, router=0.18 | плоская |
| **M1_fair vs idiomatic-Py (O(1))** | хорошо (паритет) | dispatcher=0.61, FSM=0.69, pipeline=0.69, fanout=**1.83**, router=0.69 | плоская |
| M1 компрессия vs Rust | отлично | dispatcher=0.49, FSM=0.12, pipeline=0.24, fanout=0.21, router=0.23 | плоская |
| M2 рекомбинация | отлично | 100% пар компонуются | плоская |
| M3 энтропия | терпимо/хорошо | ratio=0.70–0.80 к Python | плоская |
| M4 сем. компрессия | стабильно | 2–17 токенов/шаг АМ | плоская |
| M5 стат. глубина вывода (УТП) | хорошо | 6–8 свойств/прогон | плоская |
| M5-SMT (z3) | отлично | 0–2 по задачам | н/д |

\* M1 против naive завышен искусственно (оговорка #2).

### Прогон #2 (held-out corpus, без утечки)

Seeds зафиксированы ДО замера: `20260713-1`..`20260713-5`. Грамматика LOCKED.

| Задача | M1_fair@10/100/1000/10000 | M2 | M3 | M5 | M5-SMT |
|--------|-------------------------------|-----|-----|-----|--------|
| dispatcher (DAG) | **0.94 / 0.94 / 0.94 / 0.94** | 100% | 0.682 | 3 | 2 |
| FSM (2 shared vars) | **0.66 / 0.66 / 0.66 / —** | 100% | 0.800 | 4 | 2 |
| pipeline (parallel) | **0.66 / 0.66 / 0.66 / —** | 100% | 0.706 | 4 | 2 |
| **ratelimiter** (NEW) | **0.67 / 0.67 / 0.67 / —** | 100% | 0.819 | 4 | 3 |
| **cache** (NEW) | **0.62 / 0.62 / 0.62 / —** | 100% | 0.666 | 4 | 2 |
| **httprouter** (control) | **0.94** (фикс. 50) | 100% | — | 4 | 2 |

Честный вывод: гипотеза «EVOL масштабируется без ручного развёртывания» **подтверждена**
(M1_fair плоский, ни одна кривая не суперлинейна, включая N=10000). Но заявление
«EVOL в разы компактнее Python» **неверно** против idiomatic baseline — там паритет.
Ценность EVOL — в детерминированной АМ-семантике и M5-выводе, а не в токенах.

---

## Важные оговорки

1. **Anti-Goodhart.** Прогон #1 использовал корпус, известный агенту-дизайнеру.
   Прогон #2 (corpus #2) — held-out, seeds зафиксированы, грамматика LOCKED.
2. **Baseline — два вида, честно.** M1_naive разворачивает N веток dispatch — занижает
   Python. ВСЕГДА смотрите на M1_fair против idiomatic `dict`-диспетчера. Оба baseline
   написаны тем же агентом, что и EVOL — честный вывод **паритет с разумным baseline**.
3. **M3 энтропия — НЕ независимая мера.** Варианты генерируются одним генератором.
4. **M3/M5 на малых N.** M3 только для N≤100; M5-SMT для N≤1000 из-за прогона z3.
5. **M6 обучаемость** не измерима агентом — требует живых людей.
6. **Нет основного held-out корпуса 15–20 задач** — следующий приоритет.

---

## Структура

```
evol/
  src/lexer.rs        # токенизация (forall, import, try, raise, FLOAT, type/match, '|', ';')
  src/ast.rs          # узлы AST с позициями (Import, PyImport, EnumDecl, Match, ForEach, TryCatch, Raise, Float, Spawn)
  src/parser.rs       # рекурсивный спуск -> AST (import, кв.спавн, Call как eff, try/catch/raise, type/match)
  src/value.rs        # значения с семантикой Python (repr/str, truthiness, числовая башня, floor-деление)
  src/interp.rs       # δ(S)->S′ + модули stdlib + import .evol (разрешение путей) + FFI-ошибка как в оригинале
  src/types.rs        # проверки + proven_properties() для M5 (P1–P8)
  src/compiler.rs     # транспиляция EVOL → Python (побитово как compiler.py)
  src/bin/evol.rs     # CLI: run / check / compile
  tests/golden.rs     # golden-корпус против Python-прототипа (18 тестов)
  tests/properties.rs # семантические unit-тесты + property-тесты (33): детерминизм, чистота, терминация
  docs/semantics.md   # формальная операционная семантика + таблица трассировки spec ⇄ тесты
  samples/            # .evol файлы (симуляции, протоколы, игры, DI, typed_demo)
```

---

## Дальше

Реализовано:
- [x] Стандартная библиотека (console, random, file, sim, math, string, os)
- [x] Транспиляция EVOL → Python
- [x] Error handling (try/catch/raise)
- [x] FLOAT тип (динамический)
- [x] **Типы (аннотации + статическая проверка, опциональная runtime-проверка)** — Этап 7
- [x] **Ядро на Rust, golden-verified против Python** — v0.3

Не портировано с Python (следующие шаги):
- [ ] REPL с hot reload и checkpoint (был `repl.py`)
- [ ] Актор-рантайм `runtime_concurrent.py` (pub/sub по контенту) — ось конкурентности
- [ ] Метрики `metrics/` (генераторы корпуса, z3-SMT)
- [ ] FFI (системные вызовы, сеть)
- [ ] Основной корпус 15–20 задач

См. [CONTRIBUTING.md](CONTRIBUTING.md) и [CHANGELOG.md](CHANGELOG.md).

## Лицензия

Apache 2.0 — см. [LICENSE](LICENSE).
