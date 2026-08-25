#![forbid(unsafe_code)]

#[path = "../healthcheck_probe.rs"]
mod healthcheck_probe;

use std::ffi::OsStr;
use std::process::ExitCode;

fn main() -> ExitCode {
    match std::env::args_os().nth(1) {
        None => healthcheck_probe::run(),
        Some(value) if value == OsStr::new("--ocr") => healthcheck_probe::run_ocr(),
        Some(_) => {
            eprintln!("[HEALTH] usage: plai-healthcheck [--ocr]");
            ExitCode::FAILURE
        }
    }
}
