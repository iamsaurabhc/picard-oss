#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod agent_log;
use agent_log::{agent_log, bundled_root, resolve_resource_dir};

use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::{Manager, RunEvent};

struct SidecarState(Mutex<Option<std::process::Child>>);

fn supervisor_exe() -> Result<std::path::PathBuf, String> {
    let exe = std::env::current_exe().map_err(|e| format!("current_exe: {e}"))?;
    let dir = exe.parent().ok_or("missing executable parent directory")?;
    #[cfg(windows)]
    let candidates = [dir.join("picard-supervisor.exe"), dir.join("picard-supervisor")];
    #[cfg(not(windows))]
    let candidates = [dir.join("picard-supervisor")];
    for path in candidates {
        if path.is_file() {
            return Ok(path);
        }
    }
    Err(format!("picard-supervisor missing in {:?}", dir))
}

fn wait_for_url(url: &str, max_secs: u64) -> bool {
    for i in 0..(max_secs * 10) {
        let ok = ureq::get(url).call().map(|r| r.status() == 200).unwrap_or(false);
        if ok {
            agent_log(
                "H4",
                "main.rs:wait_for_url",
                "url ready",
                serde_json::json!({ "url": url, "attempt": i }),
            );
            return true;
        }
        thread::sleep(Duration::from_millis(100));
    }
    agent_log(
        "H4",
        "main.rs:wait_for_url",
        "url timeout",
        serde_json::json!({ "url": url, "max_secs": max_secs }),
    );
    false
}

fn spawn_supervisor(app: &tauri::AppHandle) -> Result<(), String> {
    let resource_dir = resolve_resource_dir(app);
    let bundle = bundled_root(&resource_dir);
    if !bundle.join("frontend").join("server.js").is_file() {
        return Err(format!(
            "bundled frontend missing at {:?}",
            bundle.join("frontend").join("server.js")
        ));
    }
    agent_log(
        "H1",
        "main.rs:spawn_supervisor",
        "resource paths",
        serde_json::json!({
            "resource_dir": resource_dir.display().to_string(),
            "bundle": bundle.display().to_string(),
        }),
    );

    // Spawn the supervisor binary directly. Tauri's sidecar API rejects translocated
    // .app paths under /tmp when launched from a DMG (symlink in current_exe).
    let supervisor = supervisor_exe()?;
    let child = Command::new(&supervisor)
        .env("PICARD_RESOURCE_DIR", &resource_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("spawn supervisor: {e}"))?;

    agent_log(
        "H5",
        "main.rs:spawn_supervisor",
        "supervisor spawned",
        serde_json::json!({
            "ok": true,
            "supervisor": supervisor.display().to_string(),
            "pid": child.id(),
        }),
    );

    if let Some(state) = app.try_state::<SidecarState>() {
        *state.0.lock().unwrap() = Some(child);
    }

    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(SidecarState(Mutex::new(None)))
        .setup(|app| {
            let embedded = std::env::var("PICARD_EMBEDDED").ok().as_deref() == Some("1")
                || !cfg!(debug_assertions);

            agent_log(
                "H5",
                "main.rs:setup",
                "setup start",
                serde_json::json!({ "embedded": embedded }),
            );

            if embedded {
                let handle = app.handle().clone();
                if let Err(e) = spawn_supervisor(&handle) {
                    agent_log(
                        "H5",
                        "main.rs:setup",
                        "spawn_supervisor error",
                        serde_json::json!({ "error": e }),
                    );
                    eprintln!("Picard: {e}");
                    // Do not abort setup — a panic here crashes the whole app on launch.
                }

                let backend_ok = wait_for_url("http://127.0.0.1:8000/health", 120);
                let frontend_ok = wait_for_url("http://127.0.0.1:13130", 120);
                agent_log(
                    "H4",
                    "main.rs:setup",
                    "health results",
                    serde_json::json!({ "backend_ok": backend_ok, "frontend_ok": frontend_ok }),
                );
                if !backend_ok {
                    eprintln!("Picard: backend health check timed out (see ~/Library/Application Support/Picard/desktop-backend.log)");
                }
                if !frontend_ok {
                    eprintln!("Picard: frontend health check timed out");
                }
                // Still show the window so the user sees errors instead of a silent abort.
            } else {
                eprintln!("Picard dev: use ./scripts/start.sh or set PICARD_EMBEDDED=1");
            }

            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                if let Some(state) = window.app_handle().try_state::<SidecarState>() {
                    if let Some(mut child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while running Picard desktop")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<SidecarState>() {
                    if let Some(mut child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        });
}
