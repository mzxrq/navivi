// Navivi's own installer and uninstaller: one small exe with a WebView2 window (ui/index.html). The app and its tools are
// appended to it as a zip (see payload.rs); `--silent` skips the window for scripts and tests.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod install;
mod payload;
mod system;

use install::{Event, Options};
use payload::Payload;
use serde_json::json;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use tao::dpi::{LogicalSize, PhysicalPosition};
use tao::event::{Event as TaoEvent, WindowEvent};
use tao::event_loop::{ControlFlow, EventLoopBuilder, EventLoopProxy};
use tao::window::WindowBuilder;
use wry::{WebContext, WebViewBuilder};

const PAGE: &str = include_str!("../ui/index.html");
const LOGO_SVG: &str = include_str!("../../public/navivi.svg");
const TYPE_SVG: &str = include_str!("../../public/navivi-type.svg");

#[derive(Default, Debug)]
struct Args {
    silent: bool,
    uninstall: bool,
    relaunched: bool,
    no_launch: bool,
    no_shortcuts: bool,
    /// Kinds of saved data to delete with the app (install::DATA_IDS); `--remove-data` means all of them.
    remove: Vec<String>,
    dir: Option<PathBuf>,
    log: Option<PathBuf>,
}

fn parse_args(args: impl Iterator<Item = String>) -> Args {
    let mut out = Args::default();
    let mut it = args.skip(1);
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--silent" | "/S" => out.silent = true,
            "--uninstall" => out.uninstall = true,
            "--relaunched" => out.relaunched = true,
            "--no-launch" => out.no_launch = true,
            "--no-shortcuts" => out.no_shortcuts = true,
            "--remove-data" => out.remove = install::DATA_IDS.iter().map(|s| s.to_string()).collect(),
            "--remove" => {
                out.remove = it.next().map(|list| list.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect()).unwrap_or_default()
            }
            "--dir" => out.dir = it.next().map(PathBuf::from),
            "--log" => out.log = it.next().map(PathBuf::from),
            _ => {}
        }
    }
    out
}

enum Ui {
    Js(String),
    Quit,
}

fn say(proxy: &EventLoopProxy<Ui>, value: serde_json::Value) {
    let _ = proxy.send_event(Ui::Js(format!("window.__emit({})", value)));
}

fn log_line(path: &Option<PathBuf>, line: &str) {
    if let Some(path) = path {
        use std::io::Write;
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
            let _ = writeln!(f, "{line}");
        }
    }
}

fn uncompressed_mb(payload: &Payload) -> u64 {
    let Ok(mut archive) = payload.archive() else { return 0 };
    let bytes: u64 = (0..archive.len()).filter_map(|i| archive.by_index_raw(i).ok().map(|e| e.size())).sum();
    bytes / 1_048_576 + 1
}

fn fail_box(text: &str) {
    rfd::MessageDialog::new().set_title("Navivi Setup").set_description(text).set_level(rfd::MessageLevel::Error).show();
}

fn main() {
    let args = parse_args(std::env::args());
    let exe = std::env::current_exe().expect("the path of this program");
    let payload = Payload::find(&exe).ok().flatten();

    if args.uninstall {
        return uninstall_main(args, exe);
    }
    let Some(payload) = payload else {
        return fail_box("This setup file is incomplete. Download it again.");
    };
    if args.silent {
        return silent_install(args, payload);
    }
    window_main(payload, false, args, exe);
}

fn silent_install(args: Args, payload: Payload) {
    let dir = install::resolve_dir(&args.dir.clone().unwrap_or_else(install::default_dir));
    let opts = Options { dir, desktop: !args.no_shortcuts, start_menu: !args.no_shortcuts, launch: !args.no_launch, close_running: true };
    log_line(&args.log, &format!("installing into {}", opts.dir.display()));
    match install::install(&opts, &payload, |_| {}) {
        Ok(manifest) => {
            log_line(&args.log, "done");
            if opts.launch {
                system::spawn_detached(&opts.dir.join(&manifest.exe), &[], Some(&opts.dir));
            }
        }
        Err(e) => {
            log_line(&args.log, &format!("failed: {e}"));
            std::process::exit(1);
        }
    }
}

