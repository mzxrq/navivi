//! API keys for online AI providers, kept in the operating system's credential store (Windows Credential
//! Manager, macOS Keychain, Secret Service). They never go into a project folder, the database or a `.nvv`.

use keyring::Entry;

const SERVICE: &str = "Navivi";
const MAX_VALUE_BYTES: usize = 2000; // Windows stores a credential blob of at most 2560 bytes

/// Names are `ai-key:<provider>`; anything else is refused so the webview cannot read other entries.
fn valid_name(name: &str) -> bool {
    match name.strip_prefix("ai-key:") {
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

#[tauri::command]
pub fn secret_set(name: String, value: String) -> Result<(), String> {
    if value.is_empty() || value.len() > MAX_VALUE_BYTES {
        return Err("The key is empty or too long.".into());
    }
    entry(&name)?.set_password(&value).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn secret_get(name: String) -> Result<Option<String>, String> {
    match entry(&name)?.get_password() {
        Ok(value) => Ok(Some(value)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(e.to_string()),
    }
}

#[tauri::command]
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
