import { describe, expect, it } from "vitest";
import { loadCatalog } from "../src/engine/catalog.js";
import { parseList, resolveSelection, toggleSkill } from "../src/engine/selection.js";
import { miniRoot } from "./helpers.js";

const cat = loadCatalog(miniRoot());

describe("resolveSelection", () => {
  it("adds dependencies with a note", () => {
    expect(resolveSelection(cat, ["b"])).toEqual({ names: ["a", "b"], notes: ["b needs a: added a"] });
  });
  it("keeps catalog order and says nothing when complete", () => {
    expect(resolveSelection(cat, ["c", "b", "a"])).toEqual({ names: ["a", "b", "c"], notes: [] });
  });
  it("drops dependents when asked", () => {
    expect(resolveSelection(cat, ["b", "c"], { dropDependents: true })).toEqual({
      names: ["c"],
      notes: ["b needs a, which is not selected: dropped b"],
    });
  });
  it("rejects unknown skills", () => {
    expect(() => resolveSelection(cat, ["zzz"])).toThrow("unknown skill: zzz");
  });
});

describe("toggleSkill", () => {
  it("deselecting a dependency also deselects its dependents", () => {
    expect(toggleSkill(cat, new Set(["a", "b", "c"]), "a")).toEqual({ names: ["c"], notes: ["b needs a: also deselected b"] });
  });
  it("selecting a dependent re-adds the dependency", () => {
    expect(toggleSkill(cat, new Set(["c"]), "b")).toEqual({ names: ["a", "b", "c"], notes: ["b needs a: added a"] });
  });
  it("plain toggles have no notes", () => {
    expect(toggleSkill(cat, new Set(["a"]), "c")).toEqual({ names: ["a", "c"], notes: [] });
    expect(toggleSkill(cat, new Set(["a", "c"]), "c")).toEqual({ names: ["a"], notes: [] });
  });
});

it("parseList trims and drops empties", () => {
  expect(parseList(" a, b ,,c")).toEqual(["a", "b", "c"]);
  expect(parseList(undefined)).toEqual([]);
});
