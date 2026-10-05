//! Catches the browser redirect of a sign-in flow (OpenRouter's PKCE login) on a loopback port.
//!
//! Two steps, because the page that asks the user to sign in needs the port first: `oauth_listen_start` binds a free
//! port and returns it, `oauth_listen_wait` then waits for the single request that carries `?code=`.

use std::io::{Read, Write};
use std::net::TcpListener;
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::State;

#[derive(Default)]
pub struct OauthListener(pub Mutex<Option<TcpListener>>);

const DONE_PAGE: &str = "<!doctype html><meta charset=utf-8><title>Navivi</title>\
<body style=\"font:16px system-ui;margin:15vh auto;max-width:28rem;text-align:center;color:#27272a\">\
<h2 style=\"font-weight:600\">You are signed in</h2><p>You can close this tab and go back to Navivi.</p></body>";

/// The `code` query value of a request line like `GET /callback?code=abc&x=1 HTTP/1.1`.
fn code_from_request(request: &str) -> Option<String> {
    let target = request.lines().next()?.split_whitespace().nth(1)?;
    let query = target.split_once('?')?.1;
    query
        .split('&')
        .find_map(|pair| pair.strip_prefix("code="))
        .filter(|code| !code.is_empty() && code.chars().all(|c| c.is_ascii_alphanumeric() || "-_.~".contains(c)))
        .map(str::to_string)
}

fn wait_for_code(listener: TcpListener, timeout: Duration) -> Result<String, String> {
    listener.set_nonblocking(true).map_err(|e| e.to_string())?;
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        match listener.accept() {
            Ok((mut stream, _)) => {
                let _ = stream.set_nonblocking(false);
                let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
                let mut buf = [0u8; 4096];
                let read = stream.read(&mut buf).unwrap_or(0);
                let code = code_from_request(&String::from_utf8_lossy(&buf[..read]));
                let (status, body) = if code.is_some() { ("200 OK", DONE_PAGE) } else { ("404 Not Found", "") };
                let _ = write!(
                    stream,
                    "HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                if let Some(code) = code {
                    return Ok(code);
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => std::thread::sleep(Duration::from_millis(100)),
            Err(e) => return Err(e.to_string()),
        }
    }
    Err("The sign-in was not completed in time.".to_string())
}

#[tauri::command]
pub fn oauth_listen_start(state: State<OauthListener>) -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|e| e.to_string())?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();
    *state.0.lock().map_err(|e| e.to_string())? = Some(listener);
    Ok(port)
}

#[tauri::command]
pub async fn oauth_listen_wait(state: State<'_, OauthListener>, timeout_secs: u64) -> Result<String, String> {
    let listener = state
        .0
        .lock()
        .map_err(|e| e.to_string())?
        .take()
        .ok_or_else(|| "No sign-in is waiting.".to_string())?;
    tauri::async_runtime::spawn_blocking(move || wait_for_code(listener, Duration::from_secs(timeout_secs.min(600))))
        .await
        .map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_the_code_from_the_request_line() {
        assert_eq!(code_from_request("GET /callback?code=abc123 HTTP/1.1\r\nHost: x").as_deref(), Some("abc123"));
        assert_eq!(code_from_request("GET /callback?state=1&code=a-b_c HTTP/1.1").as_deref(), Some("a-b_c"));
    }

    #[test]
    fn ignores_requests_without_a_usable_code() {
        assert_eq!(code_from_request("GET /favicon.ico HTTP/1.1"), None);
        assert_eq!(code_from_request("GET /callback?code= HTTP/1.1"), None);
        assert_eq!(code_from_request("GET /callback?code=a%20b HTTP/1.1"), None);
        assert_eq!(code_from_request(""), None);
    }

    #[test]
    fn answers_the_browser_and_returns_the_code() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let client = std::thread::spawn(move || {
            let mut s = std::net::TcpStream::connect(("127.0.0.1", port)).unwrap();
            s.write_all(b"GET /callback?code=xyz HTTP/1.1\r\nHost: localhost\r\n\r\n").unwrap();
            let mut reply = String::new();
            s.read_to_string(&mut reply).unwrap();
            reply
        });
        assert_eq!(wait_for_code(listener, Duration::from_secs(5)).unwrap(), "xyz");
        assert!(client.join().unwrap().starts_with("HTTP/1.1 200 OK"));
    }

    #[test]
    fn gives_up_after_the_timeout() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        assert!(wait_for_code(listener, Duration::from_millis(200)).is_err());
    }
}
