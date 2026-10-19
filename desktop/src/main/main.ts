// Electron main process: windows, the region picker, and the bridge to the Python backend.

import path from "node:path";
import { app, BrowserWindow, desktopCapturer, Display, dialog, ipcMain, Rectangle, screen, shell } from "electron";
import { Backend } from "./backend";
import type { BackendEvent, PickMode, Region, RendererMethod, Seat, WindowSource } from "../shared/types";

const RENDERER_METHODS: RendererMethod[] = ["get_settings", "save_settings", "test_screenshot", "reset_count"];
const BG = "#0e1116";

const backend = new Backend();
let mainWindow: BrowserWindow | null = null;
let overlayWindow: BrowserWindow | null = null;
let running = false;

function page(name: string): string {
  return path.join(__dirname, "..", "renderer", `${name}.html`);
}

function secureWebPreferences(): Electron.WebPreferences {
  return {
    preload: path.join(__dirname, "preload.js"),
    contextIsolation: true,
    sandbox: true,
    nodeIntegration: false,
  };
}

function lockDown(win: BrowserWindow): void {
  // The UI is local files only: block navigation and new windows.
  win.webContents.on("will-navigate", (e) => e.preventDefault());
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
}

function broadcast(channel: string, payload: unknown): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) win.webContents.send(channel, payload);
  }
}

function setRunning(value: boolean): void {
  running = value;
  broadcast("session:changed", value);
  if (!value && overlayWindow && !overlayWindow.isDestroyed()) overlayWindow.close();
}

// ---- windows ------------------------------------------------------------

function createMainWindow(): void {
  mainWindow = new BrowserWindow({
    width: 900,
    height: 680,
    minWidth: 760,
    minHeight: 560,
    title: "Blackjack Assistant",
    backgroundColor: BG,
    show: false,
    titleBarStyle: "hidden",
    titleBarOverlay: { color: BG, symbolColor: "#c9d1d9", height: 40 },
    autoHideMenuBar: true,
    webPreferences: secureWebPreferences(),
  });
  lockDown(mainWindow);
  // Never let the settings window end up in what the backend sees, even if it overlaps the game.
  mainWindow.setContentProtection(true);
  mainWindow.once("ready-to-show", () => mainWindow?.show());
  mainWindow.on("closed", () => {
    mainWindow = null;
    app.quit();
  });
  mainWindow.loadFile(page("index"));
}

function createOverlay(): void {
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    overlayWindow.show();
    return;
  }
  const area = screen.getPrimaryDisplay().workArea;
  const width = 460;
  overlayWindow = new BrowserWindow({
    width,
    height: 200,
    x: area.x + area.width - width - 24,
    y: area.y + 24,
    frame: false,
    transparent: true,
    resizable: false,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    alwaysOnTop: true,
    skipTaskbar: false,
    hasShadow: false,
    title: "Blackjack Assistant — Advice",
    webPreferences: secureWebPreferences(),
  });
  overlayWindow.setAlwaysOnTop(true, "screen-saver");
  overlayWindow.setVisibleOnAllWorkspaces(true);
  // Keep the overlay out of screen captures so it can never hide cards from the backend
  // (Windows 10 2004+ and macOS; elsewhere it has no effect).
  overlayWindow.setContentProtection(true);
  lockDown(overlayWindow);
  overlayWindow.on("closed", () => {
    overlayWindow = null;
    if (running) void backend.request("stop").catch(() => undefined);
  });
  overlayWindow.loadFile(page("overlay"));
}

// ---- region picker --------------------------------------------------------

/** Convert a rectangle in Electron's DIP coordinates to the pixels the backend captures. */
function toCapturePixels(rect: Rectangle, display: Display, win: BrowserWindow): Region {
  let r = rect;
  if (process.platform === "win32") {
    r = screen.dipToScreenRect(win, rect);
  } else if (process.platform === "linux") {
    const f = display.scaleFactor;
    r = { x: rect.x * f, y: rect.y * f, width: rect.width * f, height: rect.height * f };
  } // macOS: the backend captures in points, same as DIP
  return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)];
}

