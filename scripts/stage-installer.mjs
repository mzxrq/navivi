// Assembles what the installer ships into src-tauri/installer-staging/ (see src-tauri/tauri.installer.conf.json):
//   src-python/  the pipeline code, without the engines, tests and caches
//   tools/       ffmpeg/bin/{ffmpeg,ffprobe}.exe, gpsbabel/, uv.exe
// Downloads go to scripts/.cache and are reused. Run with: npm run stage:installer
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync, createReadStream, createWriteStream } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { pipeline } from "node:stream/promises";
import { Readable } from "node:stream";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const pyDir = join(root, "src-tauri", "src-python");
const staging = join(root, "src-tauri", "installer-staging");
const cache = join(root, "scripts", ".cache");

// The bundled tools are pinned to a release and a sha256 (scripts/tool-pins.json) and checked after every download, cached or not.
const pins = JSON.parse(readFileSync(join(root, "scripts", "tool-pins.json"), "utf8"));

// Not shipped: engines made on first run, caches, tests.
const SKIP_DIRS = new Set(["bin", "tests", "data", "frames", "__pycache__", ".pytest_cache", "logs", ".venv"]);
// Secrets and test config are never packaged: .env holds the developer's own API keys (users enter theirs in Settings > API keys),
// and key/certificate/credential files have no place in an installer either, whatever they are called.
const SECRET_FILES = /(^\.env(\..*)?$|\.env$|\.(pem|pfx|p12|key|kdbx|jks)$|^id_(rsa|ed25519|ecdsa)|^credentials.*\.json$|^secrets?\.(json|ya?ml|toml|txt|env)$|^\.(npmrc|netrc|git-credentials)$)/i;
const SKIP_FILES = new RegExp(`(\\.pyc$|^pytest\\.ini$|^ruff\\.toml$|^requirements-test\\.txt$|^requirements.*\\.in$|${SECRET_FILES.source})`, "i");

const mb = (bytes) => `${(bytes / 1048576).toFixed(1)} MB`;
const warn = (message) => console.warn(`  ! ${message}`);

function size(path) {
  const stat = statSync(path);
  if (!stat.isDirectory()) return stat.size;
  return readdirSync(path).reduce((sum, name) => sum + size(join(path, name)), 0);
}

function stageCode() {
  console.log("Pipeline code");
  cpSync(pyDir, join(staging, "src-python"), {
    recursive: true,
    filter: (source) => {
      const name = source.split(/[\\/]/).pop();
      if (source === pyDir) return true;
      return statSync(source).isDirectory() ? !SKIP_DIRS.has(name) : !SKIP_FILES.test(name);
    },
  });
  console.log(`  ${mb(size(join(staging, "src-python")))}`);
}

// The voices listed in scripts/stock-voices.json as verified, from the developer's own voice folder, plus a CREDITS.txt.
function stageVoices() {
  console.log("Bundled voices");
  const list = JSON.parse(readFileSync(join(root, "scripts", "stock-voices.json"), "utf8")).voices;
  const from = join(pyDir, "bin", "Irodori-TTS-Server", "voices");
  const out = join(staging, "src-python", "assets", "voices");
  mkdirSync(out, { recursive: true });
  const credits = [];
  for (const voice of list) {
    if (!voice.verified) {
      console.log(`  - ${voice.id}: not verified for redistribution, left out`);
      continue;
    }
    if (!existsSync(join(from, voice.file))) {
      warn(`${voice.file} is not in ${from}: ${voice.id} is not bundled.`);
      continue;
    }
    cpSync(join(from, voice.file), join(out, voice.file));
    if (voice.credit) credits.push(`${voice.id}: ${voice.credit}`);
    else warn(`${voice.id} has no credit line in scripts/stock-voices.json (add one if its license asks for it).`);
  }
  if (credits.length) writeFileSync(join(out, "CREDITS.txt"), `${credits.join("\n")}\n`);
  console.log(`  ${mb(size(out))}`);
}

async function sha256Of(file) {
  const hash = createHash("sha256");
  await pipeline(createReadStream(file), hash);
  return hash.digest("hex");
}

// Downloads `url` once into the cache and checks it against the pinned sha256, also when it was cached by an earlier run:
// a cache entry that does not match is deleted, not trusted.
async function download(url, file, sha256) {
  if (existsSync(file) && (await sha256Of(file)) !== sha256) {
    warn(`${file} does not match its pinned sha256; downloading it again.`);
    rmSync(file);
  }
  if (!existsSync(file)) {
    mkdirSync(dirname(file), { recursive: true });
    console.log(`  downloading ${url}`);
    const response = await fetch(url, { redirect: "follow" });
    if (!response.ok) throw new Error(`${url} answered ${response.status}`);
    await pipeline(Readable.fromWeb(response.body), createWriteStream(`${file}.part`));
    const actual = await sha256Of(`${file}.part`);
    if (actual !== sha256) {
      rmSync(`${file}.part`);
      throw new Error(`${url} has sha256 ${actual}, not the pinned ${sha256}. Nothing was bundled from it.`);
    }
    cpSync(`${file}.part`, file);
    rmSync(`${file}.part`);
  }
  return file;
}

