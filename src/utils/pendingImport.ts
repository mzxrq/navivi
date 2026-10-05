export type PendingImport = { kind: "route"; path: string } | { kind: "files"; paths: string[] };

let pending: PendingImport | null = null;

export function setPendingImport(value: PendingImport | null) {
  pending = value;
}

export function takePendingImport(): PendingImport | null {
  const value = pending;
  pending = null;
  return value;
}
