//! The app and its tools travel inside the setup exe: `[setup exe][payload zip][footer]`, the footer being a magic
//! string and the zip's length. `scripts/build-setup.mjs` appends them; the uninstaller is the exe part alone.

use serde::Deserialize;
use std::fs::{self, File};
use std::io::{self, Read, Seek, SeekFrom, Write};
use std::path::{Component, Path, PathBuf};
use zip::ZipArchive;

const MAGIC: &[u8; 8] = b"NAVIVIPL";
pub const FOOTER_LEN: u64 = 16;
/// Entries with this prefix describe the payload and are not installed.
const META_PREFIX: &str = ".navivi-";
pub const MANIFEST_NAME: &str = ".navivi-install.json";
/// Written next to the app: every file we put there, so the uninstaller removes exactly those.
pub const FILE_LIST: &str = ".navivi-files.txt";

/// Used by scripts/build-setup.mjs (same layout there) and by the tests here.
#[cfg(test)]
pub fn encode_footer(zip_len: u64) -> [u8; 16] {
    let mut out = [0u8; 16];
    out[..8].copy_from_slice(MAGIC);
    out[8..].copy_from_slice(&zip_len.to_le_bytes());
    out
}

pub fn decode_footer(footer: &[u8; 16]) -> Option<u64> {
    if &footer[..8] != MAGIC {
        return None;
    }
    Some(u64::from_le_bytes(footer[8..].try_into().ok()?))
}

/// A byte range of a file as its own seekable reader.
pub struct Section {
    file: File,
    start: u64,
    len: u64,
    pos: u64,
}

impl Section {
    pub fn new(mut file: File, start: u64, len: u64) -> io::Result<Self> {
        file.seek(SeekFrom::Start(start))?;
        Ok(Section { file, start, len, pos: 0 })
    }
}

impl Read for Section {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        let left = self.len.saturating_sub(self.pos) as usize;
        if left == 0 {
            return Ok(0);
        }
        let take = buf.len().min(left);
        let n = self.file.read(&mut buf[..take])?;
        self.pos += n as u64;
        Ok(n)
    }
}

impl Seek for Section {
    fn seek(&mut self, to: SeekFrom) -> io::Result<u64> {
        let target = match to {
            SeekFrom::Start(n) => n as i128,
            SeekFrom::End(n) => self.len as i128 + n as i128,
            SeekFrom::Current(n) => self.pos as i128 + n as i128,
        };
        if target < 0 {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "seek before the start"));
        }
        self.pos = (target as u64).min(self.len);
        self.file.seek(SeekFrom::Start(self.start + self.pos))?;
        Ok(self.pos)
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct Manifest {
    pub name: String,
    pub version: String,
    /// The program to start and to point shortcuts at, relative to the install folder.
    pub exe: String,
}

/// Where a PE file keeps its Authenticode signature entry: (position of the entry, file offset of the signature, size). Read from the first bytes.
pub fn security_entry(head: &[u8]) -> Option<(usize, u32, u32)> {
    let word = |at: usize| head.get(at..at + 4).map(|b| u32::from_le_bytes(b.try_into().unwrap()));
    let pe = word(0x3c)? as usize;
    let opt = pe + 24;
    let plus = u16::from_le_bytes(head.get(opt..opt + 2)?.try_into().ok()?) == 0x20b;
    let at = opt + if plus { 144 } else { 128 };
    Some((at, word(at)?, word(at + 4)?))
}

pub struct Payload {
    pub path: PathBuf,
    /// Where the zip starts, which is also how long the plain setup exe is.
    pub start: u64,
    pub len: u64,
}

impl Payload {
    /// The payload appended to `exe`, if it has one (the uninstaller and a bare build do not).
    /// A code-signed setup has the signature after the footer (padded to 8 bytes), so the footer is looked for before it.
    pub fn find(exe: &Path) -> io::Result<Option<Payload>> {
        let mut file = File::open(exe)?;
        let size = file.metadata()?.len();
        if size < FOOTER_LEN {
            return Ok(None);
        }
        let mut head = vec![0u8; size.min(4096) as usize];
        file.read_exact(&mut head)?;
        let end = match security_entry(&head) {
            Some((_, offset, _)) if offset > 0 && u64::from(offset) <= size => u64::from(offset),
            _ => size,
        };
        for pad in 0..8 {
            let Some(at) = end.checked_sub(FOOTER_LEN + pad) else { break };
            file.seek(SeekFrom::Start(at))?;
            let mut footer = [0u8; 16];
            file.read_exact(&mut footer)?;
            let Some(len) = decode_footer(&footer) else { continue };
            if len == 0 || len > at {
                return Ok(None);
            }
            return Ok(Some(Payload { path: exe.to_path_buf(), start: at - len, len }));
        }
        Ok(None)
    }

