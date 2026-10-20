use std::path::PathBuf;

fn main() {
    let mut arguments = std::env::args_os();
    let _program = arguments.next();
    let Some(script) = arguments.next() else {
        eprintln!("Usage: powcurl <script.powcurl>");
        std::process::exit(2);
    };
    if arguments.next().is_some() {
        eprintln!("Usage: powcurl <script.powcurl>");
        std::process::exit(2);
    }

    if let Err(error) = powcurl::run_script(&PathBuf::from(script)) {
        eprintln!("[POWCURL ERROR] {error}");
        std::process::exit(1);
    }
}
