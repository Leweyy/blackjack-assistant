// Exposes a small, typed API to the UI. The UI never gets direct Node or Electron access.

import { contextBridge, ipcRenderer, IpcRendererEvent } from "electron";
import type { Api, BackendEvent } from "../shared/types";

const api: Api = {
  request: (method, params = {}) => ipcRenderer.invoke("backend:request", method, params),
  startSession: () => ipcRenderer.invoke("session:start"),
  stopSession: () => ipcRenderer.invoke("session:stop"),
  isRunning: () => ipcRenderer.invoke("session:running"),
  pickRegion: () => ipcRenderer.invoke("region:pick"),
  listWindows: () => ipcRenderer.invoke("windows:list"),
  platform: process.platform,
  openImage: () => ipcRenderer.invoke("dialog:openImage"),
  openExternal: (url) => ipcRenderer.invoke("shell:openExternal", url),
  closeOverlay: () => ipcRenderer.send("overlay:close"),
  resizeOverlay: (height) => ipcRenderer.send("overlay:resize", height),
  pickerDone: (rect) => ipcRenderer.send("picker:done", rect),
  onEvent: (callback) => {
    const listener = (_e: IpcRendererEvent, event: BackendEvent) => callback(event);
    ipcRenderer.on("backend:event", listener);
    return () => ipcRenderer.removeListener("backend:event", listener);
  },
  onSessionChange: (callback) => {
    const listener = (_e: IpcRendererEvent, running: boolean) => callback(running);
    ipcRenderer.on("session:changed", listener);
    return () => ipcRenderer.removeListener("session:changed", listener);
  },
};

contextBridge.exposeInMainWorld("api", api);
