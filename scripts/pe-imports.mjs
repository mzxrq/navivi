import { readFileSync } from "node:fs";

// DLL names in a Windows exe's import table (not strings that merely appear in the file).
export function importedDlls(file) {
  const b = readFileSync(file);
  const peAt = b.readUInt32LE(0x3c);
  const sections = b.readUInt16LE(peAt + 6);
  const optSize = b.readUInt16LE(peAt + 20);
  const opt = peAt + 24;
  const plus = b.readUInt16LE(opt) === 0x20b;
  const importRva = b.readUInt32LE(opt + (plus ? 120 : 104));
  const table = opt + optSize;
  const toOffset = (rva) => {
    for (let i = 0; i < sections; i++) {
      const s = table + i * 40;
      const va = b.readUInt32LE(s + 12);
      if (rva >= va && rva < va + Math.max(b.readUInt32LE(s + 8), b.readUInt32LE(s + 16))) return rva - va + b.readUInt32LE(s + 20);
    }
    return -1;
  };
  const names = [];
  for (let at = toOffset(importRva); at >= 0; at += 20) {
    const nameRva = b.readUInt32LE(at + 12);
    if (!nameRva) break;
    const start = toOffset(nameRva);
    names.push(b.toString("latin1", start, b.indexOf(0, start)).toLowerCase());
  }
  return names;
}

export const needsVcRuntime = (file) => importedDlls(file).filter((n) => /^(vcruntime|msvcp)\d/.test(n));
