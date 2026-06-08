import { create } from "zustand";
import type {
  LogData,
  ScreenshotData,
  StepCompletedData,
  CalibrationState,
  SessionSummary,
} from "./types";

export type ConnectionState = "未连接" | "连接中" | "已连接" | "已崩溃";
export type ActiveTab = "实时监控" | "标定" | "配置" | "历史" | "日志";

type PauseState = {
  pending: boolean;
  step: number | null;
  reason: string | null;
  screenshot_b64: string | null;
};

export type StepHistoryItem = {
  step: number;
  question: string;
  answer: string[];
  confidence: number;
  status: "ok" | "skipped" | "error";
  timestamp: string;
};

type CalibrationData = CalibrationState | null;
type ConfigData = Record<string, unknown> | null;
type ModelServicesData = Record<string, unknown> | null;

type AppState = {
  // 连接状态
  connection: ConnectionState;
  setConnection: (s: ConnectionState) => void;

  // 当前 tab
  activeTab: ActiveTab;
  setActiveTab: (t: ActiveTab) => void;

  // 目标窗口
  target: { hwnd: number; title: string; processName: string } | null;
  setTarget: (t: AppState["target"]) => void;

  // 标定数据
  calibration: CalibrationData;
  setCalibration: (c: CalibrationData) => void;

  // 实时画面
  screenshot: ScreenshotData | null;
  setScreenshot: (s: ScreenshotData | null) => void;

  // 当前 step
  currentStep: StepCompletedData | null;
  setCurrentStep: (s: StepCompletedData | null) => void;

  // step 历史
  stepHistory: StepHistoryItem[];
  appendStep: (s: StepHistoryItem) => void;
  clearHistory: () => void;

  // 暂停
  pause: PauseState;
  setPause: (p: Partial<PauseState>) => void;
  clearPause: () => void;

  // 日志
  logs: LogData[];
  appendLog: (l: LogData) => void;
  clearLogs: () => void;

  // 历史 session
  sessions: SessionSummary[];
  setSessions: (s: SessionSummary[]) => void;

  // 配置缓存
  configData: ConfigData;
  setConfigData: (c: ConfigData) => void;
  modelServices: ModelServicesData;
  setModelServices: (m: ModelServicesData) => void;

  // 状态机
  isRunning: boolean;
  setRunning: (r: boolean) => void;
  totalSteps: number;
  setTotalSteps: (n: number) => void;
};

export const useAppStore = create<AppState>((set) => ({
  connection: "未连接",
  setConnection: (s) => set({ connection: s }),

  activeTab: "实时监控",
  setActiveTab: (t) => set({ activeTab: t }),

  target: null,
  setTarget: (t) => set({ target: t }),

  calibration: null,
  setCalibration: (c) => set({ calibration: c }),

  screenshot: null,
  setScreenshot: (s) => set({ screenshot: s }),

  currentStep: null,
  setCurrentStep: (s) => set({ currentStep: s }),

  stepHistory: [],
  appendStep: (s) =>
    set((state) => ({ stepHistory: [s, ...state.stepHistory].slice(0, 50) })),
  clearHistory: () => set({ stepHistory: [] }),

  pause: { pending: false, step: null, reason: null, screenshot_b64: null },
  setPause: (p) => set((state) => ({ pause: { ...state.pause, ...p } })),
  clearPause: () =>
    set({ pause: { pending: false, step: null, reason: null, screenshot_b64: null } }),

  logs: [],
  appendLog: (l) => set((state) => ({ logs: [...state.logs, l].slice(-500) })),
  clearLogs: () => set({ logs: [] }),

  sessions: [],
  setSessions: (s) => set({ sessions: s }),

  configData: null,
  setConfigData: (c) => set({ configData: c }),
  modelServices: null,
  setModelServices: (m) => set({ modelServices: m }),

  isRunning: false,
  setRunning: (r) => set({ isRunning: r }),
  totalSteps: 0,
  setTotalSteps: (n) => set({ totalSteps: n }),
}));
