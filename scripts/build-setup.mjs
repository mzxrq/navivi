// Builds Navivi's own setup program: setup/dist/Navivi-Setup-<version>.exe
//   1. the app (`tauri build --no-bundle`), unless --skip-app reuses src-tauri/target/release/navivi.exe
//   2. the tools and code (scripts/stage-installer.mjs)
//   3. a zip of navivi.exe + src-python + tools, the payload
//   4. the setup program (setup/, Rust + WebView2), with the payload and a footer appended (see setup/src/payload.rs)
// Run with: npm run build:setup   (add -- --skip-app to repackage without rebuilding the app)
import { needsVcRuntime } from "./pe-imports.mjs";
import { signFile, signingConfigured } from "./sign.mjs";
import { execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const tauriDir = join(root, "src-tauri");
const setupDir = join(root, "setup");
const stage = join(setupDir, "stage");
const dist = join(setupDir, "dist");
const skipApp = process.argv.includes("--skip-app");
const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const run = (cmd, args, cwd = root) => execFileSync(cmd, args, { cwd, stdio: "inherit", shell: process.platform === "win32" && cmd.endsWith(".cmd") });
const mb = (path) => `${(statSync(path).size / 1048576).toFixed(1)} MB`;

const conf = JSON.parse(readFileSync(join(tauriDir, "tauri.conf.json"), "utf8"));
const version = conf.version;
const appExe = join(tauriDir, "target", "release", "navivi.exe");

console.log(`\n[1/4] The app`);
if (!skipApp || !existsSync(appExe)) run(npm, ["run", "tauri", "--", "build", "--no-bundle"]);
console.log(`  ${appExe} (${mb(appExe)})`);

console.log(`\n[2/4] Tools and code`);
run("node", ["scripts/stage-installer.mjs"]);

console.log(`\n[3/4] The payload`);
rmSync(stage, { recursive: true, force: true });
mkdirSync(stage, { recursive: true });
if (needsVcRuntime(appExe).length) throw new Error("navivi.exe imports the VC++ runtime; src-tauri/.cargo/config.toml must link it statically");
cpSync(appExe, join(stage, "navivi.exe"));
signFile(join(stage, "navivi.exe"));
cpSync(join(tauriDir, "installer-staging", "src-python"), join(stage, "src-python"), { recursive: true });
cpSync(join(tauriDir, "installer-staging", "tools"), join(stage, "tools"), { recursive: true });
writeFileSync(join(stage, ".navivi-install.json"), JSON.stringify({ name: "Navivi", version, exe: "navivi.exe" }));
const zip = join(setupDir, "payload.zip");
rmSync(zip, { force: true });
// Windows' own bsdtar writes zip files; a GNU tar earlier on PATH (Git Bash) cannot.
const tar = process.platform === "win32" ? join(process.env.SystemRoot ?? "C:\\Windows", "System32", "tar.exe") : "tar";
// Named one by one so the entries have no "./" in front.
run(tar, ["-a", "-cf", zip, "-C", stage, "navivi.exe", "src-python", "tools", ".navivi-install.json"]);
console.log(`  payload.zip ${mb(zip)}`);

console.log(`\n[4/4] The setup program`);
// cwd must be setup/: cargo reads .cargo/config.toml (static C runtime) from the working directory, not from --manifest-path.
run("cargo", ["build", "--release"], setupDir);
const plain = join(setupDir, "target", "release", "navivi-setup.exe");
if (needsVcRuntime(plain).length) throw new Error("navivi-setup.exe imports the VC++ runtime; it would not start on a clean PC");
mkdirSync(dist, { recursive: true });
const out = join(dist, `Navivi-Setup-${version}.exe`);
const footer = Buffer.alloc(16);
footer.write("NAVIVIPL", 0, "latin1");
footer.writeBigUInt64LE(BigInt(statSync(zip).size), 8);
writeFileSync(out, Buffer.concat([readFileSync(plain), readFileSync(zip), footer]));
signFile(out);
rmSync(stage, { recursive: true, force: true });
console.log(`\nBuilt ${out} (${mb(out)}; the setup program alone is ${mb(plain)})`);
if (!signingConfigured()) console.log("Not code-signed (set NAVIVI_SIGN_PFX or NAVIVI_SIGN_COMMAND, see scripts/sign.mjs): Smart App Control blocks unsigned installers on some PCs.");
