//! evol CLI: run / check / compile a program.

use std::process::ExitCode;

use evol::compiler::compile_evol;
use evol::interp::{run, EnforceTypes};
use evol::parser::parse;
use evol::types::{proven_properties, typecheck};

fn usage() -> &'static str {
    "usage:
  evol run <file.evol> [msg...] [--enforce-types] [--max-steps N]
  evol check <file.evol>              # typecheck + proven properties
  evol compile <file.evol> [-o out.py]  # transpile to Python"
}

fn read_program(path: &str) -> Result<evol::Program, String> {
    let src = std::fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))?;
    parse(&src, path).map_err(|e| e.0)
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        eprintln!("{}", usage());
        return ExitCode::from(1);
    }
    match args[0].as_str() {
        "run" => cmd_run(&args[1..]),
        "check" => cmd_check(&args[1..]),
        "compile" => cmd_compile(&args[1..]),
        "--help" | "-h" | "help" => {
            println!("{}", usage());
            ExitCode::SUCCESS
        }
        other => {
            eprintln!("неизвестная команда {other:?}\n{}", usage());
            ExitCode::from(1)
        }
    }
}

fn cmd_run(args: &[String]) -> ExitCode {
    let mut path = None;
    let mut msgs: Vec<String> = Vec::new();
    let mut enforce = false;
    let mut max_steps = 100_000u64;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--enforce-types" => enforce = true,
            "--max-steps" => {
                i += 1;
                match args.get(i).and_then(|s| s.parse().ok()) {
                    Some(n) => max_steps = n,
                    None => {
                        eprintln!("--max-steps требует число");
                        return ExitCode::from(1);
                    }
                }
            }
            p if path.is_none() => path = Some(p.to_string()),
            m => msgs.push(m.to_string()),
        }
        i += 1;
    }
    let Some(path) = path else {
        eprintln!("run: нужен файл\n{}", usage());
        return ExitCode::from(1);
    };
    let ast = match read_program(&path) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("ошибка: {e}");
            return ExitCode::from(1);
        }
    };
    let base_dir = std::path::Path::new(&path)
        .parent()
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_else(|| ".".into());
    match run(
        &ast,
        &msgs.iter().map(String::as_str).collect::<Vec<_>>(),
        max_steps,
        EnforceTypes(enforce),
        &base_dir,
    ) {
        Ok(res) => {
            println!("steps: {}", res.steps);
            let mut keys: Vec<&String> = res.store.keys().collect();
            keys.sort();
            for k in keys {
                let v = &res.store[k];
                println!("{k} = {}", v.str_repr());
            }
            println!("emitted: {} сообщений", res.emitted.len());
            if res.stopped_by_max_steps {
                println!("остановлен по лимиту шагов ({max_steps})");
            }
            // console.print output was captured; print it after the report
            print!("{}", res.output);
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("ошибка исполнения: {e}");
            ExitCode::from(1)
        }
    }
}

fn cmd_check(args: &[String]) -> ExitCode {
    let Some(path) = args.first() else {
        eprintln!("check: нужен файл\n{}", usage());
        return ExitCode::from(1);
    };
    let ast = match read_program(path) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("ошибка: {e}");
            return ExitCode::from(1);
        }
    };
    let errors = typecheck(&ast);
    if errors.is_empty() {
        println!("тайпчекер: ошибок нет");
    } else {
        for e in &errors {
            println!("ошибка типизации: {}", e.0);
        }
    }
    let (proven, failed) = proven_properties(&ast);
    println!("доказанные свойства:");
    for p in &proven {
        println!("  + {p}");
    }
    if !failed.is_empty() {
        println!("проваленные свойства:");
        for f in &failed {
            println!("  - {f}");
        }
    }
    if errors.is_empty() {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(1)
    }
}

fn cmd_compile(args: &[String]) -> ExitCode {
    let mut path = None;
    let mut out = None;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "-o" => {
                i += 1;
                out = args.get(i).cloned();
            }
            p if path.is_none() => path = Some(p.to_string()),
            _ => {}
        }
        i += 1;
    }
    let Some(path) = path else {
        eprintln!("compile: нужен файл\n{}", usage());
        return ExitCode::from(1);
    };
    let ast = match read_program(&path) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("ошибка: {e}");
            return ExitCode::from(1);
        }
    };
    let py_code = compile_evol(&ast);
    let out_path = out.unwrap_or_else(|| {
        path.rsplit_once('.')
            .map_or(format!("{path}.py"), |(b, _)| format!("{b}.py"))
    });
    if let Err(e) = std::fs::write(&out_path, &py_code) {
        eprintln!("не удалось записать {out_path}: {e}");
        return ExitCode::from(1);
    }
    println!("Compiled: {path} -> {out_path}");
    ExitCode::SUCCESS
}
