use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::process::ExitCode;
use std::time::Duration;

pub fn run() -> ExitCode {
    run_core()
}

pub fn run_core() -> ExitCode {
    let control_port = match env_port("PROMPT_UI_PORT", 8080) {
        Ok(port) => port,
        Err(error) => {
            eprintln!("[HEALTH] {error}");
            return ExitCode::FAILURE;
        }
    };
    let bridge_port = match env_port("SUGGESTION_BRIDGE_PORT", 8081) {
        Ok(port) => port,
        Err(error) => {
            eprintln!("[HEALTH] {error}");
            return ExitCode::FAILURE;
        }
    };

    for (port, path) in [(control_port, "/api/health"), (bridge_port, "/api/version")] {
        if let Err(error) = check_http_endpoint(port, path) {
            eprintln!("[HEALTH] 127.0.0.1:{port}{path}: {error}");
            return ExitCode::FAILURE;
        }
    }
    ExitCode::SUCCESS
}

#[allow(dead_code)]
pub fn run_ocr() -> ExitCode {
    let port = match env_port("OCR_SERVICE_PORT", 8082) {
        Ok(port) => port,
        Err(error) => {
            eprintln!("[HEALTH] {error}");
            return ExitCode::FAILURE;
        }
    };
    if let Err(error) = check_http_endpoint(port, "/health") {
        eprintln!("[HEALTH] 127.0.0.1:{port}/health: {error}");
        return ExitCode::FAILURE;
    }
    ExitCode::SUCCESS
}

fn env_port(name: &str, default: u16) -> Result<u16, String> {
    match std::env::var(name) {
        Ok(value) => value
            .parse::<u16>()
            .map_err(|_| format!("{name} must be a valid TCP port")),
        Err(_) => Ok(default),
    }
}

fn check_http_endpoint(port: u16, path: &str) -> std::io::Result<()> {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let timeout = Duration::from_secs(5);
    let mut stream = TcpStream::connect_timeout(&address, timeout)?;
    stream.set_read_timeout(Some(timeout))?;
    stream.set_write_timeout(Some(timeout))?;
    write!(
        stream,
        "GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
    )?;
    stream.flush()?;

    let mut response = [0_u8; 64];
    let read = stream.read(&mut response)?;
    let status = std::str::from_utf8(&response[..read]).unwrap_or_default();
    if status.starts_with("HTTP/1.1 200 ") || status.starts_with("HTTP/1.0 200 ") {
        Ok(())
    } else {
        Err(std::io::Error::other("endpoint did not return HTTP 200"))
    }
}
