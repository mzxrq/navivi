//! API keys for online AI providers and the map services, kept in the operating system's credential store
//! (Windows Credential Manager, macOS Keychain, Secret Service). They never go into a project folder, the
//! database or a `.nvv`.

use keyring::Entry;

const SERVICE: &str = "Navivi";
const MAX_VALUE_BYTES: usize = 2000; // Windows stores a credential blob of at most 2560 bytes

/// Names are `ai-key:<provider>` or `map-key:<service>`; anything else is refused so the webview cannot
/// read other entries.
fn valid_name(name: &str) -> bool {
    match name.strip_prefix("ai-key:").or_else(|| name.strip_prefix("map-key:")) {
        Some(provider) => {
            !provider.is_empty()
                && provider.len() <= 40
                && provider.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
        }
        None => false,
    }
}

fn entry(name: &str) -> Result<Entry, String> {
    if !valid_name(name) {
        return Err(format!("'{name}' is not a key name."));
    }
    Entry::new(SERVICE, name).map_err(|e| e.to_string())
}

const PROVIDERS: [&str; 5] = ["anthropic", "openai", "gemini", "openrouter", "custom"];

/// The map services' keys (Settings > Services), the frontend's `AppApiKeys`.
pub const MAP_KEYS: [&str; 3] = ["mapbox", "ors", "mapillary"];

/// One map service's key, if it is set.
pub fn map_key(service: &str) -> Option<String> {
    let key = secret_get(format!("map-key:{service}")).ok().flatten()?;
    let key = key.trim();
    (!key.is_empty()).then(|| key.to_string())
}

/// Versions before 2026-10-22 kept the map keys in plain text in the `api_keys` app setting: moved into the
/// credential store once, and the setting removed only when every key made it.
pub fn move_map_keys_from_db(conn: &rusqlite::Connection) {
    use crate::db::app_settings;
    let Ok(Some(saved)) = app_settings::get(conn, app_settings::API_KEYS) else { return };
    let mut all_moved = true;
    for service in MAP_KEYS {
        if let Some(key) = saved.get(service).and_then(|v| v.as_str()).map(str::trim).filter(|k| !k.is_empty()) {
            if secret_set(format!("map-key:{service}"), key.to_string()).is_err() {
                all_moved = false;
            }
        }
    }
    if all_moved {
        let _ = app_settings::delete(conn, app_settings::API_KEYS);
    }
}

fn env_name(provider: &str) -> String {
    format!("NAVIVI_AI_KEY_{}", provider.to_ascii_uppercase())
}

/// Hands the saved provider keys to a Python child as `NAVIVI_AI_KEY_<PROVIDER>`, which is how the pipeline
/// (overview narration written by an online model) gets them. They live in that process only.
pub fn export_keys(cmd: &mut std::process::Command) {
    for provider in PROVIDERS {
        if let Ok(Some(key)) = secret_get(format!("ai-key:{provider}")) {
            cmd.env(env_name(provider), key);
        }
    }
}

#[tauri::command(async)]
pub fn secret_set(name: String, value: String) -> Result<(), String> {
    if value.is_empty() || value.len() > MAX_VALUE_BYTES {
        return Err("The key is empty or too long.".into());
    }
    entry(&name)?.set_password(&value).map_err(|e| e.to_string())
}

#[tauri::command(async)]
pub fn secret_get(name: String) -> Result<Option<String>, String> {
    match entry(&name)?.get_password() {
        Ok(value) => Ok(Some(value)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(e.to_string()),
    }
}

#[tauri::command(async)]
pub fn secret_delete(name: String) -> Result<(), String> {
    match entry(&name)?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(e) => Err(e.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_provider_key_names_are_allowed() {
        assert!(valid_name("ai-key:anthropic"));
        assert!(valid_name("ai-key:openai-2"));
        assert!(!valid_name("ai-key:"));
        assert!(!valid_name("ai-key:Open AI"));
        assert!(!valid_name("other:anthropic"));
        assert!(!valid_name("ai-key:../x"));
        assert!(valid_name("map-key:mapbox") && valid_name("map-key:mapillary"));
        assert!(!valid_name("map-key:") && !valid_name("map-key:../db"));
        assert!(!valid_name(&format!("ai-key:{}", "a".repeat(41))));
    }

    #[test]
    fn a_key_reaches_python_under_its_providers_variable() {
        assert_eq!(env_name("anthropic"), "NAVIVI_AI_KEY_ANTHROPIC");
        assert_eq!(env_name("openrouter"), "NAVIVI_AI_KEY_OPENROUTER");
        assert!(PROVIDERS.iter().all(|p| valid_name(&format!("ai-key:{p}"))));
    }

    // Touches the real credential store (a throwaway entry): `cargo test -- --ignored`.
    #[test]
    #[ignore]
    fn a_key_survives_a_new_handle_and_can_be_deleted() {
        let name = "ai-key:selftest".to_string();
        secret_set(name.clone(), "sk-test-123".into()).unwrap();
        assert_eq!(secret_get(name.clone()).unwrap().as_deref(), Some("sk-test-123"));
        secret_delete(name.clone()).unwrap();
        assert_eq!(secret_get(name.clone()).unwrap(), None);
        secret_delete(name).unwrap(); // deleting what is not there is fine
    }

    #[test]
    fn a_bad_name_or_value_is_refused_before_the_store_is_touched() {
        assert!(secret_get("nope".into()).is_err());
        assert!(secret_set("ai-key:openai".into(), String::new()).is_err());
        assert!(secret_set("ai-key:openai".into(), "x".repeat(MAX_VALUE_BYTES + 1)).is_err());
    }
}
