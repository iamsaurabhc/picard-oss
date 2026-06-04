//! Clear stale Picard sidecar listeners before starting supervisor (macOS dev quit often orphans node).

use std::process::Command;

const PICARD_PORTS: &[u16] = &[8000, 13130, 3000];

/// Kill any process listening on Picard dev/desktop ports (best-effort).
pub fn free_picard_ports() {
    for port in PICARD_PORTS {
        kill_listeners_on_port(*port);
    }
}

fn kill_listeners_on_port(port: u16) {
    #[cfg(unix)]
    {
        let Ok(output) = Command::new("lsof")
            .args(["-ti", &format!(":{port}")])
            .output()
        else {
            return;
        };
        if !output.status.success() {
            return;
        }
        let pids = String::from_utf8_lossy(&output.stdout);
        for pid in pids.split_whitespace() {
            let _ = Command::new("kill").arg(pid).status();
        }
    }
}
