// Starts the Python backend and talks to it over JSON lines on stdin/stdout.

import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { app } from "electron";
import type { BackendEvent } from "../shared/types";

interface Pending {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
}

function backendCommand(): { command: string; args: string[]; cwd: string } {
  if (app.isPackaged) {
    const exe = process.platform === "win32" ? "blackjack-backend.exe" : "blackjack-backend";
    const dir = path.join(process.resourcesPath, "backend");
    return { command: path.join(dir, exe), args: [], cwd: dir };
  }
  // Development: run the Python package from the repository root (desktop/dist/main -> repo root).
  const repoRoot = path.resolve(__dirname, "..", "..", "..");
  const python = process.env.BJ_PYTHON || (process.platform === "win32" ? "python" : "python3");
  return { command: python, args: ["-m", "blackjack_assistant.server"], cwd: repoRoot };
}

export class Backend extends EventEmitter {
  private proc: ChildProcessWithoutNullStreams | null = null;
  private pending = new Map<number, Pending>();
  private nextId = 1;

  start(): void {
    const { command, args, cwd } = backendCommand();
    if (app.isPackaged && !fs.existsSync(command)) {
      throw new Error(`Backend not found at ${command}`);
    }
    const proc = spawn(command, args, {
      cwd,
      windowsHide: true,
      env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" },
    });
    this.proc = proc;

    readline.createInterface({ input: proc.stdout }).on("line", (line) => this.onLine(line));
    proc.stderr.on("data", (chunk: Buffer) => process.stderr.write(`[backend] ${chunk}`));
    proc.on("error", (err) => this.onExit(null, err));
    proc.on("exit", (code) => this.onExit(code));
  }

  request<T = unknown>(method: string, params: Record<string, unknown> = {}, timeoutMs = 180_000): Promise<T> {
    if (!this.proc || this.proc.exitCode !== null) {
      return Promise.reject(new Error("The backend isn't running. Restart the app."));
    }
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Backend timed out on ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject, timer });
      this.proc!.stdin.write(JSON.stringify({ id, method, params }) + "\n");
    });
  }

  stop(): void {
    if (this.proc && this.proc.exitCode === null) {
      this.proc.stdin.end(); // backend stops its session and exits when stdin closes
      const proc = this.proc;
      setTimeout(() => proc.exitCode === null && proc.kill(), 3000);
    }
  }

  private onLine(line: string): void {
    let msg: { id?: number; result?: unknown; error?: string; event?: string; data?: unknown };
    try {
      msg = JSON.parse(line);
    } catch {
      process.stderr.write(`[backend] non-JSON output: ${line}\n`);
      return;
    }
    if (msg.event) {
      this.emit("event", { event: msg.event, data: msg.data ?? null } as BackendEvent);
      return;
    }
    const pending = msg.id != null ? this.pending.get(msg.id) : undefined;
    if (!pending) return;
    this.pending.delete(msg.id!);
    clearTimeout(pending.timer);
    if (msg.error !== undefined) pending.reject(new Error(msg.error));
    else pending.resolve(msg.result);
  }

  private onExit(code: number | null, err?: Error): void {
    if (!this.proc) return;
    this.proc = null;
    const reason = err ? `Couldn't start the backend: ${err.message}` : "The backend stopped unexpectedly.";
    for (const p of this.pending.values()) {
      clearTimeout(p.timer);
      p.reject(new Error(reason));
    }
    this.pending.clear();
    this.emit("event", { event: "backend-exit", data: { code } } as BackendEvent);
  }
}
