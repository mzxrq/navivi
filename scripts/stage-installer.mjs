// Assembles what the installer ships into src-tauri/installer-staging/ (see src-tauri/tauri.installer.conf.json):
//   src-python/  the pipeline code, without the engines, tests and caches
//   tools/       ffmpeg/bin/{ffmpeg,ffprobe}.exe, gpsbabel/, uv.exe
// Downloads go to scripts/.cache and are reused. Run with: npm run stage:installer
import { execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync, createWriteStream } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { pipeline } from "node:stream/promises";
import { Readable } from "node:stream";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const pyDir = join(root, "src-tauri", "src-python");
const staging = join(root, "src-tauri", "installer-staging");
const cache = join(root, "scripts", ".cache");

const FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip";
const UV_URL = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip";

// Not shipped: engines made on first run, caches, tests.
const SKIP_DIRS = new Set(["bin", "tests", "data", "frames", "__pycache__", ".pytest_cache", "logs", ".venv"]);
// .env holds the developer's own API keys: never packaged. Users enter theirs in Settings > API keys.
const SKIP_FILES = /(\.pyc$|^pytest\.ini$|^ruff\.toml$|^requirements-test\.txt$|^requirements.*\.in$|^\.env(\..*)?$)/;

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

async function download(url, file) {
  if (existsSync(file)) return file;
  mkdirSync(dirname(file), { recursive: true });
  console.log(`  downloading ${url}`);
  const response = await fetch(url, { redirect: "follow" });
  if (!response.ok) throw new Error(`${url} answered ${response.status}`);
  await pipeline(Readable.fromWeb(response.body), createWriteStream(`${file}.part`));
  cpSync(`${file}.part`, file);
  rmSync(`${file}.part`);
  return file;
}

// Windows 10+ ships bsdtar, which reads zip files. Called by path: a GNU tar earlier on PATH (Git Bash) cannot.
function unzip(zip, into, patterns = []) {
  mkdirSync(into, { recursive: true });
  const tar = process.platform === "win32" ? join(process.env.SystemRoot ?? "C:\\Windows", "System32", "tar.exe") : "tar";
  execFileSync(tar, ["-xf", zip, "-C", into, ...patterns], { stdio: "inherit" });
}

function findOnPath(name) {
  try {
    return execFileSync("where", [name], { encoding: "utf8" }).split(/\r?\n/)[0].trim() || null;
  } catch {
    return null;
  }
}

async function stageFfmpeg() {
  console.log("ffmpeg");
  const out = join(staging, "tools", "ffmpeg", "bin");
  mkdirSync(out, { recursive: true });
  const zip = await download(FFMPEG_URL, join(cache, "ffmpeg-essentials.zip"));
  const extracted = join(cache, "ffmpeg-essentials");
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
  const local = findOnPath("uv");
  if (local) {
    cpSync(local, join(out, "uv.exe"));
  } else {
    const zip = await download(UV_URL, join(cache, "uv.zip"));
    const extracted = join(cache, "uv");
    if (!existsSync(extracted)) unzip(zip, extracted);
    const exe = [extracted, ...readdirSync(extracted).map((n) => join(extracted, n))].map((d) => join(d, "uv.exe")).find(existsSync);
    if (!exe) throw new Error("uv.exe was not found in the downloaded archive");
    cpSync(exe, join(out, "uv.exe"));
  }
  console.log(`  ${mb(size(join(out, "uv.exe")))}`);
}

rmSync(staging, { recursive: true, force: true });
mkdirSync(staging, { recursive: true });
stageCode();
stageVoices();
await stageFfmpeg();
stageGpsbabel();
await stageUv();
console.log(`\nStaged ${mb(size(staging))} in ${staging}`);
