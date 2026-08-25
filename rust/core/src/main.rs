#![forbid(unsafe_code)]

use plai_core::{bridge, control, error::Error, state::CoreState, worker};
use std::future::Future;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::process::ExitCode;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::net::TcpListener;
use tokio::sync::{mpsc, watch};
use tokio::task::JoinHandle;

const SHUTDOWN_JOIN_SECONDS: u64 = 5;

#[derive(Debug)]
enum CoreEvent {
    Signal(&'static str),
    ComponentStopped {
        name: &'static str,
        error: Option<String>,
    },
}

fn main() -> ExitCode {
    if std::env::args_os().nth(1).as_deref() == Some(std::ffi::OsStr::new("--healthcheck")) {
        return core_healthcheck();
    }

    let runtime = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(error) => {
            eprintln!("[CORE] could not build Tokio runtime: {error}");
            return ExitCode::FAILURE;
        }
    };

    match runtime.block_on(async_main()) {
        Ok(code) => ExitCode::from(code),
        Err(error) => {
            eprintln!("[CORE] fatal startup error: {error}");
            ExitCode::FAILURE
        }
    }
}

fn core_healthcheck() -> ExitCode {
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

async fn async_main() -> Result<u8, Error> {
    let state = CoreState::from_env()?;
    let app = state.app_config.ensure()?;
    let prompt = state.prompt_config.ensure()?;

    let control_host = env_string("PROMPT_UI_HOST", "0.0.0.0");
    let control_port = env_port("PROMPT_UI_PORT", 8080)?;
    let bridge_host = env_string("SUGGESTION_BRIDGE_HOST", "0.0.0.0");
    let bridge_port = env_port("SUGGESTION_BRIDGE_PORT", 8081)?;

    // Bind before spawning anything so a bad port/address fails atomically instead
    // of leaving only part of the unified core running.
    let control_listener = TcpListener::bind((control_host.as_str(), control_port)).await?;
    let bridge_listener = TcpListener::bind((bridge_host.as_str(), bridge_port)).await?;

    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let (event_tx, mut event_rx) = mpsc::unbounded_channel();
    let mut tasks: Vec<(&'static str, JoinHandle<()>)> = Vec::new();

    let control_state = Arc::clone(&state);
    tasks.push((
        "control-center",
        spawn_component(
            "control-center",
            shutdown_rx.clone(),
            event_tx.clone(),
            async move {
                axum::serve(control_listener, control::router(control_state))
                    .with_graceful_shutdown(wait_for_shutdown(shutdown_rx.clone()))
                    .await
                    .map_err(Error::Io)
            },
        ),
    ));

    let bridge_state = Arc::clone(&state);
    let bridge_shutdown = shutdown_tx.subscribe();
    tasks.push((
        "suggestion-bridge",
        spawn_component(
            "suggestion-bridge",
            bridge_shutdown.clone(),
            event_tx.clone(),
            async move {
                axum::serve(bridge_listener, bridge::router(bridge_state))
                    .with_graceful_shutdown(wait_for_shutdown(bridge_shutdown))
                    .await
                    .map_err(Error::Io)
            },
        ),
    ));

    let worker_state = Arc::clone(&state);
    let worker_shutdown = shutdown_tx.subscribe();
    tasks.push((
        "metadata-worker",
        spawn_component(
            "metadata-worker",
            worker_shutdown.clone(),
            event_tx.clone(),
            worker::run(worker_state, worker_shutdown),
        ),
    ));

    let reaper_shutdown = shutdown_tx.subscribe();
    let reaper_history = Arc::clone(&state.history);
    tasks.push((
        "history-idle-reaper",
        spawn_component(
            "history-idle-reaper",
            reaper_shutdown.clone(),
            event_tx.clone(),
            reaper_history.idle_reaper(reaper_shutdown),
        ),
    ));

    #[cfg(unix)]
    {
        let broker_shutdown = shutdown_tx.subscribe();
        let broker_history = Arc::clone(&state.history);
        tasks.push((
            "history-broker",
            spawn_component(
                "history-broker",
                broker_shutdown.clone(),
                event_tx.clone(),
                broker_history.serve_unix_socket(broker_shutdown),
            ),
        ));
    }

    let signal_tx = event_tx.clone();
    let signal_handle = tokio::spawn(async move {
        match shutdown_signal().await {
            Ok(signal) => {
                let _ = signal_tx.send(CoreEvent::Signal(signal));
            }
            Err(error) => {
                let _ = signal_tx.send(CoreEvent::ComponentStopped {
                    name: "signal-handler",
                    error: Some(error.to_string()),
                });
            }
        }
    });
    drop(event_tx);

    println!(
        "[CORE] unified Rust core ready: metadata worker + Control Center {control_host}:{control_port} + suggestion bridge {bridge_host}:{bridge_port} + History broker"
    );
    println!(
        "[CORE] AppConfig v{} · PromptConfig v{} · model={} · tagging={:?}",
        app.version, prompt.version, prompt.model, prompt.tagging_mode
    );

    let event = event_rx.recv().await.ok_or_else(|| {
        Error::Invalid("all core components disappeared without a shutdown event".into())
    })?;
    let exit_code = match event {
        CoreEvent::Signal(signal) => {
            println!("[CORE] received {signal}; shutting down");
            0
        }
        CoreEvent::ComponentStopped { name, error } => {
            if let Some(error) = error {
                eprintln!("[CORE] {name} failed: {error}");
            } else {
                eprintln!("[CORE] {name} stopped unexpectedly");
            }
            1
        }
    };

    let _ = shutdown_tx.send(true);
    signal_handle.abort();
    let _ = signal_handle.await;
    graceful_join(&mut tasks).await;
    state.history.shutdown().await;
    println!("[CORE] unified core stopped");
    Ok(exit_code)
}

fn spawn_component<F>(
    name: &'static str,
    shutdown: watch::Receiver<bool>,
    events: mpsc::UnboundedSender<CoreEvent>,
    future: F,
) -> JoinHandle<()>
where
    F: Future<Output = Result<(), Error>> + Send + 'static,
{
    tokio::spawn(async move {
        let result = future.await;
        if !*shutdown.borrow() {
            let _ = events.send(CoreEvent::ComponentStopped {
                name,
                error: result.err().map(|error| error.to_string()),
            });
        }
    })
}

async fn wait_for_shutdown(mut shutdown: watch::Receiver<bool>) {
    while !*shutdown.borrow() {
        if shutdown.changed().await.is_err() {
            break;
        }
    }
}

async fn graceful_join(tasks: &mut [(&'static str, JoinHandle<()>)]) {
    let deadline = Instant::now() + Duration::from_secs(SHUTDOWN_JOIN_SECONDS);
    loop {
        if tasks.iter().all(|(_, handle)| handle.is_finished()) {
            break;
        }
        if Instant::now() >= deadline {
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }

    let mut still_active = Vec::new();
    for (name, handle) in tasks.iter_mut() {
        if !handle.is_finished() {
            still_active.push(*name);
            handle.abort();
        }
    }
    if !still_active.is_empty() {
        eprintln!(
            "[CORE] components still active during final shutdown: {}",
            still_active.join(", ")
        );
    }
    for (_, handle) in tasks.iter_mut() {
        let _ = handle.await;
    }
}

fn env_string(name: &str, default: &str) -> String {
    std::env::var(name).unwrap_or_else(|_| default.to_owned())
}

fn env_port(name: &str, default: u16) -> Result<u16, Error> {
    match std::env::var(name) {
        Ok(value) => value
            .parse::<u16>()
            .map_err(|_| Error::Config(format!("{name} must be a valid TCP port"))),
        Err(_) => Ok(default),
    }
}

#[cfg(unix)]
async fn shutdown_signal() -> Result<&'static str, Error> {
    use tokio::signal::unix::{SignalKind, signal};
    let mut terminate = signal(SignalKind::terminate())?;
    tokio::select! {
        result = tokio::signal::ctrl_c() => {
            result?;
            Ok("SIGINT")
        }
        _ = terminate.recv() => Ok("SIGTERM"),
    }
}

#[cfg(not(unix))]
async fn shutdown_signal() -> Result<&'static str, Error> {
    tokio::signal::ctrl_c().await?;
    Ok("Ctrl+C")
}
