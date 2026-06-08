// 封装 Tauri 命令调用和事件监听
import { invoke } from "@tauri-apps/api/core";
import { listen, UnlistenFn, Event } from "@tauri-apps/api/event";
import type {
  WindowInfo,
  CalibrationState,
  SessionSummary,
  ReadyData,
  ScreenshotData,
  StepCompletedData,
  PausedData,
  LogData,
  ConfigChangedData,
  CrashedData,
  StoppedData,
  CalibrationChangedData,
} from "./types";

function isAlreadyStartedError(error: unknown): boolean {
  return String(error).includes("python already started");
}

export async function ensurePythonStarted(): Promise<void> {
  try {
    await invoke("start_python");
  } catch (error) {
    if (!isAlreadyStartedError(error)) {
      throw error;
    }
  }
}

export async function startPython(): Promise<void> {
  return ensurePythonStarted();
}

export async function stopPython(): Promise<void> {
  return invoke("stop_python");
}

async function rpcCall<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  await ensurePythonStarted();
  // 走统一 rpc_call command
  return invoke<T>("rpc_call", { method, params });
}

export function on<T>(
  event: string,
  handler: (data: T) => void
): Promise<UnlistenFn> {
  return listen<T>(event, (e: Event<T>) => handler(e.payload));
}

// 业务方法封装（类型化）
export const api = {
  listWindows: (processName?: string, pid?: number) =>
    rpcCall<WindowInfo[]>("list_windows", { process_name: processName, pid }),

  getCalibration: () => rpcCall<CalibrationState>("get_calibration", {}),

  launchCalibrationWizard: () =>
    rpcCall<{ accepted: true }>("launch_calibration_wizard", {}),

  startRun: (opts: {
    reuse_binding?: boolean;
    reuse_calibration?: boolean;
    config_overrides?: Record<string, unknown>;
  }) => rpcCall<{ session_id: string }>("start_run", opts),

  stopRun: () => rpcCall<{ stopped_at_step: number }>("stop_run", {}),

  pauseDecision: (decision: "retry" | "skip" | "quit") =>
    rpcCall("pause_decision", { decision }),

  listTraceSessions: (limit = 50) =>
    rpcCall<SessionSummary[]>("list_trace_sessions", { limit }),

  getSessionDetail: (sessionId: string, step?: number) =>
    rpcCall("get_session_detail", { session_id: sessionId, step }),

  getConfig: () => rpcCall<Record<string, unknown>>("get_config", {}),

  updateConfig: (patch: Record<string, unknown>) =>
    rpcCall<{ hot_fields: string[] }>("update_config", { patch }),

  getModelServices: () =>
    rpcCall<Record<string, unknown>>("get_model_services", {}),

  switchModel: (role: "vision" | "solver", key: string) =>
    rpcCall("switch_model", { role, key }),

  testModel: (role: "vision" | "solver", key: string) =>
    rpcCall<{ ok: boolean; latency_ms: number; error?: string }>(
      "test_model",
      { role, key }
    ),
};

// 事件类型化订阅快捷方式
export const events = {
  ready: (h: (d: ReadyData) => void) => on<ReadyData>("ready", h),
  screenshot: (h: (d: ScreenshotData) => void) => on<ScreenshotData>("screenshot", h),
  stepStarted: (h: (d: { step: number; page_state: string }) => void) =>
    on<{ step: number; page_state: string }>("step_started", h),
  stepCompleted: (h: (d: StepCompletedData) => void) =>
    on<StepCompletedData>("step_completed", h),
  paused: (h: (d: PausedData) => void) => on<PausedData>("paused", h),
  log: (h: (d: LogData) => void) => on<LogData>("log", h),
  configChanged: (h: (d: ConfigChangedData) => void) =>
    on<ConfigChangedData>("config_changed", h),
  crashed: (h: (d: CrashedData) => void) => on<CrashedData>("python:crashed", h),
  stopped: (h: (d: StoppedData) => void) => on<StoppedData>("stopped", h),
  calibrationChanged: (h: (d: CalibrationChangedData) => void) =>
    on<CalibrationChangedData>("calibration_changed", h),
};
