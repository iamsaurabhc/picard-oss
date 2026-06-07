import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, beforeEach, vi } from "vitest";
import {
  PiiProtectionToggle,
  PII_STORAGE_KEY,
  readPiiPreference,
  writePiiPreference,
} from "./PiiProtectionToggle";

describe("PiiProtectionToggle", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("defaults on for cloud providers", () => {
    const onChange = vi.fn();
    render(
      <PiiProtectionToggle
        llmProvider="openai"
        defaultEnabled
        enabled
        onChange={onChange}
      />
    );
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(true);
  });

  it("disables for ollama", () => {
    render(
      <PiiProtectionToggle
        llmProvider="ollama"
        defaultEnabled
        enabled
        onChange={() => {}}
      />
    );
    const checkbox = screen.getByRole("checkbox");
    expect((checkbox as HTMLInputElement).disabled).toBe(true);
  });

  it("persists preference in localStorage", () => {
    const onChange = vi.fn();
    render(
      <PiiProtectionToggle
        llmProvider="openai"
        defaultEnabled
        enabled
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByRole("checkbox"));
    expect(localStorage.getItem(PII_STORAGE_KEY)).toBe("false");
    expect(onChange).toHaveBeenCalledWith(false);
  });

  it("readPiiPreference respects stored value", () => {
    writePiiPreference(false);
    expect(readPiiPreference(true)).toBe(false);
  });
});
