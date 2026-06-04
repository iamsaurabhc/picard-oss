//! Sidecar: starts bundled backend + Next standalone from Tauri resources.
mod agent_log {
    include!("../agent_log.rs");
}
mod port_cleanup {
    include!("../port_cleanup.rs");
}
use agent_log::{agent_log, bundled_root};
use port_cleanup::free_picard_ports;

use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::thread;
use std::time::Duration;

fn picard_data_dir() -> PathBuf {
    if let Ok(d) = std::env::var("PICARD_DATA_DIR") {
        return PathBuf::from(d);
    }
    #[cfg(target_os = "macos")]
    {
        if let Ok(home) = std::env::var("HOME") {
            return PathBuf::from(home).join("Library/Application Support/Picard");
        }
    }
    #[cfg(target_os = "windows")]
    {
        if let Ok(appdata) = std::env::var("APPDATA") {
            return PathBuf::from(appdata).join("Picard");
        }
    }
    #[cfg(target_os = "linux")]
    {
        if let Ok(home) = std::env::var("HOME") {
            return PathBuf::from(home).join(".local/share/picard");
        }
    }
    PathBuf::from(".picard-data")
}

fn backend_exe(bundle: &PathBuf) -> PathBuf {
    let in_bundle = bundle.join("backend").join("picard-backend");
    if in_bundle.is_file() {
        return in_bundle;
    }
    #[cfg(windows)]
    {
        return bundle.join("backend").join("picard-backend.exe");
    }
    let dir = std::env::current_exe()
        .expect("current_exe")
        .parent()
        .expect("exe parent")
        .to_path_buf();
    #[cfg(windows)]
    {
        return dir.join("picard-backend.exe");
    }
    #[cfg(not(windows))]
    {
        return dir.join("picard-backend");
    }
}

fn node_exe(bundle: &PathBuf) -> PathBuf {
    let bundled = bundle.join("node").join("node");
    if bundled.is_file() {
        return bundled;
    }
    #[cfg(windows)]
    {
        return PathBuf::from("node.exe");
    }
    #[cfg(not(windows))]
    {
        return PathBuf::from("node");
    }
}

fn url_ok(url: &str) -> bool {
    ureq::get(url).call().map(|r| r.status() == 200).unwrap_or(false)
}

fn spawn_backend(
    bundle: &PathBuf,
    data_dir: &PathBuf,
    db_url: &str,
    backend_port: &str,
) -> std::process::Child {
    let backend = backend_exe(bundle);
    let mut cmd = Command::new(&backend);
    cmd.current_dir(backend.parent().unwrap_or(bundle))
        .env("PICARD_DATA_DIR", data_dir)
        .env("DATABASE_URL", db_url)
        .env("BACKEND_PORT", backend_port)
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    cmd.spawn().expect("spawn backend")
}

fn main() {
    let raw_resource = std::env::var("PICARD_RESOURCE_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            let exe = std::env::current_exe().expect("current_exe");
            let parent = exe.parent().expect("exe parent");
            #[cfg(target_os = "macos")]
            {
                return parent
                    .parent()
                    .expect("Contents")
                    .join("Resources");
            }
            #[cfg(target_os = "windows")]
            {
                return parent.join("resources");
            }
            #[cfg(target_os = "linux")]
            {
                return parent.join("../lib/picard/resources");
            }
        });

    free_picard_ports();

    let bundle = bundled_root(&raw_resource);
    agent_log(
        "H1",
        "picard_supervisor.rs:main",
        "resolved bundle root",
        serde_json::json!({
            "raw_resource": raw_resource.display().to_string(),
            "bundle": bundle.display().to_string(),
            "server_js_exists": bundle.join("frontend").join("server.js").is_file(),
        }),
    );

    let data_dir = picard_data_dir();
    std::fs::create_dir_all(&data_dir).ok();

    let backend_port = std::env::var("BACKEND_PORT").unwrap_or_else(|_| "8000".into());
    // 13130 avoids colliding with `next dev` / Docker on :3000 when the desktop app runs.
    let frontend_port = std::env::var("FRONTEND_PORT").unwrap_or_else(|_| "13130".into());
    let db_url = format!("sqlite:///{}", data_dir.join("picard.db").display());

    let backend = backend_exe(&bundle);
    if !backend.is_file() {
        eprintln!("picard-supervisor: backend missing at {:?}", backend);
        std::process::exit(1);
    }

    let mut backend_child = spawn_backend(&bundle, &data_dir, &db_url, &backend_port);
    agent_log(
        "H2",
        "picard_supervisor.rs:spawn_backend",
        "backend spawned",
        serde_json::json!({ "pid": backend_child.id(), "path": backend.display().to_string() }),
    );

    let frontend_dir = bundle.join("frontend");
    let server_js = frontend_dir.join("server.js");
    if !server_js.is_file() {
        eprintln!(
            "picard-supervisor: frontend missing at {:?}",
            server_js
        );
        let _ = backend_child.kill();
        std::process::exit(1);
    }

    let node = node_exe(&bundle);
    let polyfill = frontend_dir.join("node-polyfills.cjs");
    let mut fe_cmd = Command::new(&node);
    if polyfill.is_file() {
        fe_cmd.arg("--require").arg(&polyfill);
    }
    let fe_url = format!("http://127.0.0.1:{frontend_port}");
    let mut fe_child: Option<std::process::Child> = None;
    if url_ok(&fe_url) {
        eprintln!("picard-supervisor: reusing UI already listening on {fe_url}");
    } else {
        fe_child = Some(
            fe_cmd
                .arg(&server_js)
                .current_dir(&frontend_dir)
                .env("PORT", &frontend_port)
                .env("HOSTNAME", "127.0.0.1")
                .env("NODE_ENV", "production")
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .unwrap_or_else(|e| {
                    eprintln!("picard-supervisor: spawn frontend failed: {e}");
                    std::process::exit(1);
                }),
        );
        agent_log(
            "H3",
            "picard_supervisor.rs:spawn_frontend",
            "frontend spawned",
            serde_json::json!({ "pid": fe_child.as_ref().map(|c| c.id()) }),
        );
    }

    loop {
        thread::sleep(Duration::from_secs(2));
        if let Ok(Some(status)) = backend_child.try_wait() {
            agent_log(
                "H6",
                "picard_supervisor.rs:backend_exit",
                "backend exited — restarting",
                serde_json::json!({ "code": status.code() }),
            );
            backend_child = spawn_backend(&bundle, &data_dir, &db_url, &backend_port);
        }
        if let Some(ref mut child) = fe_child {
            if child.try_wait().ok().flatten().is_some() {
                agent_log(
                    "H4",
                    "picard_supervisor.rs:exit",
                    "frontend exited — stopping supervisor",
                    serde_json::json!({}),
                );
                let _ = backend_child.kill();
                break;
            }
        }
    }
}
