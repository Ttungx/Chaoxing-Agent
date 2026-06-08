import { useEffect } from "react";
import { TopBar } from "./components/TopBar";
import { TabRail } from "./components/TabRail";
import { StatusBar } from "./components/StatusBar";
import { PauseOverlay } from "./components/PauseOverlay";
import { useAppStore } from "./lib/store";
import { api, events, startPython } from "./lib/tauri-bridge";
import { Monitor } from "./tabs/Monitor";
import { Calibration } from "./tabs/Calibration";
import { Config } from "./tabs/Config";
import { History } from "./tabs/History";
import { Logs } from "./tabs/Logs";

export default function App() {
  const {
    setConnection,
    appendLog,
    setCurrentStep,
    appendStep,
    setPause,
    setRunning,
    setTotalSteps,
    setScreenshot,
    activeTab,
    setConfigData,
    setModelServices,
  } = useAppStore();

  useEffect(() => {
    setConnection("连接中");
    startPython()
      .then(async () => {
        setConnection("已连接");
        try {
          const [config, modelServices] = await Promise.all([
            api.getConfig(),
            api.getModelServices(),
          ]);
          setConfigData(config);
          setModelServices(modelServices);
        } catch (error) {
          console.error("initial config preload failed", error);
        }
      })
      .catch((error) => {
        console.error("startPython on app mount failed", error);
        setConnection("已崩溃");
      });

    const unlistens: Array<() => void> = [];

    events
      .ready((d) => {
        console.log("python ready", d);
        setConnection("已连接");
      })
      .then((u) => unlistens.push(u));

    events
      .log((l) => appendLog(l))
      .then((u) => unlistens.push(u));

    events
      .configChanged((d) => {
        setConfigData(d.new_config);
      })
      .then((u) => unlistens.push(u));

    events
      .screenshot((s) => setScreenshot(s))
      .then((u) => unlistens.push(u));

    events
      .stepCompleted((s) => {
        setCurrentStep(s);
        appendStep({
          step: s.step,
          question: s.question.slice(0, 50),
          answer: s.answer,
          confidence: s.confidence,
          status: "ok",
          timestamp: new Date().toISOString(),
        });
        setTotalSteps(s.step);
      })
      .then((u) => unlistens.push(u));

    events
      .paused((p) => {
        setPause({
          pending: true,
          step: p.step,
          reason: p.reason,
          screenshot_b64: p.screenshot_b64,
        });
        useAppStore.getState().setActiveTab("实时监控");
      })
      .then((u) => unlistens.push(u));

    events
      .stopped((s) => {
        setRunning(false);
        appendLog({
          level: "INFO",
          message: `状态机停止: ${s.reason}（共 ${s.total_steps} 步）`,
          ts: new Date().toISOString(),
        });
      })
      .then((u) => unlistens.push(u));

    events
      .crashed((c) => {
        setConnection("已崩溃");
        setRunning(false);
        appendLog({
          level: "ERROR",
          message: `Python 崩溃: exit=${c.exit_code}`,
          ts: new Date().toISOString(),
        });
      })
      .then((u) => unlistens.push(u));

    events
      .calibrationChanged(() => {
        // Calibration tab 自己监听 + 拉取
      })
      .then((u) => unlistens.push(u));

    return () => unlistens.forEach((u) => u());
  }, []);

  return (
    <div className="flex flex-col h-full bg-bg text-fg">
      <TopBar />
      <TabRail />
      <main className="flex-1 overflow-hidden">
        {activeTab === "实时监控" && <Monitor />}
        {activeTab === "标定" && <Calibration />}
        {activeTab === "配置" && <Config />}
        {activeTab === "历史" && <History />}
        {activeTab === "日志" && <Logs />}
      </main>
      <StatusBar />
      <PauseOverlay />
    </div>
  );
}