// Windows 10+ ships bsdtar, which reads zip files. Called by path: a GNU tar earlier on PATH (Git Bash) cannot.
function unzip(zip, into, patterns = []) {
  mkdirSync(into, { recursive: true });
  const tar = process.platform === "win32" ? join(process.env.SystemRoot ?? "C:\\Windows", "System32", "tar.exe") : "tar";
  execFileSync(tar, ["-xf", zip, "-C", into, ...patterns], { stdio: "inherit" });
}

async function stageFfmpeg() {
  console.log("ffmpeg");
  const out = join(staging, "tools", "ffmpeg", "bin");
  mkdirSync(out, { recursive: true });
  const { version, url, sha256 } = pins.ffmpeg;
  const zip = await download(url, join(cache, `ffmpeg-${version}.zip`), sha256);
  // Versioned, so a newer pin is never served from an older extraction.
  const extracted = join(cache, `ffmpeg-${version}`);
  if (!existsSync(extracted)) unzip(zip, extracted);
  const top = readdirSync(extracted).find((name) => existsSync(join(extracted, name, "bin", "ffmpeg.exe")));
  if (!top) throw new Error("ffmpeg.exe was not found in the downloaded archive");
  for (const exe of ["ffmpeg.exe", "ffprobe.exe"]) cpSync(join(extracted, top, "bin", exe), join(out, exe));
  for (const doc of ["LICENSE", "README.txt"]) {
    if (existsSync(join(extracted, top, doc))) cpSync(join(extracted, top, doc), join(staging, "tools", "ffmpeg", doc));
  }
  console.log(`  ${mb(size(join(staging, "tools", "ffmpeg")))}`);
}

// The command-line tool only needs Qt5Core and Qt5Xml next to it, not the 160 MB desktop build.
function stageGpsbabel() {
  console.log("GPSBabel");
  const from = join(pyDir, "bin", "GPSBabel");
  if (!existsSync(join(from, "gpsbabel.exe"))) {
    warn("src-python/bin/GPSBabel/gpsbabel.exe is missing: the installer will not convert .fit/.tcx/.kml tracks (GPX still works).");
    return;
  }
  const out = join(staging, "tools", "gpsbabel");
  mkdirSync(out, { recursive: true });
  for (const file of ["gpsbabel.exe", "Qt5Core.dll", "Qt5Xml.dll", "COPYING.txt"]) {
    if (existsSync(join(from, file))) cpSync(join(from, file), join(out, file));
  }
  console.log(`  ${mb(size(out))}`);
}

async function stageUv() {
  console.log("uv");
  const out = join(staging, "tools");
  mkdirSync(out, { recursive: true });
  // The pinned release, never whatever uv.exe happens to be first on PATH: that file would end up on every user's PC.
  const { version, url, sha256 } = pins.uv;
  const zip = await download(url, join(cache, `uv-${version}.zip`), sha256);
  const extracted = join(cache, `uv-${version}`);
  if (!existsSync(extracted)) unzip(zip, extracted);
  const exe = [extracted, ...readdirSync(extracted).map((n) => join(extracted, n))].map((d) => join(d, "uv.exe")).find(existsSync);
  if (!exe) throw new Error("uv.exe was not found in the downloaded archive");
  cpSync(exe, join(out, "uv.exe"));
  console.log(`  ${mb(size(join(out, "uv.exe")))}`);
}

// Last line of defence: nothing secret-looking may be in what is about to be packaged, by name or by content.
function assertNoSecrets() {
  console.log("Checking for secrets");
  const walk = (dir) => readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)]));
  const files = walk(staging);
  const named = files.filter((f) => SECRET_FILES.test(f.split(/[\\/]/).pop()));
  if (named.length) throw new Error(`These look like secrets and must not be packaged:\n  ${named.join("\n  ")}`);
  // The values of this machine's own keys (VITE_ and *_API_KEY / *_TOKEN variables) must not appear inside any staged text file.
  const values = Object.entries(process.env)
    .filter(([name, value]) => /^VITE_|API_KEY|TOKEN|SECRET|PASSWORD/i.test(name) && value && value.trim().length >= 16)
    .map(([name, value]) => [name, value.trim()]);
  const textual = /\.(py|json|txt|md|html|js|mjs|css|toml|ya?ml|cfg|ini|bat|ps1|sh|csv)$/i;
  const leaks = [];
  for (const file of files.filter((f) => textual.test(f) && statSync(f).size < 8 * 1048576)) {
    const text = readFileSync(file, "utf8");
    for (const [name, value] of values) if (text.includes(value)) leaks.push(`${file} contains the value of ${name}`);
  }
  if (leaks.length) throw new Error(`A secret would be packaged:\n  ${leaks.join("\n  ")}`);
  console.log(`  ${files.length} files checked, ${values.length} secret value(s) searched for: none found.`);
}

rmSync(staging, { recursive: true, force: true });
mkdirSync(staging, { recursive: true });
stageCode();
stageVoices();
await stageFfmpeg();
stageGpsbabel();
await stageUv();
assertNoSecrets();
console.log(`\nStaged ${mb(size(staging))} in ${staging}`);
