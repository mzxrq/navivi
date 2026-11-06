// A project has a main course and at most one sub course. Sub stops live in the same `waypoints` list (course "sub"),
// after the main ones. The sub course's first stop is an anchor: `branchOf` = the main stop it leaves from, so it sits
// on that stop and only holds the sub course's first leg. Its last stop can be an anchor too (it ends at a main stop).
type Stop = { id?: string; lat: number; lng: number; name?: string; isStopBy?: boolean; connectToRoute?: boolean; course?: "sub"; branchOf?: string };

export const SUB_COURSE_COLOR = "#f59e0b";

export const onRoute =(w: Stop) => !w.isStopBy || !!w.connectToRoute;
export const inSubCourse = (w: Stop) => w.course === "sub";

// An anchor takes the place, and name, of the main stop it stands for.
export function resolveAnchor<T extends Stop>(w: T, all: readonly T[]): T {
  const main = w.branchOf ? all.find((x) => x.id === w.branchOf) : undefined;
  return main ? { ...w, lat: main.lat, lng: main.lng, name: main.name } : w;
}

export const mainStops = <T extends Stop>(all: readonly T[]) => all.filter((w) => !inSubCourse(w));
export const subStops = <T extends Stop>(all: readonly T[]) => all.filter(inSubCourse).map((w) => resolveAnchor(w, all));

/** The stops of `w`'s own course (raw, anchors unresolved), for "first / last stop" questions. */
export const courseOf = <T extends Stop>(all: readonly T[], w: Stop) => all.filter((x) => inSubCourse(x) === inSubCourse(w));

/** The list with every sub stop after the main ones (order within each course kept); the same array when it already is. */
export function withSubLast<T extends Stop>(all: T[]): T[] {
  const firstSub = all.findIndex(inSubCourse);
  if (firstSub === -1 || all.slice(firstSub).every(inSubCourse)) return all;
  return [...mainStops(all), ...all.filter(inSubCourse)];
}

const newId = () => crypto.randomUUID();

/** Starts the sub course at main stop `mainId`: its first stop, an anchor that holds the first sub leg. */
export function startSubCourse<T extends Stop & { routeMode?: string }>(all: T[], mainId: string): T[] {
  const main = all.find((w) => w.id === mainId);
  if (!main || all.some(inSubCourse)) return all;
  const anchor = { id: newId(), lat: main.lat, lng: main.lng, name: main.name, routeMode: main.routeMode, course: "sub", branchOf: mainId } as T;
  return [...all, anchor];
}

/** Adds a stop to the main course's end, or to the sub course's (before its end anchor when it rejoins the main course). */
export function appendStop<T extends Stop>(all: T[], wp: T, toSub: boolean): T[] {
  const sub = all.filter(inSubCourse);
  if (!toSub || sub.length === 0) return withSubLast([...all, { ...wp, course: undefined }]);
  const last = sub[sub.length - 1];
  const at = sub.length > 1 && last.branchOf ? all.indexOf(last) : all.length;
  return [...all.slice(0, at), { ...wp, course: "sub" }, ...all.slice(at)];
}

/** The main stop the sub course ends at, if it rejoins the main course. */
export function subEnd<T extends Stop>(all: readonly T[]): T | undefined {
  const sub = all.filter(inSubCourse);
  const last = sub[sub.length - 1];
  return sub.length > 1 && last.branchOf ? all.find((w) => w.id === last.branchOf) : undefined;
}

/** The sub course ends at the main destination (an end anchor), or at its own last stop. */
export function setEndsAtDestination<T extends Stop & { routeMode?: string }>(all: T[], on: boolean): T[] {
  const sub = all.filter(inSubCourse);
  if (sub.length === 0) return all;
  const end = subEnd(all);
  if (!on) return end ? all.filter((w) => w !== sub[sub.length - 1]) : all;
  const main = mainStops(all);
  const dest = main[main.length - 1];
  if (!dest || end) return all;
  return [...all, { id: newId(), lat: dest.lat, lng: dest.lng, name: dest.name, routeMode: "walking", course: "sub", branchOf: dest.id } as T];
}

export const removeSubCourse = <T extends Stop>(all: T[]) => mainStops(all);

/** Every leg as [from, to], in routeSegments order: the main course's, then the sub course's. */
export function legEnds<T extends Stop>(all: readonly T[]): [T, T][] {
  const chains = [mainStops(all).filter(onRoute), subStops(all).filter(onRoute)];
  return chains.flatMap((c) => c.slice(1).map((to, i): [T, T] => [c[i], to]));
}

/** The leg that leaves `id` (its index in routeSegments), or -1. */
export const legIndexOf = (all: readonly Stop[], id: string) => legEnds(all).findIndex(([from]) => from.id === id);

/** How many of the legs belong to the main course (the rest are the sub course's). */
export const mainLegCount = (all: readonly Stop[]) => Math.max(0, mainStops(all).filter(onRoute).length - 1);
