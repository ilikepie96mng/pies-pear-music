use serde::Serialize;
use std::fs;
use std::io::Read;
use std::net::TcpListener;
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::Manager;
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

struct PythonProcess(Mutex<Option<CommandChild>>);
#[derive(Clone, Serialize)]
struct ApiConnection {
    port: u16,
    capability: String,
}

fn generate_api_capability() -> Result<String, String> {
    let mut bytes = [0_u8; 32];
    fs::File::open("/dev/urandom")
        .and_then(|mut file| file.read_exact(&mut bytes))
        .map_err(|e| format!("Could not generate backend capability: {e}"))?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn allocate_backend_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0")
        .map_err(|e| format!("Could not allocate backend port: {e}"))?;
    let port = listener
        .local_addr()
        .map_err(|e| format!("Could not inspect backend port: {e}"))
        .map(|address| address.port())?;
    if !is_valid_backend_port(port) {
        return Err("Could not allocate a usable backend port".into());
    }
    Ok(port)
}

fn is_valid_backend_port(port: u16) -> bool {
    port != 0
}

#[tauri::command]
fn get_api_connection(connection: tauri::State<ApiConnection>) -> ApiConnection {
    connection.inner().clone()
}

fn wait_for_python(port: u16, capability: &str, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        let url = format!("http://127.0.0.1:{}/health", port);
        if ureq::get(&url)
            .set("x-pies-api-token", capability)
            .call()
            .map(|r| r.status() == 200)
            .unwrap_or(false)
        {
            return true;
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

#[cfg(test)]
mod tests {
    use super::{generate_api_capability, is_valid_backend_port};

    #[test]
    fn rejects_port_zero() {
        assert!(!is_valid_backend_port(0));
        assert!(is_valid_backend_port(43129));
    }

    #[test]
    fn generates_a_256_bit_hex_capability() {
        assert!(generate_api_capability().is_ok_and(|token| {
            token.len() == 64 && token.bytes().all(|byte| byte.is_ascii_hexdigit())
        }));
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let connection = ApiConnection {
                port: allocate_backend_port()?,
                capability: generate_api_capability()?,
            };
            let (_, mut child) = app
                .shell()
                .sidecar("pies-backend")
                .map_err(|e| format!("Failed to configure backend sidecar: {e}"))?
                .arg("--sidecar-handshake")
                .spawn()
                .map_err(|e| format!("Failed to launch backend sidecar: {e}"))?;
            child
                .write(
                    format!(
                        "{}\n",
                        serde_json::to_string(&connection)
                            .map_err(|e| format!("Could not encode backend handshake: {e}"))?
                    )
                    .as_bytes(),
                )
                .map_err(|e| format!("Failed to send backend capability: {e}"))?;
            app.manage(PythonProcess(Mutex::new(Some(child))));
            app.manage(connection.clone());

            if !wait_for_python(
                connection.port,
                &connection.capability,
                Duration::from_secs(15),
            ) {
                eprintln!("WARNING: Python server did not respond within 15 seconds");
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                if let Ok(mut guard) = window.state::<PythonProcess>().0.lock() {
                    if let Some(child) = guard.take() {
                        let _ = child.kill();
                    }
                }
            }
        })
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![get_api_connection])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