let pickerInProgress: Promise<Region | null> | null = null;

/** Let the user drag a box on screen. Returns it in capture pixels, or null if cancelled. */
function pickRegion(mode: PickMode = "region"): Promise<Region | null> {
  if (pickerInProgress) return pickerInProgress;
  pickerInProgress = new Promise<Region | null>((resolve) => {
    const pickers: { win: BrowserWindow; display: Display }[] = [];
    let finished = false;
    const overlayWasVisible = !!overlayWindow && !overlayWindow.isDestroyed() && overlayWindow.isVisible();
    mainWindow?.hide();
    overlayWindow?.hide();

    const finish = (region: Region | null) => {
      if (finished) return;
      finished = true;
      ipcMain.removeListener("picker:done", onDone);
      for (const p of pickers) if (!p.win.isDestroyed()) p.win.close();
      if (overlayWasVisible) overlayWindow?.showInactive();
      // Marking a seat from the overlay shouldn't pop the settings window up mid-game.
      if (mode === "region" || !overlayWasVisible) mainWindow?.show();
      pickerInProgress = null;
      resolve(region);
    };

    const onDone = (event: Electron.IpcMainEvent, rect: Rectangle | null) => {
      const picker = pickers.find((p) => p.win.webContents === event.sender);
      if (!picker || !rect || rect.width < 20 || rect.height < 20) return finish(null);
      const { bounds } = picker.display;
      const absolute = { x: bounds.x + rect.x, y: bounds.y + rect.y, width: rect.width, height: rect.height };
      finish(toCapturePixels(absolute, picker.display, picker.win));
    };
    ipcMain.on("picker:done", onDone);

    // One picker window per monitor: spanning monitors with different scaling is unreliable.
    for (const display of screen.getAllDisplays()) {
      const win = new BrowserWindow({
        ...display.bounds,
        frame: false,
        transparent: true,
        resizable: false,
        movable: false,
        alwaysOnTop: true,
        skipTaskbar: true,
        hasShadow: false,
        enableLargerThanScreen: true,
        webPreferences: secureWebPreferences(),
      });
      win.setAlwaysOnTop(true, "screen-saver");
      win.setBounds(display.bounds);
      lockDown(win);
      win.on("closed", () => {
        if (!finished) finish(null);
      });
      win.loadFile(page("picker"), { query: { mode } });
      pickers.push({ win, display });
    }
    pickers.find((p) => p.display.id === screen.getDisplayNearestPoint(screen.getCursorScreenPoint()).id)?.win.focus();
  });
  return pickerInProgress;
}

/**
 * Let the user drag a box around their own cards, on top of the live game, and save it
 * as the seat: a box in fractions of the captured image. Works while running, too.
 */
async function markSeat(): Promise<Seat | null> {
  const [left, top, width, height] = await backend.request<Region>("capture_bounds");
  const box = await pickRegion("seat");
  if (!box) return null;
  const [bx, by, bw, bh] = box;
  const x0 = Math.max(bx, left), y0 = Math.max(by, top);
  const x1 = Math.min(bx + bw, left + width), y1 = Math.min(by + bh, top + height);
  if (x1 - x0 < 10 || y1 - y0 < 10) {
    throw new Error("That box is outside the area being watched. Draw it over your cards in the game.");
  }
  const seat = await backend.request<Seat>("set_seat", {
    seat: [(x0 - left) / width, (y0 - top) / height, (x1 - x0) / width, (y1 - y0) / height],
  });
  broadcast("backend:event", { event: "seat", data: seat });
  return seat;
}

// ---- window picker --------------------------------------------------------

