import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { inspectLink, linkPlugin, planUninstall, uninstall } from "../src/engine/link.js";
import { tmpDir, write } from "./helpers.js";

const yes = async () => true;
const no = async () => false;

describe("linkPlugin", () => {
  it("creates the symlink and is idempotent", async () => {
    const dir = tmpDir();
    const target = path.join(dir, "target");
    fs.mkdirSync(target);
    const link = path.join(dir, "skills", "sf");
    expect(await linkPlugin(target, link, no)).toBe(link);
    expect(fs.readlinkSync(link)).toBe(target);
    expect(inspectLink(link, target)).toEqual({ kind: "ours" });
    expect(await linkPlugin(target, link, no)).toBe(link);
  });

  it("replaces a foreign symlink or real directory only with consent", async () => {
    const dir = tmpDir();
    const target = path.join(dir, "target");
    const other = path.join(dir, "other");
    fs.mkdirSync(target);
    fs.mkdirSync(other);
    const link = path.join(dir, "link");
    fs.symlinkSync(other, link);
    expect(inspectLink(link, target)).toEqual({ kind: "symlink", to: other });
    await expect(linkPlugin(target, link, no)).rejects.toMatchObject({ message: expect.stringContaining("declined") });
    expect(fs.readlinkSync(link)).toBe(other);
    const asked: string[] = [];
    await linkPlugin(target, link, async (q) => { asked.push(q); return true; });
    expect(asked[0]).toContain(`is a symlink to ${other}`);
    expect(fs.readlinkSync(link)).toBe(target);
    const real = path.join(dir, "real");
    write(path.join(real, "f"), "x");
    expect(inspectLink(real, target)).toEqual({ kind: "directory" });
    await expect(linkPlugin(target, real, no)).rejects.toThrow();
    expect(fs.existsSync(path.join(real, "f"))).toBe(true);
    await linkPlugin(target, real, yes);
    expect(fs.readlinkSync(real)).toBe(target);
  });
});

describe("uninstall", () => {
  function scene() {
    const dir = tmpDir();
    const target = path.join(dir, "target");
    const link = path.join(dir, "link");
    const data = path.join(dir, "data");
    write(path.join(target, "f"), "x");
    write(path.join(data, "ledger.db"), "x");
    fs.symlinkSync(target, link);
    return { target, link, data };
  }

  it("keeps data unless purge and reports the symlink target in the plan", async () => {
    const { target, link, data } = scene();
    const plan = planUninstall(target, link, data, false);
    expect(plan.remove).toEqual([`${link} -> ${target}`, target]);
    expect(plan.keep[0]).toContain("--purge-data");
    const res = await uninstall(target, link, data, false, yes);
    expect(res.removed).toEqual([link, target]);
    expect(res.kept[0]).toContain(data);
    expect(fs.existsSync(data)).toBe(true);
    const s2 = scene();
    const purged = await uninstall(s2.target, s2.link, s2.data, true, yes);
    expect(purged.removed).toEqual([s2.link, s2.target, s2.data]);
    expect(fs.existsSync(s2.data)).toBe(false);
  });

  it("declined changes nothing; a real directory at the link is left in place", async () => {
    const { target, link, data } = scene();
    await expect(uninstall(target, link, data, false, no)).rejects.toMatchObject({ message: "uninstall declined" });
    expect(fs.existsSync(target)).toBe(true);
    fs.unlinkSync(link);
    write(path.join(link, "keep"), "x");
    const res = await uninstall(target, link, data, false, yes);
    expect(res.removed).toEqual([target]);
    expect(res.kept.some((k) => k.includes("real directory"))).toBe(true);
    expect(fs.existsSync(path.join(link, "keep"))).toBe(true);
  });
});
