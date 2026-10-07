import { execFileSync, execSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

// Code signing for the exes the build makes. Nothing happens unless one of these is set:
//   NAVIVI_SIGN_PFX [+ NAVIVI_SIGN_PASSWORD]   a .pfx certificate file (OV/EV certificate from a certificate authority)
//   NAVIVI_SIGN_COMMAND                        any command, `{file}` is replaced by the exe's path; use it for cloud signing
//                                              (e.g. Microsoft Artifact Signing: signtool sign /dlib ... /dmdf metadata.json {file})
// NAVIVI_SIGN_TIMESTAMP overrides the timestamp server. A self-signed certificate signs fine but Smart App Control still blocks it.
export const signingConfigured = () => !!(process.env.NAVIVI_SIGN_PFX || process.env.NAVIVI_SIGN_COMMAND);

function findSigntool() {
  const kits = join(process.env["ProgramFiles(x86)"] ?? "C:\Program Files (x86)", "Windows Kits", "10", "bin");
  if (existsSync(kits)) {
    const versions = readdirSync(kits).filter((v) => /^\d/.test(v)).sort().reverse();
    for (const v of versions) {
      const exe = join(kits, v, "x64", "signtool.exe");
      if (existsSync(exe)) return exe;
    }
  }
  return "signtool";
}

export function signFile(file) {
  if (!signingConfigured()) return false;
  console.log(`  signing ${file}`);
  if (process.env.NAVIVI_SIGN_COMMAND) {
    execSync(process.env.NAVIVI_SIGN_COMMAND.replaceAll("{file}", `"${file}"`), { stdio: "inherit" });
    return true;
  }
  const args = ["sign", "/fd", "sha256", "/f", process.env.NAVIVI_SIGN_PFX];
  if (process.env.NAVIVI_SIGN_PASSWORD) args.push("/p", process.env.NAVIVI_SIGN_PASSWORD);
  args.push("/tr", process.env.NAVIVI_SIGN_TIMESTAMP || "http://timestamp.digicert.com", "/td", "sha256", file);
  execFileSync(findSigntool(), args, { stdio: "inherit" });
  return true;
}