async function listWindows(): Promise<WindowSource[]> {
  const own = new Set(BrowserWindow.getAllWindows().map((w) => w.getMediaSourceId()));
  const sources = await desktopCapturer.getSources({
    types: ["window"],
    thumbnailSize: { width: 320, height: 200 },
    fetchWindowIcons: true,
  });
  return sources
    .filter((s) => !own.has(s.id) && s.name.trim() !== "")
    .map((s) => ({
      id: s.id,
      // Source ids look like "window:<handle>:0"; on Windows the handle is the HWND.
      handle: Number(s.id.split(":")[1]) || 0,
      title: s.name,
      thumbnail: s.thumbnail.isEmpty() ? "" : s.thumbnail.toDataURL(),
      icon: s.appIcon && !s.appIcon.isEmpty() ? s.appIcon.toDataURL() : null,
    }));
}

// ---- IPC ------------------------------------------------------------------

function registerIpc(): void {
  ipcMain.handle("backend:request", (_e, method: RendererMethod, params: Record<string, unknown>) => {
    if (!RENDERER_METHODS.includes(method)) throw new Error(`Not allowed: ${method}`);
    return backend.request(method, params);
  });
  ipcMain.handle("session:start", async () => {
    await backend.request("start");
    createOverlay();
    setRunning(true);
  });
  ipcMain.handle("session:stop", async () => {
    await backend.request("stop");
  });
  ipcMain.handle("session:running", () => running);
  ipcMain.handle("region:pick", () => pickRegion("region"));
  ipcMain.handle("seat:mark", () => markSeat());
  ipcMain.handle("windows:list", () => listWindows());
  ipcMain.handle("dialog:openImage", async () => {
    const options: Electron.OpenDialogOptions = {
      title: "Choose a screenshot of your blackjack game",
      properties: ["openFile"],
      filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "bmp", "webp"] }],
    };
    const result = mainWindow ? await dialog.showOpenDialog(mainWindow, options) : await dialog.showOpenDialog(options);
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle("shell:openExternal", (_e, url: string) => {
    if (url.startsWith("https://console.anthropic.com/") || url.startsWith("https://platform.claude.com/")) {
      return shell.openExternal(url);
    }
  });
  ipcMain.on("overlay:close", () => {
    void backend.request("stop").catch(() => undefined);
    overlayWindow?.close();
  });
  ipcMain.on("overlay:resize", (_e, height: number) => {
    if (overlayWindow && !overlayWindow.isDestroyed() && Number.isFinite(height)) {
      const [w] = overlayWindow.getSize();
      // Some platforms ignore setSize on non-resizable windows, so allow it just for this call.
      overlayWindow.setResizable(true);
      overlayWindow.setSize(w, Math.max(80, Math.min(600, Math.ceil(height))));
      overlayWindow.setResizable(false);
    }
  });
}

function onBackendEvent(event: BackendEvent): void {
  if (event.event === "stopped" || event.event === "backend-exit") setRunning(false);
  if (event.event === "backend-exit") {
    broadcast("backend:event", { event: "error", data: "The backend stopped unexpectedly. Restart the app." });
  }
  broadcast("backend:event", event);
}

// ---- smoke test (CI) ------------------------------------------------------

async function smokeTest(): Promise<void> {
  const timeout = setTimeout(() => {
    console.error("smoke test timed out");
    app.exit(1);
  }, 60_000);
  try {
    backend.start();
    const pong = await backend.request("ping");
    const info = await backend.request<{ config_path: string }>("get_settings");
    console.log(`smoke test ok: ${pong}, settings at ${info.config_path}`);
    clearTimeout(timeout);
    backend.stop();
    app.exit(pong === "pong" ? 0 : 1);
  } catch (err) {
    console.error("smoke test failed:", err);
    app.exit(1);
  }
}

// ---- app lifecycle --------------------------------------------------------

if (process.argv.includes("--smoke-test")) {
  app.whenReady().then(smokeTest);
} else if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    registerIpc();
    backend.on("event", onBackendEvent);
    try {
      backend.start();
    } catch (err) {
      dialog.showErrorBox("Blackjack Assistant", String(err));
    }
    createMainWindow();
  });

  app.on("window-all-closed", () => app.quit());
  app.on("before-quit", () => backend.stop());
}
