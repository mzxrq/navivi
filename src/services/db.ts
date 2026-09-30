import { invoke } from "@tauri-apps/api/core";
import {
  DbError,
  DbImportReport,
  DbLegacyImport,
  DbProject,
  DbProjectInput,
  DbProjectPatch,
  DbProjectQuery,
  DbVersion,
  ProjectSettings,
  ProjectVersion,
} from "../types";

type RouteCache = Record<string, [number, number][]>;

export function isDbError(value: unknown): value is DbError {
  return Boolean(
    value && typeof value === "object" && "code" in value && "message" in value,
  );
}

const projects = {
  create: (input: DbProjectInput) => invoke<DbProject>("project_create", { input }),
  upsert: (input: DbProjectInput) => invoke<DbProject>("project_upsert", { input }),
  get: (id: string) => invoke<DbProject | null>("project_get", { id }),
  getByDir: (directoryPath: string) =>
    invoke<DbProject | null>("project_get_by_dir", { directoryPath }),
  list: (query: DbProjectQuery = {}) => invoke<DbProject[]>("project_list", { query }),
  update: (id: string, patch: DbProjectPatch) =>
    invoke<DbProject>("project_update", { id, patch }),
  touchOpened: (id: string) => invoke<DbProject>("project_touch_opened", { id }),
  forgetOpened: (id: string) => invoke<boolean>("project_forget_opened", { id }),
  /** Soft delete; `restore` undoes it, `purge` removes the row and everything under it. */
  delete: (id: string) => invoke<boolean>("project_delete", { id }),
  restore: (id: string) => invoke<boolean>("project_restore", { id }),
  purge: (id: string) => invoke<boolean>("project_purge", { id }),
  importLegacy: (data: DbLegacyImport) =>
    invoke<DbImportReport>("project_import_legacy", { data }),
};

const settings = {
  get: (projectId: string) =>
    invoke<ProjectSettings | null>("settings_get", { projectId }),
  put: (projectId: string, value: ProjectSettings) =>
    invoke<ProjectSettings>("settings_put", { projectId, settings: value }),
  /** JSON merge patch: nested objects merge, `null` removes a key. */
  patch: (projectId: string, patch: Partial<Record<keyof ProjectSettings, unknown>>) =>
    invoke<ProjectSettings>("settings_patch", { projectId, patch }),
  reset: (projectId: string, defaults: ProjectSettings) =>
    invoke<ProjectSettings>("settings_put", { projectId, settings: defaults }),
  delete: (projectId: string) => invoke<boolean>("settings_delete", { projectId }),
};

const versions = {
  create: (version: DbVersion) => invoke<ProjectVersion>("version_create", { version }),
  list: (projectId: string) => invoke<ProjectVersion[]>("version_list", { projectId }),
  get: (projectId: string, id: string) =>
    invoke<DbVersion | null>("version_get", { projectId, id }),
  rename: (projectId: string, id: string, label: string) =>
    invoke<ProjectVersion>("version_rename", { projectId, id, label }),
  delete: (projectId: string, id: string) =>
    invoke<boolean>("version_delete", { projectId, id }),
  deleteAll: (projectId: string) => invoke<number>("version_delete_all", { projectId }),
};

const routeCache = {
  getAll: (projectId: string) => invoke<RouteCache>("route_cache_get_all", { projectId }),
  get: (projectId: string, key: string) =>
    invoke<[number, number][] | null>("route_cache_get", { projectId, key }),
  put: (projectId: string, key: string, points: [number, number][]) =>
    invoke<void>("route_cache_put", { projectId, key, points }),
  putMany: (projectId: string, entries: RouteCache) =>
    invoke<number>("route_cache_put_many", { projectId, entries }),
  /** Makes the stored cache exactly `entries`. */
  replace: (projectId: string, entries: RouteCache) =>
    invoke<number>("route_cache_replace", { projectId, entries }),
  delete: (projectId: string, key: string) =>
    invoke<boolean>("route_cache_delete", { projectId, key }),
  prune: (projectId: string, keepKeys: string[]) =>
    invoke<number>("route_cache_prune", { projectId, keepKeys }),
  clear: (projectId: string) => invoke<number>("route_cache_clear", { projectId }),
};

const appSettings = {
  get: <T = unknown>(key: string) => invoke<T | null>("app_setting_get", { key }),
  set: (key: string, value: unknown) => invoke<void>("app_setting_set", { key, value }),
  delete: (key: string) => invoke<boolean>("app_setting_delete", { key }),
  list: (prefix?: string) =>
    invoke<Record<string, unknown>>("app_setting_list", { prefix: prefix ?? null }),
};

export const db = { projects, settings, versions, routeCache, appSettings };
