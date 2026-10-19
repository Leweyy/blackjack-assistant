// Types shared by the Electron main process, the preload bridge and the React UI.
// They mirror the Python backend (blackjack_assistant/server.py, config.py, advisor.py).

export type Region = [left: number, top: number, width: number, height: number];

export type CaptureMode = "monitor" | "region" | "window";

/** A box around the player's cards: [x, y, width, height] as fractions of the captured image. */
export type Seat = [x: number, y: number, width: number, height: number];

/** What the on-screen box picker is for. */
export type PickMode = "region" | "seat";

/** A window the user picked to watch. `handle` is the Windows HWND. */
export interface ChosenWindow {
  handle: number;
  title: string;
}

/** An open window offered in the window picker. */
export interface WindowSource {
  id: string;
  handle: number;
  title: string;
  thumbnail: string; // data: URL
  icon: string | null; // data: URL
}

export type Provider = "anthropic" | "local";

export interface Settings {
  provider: Provider;
  api_key: string;
  model: string;
  local_url: string;
  local_model: string;
  local_api_key: string;
  local_max_side: number;
  save_frames: boolean;
  interval: number;
  fast_reads: boolean;
  monitor: number;
  capture: CaptureMode;
  region: Region | null;
  window: ChosenWindow | null;
  /** The player's seat box as fractions of the captured image; null = detect automatically. */
  seat: Seat | null;
  dealer_hits_soft_17: boolean;
  double_after_split: boolean;
  surrender_allowed: boolean;
  counting: boolean;
  decks: number;
  unit: number | null;
  max_units: number;
}

export interface SettingsInfo {
  settings: Settings;
  config_path: string;
  frames_dir: string;
  env_api_key: boolean;
}

export type ActionName = "HIT" | "STAND" | "DOUBLE" | "SPLIT" | "SURRENDER" | "INSURANCE" | "NO_INSURANCE";

export interface Advice {
  headline: string;
  detail: string;
  action: ActionName | null;
  count_line: string;
  bet_units: number | null;
  reason: string;
  player_cards: string[];
  dealer_cards: string[];
  player_total: string;
  dealer_total: string;
  hand_label: string;
}

export interface TableState {
  table_visible: boolean;
  dealer_cards: string[];
  player_hands: string[][];
  other_players_cards: string[];
  is_player_turn: boolean;
  is_betting_phase: boolean;
  round_complete: boolean;
  confident: boolean;
}

export interface ScreenshotResult {
  advice: Advice;
  table: TableState;
  image: string; // data: URL of the image as sent to Claude (with the seat marker)
}


export type BackendEvent =
  | { event: "ready"; data: null }
  | { event: "advice"; data: Advice }
  | { event: "status"; data: string }
  | { event: "error"; data: string }
  | { event: "stopped"; data: null }
  | { event: "seat"; data: Seat | null }
  | { event: "backend-exit"; data: { code: number | null } };

export type RendererMethod = "get_settings" | "save_settings" | "test_screenshot" | "reset_count" | "local_models";

/** The API the preload script exposes to the UI as `window.api`. */
export interface Api {
  request<T = unknown>(method: RendererMethod, params?: Record<string, unknown>): Promise<T>;
  startSession(): Promise<void>;
  stopSession(): Promise<void>;
  isRunning(): Promise<boolean>;
  pickRegion(): Promise<Region | null>;
  listWindows(): Promise<WindowSource[]>;
  /** Drag a box around your cards on screen; saves and returns it (null if cancelled). */
  markSeat(): Promise<Seat | null>;
  platform: string;
  openImage(): Promise<string | null>;
  openExternal(url: string): Promise<void>;
  /** Open the folder where "Save screenshots for testing" puts frames. */
  openFramesFolder(): Promise<void>;
  closeOverlay(): void;
  resizeOverlay(height: number): void;
  pickerDone(rect: { x: number; y: number; width: number; height: number } | null): void;
  onEvent(callback: (event: BackendEvent) => void): () => void;
  onSessionChange(callback: (running: boolean) => void): () => void;
}
