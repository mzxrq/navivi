//! Catches the browser redirect of a sign-in flow (OpenRouter's PKCE login) on a loopback port.
//!
//! Two steps, because the page that asks the user to sign in needs the port first: `oauth_listen_start` binds a free
//! port and returns it, `oauth_listen_wait` then waits for the single request to `/callback/<nonce>` that carries `?code=`.
//! The nonce keeps other local processes and web pages from feeding the listener a code; `oauth_listen_cancel` frees it.

use std::io::{Read, Write};
use std::net::TcpListener;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::State;

#[derive(Default)]
pub struct OauthListener {
    pending: Mutex<Option<(TcpListener, String)>>,
    cancelled: Arc<AtomicBool>,
}

const DONE_PAGE: &str = "<!doctype html><meta charset=utf-8><title>Navivi</title>\
<body style=\"font:16px system-ui;margin:15vh auto;max-width:28rem;text-align:center;color:#27272a\">\
<h2 style=\"font-weight:600\">You are signed in</h2><p>You can close this tab and go back to Navivi.</p></body>";

enum Callback {
    Code(String),
    Denied(String),
    Other,
}

/// What a request line like `GET /callback/<nonce>?code=abc&x=1 HTTP/1.1` carries: a `code`, an `error`, or nothing usable.
fn parse_callback(request: &str, nonce: &str) -> Callback {
    let Some(target) = request.lines().next().and_then(|l| l.split_whitespace().nth(1)) else {
        return Callback::Other;
    };
    let (path, query) = target.split_once('?').unwrap_or((target, ""));
    if path != format!("/callback/{nonce}") {
        return Callback::Other;
    }
    let value = |key: &str| query.split('&').find_map(|pair| pair.strip_prefix(key));
    if let Some(error) = value("error=").filter(|e| !e.is_empty()) {
        return Callback::Denied(error.chars().take(80).collect());
    }
    match value("code=").filter(|code| !code.is_empty() && code.chars().all(|c| c.is_ascii_alphanumeric() || "-_.~".contains(c))) {
        Some(code) => Callback::Code(code.to_string()),
        None => Callback::Other,
    }
}

fn wait_for_code(listener: TcpListener, nonce: &str, timeout: Duration, cancelled: &AtomicBool) -> Result<String, String> {
    listener.set_nonblocking(true).map_err(|e| e.to_string())?;
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if cancelled.load(Ordering::Relaxed) {
            return Err("The sign-in was cancelled.".to_string());
        }
        match listener.accept() {
            Ok((mut stream, _)) => {
                let _ = stream.set_nonblocking(false);
                let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
                let mut buf = [0u8; 4096];
                let read = stream.read(&mut buf).unwrap_or(0);
                let callback = parse_callback(&String::from_utf8_lossy(&buf[..read]), nonce);
                let (status, body) = match callback {
                    Callback::Code(_) => ("200 OK", DONE_PAGE),
                    _ => ("404 Not Found", ""),
                };
                let _ = write!(
                    stream,
                    "HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                match callback {
                    Callback::Code(code) => return Ok(code),
                    Callback::Denied(error) => return Err(format!("The sign-in was refused ({error}).")),
                    Callback::Other => {}
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => std::thread::sleep(Duration::from_millis(100)),
            Err(e) => return Err(e.to_string()),
        }
    }
    Err("The sign-in was not completed in time.".to_string())
}

#[tauri::command]
pub fn oauth_listen_start(state: State<OauthListener>, nonce: String) -> Result<u16, String> {
    if nonce.len() < 16 || !nonce.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
        return Err("Invalid sign-in nonce.".to_string());
    }
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|e| e.to_string())?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();
    state.cancelled.store(false, Ordering::Relaxed);
    *state.pending.lock().map_err(|e| e.to_string())? = Some((listener, nonce));
    Ok(port)
}

#[tauri::command]
pub async fn oauth_listen_wait(state: State<'_, OauthListener>, timeout_secs: u64) -> Result<String, String> {
    let (listener, nonce) = state
        .pending
        .lock()
        .map_err(|e| e.to_string())?
        .take()
        .ok_or_else(|| "No sign-in is waiting.".to_string())?;
    let timeout = Duration::from_secs(timeout_secs.min(600));
    let cancelled = state.cancelled.clone();
    tauri::async_runtime::spawn_blocking(move || wait_for_code(listener, &nonce, timeout, &cancelled))
        .await
        .map_err(|e| e.to_string())?
}

/// Stops a waiting sign-in and frees the port, also when the browser could not be opened and nothing is waiting yet.
#[tauri::command]
pub fn oauth_listen_cancel(state: State<OauthListener>) {
    state.cancelled.store(true, Ordering::Relaxed);
    if let Ok(mut pending) = state.pending.lock() {
        pending.take();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const NONCE: &str = "n0nce-n0nce-n0nce";

    fn code(request: &str) -> Option<String> {
        match parse_callback(request, NONCE) {
            Callback::Code(c) => Some(c),
            _ => None,
        }
    }

    #[test]
    fn reads_the_code_from_the_request_line() {
        assert_eq!(code("GET /callback/n0nce-n0nce-n0nce?code=abc123 HTTP/1.1\r\nHost: x").as_deref(), Some("abc123"));
        assert_eq!(code("GET /callback/n0nce-n0nce-n0nce?state=1&code=a-b_c HTTP/1.1").as_deref(), Some("a-b_c"));
    }

    #[test]
    fn ignores_requests_without_a_usable_code() {
        assert_eq!(code("GET /favicon.ico HTTP/1.1"), None);
        assert_eq!(code("GET /callback/n0nce-n0nce-n0nce?code= HTTP/1.1"), None);
        assert_eq!(code("GET /callback/n0nce-n0nce-n0nce?code=a%20b HTTP/1.1"), None);
        assert_eq!(code(""), None);
    }

    #[test]
    fn ignores_a_code_sent_to_the_wrong_path() {
        assert_eq!(code("GET /callback?code=abc HTTP/1.1"), None);
        assert_eq!(code("GET /callback/other?code=abc HTTP/1.1"), None);
    }

    #[test]
    fn reports_a_refused_sign_in() {
        assert!(matches!(parse_callback("GET /callback/n0nce-n0nce-n0nce?error=access_denied HTTP/1.1", NONCE), Callback::Denied(e) if e == "access_denied"));
    }

    #[test]
    fn answers_the_browser_and_returns_the_code() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let client = std::thread::spawn(move || {
            let mut s = std::net::TcpStream::connect(("127.0.0.1", port)).unwrap();
            s.write_all(b"GET /callback/n0nce-n0nce-n0nce?code=xyz HTTP/1.1\r\nHost: localhost\r\n\r\n").unwrap();
            let mut reply = String::new();
            s.read_to_string(&mut reply).unwrap();
            reply
        });
        assert_eq!(wait_for_code(listener, NONCE, Duration::from_secs(5), &AtomicBool::new(false)).unwrap(), "xyz");
        assert!(client.join().unwrap().starts_with("HTTP/1.1 200 OK"));
    }

    #[test]
    fn gives_up_after_the_timeout() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        assert!(wait_for_code(listener, NONCE, Duration::from_millis(200), &AtomicBool::new(false)).is_err());
    }

    #[test]
    fn stops_when_cancelled() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let err = wait_for_code(listener, NONCE, Duration::from_secs(30), &AtomicBool::new(true)).unwrap_err();
        assert!(err.contains("cancelled"));
    }
}