    pub fn archive(&self) -> Result<ZipArchive<Section>, String> {
        let section = Section::new(File::open(&self.path).map_err(|e| e.to_string())?, self.start, self.len).map_err(|e| e.to_string())?;
        ZipArchive::new(section).map_err(|e| format!("The setup file is damaged: {e}"))
    }
}

pub fn read_manifest(archive: &mut ZipArchive<Section>) -> Result<Manifest, String> {
    let mut entry = archive.by_name(MANIFEST_NAME).map_err(|_| "The setup file has no manifest.".to_string())?;
    let mut text = String::new();
    entry.read_to_string(&mut text).map_err(|e| e.to_string())?;
    serde_json::from_str(&text).map_err(|e| format!("The setup manifest is unreadable: {e}"))
}

/// `name` inside `base`, or None when it would land outside (absolute, drive letters, `..`): a zip must not write elsewhere.
pub fn safe_join(base: &Path, name: &str) -> Option<PathBuf> {
    let mut out = base.to_path_buf();
    for part in Path::new(&name.replace('\\', "/")).components() {
        match part {
            Component::Normal(p) => out.push(p),
            Component::CurDir => {}
            _ => return None,
        }
    }
    (out != base).then_some(out)
}

/// Unpacks everything except the metadata entries into `dest`, calling `progress(done_bytes, total_bytes, current_file)`.
/// Returns the relative paths written (folders end in `/`), for the uninstaller's list.
pub fn extract(
    archive: &mut ZipArchive<Section>,
    dest: &Path,
    mut progress: impl FnMut(u64, u64, &str),
) -> Result<Vec<String>, String> {
    let mut total = 0u64;
    for i in 0..archive.len() {
        let entry = archive.by_index_raw(i).map_err(|e| e.to_string())?;
        if !entry.is_dir() && !entry.name().starts_with(META_PREFIX) {
            total += entry.size();
        }
    }

    let mut written = Vec::new();
    let mut done = 0u64;
    let mut buffer = vec![0u8; 256 * 1024];
    for i in 0..archive.len() {
        let mut entry = archive.by_index(i).map_err(|e| e.to_string())?;
        let name = entry.name().to_string();
        if name.starts_with(META_PREFIX) {
            continue;
        }
        let Some(target) = safe_join(dest, &name) else {
            return Err(format!("The setup file contains an unsafe path: {name}"));
        };
        if entry.is_dir() {
            fs::create_dir_all(&target).map_err(|e| format!("{}: {e}", target.display()))?;
            written.push(format!("{}/", name.replace('\\', "/").trim_end_matches('/')));
            continue;
        }
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent).map_err(|e| format!("{}: {e}", parent.display()))?;
        }
        let mut out = File::create(&target).map_err(|e| format!("{}: {e}", target.display()))?;
        loop {
            let n = entry.read(&mut buffer).map_err(|e| format!("{name}: {e}"))?;
            if n == 0 {
                break;
            }
            out.write_all(&buffer[..n]).map_err(|e| format!("{}: {e}", target.display()))?;
            done += n as u64;
            progress(done, total, &name);
        }
        written.push(name.replace('\\', "/"));
    }
    Ok(written)
}

#[cfg(test)]
mod tests {
    use super::*;
    use zip::write::SimpleFileOptions;
    use zip::ZipWriter;

