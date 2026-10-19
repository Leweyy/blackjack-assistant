// Publishes the electron-builder artifacts in `release/` to a GitHub release
// for the current package version (tag v<version>).
//
// Idempotent: creates the release if the tag has none, otherwise re-uploads
// every asset with --clobber so a partially published release gets repaired
// instead of erroring out. The tag-triggered GitHub workflow does the same.
//
// Requires the `gh` CLI, authenticated (`gh auth login`) with contents:write
// on the repo, and the backend already built into desktop/backend-dist:
//
//   pyinstaller --onefile --console --name blackjack-backend --distpath desktop/backend-dist run_backend.py
//
// Usage (from desktop/):
//   npm run release

import { existsSync } from "node:fs";
import { readFile, readdir } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const RELEASE_DIR = path.join(ROOT, "release");
const ASSET_SUFFIXES = [".exe", ".AppImage"];

function run(cmd, args) {
  return spawnSync(cmd, args, { stdio: "inherit" }).status ?? 1;
}

function runQuiet(cmd, args) {
  return spawnSync(cmd, args, { encoding: "utf8" }).status ?? 1;
}

async function main() {
  if (runQuiet("gh", ["--version"]) !== 0) {
    console.error("gh CLI not found. Install it from https://cli.github.com/ and run `gh auth login`.");
    process.exit(1);
  }
  if (!existsSync(path.join(ROOT, "backend-dist"))) {
    console.error("desktop/backend-dist is missing: build the Python backend with PyInstaller first (see the top of this file).");
    process.exit(1);
  }

  const pkg = JSON.parse(await readFile(path.join(ROOT, "package.json"), "utf8"));
  const tag = `v${pkg.version}`;
  const files = (await readdir(RELEASE_DIR))
    .filter((name) => ASSET_SUFFIXES.some((suffix) => name.endsWith(suffix)))
    .filter((name) => name.includes(pkg.version))
    .map((name) => path.join(RELEASE_DIR, name));
  if (files.length === 0) {
    console.error(`No ${pkg.version} installers found in ${RELEASE_DIR}. Run \`npm run dist\` first.`);
    process.exit(1);
  }

  console.log(`Publishing ${tag} with ${files.length} asset(s):`);
  for (const file of files) console.log(`  · ${path.basename(file)}`);

  if (runQuiet("gh", ["release", "view", tag, "--json", "tagName"]) === 0) {
    console.log(`Release ${tag} already exists — refreshing its assets.`);
    process.exit(run("gh", ["release", "upload", tag, ...files, "--clobber"]));
  }
  console.log(`Release ${tag} does not exist — creating it.`);
  process.exit(run("gh", ["release", "create", tag, "--title", `Blackjack Assistant ${tag}`, "--generate-notes", ...files]));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
