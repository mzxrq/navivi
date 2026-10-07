// @vitest-environment jsdom
import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../services/sidecar", () => ({ callSidecar: vi.fn() }));
vi.mock("../../services/ollamaApi", () => ({ warmUpModel: vi.fn() }));
vi.mock("../../services/ai/engine", () => ({ aiEngine: () => "ollama" }));
vi.mock("../../hooks/useWorkspace", () => ({ useWorkspace: () => ({ settings: {}, updateSettings: vi.fn(), setIsDirty: vi.fn() }) }));

import { ScriptInput, insertCue } from "./ScriptInput";

i18n.load("en", {});
i18n.activate("en");
afterEach(cleanup);

describe("insertCue", () => {
  it("puts the tag at the caret and moves the caret behind it", () => {
    expect(insertCue("ABCD", "start", 2, 2)).toEqual({ text: "AB{start}CD", caret: 9 });
  });

  it("replaces a selection and clamps a caret past the end", () => {
    expect(insertCue("ABCD", "end", 1, 3).text).toBe("A{end}D");
    expect(insertCue("AB", "arrive", 99, 99).text).toBe("AB{arrive}");
  });
});

describe("ScriptInput cue buttons", () => {
  const show = (props: Partial<Parameters<typeof ScriptInput>[0]> = {}) => {
    const onChange = vi.fn();
    render(
      <I18nProvider i18n={i18n}>
        <ScriptInput showLabel={false} value="こんにちは" onChange={onChange} onGenerate={vi.fn()} isGenerating={false} {...props} />
      </I18nProvider>,
    );
    return { onChange, box: screen.getByRole("textbox") as HTMLTextAreaElement };
  };

  it("offers start, arrive and end, each with a tooltip", () => {
    show();
    expect(screen.getByRole("button", { name: /walk starts moving/ }).textContent).toBe("{start}");
    expect(screen.getByRole("button", { name: /nearly at the stop/ }).textContent).toBe("{arrive}");
    expect(screen.getByRole("button", { name: /stop is reached/ }).textContent).toBe("{end}");
  });

  it("inserts at the caret and saves the script with the tag in it", () => {
    const { box, onChange } = show();
    box.setSelectionRange(2, 2);
    fireEvent.click(screen.getByRole("button", { name: /walk starts moving/ }));
    expect(box.value).toBe("こん{start}にちは");
    fireEvent.blur(box);
    expect(onChange).toHaveBeenCalledWith("こん{start}にちは");
  });

  it("hides the buttons while the script is being written", () => {
    show({ isGenerating: true });
    expect(screen.queryByRole("button", { name: /walk starts moving/ })).toBeNull();
  });
});