    fn temp(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("navivi-setup-test-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    /// A fake setup exe: some bytes, then a payload zip, then the footer.
    fn fake_setup(dir: &Path, files: &[(&str, &str)]) -> PathBuf {
        let mut zip = Vec::new();
        {
            let mut writer = ZipWriter::new(io::Cursor::new(&mut zip));
            let options = SimpleFileOptions::default();
            for (name, data) in files {
                writer.start_file(*name, options).unwrap();
                writer.write_all(data.as_bytes()).unwrap();
            }
            writer.finish().unwrap();
        }
        let exe = dir.join("setup.exe");
        let mut bytes = b"MZ-fake-setup-program".to_vec();
        bytes.extend_from_slice(&zip);
        bytes.extend_from_slice(&encode_footer(zip.len() as u64));
        fs::write(&exe, bytes).unwrap();
        exe
    }

    #[test]
    fn the_footer_round_trips_and_rejects_other_bytes() {
        assert_eq!(decode_footer(&encode_footer(123_456_789)), Some(123_456_789));
        assert_eq!(decode_footer(&[0u8; 16]), None);
    }

    #[test]
    fn a_plain_exe_has_no_payload() {
        let dir = temp("plain");
        let exe = dir.join("plain.exe");
        fs::write(&exe, b"just a program, no footer here at all").unwrap();
        assert!(Payload::find(&exe).unwrap().is_none());
        fs::write(&exe, b"tiny").unwrap();
        assert!(Payload::find(&exe).unwrap().is_none());
    }

    #[test]
    fn a_signed_setup_still_finds_its_payload() {
        let dir = temp("signed");
        let zip = {
            let mut zip = Vec::new();
            let mut writer = ZipWriter::new(io::Cursor::new(&mut zip));
            writer.start_file("a.txt", SimpleFileOptions::default()).unwrap();
            writer.write_all(b"hello").unwrap();
            writer.finish().unwrap();
            zip
        };
        let mut bytes = vec![0u8; 0x200];
        bytes[0..2].copy_from_slice(b"MZ");
        bytes[0x3c..0x40].copy_from_slice(&0x80u32.to_le_bytes());
        bytes[0x80 + 24..0x80 + 26].copy_from_slice(&0x20bu16.to_le_bytes());
        bytes.extend_from_slice(&zip);
        bytes.extend_from_slice(&encode_footer(zip.len() as u64));
        let pad = (8 - bytes.len() % 8) % 8; // signtool pads to 8 bytes
        bytes.extend_from_slice(&vec![0u8; pad]);
        let cert_at = bytes.len() as u32;
        assert_eq!(cert_at % 8, 0);
        bytes[0x80 + 24 + 144..0x80 + 24 + 148].copy_from_slice(&cert_at.to_le_bytes());
        bytes[0x80 + 24 + 148..0x80 + 24 + 152].copy_from_slice(&16u32.to_le_bytes());
        bytes.extend_from_slice(&[7u8; 16]);
        let exe = dir.join("signed.exe");
        fs::write(&exe, &bytes).unwrap();
        let payload = Payload::find(&exe).unwrap().expect("a payload");
        assert_eq!((payload.start, payload.len), (0x200, zip.len() as u64));
        assert!(payload.archive().is_ok());
        assert!(security_entry(&bytes).is_some_and(|(_, offset, _)| offset == cert_at));
    }

    #[test]
    fn the_payload_is_found_and_the_zip_reads_through_the_section() {
        let dir = temp("find");
        let exe = fake_setup(&dir, &[(MANIFEST_NAME, r#"{"name":"Navivi","version":"1.2.3","exe":"navivi.exe"}"#), ("a.txt", "hello")]);
        let payload = Payload::find(&exe).unwrap().expect("a payload");
        assert_eq!(payload.start, b"MZ-fake-setup-program".len() as u64);
        let mut archive = payload.archive().unwrap();
        let manifest = read_manifest(&mut archive).unwrap();
        assert_eq!((manifest.name.as_str(), manifest.version.as_str(), manifest.exe.as_str()), ("Navivi", "1.2.3", "navivi.exe"));
    }

    #[test]
    fn extract_writes_files_reports_progress_and_skips_the_metadata() {
        let dir = temp("extract");
        let exe = fake_setup(&dir, &[(MANIFEST_NAME, "{}"), ("navivi.exe", "binary"), ("src-python/main.py", "print(1)")]);
        let mut archive = Payload::find(&exe).unwrap().unwrap().archive().unwrap();
        let dest = dir.join("out");
        let mut last = (0, 0);
        let written = extract(&mut archive, &dest, |done, total, _| last = (done, total)).unwrap();
        assert_eq!(written, vec!["navivi.exe", "src-python/main.py"]);
        assert_eq!(fs::read_to_string(dest.join("src-python").join("main.py")).unwrap(), "print(1)");
        assert!(!dest.join(MANIFEST_NAME).exists());
        assert_eq!(last, (14, 14), "all bytes counted, none of the manifest");
    }

    #[test]
    fn a_zip_cannot_write_outside_the_install_folder() {
        let base = Path::new("C:/Apps/Navivi");
        assert!(safe_join(base, "src-python/main.py").is_some());
        assert!(safe_join(base, "../evil.exe").is_none());
        assert!(safe_join(base, "a/../../evil.exe").is_none());
        assert!(safe_join(base, "C:/Windows/evil.exe").is_none());
        assert!(safe_join(base, "/evil.exe").is_none());
        assert!(safe_join(base, "..\\evil.exe").is_none());
        assert!(safe_join(base, "").is_none());

        let dir = temp("slip");
        let exe = fake_setup(&dir, &[("../escaped.txt", "x")]);
        let mut archive = Payload::find(&exe).unwrap().unwrap().archive().unwrap();
        assert!(extract(&mut archive, &dir.join("out"), |_, _, _| {}).is_err());
        assert!(!dir.join("escaped.txt").exists());
    }
}
