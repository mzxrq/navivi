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
  upsert: (input: DbProjectInput) => invoke<DbProject>("project_upsert", { input }),
  get: (id: string) => invoke<DbProject | null>("project_get", { id }),
  list: (query: DbProjectQuery = {}) => invoke<DbProject[]>("project_list", { query }),
  update: (id: string, patch: DbProjectPatch) =>
    invoke<DbProject>("project_update", { id, patch }),
  touchOpened: (id: string) => invoke<DbProject>("project_touch_opened", { id }),
  forgetOpened: (id: string) => invoke<boolean>("project_forget_opened", { id }),
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
};

const routeCache = {
  getAll: (projectId: string) => invoke<RouteCache>("route_cache_get_all", { projectId }),
  /** Makes the stored cache exactly `entries`. */
  replace: (projectId: string, entries: RouteCache) =>
    invoke<number>("route_cache_replace", { projectId, entries }),
};

const appSettings = {
  get: <T = unknown>(key: string) => invoke<T | null>("app_setting_get", { key }),
  set: (key: string, value: unknown) => invoke<void>("app_setting_set", { key, value }),
};

export const db = { projects, settings, versions, routeCache, appSettings };
