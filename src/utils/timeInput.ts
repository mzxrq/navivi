/** A time as typed: "75", "75s", "1.5m", "1m15s", "1:15" or "1:15.5". Returns seconds, or null when it is not a time. */
export function parseTime(input: string): number | null {
  const text = input.trim().toLowerCase().replace(/\s+/g, "").replace(/sec$|秒$/, "s").replace(/min$|分$/, "m");
  if (!text) return null;

  const clock = /^(\d+):(\d{1,2}(?:\.\d+)?)$/.exec(text);
  if (clock) {
    const seconds = Number(clock[2]);
    return seconds < 60 ? Number(clock[1]) * 60 + seconds : null;
  }

  const units = /^(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s?)?$/.exec(text);
  if (units && (units[1] !== undefined || units[2] !== undefined)) {
    return Number(units[1] ?? 0) * 60 + Number(units[2] ?? 0);
  }
  const bareMinutes = /^(\d+(?:\.\d+)?)m$/.exec(text);
  return bareMinutes ? Number(bareMinutes[1]) * 60 : null;
}

/** What the box shows: seconds with two decimals under a minute (unit "sec"), `m:ss.cc` from a minute on (unit "min"). */
export function formatTimeValue(seconds: number): { text: string; unit: "sec" | "min" } {
  const v = Math.max(0, seconds);
  if (v < 60) return { text: v.toFixed(2), unit: "sec" };
  const whole = Math.floor(v / 60);
  const rest = v - whole * 60;
  // 59.996 rounds to 60.00: carry it into the minutes instead of showing "1:60.00".
  if (rest.toFixed(2) === "60.00") return { text: `${whole + 1}:00.00`, unit: "min" };
  return { text: `${whole}:${rest.toFixed(2).padStart(5, "0")}`, unit: "min" };
}