/// The uninstaller runs from a copy in %TEMP% so it can delete its own folder.
fn uninstall_main(args: Args, exe: PathBuf) {
    let dir = args.dir.clone().or_else(|| exe.parent().map(Path::to_path_buf)).expect("a folder to remove");
    // Only a folder this installer made: a setup file run with --uninstall from Downloads, or a mistyped --dir, must not stop or
    // remove anything there.
    if !dir.join(install::MARKER).exists() && !dir.join(install::UNINSTALLER).exists() {
        let message = format!("{} is not a Navivi install folder, so nothing was removed.", dir.display());
        log_line(&args.log, &message);
        if !args.silent {
            fail_box(&message);
        }
        std::process::exit(2);
    }
    if !args.relaunched {
        let copy = std::env::temp_dir().join(format!("navivi-uninstall-{}.exe", std::process::id()));
        if std::fs::copy(&exe, &copy).is_ok() {
            let mut forward = vec!["--uninstall", "--relaunched", "--dir"];
            let dir_text = dir.display().to_string();
            forward.push(&dir_text);
            if args.silent {
                forward.push("--silent");
            }
            let remove_text = args.remove.join(",");
            if !args.remove.is_empty() {
                forward.extend(["--remove", &remove_text]);
            }
            let log_text = args.log.as_ref().map(|p| p.display().to_string());
            if let Some(l) = &log_text {
                forward.extend(["--log", l]);
            }
            system::spawn_detached(&copy, &forward, None);
            return;
        }
    }
    if args.silent {
        let result = install::uninstall(&dir, &args.remove);
        log_line(&args.log, &format!("uninstall: {result:?}"));
        finish_uninstall(&dir, &exe);
        if result.is_err() {
            std::process::exit(1);
        }
        return;
    }
    window_main_uninstall(dir, exe, args);
}

fn finish_uninstall(dir: &Path, own_exe: &Path) {
    let _ = std::fs::remove_dir(dir); // only if nothing else is in it
    system::delete_after_exit(own_exe);
}

