//! Golden tests: the Rust interpreter/typechecker must reproduce the ORIGINAL
//! Python implementation on the deterministic sample corpus, byte for byte.

use evol::interp::{run, EnforceTypes};
use evol::parser::parse;
use evol::types::{proven_properties, typecheck};

mod golden_cases;
use golden_cases::Case;

fn sample_path(name: &str) -> String {
    format!("{}/samples/{}", env!("CARGO_MANIFEST_DIR"), name)
}

fn read_sample(name: &str) -> String {
    std::fs::read_to_string(sample_path(name)).expect("sample file")
}

#[test]
fn golden_corpus_matches_python() {
    let mut run_n = 0;
    let mut parse_err_n = 0;
    let mut tc_n = 0;
    for case in golden_cases::cases() {
        match case {
            Case::Run {
                name,
                steps,
                store,
                emitted,
                stopped,
                console,
            } => {
                run_n += 1;
                let src = read_sample(name);
                let ast = parse(&src, &sample_path(name)).expect("parse");
                let base = std::path::Path::new(&sample_path(name))
                    .parent()
                    .unwrap()
                    .to_string_lossy()
                    .into_owned();
                let res = run(&ast, &["boot"], 100_000, EnforceTypes(false), &base)
                    .expect("run should succeed");
                assert_eq!(res.steps, steps, "{name}: steps");
                // store rendered exactly like the Python harness: sorted "k=repr"
                let mut keys: Vec<&String> = res.store.keys().collect();
                keys.sort();
                let rendered: Vec<String> = keys
                    .iter()
                    .map(|k| format!("{}={}", k, res.store[*k].repr()))
                    .collect();
                assert_eq!(rendered.join("; "), store, "{name}: store");
                // emitted rendered as [repr, ...]
                let em: Vec<String> = res.emitted.iter().map(|v| v.repr()).collect();
                assert_eq!(format!("[{}]", em.join(", ")), emitted, "{name}: emitted");
                assert_eq!(res.stopped_by_max_steps, stopped, "{name}: stopped");
                assert_eq!(res.output, console, "{name}: console output");
            }
            Case::ParseError { name, needle } => {
                parse_err_n += 1;
                let src = read_sample(name);
                let err = parse(&src, &sample_path(name))
                    .expect_err(&format!("{name}: must fail to parse"));
                assert!(err.0.contains(needle), "{name}: {err:?} lacks {needle:?}");
            }
            Case::Typecheck {
                name,
                n_errors,
                proven,
                failed,
            } => {
                tc_n += 1;
                let src = read_sample(name);
                let ast = parse(&src, &sample_path(name)).expect("parse");
                let errors = typecheck(&ast);
                assert_eq!(errors.len(), n_errors, "{name}: error count");
                let (prov, fail) = proven_properties(&ast);
                for p in proven {
                    assert!(
                        prov.iter().any(|x| x == p),
                        "{name}: proven lacks {p:?} (got {prov:?})"
                    );
                }
                for f in failed {
                    assert!(
                        fail.iter().any(|x| x == f),
                        "{name}: failed lacks {f:?} (got {fail:?})"
                    );
                }
            }
        }
    }
    assert_eq!(run_n, 15, "run cases");
    assert_eq!(parse_err_n, 4, "parse-error cases");
    assert_eq!(tc_n, 5, "typecheck cases");
}

#[test]
fn ffi_py_reports_unavailable() {
    // `import py "time"` needs a Python host; the port reports the same error
    // shape the Python runtime gives for an unregistered FFI (documented).
    let src = std::fs::read_to_string(sample_path("concurrent_fanout.evol")).unwrap();
    let ast = parse(&src, "concurrent_fanout.evol").unwrap();
    let err =
        run(&ast, &["boot"], 1000, EnforceTypes(false), ".").expect_err("FFI must be unavailable");
    assert!(err.to_string().contains("Python"), "{err}");
}

mod golden_compiler;

#[test]
fn transpiler_matches_python_byte_for_byte() {
    for (name, expected) in golden_compiler::GOLDEN {
        let src = read_sample(name);
        let ast = parse(&src, name).expect("parse");
        assert_eq!(
            evol::compiler::compile_evol(&ast),
            *expected,
            "{name}: transpiled Python differs"
        );
    }
}
