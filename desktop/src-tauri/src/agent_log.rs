use std::path::PathBuf;

use tauri::Manager;

/// No-op in release builds; optional `PICARD_AGENT_LOG` path in debug.
pub fn agent_log(_hypothesis_id: &str, _location: &str, _message: &str, _data: serde_json::Value) {
    #[cfg(debug_assertions)]
    {
        use std::io::Write;
        use std::time::{SystemTime, UNIX_EPOCH};
        let Some(log_path) = std::env::var_os("PICARD_AGENT_LOG") else {
            return;
        };
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis())
            .unwrap_or(0);
        let line = serde_json::json!({
            "location": _location,
            "message": _message,
            "data": _data,
            "timestamp": ts,
        });
        if let Ok(mut f) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(log_path)
        {
            let _ = writeln!(f, "{line}");
        }
    }
}

/// Resolve `Contents/Resources` for the running bundle.
///
/// Tauri's `PathResolver::resource_dir()` can return `unknown path` when the app is
/// launched from a DMG (Gatekeeper translocates the .app under `/tmp/...` while
/// `STARTING_BINARY` still points at `/Volumes/...`). Fall back to the executable path,
/// same strategy as `picard_supervisor`.
pub fn resolve_resource_dir(app: &tauri::AppHandle) -> PathBuf {
    if let Ok(dir) = app.path().resource_dir() {
        if bundled_root(&dir).join("frontend").join("server.js").is_file() {
            return dir;
        }
    }
    resource_dir_from_exe().unwrap_or_else(|| {
        app.path()
            .resource_dir()
            .unwrap_or_else(|_| PathBuf::from("."))
    })
}

fn resource_dir_from_exe() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let parent = exe.parent()?;
    #[cfg(target_os = "macos")]
    {
        let dir = parent.parent()?.join("Resources");
        if bundled_root(&dir).join("frontend").join("server.js").is_file() {
            return Some(dir);
        }
    }
    #[cfg(target_os = "windows")]
    {
        let dir = parent.join("resources");
        if bundled_root(&dir).join("frontend").join("server.js").is_file() {
            return Some(dir);
        }
    }
    #[cfg(target_os = "linux")]
    {
        let dir = parent.join("../lib/picard/resources");
        if bundled_root(&dir).join("frontend").join("server.js").is_file() {
            return dir.canonicalize().ok();
        }
    }
    None
}

/// Tauri copies `resources/frontend` → `Contents/Resources/resources/frontend`.
pub fn bundled_root(resource_dir: &PathBuf) -> PathBuf {
    let nested = resource_dir.join("resources");
    if nested.join("frontend").join("server.js").is_file() {
        return nested;
    }
    if resource_dir
        .join("frontend")
        .join("server.js")
        .is_file()
    {
        return resource_dir.clone();
    }
    nested
}
