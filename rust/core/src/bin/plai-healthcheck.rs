#![forbid(unsafe_code)]

#[path = "../healthcheck_probe.rs"]
mod healthcheck_probe;

use std::process::ExitCode;

fn main() -> ExitCode {
    healthcheck_probe::run()
}