/// An SVG as a `data:` URL for an `<img>`, so a stylesheet cannot reach into it and a missing size cannot blow it up.
fn svg_data_uri(svg: &str) -> String {
    let mut out = String::from("data:image/svg+xml;utf8,");
    for b in svg.trim_start_matches('\u{feff}').trim().bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => out.push(b as char),
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

fn page() -> String {
    PAGE.replace("{{LOGO_SVG}}", LOGO_SVG.trim_start_matches('\u{feff}')).replace("{{TYPE_URI}}", &svg_data_uri(TYPE_SVG))
}

fn window_main_uninstall(dir: PathBuf, exe: PathBuf, args: Args) {
    let _ = args;
    run_window(None, true, dir, exe);
}

fn window_main(payload: Payload, _uninstall: bool, _args: Args, exe: PathBuf) {
    let dir = install::default_dir();
    run_window(Some(payload), false, dir, exe);
}

fn run_window(payload: Option<Payload>, uninstall: bool, default_dir: PathBuf, own_exe: PathBuf) {
    let event_loop = EventLoopBuilder::<Ui>::with_user_event().build();
    let proxy = event_loop.create_proxy();
    let window = Arc::new(
        WindowBuilder::new()
            .with_title(if uninstall { "Navivi Uninstall" } else { "Navivi Setup" })
            .with_inner_size(LogicalSize::new(780.0, 480.0))
            .with_resizable(false)
            .with_maximizable(false)
            .with_decorations(false)
            .build(&event_loop)
            .expect("a window"),
    );
    if let Some(monitor) = window.primary_monitor() {
        let size = window.outer_size();
        let m = monitor.size();
        window.set_outer_position(PhysicalPosition::new(
            monitor.position().x + (m.width as i32 - size.width as i32) / 2,
            monitor.position().y + (m.height as i32 - size.height as i32) / 2,
        ));
    }

    let installed_dir: Arc<Mutex<Option<(PathBuf, String)>>> = Arc::new(Mutex::new(None));
    let payload = payload.map(Arc::new);
    let handler_window = window.clone();
    let handler_proxy = proxy.clone();
    let handler_dir = default_dir.clone();
    let handler_exe = own_exe.clone();

    // Keep the browser profile out of the folder the setup was downloaded to.
    let mut context = WebContext::new(Some(std::env::temp_dir().join("navivi-setup-webview")));
    let built = WebViewBuilder::new_with_web_context(&mut context)
        .with_html(page())
        .with_background_color((11, 16, 32, 255))
        .with_ipc_handler(move |request| {
            let Ok(msg) = serde_json::from_str::<serde_json::Value>(request.body()) else { return };
            let proxy = handler_proxy.clone();
            match msg["cmd"].as_str().unwrap_or("") {
                "ready" => {
                    let running = if uninstall { false } else { !system::running_instances(&handler_dir).is_empty() };
                    let (version, name, size_mb) = match &payload {
                        Some(p) => {
                            let manifest = p.archive().ok().and_then(|mut a| payload::read_manifest(&mut a).ok());
                            (
                                manifest.as_ref().map(|m| m.version.clone()).unwrap_or_default(),
                                manifest.as_ref().map(|m| m.name.clone()).unwrap_or_else(|| "Navivi".into()),
                                uncompressed_mb(p),
                            )
                        }
                        None => (String::new(), "Navivi".into(), 0),
                    };
                    say(&proxy, json!({
                        "type": "init", "mode": if uninstall { "uninstall" } else { "install" },
                        "lang": if system::ui_is_japanese() { "ja" } else { "en" },
                        "version": version, "name": name, "dir": handler_dir.display().to_string(),
                        "sizeMb": size_mb, "running": running,
                        // Only the uninstaller lists saved data (asking Windows for the Documents folder takes a moment).
                        "data": if uninstall {
                            install::DATA_IDS.iter().map(|id| json!({ "id": id, "mb": install::data_size_of(id) / 1_048_576 })).collect::<Vec<_>>()
                        } else {
                            Vec::new()
                        },
                    }));
                }
                "drag" => {
                    let _ = handler_window.drag_window();
                }
                "min" => handler_window.set_minimized(true),
                "close" => {
                    let _ = proxy.send_event(Ui::Quit);
                }
                "browse" => {
                    let start = handler_dir.clone();
                    std::thread::spawn(move || {
                        if let Some(picked) = rfd::FileDialog::new().set_directory(&start).pick_folder() {
                            let resolved = install::resolve_dir(&picked);
                            // A folder the install cannot go into is refused right here, so the old choice stays.
                            match install::check_dir(&resolved) {
                                Ok(()) => say(&proxy, json!({ "type": "dir", "path": resolved.display().to_string() })),
                                Err(problem) => say(&proxy, json!({ "type": "dirRejected", "reason": problem.code() })),
                            }
                        }
                    });
                }
                "install" => {
                    let Some(payload) = payload.clone() else { return };
                    let installed = installed_dir.clone();
                    let dir = PathBuf::from(msg["dir"].as_str().unwrap_or_default());
                    let opts = Options {
                        dir: install::resolve_dir(&dir),
                        desktop: msg["desktop"].as_bool().unwrap_or(true),
                        start_menu: msg["startMenu"].as_bool().unwrap_or(true),
                        launch: true,
                        close_running: msg["closeRunning"].as_bool().unwrap_or(false),
                    };
                    std::thread::spawn(move || {
                        let progress = proxy.clone();
                        match install::install(&opts, &payload, |event| match event {
                            Event::Progress { pct, file } => say(&progress, json!({ "type": "progress", "pct": pct, "file": file })),
                            Event::Step { name } => say(&progress, json!({ "type": "step", "name": name })),
                            Event::Note { name } => say(&progress, json!({ "type": "note", "name": name })),
                        }) {
                            Ok(manifest) => {
                                *installed.lock().unwrap() = Some((opts.dir.clone(), manifest.exe));
                                say(&proxy, json!({ "type": "done" }));
                            }
                            Err(e) if e == "RUNNING" => say(&proxy, json!({ "type": "running" })),
                            Err(e) => say(&proxy, json!({ "type": "error", "message": e })),
                        }
                    });
                }
                "launch" => {
                    if let Some((dir, exe)) = installed_dir.lock().unwrap().clone() {
                        system::spawn_detached(&dir.join(exe), &[], Some(&dir));
                    }
                    let _ = proxy.send_event(Ui::Quit);
                }
                "uninstall" => {
                    let dir = handler_dir.clone();
                    let own = handler_exe.clone();
                    let remove: Vec<String> = msg["remove"]
                        .as_array()
                        .map(|list| list.iter().filter_map(|v| v.as_str().map(String::from)).collect())
                        .unwrap_or_default();
                    std::thread::spawn(move || match install::uninstall(&dir, &remove) {
                        Ok(()) => {
                            finish_uninstall(&dir, &own);
                            say(&proxy, json!({ "type": "done" }));
                        }
                        Err(e) => say(&proxy, json!({ "type": "error", "message": e })),
                    });
                }
                _ => {}
            }
        })
        .build(window.as_ref());

    let webview = match built {
        Ok(webview) => webview,
        Err(e) => {
            fail_box(&format!("Navivi Setup needs Microsoft Edge WebView2, which is missing or damaged.\nInstall it from https://go.microsoft.com/fwlink/p/?LinkId=2124703 and run this again.\n\n({e})"));
            return;
        }
    };

    event_loop.run(move |event, _, control_flow| {
        *control_flow = ControlFlow::Wait;
        match event {
            TaoEvent::UserEvent(Ui::Js(script)) => {
                let _ = webview.evaluate_script(&script);
            }
            TaoEvent::UserEvent(Ui::Quit) | TaoEvent::WindowEvent { event: WindowEvent::CloseRequested, .. } => {
                *control_flow = ControlFlow::Exit;
            }
            _ => {}
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(list: &[&str]) -> Args {
        parse_args(std::iter::once("setup.exe").chain(list.iter().copied()).map(String::from))
    }

    #[test]
    fn the_command_line_flags_are_read() {
        let a = args(&["--silent", "--dir", r"C:\Apps\Navivi", "--no-launch", "--no-shortcuts", "--log", "x.log"]);
        assert!(a.silent && a.no_launch && a.no_shortcuts && !a.uninstall);
        assert_eq!(a.dir, Some(PathBuf::from(r"C:\Apps\Navivi")));
        assert_eq!(a.log, Some(PathBuf::from("x.log")));
        let u = args(&["--uninstall", "--relaunched", "--remove-data"]);
        assert!(u.uninstall && u.relaunched);
        assert_eq!(u.remove.len(), install::DATA_IDS.len(), "--remove-data means every kind");
        let some = args(&["--uninstall", "--remove", "runtime, engines,,keys"]);
        assert_eq!(some.remove, ["runtime", "engines", "keys"]);
        assert!(args(&["--uninstall"]).remove.is_empty(), "nothing is deleted unless asked");
        assert!(args(&["/S"]).silent, "NSIS-style silent flag still works");
    }

    #[test]
    fn the_page_gets_both_logos_filled_in() {
        let html = page();
        assert!(!html.contains("{{LOGO_SVG}}") && !html.contains("{{TYPE_URI}}"));
        assert!(html.contains("<svg"));
        assert!(html.contains("src=\"data:image/svg+xml;utf8,%3Csvg"));
    }
}
