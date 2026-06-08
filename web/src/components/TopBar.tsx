import { useState } from "react";
import { useAppStore, type ConnectionState } from "../lib/store";
import { api, stopPython } from "../lib/tauri-bridge";

const connLabel: Record<ConnectionState, { text: string; cls: string }> = {
  未连接: { text: "未连接", cls: "text-dim" },
  连接中: { text: "连接中", cls: "text-warn" },
  已连接: { text: "已连接", cls: "text-ok" },
  已崩溃: { text: "已崩溃", cls: "text-err" },
};

export function TopBar() {
  const { connection, setConnection, target, isRunning, setRunning, setTotalSteps } =
    useAppStore();
  const [busy, setBusy] = useState(false);

  async function handleStart() {
    setBusy(true);
    try {
      try {
        await api.startRun({});
        setRunning(true);
        setTotalSteps(0);
      } catch (e) {
        console.error("startRun failed", e);
        setConnection("已崩溃");
      }
    } catch (e) {
      setConnection("已崩溃");
      console.error("startRun failed", e);
    } finally {
      setBusy(false);
    }
  }

  async function handleStop() {
    setBusy(true);
    try {
      await api.stopRun();
      setRunning(false);
    } catch (e) {
      console.warn("stopRun", e);
    }
    try {
      await stopPython();
    } catch (e) {
      console.warn("stopPython", e);
    }
    setConnection("未连接");
    setBusy(false);
  }

  const conn = connLabel[connection];

  return (
    <header className="flex items-center h-14 px-5 border-b border-line bg-bg">
      <div className="flex items-baseline gap-[10px] mr-8">
        <span className="text-sm font-semibold text-fg">ChaoxingAgent</span>
      </div>
      <div className="w-px h-4 bg-line mr-8" />
      <div className="flex items-center gap-1 text-[12px] text-muted font-mono">
        <span className={conn.cls}>{conn.text}</span>
        {target && (
          <span className="ml-3 text-dim">目标 {target.title || target.processName}</span>
        )}
      </div>
      <div className="flex-1" />
      <div className="flex items-center gap-1.5">
        {!isRunning ? (
          <button
            onClick={handleStart}
            disabled={busy || connection === "连接中"}
            className="inline-flex items-center h-[30px] px-3 rounded-md border border-accent bg-accent text-accent-fg text-[12.5px] font-medium transition-all duration-150 hover:bg-accent-hover hover:border-accent-hover disabled:opacity-50 active:translate-y-px"
          >
            启动
          </button>
        ) : (
          <button
            onClick={handleStop}
            disabled={busy}
            className="inline-flex items-center h-[30px] px-3 rounded-md border border-err/40 text-err text-[12.5px] font-medium transition-all duration-150 hover:bg-err/10 hover:border-err disabled:opacity-50"
          >
            停止
          </button>
        )}
      </div>
    </header>
  );
}
