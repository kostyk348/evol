//! Golden cases generated from the ORIGINAL Python interpreter
//! (scripts/evol_golden.py + scripts/evol_golden.json). Regenerate
//! with: python3 scripts/evol_make_golden_tests.py

pub enum Case {
    Run {
        name: &'static str,
        steps: u64,
        store: &'static str,
        emitted: &'static str,
        stopped: bool,
        console: &'static str,
    },
    ParseError {
        name: &'static str,
        needle: &'static str,
    },
    Typecheck {
        name: &'static str,
        n_errors: usize,
        proven: &'static [&'static str],
        failed: &'static [&'static str],
    },
}

pub fn cases() -> Vec<Case> {
    vec![
        Case::Run { name: "chat_router.evol", steps: 20, store: "from=3; id=3; text='ответ'; users=3", emitted: "[^check, (^user_joined, 1), ^check, (^msg, 1, 'присоединился к чату'), (^user_joined, 2), ^check, (^msg, 2, 'присоединился к чату'), (^user_joined, 3), ^check, (^msg, 3, 'присоединился к чату'), ^ready, (^msg, 0, 'чат запущен'), (^send, 1, 'привет'), (^msg, 1, 'привет'), (^send, 2, 'ответ'), (^msg, 2, 'ответ'), (^send, 3, 'ответ'), (^msg, 3, 'ответ'), ^done]", stopped: false, console: "" },
        Case::Run { name: "demo_counter.evol", steps: 13, store: "n=5", emitted: "[^run, ^tick, ^run, ^tick, ^run, ^tick, ^run, ^tick, ^run, ^tick, ^run, ^done]", stopped: false, console: "" },
        Case::Run { name: "demo_forall.evol", steps: 6, store: "x=4; y=4", emitted: "[(^tick, 0), (^tick, 1), (^tick, 2), (^tick, 3), (^tick, 4)]", stopped: false, console: "" },
        Case::Run { name: "demo_par.evol", steps: 2, store: "x=1; y=2", emitted: "[^done]", stopped: false, console: "" },
        Case::Run { name: "epidemic_sim.evol", steps: 25, store: "cured=1; d=7; day=7; h=68; healthy=68; i=0; infected=0; new_cases=1; prev=1; r=10; recovered=10", emitted: "[^tick, (^report, 1, 90, 7, 3), ^tick, (^msg, 'день', 1, 'здоров:', 90, 'болен:', 7, 'выздоровел:', 3), (^report, 2, 83, 5, 5), ^tick, (^msg, 'день', 2, 'здоров:', 83, 'болен:', 5, 'выздоровел:', 5), (^report, 3, 78, 4, 6), ^tick, (^msg, 'день', 3, 'здоров:', 78, 'болен:', 4, 'выздоровел:', 6), (^report, 4, 74, 3, 7), ^tick, (^msg, 'день', 4, 'здоров:', 74, 'болен:', 3, 'выздоровел:', 7), (^report, 5, 71, 2, 8), ^tick, (^msg, 'день', 5, 'здоров:', 71, 'болен:', 2, 'выздоровел:', 8), (^report, 6, 69, 1, 9), ^tick, (^msg, 'день', 6, 'здоров:', 69, 'болен:', 1, 'выздоровел:', 9), (^report, 7, 68, 0, 10), ^tick, (^msg, 'день', 7, 'здоров:', 68, 'болен:', 0, 'выздоровел:', 10), ^done, (^msg, 'эпидемия завершена')]", stopped: false, console: "" },
        Case::Run { name: "etl_pipeline.evol", steps: 24, store: "clean=40; raw=4; v=40; x=4", emitted: "[^extract_next, (^transform, 1), ^extract_next, (^validated, 10), (^transform, 2), ^extract_next, (^skip, 10), (^validated, 20), (^transform, 3), ^extract_next, (^msg, 'пропущено:', 10), (^skip, 20), (^validated, 30), (^transform, 4), ^extract_next, (^msg, 'пропущено:', 20), (^good, 30), (^validated, 40), ^load, (^msg, 'загружено:', 30), (^good, 40), (^msg, 'ETL завершён'), (^msg, 'загружено:', 40)]", stopped: false, console: "" },
        Case::Run { name: "game_loop.evol", steps: 35, store: "enemies=5; hp=-5; remaining=-5", emitted: "[^spawn_wave, (^enemy_appears, 1), ^spawn_wave, (^enemy_appears, 2), ^spawn_wave, (^enemy_appears, 3), ^spawn_wave, (^enemy_appears, 4), ^spawn_wave, (^enemy_appears, 5), ^spawn_wave, ^combat, (^hit, 85), ^combat, (^msg, 'HP:', 85), (^hit, 70), ^combat, (^msg, 'HP:', 70), (^hit, 55), ^combat, (^msg, 'HP:', 55), (^hit, 40), ^combat, (^msg, 'HP:', 40), (^hit, 25), ^combat, (^msg, 'HP:', 25), (^hit, 10), ^combat, (^msg, 'HP:', 10), (^hit, -5), ^game_over, (^msg, 'HP:', -5), (^msg, 'конец игры')]", stopped: false, console: "" },
        Case::ParseError { name: "invalid1_no_arrow.evol", needle: "получен OP '{' в 2:28" },
        Case::ParseError { name: "invalid2_unclosed.evol", needle: "незакрытый блок (нет '}')" },
        Case::ParseError { name: "invalid3_bad_assign.evol", needle: "получен выражение NAME 'x' в 3:5" },
        Case::ParseError { name: "invalid4_bad_token.evol", needle: "/home/z/my-project/work/evol/samples/invalid4_bad_token.evol:3:10 неожиданный символ '@'" },
        Case::Run { name: "mod_counter.evol", steps: 1, store: "", emitted: "[]", stopped: false, console: "" },
        Case::Run { name: "server_farm_sim.evol", steps: 57, store: "done_count=9; id=9; jobs=9; servers_on=3", emitted: "[^provision, (^server_ready, 1), ^provision, (^server_ready, 2), ^provision, (^server_ready, 3), ^provision, ^accept, (^dispatch, 1), ^accept, (^process, 1), (^dispatch, 2), ^accept, (^job_done, 1), (^process, 2), (^dispatch, 3), ^accept, (^msg, 'job', 1, 'выполнен'), (^job_done, 2), (^process, 3), (^dispatch, 4), ^accept, (^msg, 'job', 2, 'выполнен'), (^job_done, 3), (^process, 4), (^dispatch, 5), ^accept, (^msg, 'job', 3, 'выполнен'), (^job_done, 4), (^process, 5), (^dispatch, 6), ^accept, (^msg, 'job', 4, 'выполнен'), (^job_done, 5), (^process, 6), (^dispatch, 7), ^accept, (^msg, 'job', 5, 'выполнен'), (^job_done, 6), (^process, 7), (^dispatch, 8), ^accept, (^msg, 'job', 6, 'выполнен'), (^job_done, 7), (^process, 8), (^dispatch, 9), ^accept, (^msg, 'job', 7, 'выполнен'), (^job_done, 8), (^process, 9), ^drain, (^msg, 'job', 8, 'выполнен'), (^job_done, 9), ^shutdown, (^msg, 'job', 9, 'выполнен'), (^msg, 'все задачи выполнены:', 9)]", stopped: false, console: "" },
        Case::Typecheck { name: "tc_bad_spawn.evol", n_errors: 1, proven: &["все retract -> объявленные правила", "все правила достижимы из boot (нет dead-кода)", "нет конфликта тегов (детерминизм выбора правила)"], failed: &["spawn несуществующего правила", "ошибки типизации", "непокрытые emit-теги: ['a']"] },
        Case::Typecheck { name: "tc_bad_spawn_qual.evol", n_errors: 1, proven: &["все retract -> объявленные правила", "нет конфликта тегов (детерминизм выбора правила)"], failed: &["spawn несуществующего правила", "ошибки типизации", "недостижимые правила: [('counter', 'tick')]", "непокрытые emit-теги: ['ticked']"] },
        Case::Typecheck { name: "tc_bad_type.evol", n_errors: 1, proven: &["все spawn -> объявленные правила", "все retract -> объявленные правила", "все правила достижимы из boot (нет dead-кода)", "нет конфликта тегов (детерминизм выбора правила)"], failed: &["ошибки типизации", "непокрытые emit-теги: ['a']"] },
        Case::Typecheck { name: "tc_ok.evol", n_errors: 0, proven: &["все spawn -> объявленные правила", "все retract -> объявленные правила", "программа типобезопасна (без ошибок тайпчекера)", "все правила достижимы из boot (нет dead-кода)", "все emit-теги покрыты обработчиком when (нет гарантированного drop)", "нет конфликта тегов (детерминизм выбора правила)"], failed: &[] },
        Case::Typecheck { name: "tc_uncovered.evol", n_errors: 0, proven: &["все spawn -> объявленные правила", "все retract -> объявленные правила", "программа типобезопасна (без ошибок тайпчекера)", "нет конфликта тегов (детерминизм выбора правила)"], failed: &["недостижимые правила: [('t', 'a'), ('t', 'b')]", "непокрытые emit-теги: ['orphan']"] },
        Case::Run { name: "traffic_sim.evol", steps: 16, store: "cars_e=0; cars_n=0; cars_s=0; cars_w=0; g=1; green_ns=1; s=12; served=12", emitted: "[^arrive, ^arrive, ^arrive, ^arrive, ^arrive, ^arrive, ^arrive, ^cycle, (^status, 0, 0), ^cycle, (^msg, 'свет:', 0, 'обслужено:', 0), (^status, 1, 12), ^done, (^msg, 'свет:', 1, 'обслужено:', 12), (^msg, 'светофор завершён, всего:', 12)]", stopped: false, console: "" },
        Case::Run { name: "typed_demo.evol", steps: 3, store: "add=('closure', ...); doubled=10; label='счётчик'; n=5; step=1.5; total=5; value=5; xs=[1, 2, 3, 4, 5]", emitted: "[(^go, 5), ^done]", stopped: false, console: "счётчик : 5 из 5 элементов, шаг 1.5\nудвоенное значение: 10\nготово\n" },
        Case::Run { name: "valid1_dispatcher.evol", steps: 4, store: "x=1; y=2", emitted: "[^tick, ^a_done, ^b_done]", stopped: false, console: "" },
        Case::Run { name: "valid2_statemachine.evol", steps: 1, store: "", emitted: "[]", stopped: false, console: "" },
        Case::Run { name: "valid3_pipeline.evol", steps: 1, store: "", emitted: "[]", stopped: false, console: "" },
        Case::Run { name: "valid4_di.evol", steps: 2, store: "deps=[(^svcB, ^svcA), (^svcC, ^svcA), (^svcD, ^svcB), (^svcE, ^svcC)]; services=[^svcA, ^svcB, ^svcC, ^svcD, ^svcE]", emitted: "[^wire_ok]", stopped: false, console: "" },
    ]
}
