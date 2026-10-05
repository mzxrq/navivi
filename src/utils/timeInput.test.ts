import { describe, expect, it } from "vitest";
import { formatTimeValue, parseTime } from "./timeInput";

describe("parseTime", () => {
  it("reads plain numbers and seconds", () => {
    expect(parseTime("75")).toBe(75);
    expect(parseTime("12.5")).toBe(12.5);
    expect(parseTime(" 7s ")).toBe(7);
    expect(parseTime("7 sec")).toBe(7);
    expect(parseTime("7秒")).toBe(7);
  });

  it("reads minutes, with or without seconds", () => {
    expect(parseTime("2m")).toBe(120);
    expect(parseTime("1.5m")).toBe(90);
    expect(parseTime("1m15s")).toBe(75);
    expect(parseTime("1 min")).toBe(60);
    expect(parseTime("3分")).toBe(180);
  });

  it("reads clock style", () => {
    expect(parseTime("1:15")).toBe(75);
    expect(parseTime("0:07.5")).toBe(7.5);
    expect(parseTime("10:00")).toBe(600);
  });

  it("rejects what is not a time", () => {
    for (const bad of ["", "abc", "1:75", "1::2", "-5", "1m2m", "s", ":"]) expect(parseTime(bad)).toBeNull();
  });
});

describe("formatTimeValue", () => {
  it("shows seconds under a minute", () => {
    expect(formatTimeValue(0)).toEqual({ text: "0.00", unit: "sec" });
    expect(formatTimeValue(12.5)).toEqual({ text: "12.50", unit: "sec" });
    expect(formatTimeValue(59.99)).toEqual({ text: "59.99", unit: "sec" });
  });

  it("switches to minutes and seconds from a minute on", () => {
    expect(formatTimeValue(60)).toEqual({ text: "1:00.00", unit: "min" });
    expect(formatTimeValue(66)).toEqual({ text: "1:06.00", unit: "min" });
    expect(formatTimeValue(605.25)).toEqual({ text: "10:05.25", unit: "min" });
  });

  it("carries a rounded-up 60 seconds into the minute", () => {
    expect(formatTimeValue(119.999)).toEqual({ text: "2:00.00", unit: "min" });
  });

  it("round-trips through parseTime", () => {
    for (const v of [0, 3.25, 59.5, 60, 66, 125.75, 3599.5]) {
      expect(parseTime(formatTimeValue(v).text)).toBeCloseTo(v, 2);
    }
  });
});
