import { useEffect, useState } from "react";
import { api } from "../lib/tauri-bridge";
import { useAppStore } from "../lib/store";

type Config = {
  thresholds?: { vision_text_confidence?: number; vision_layout_confidence?: number; solver_confidence?: number };
  timing?: { between_multi_select_clicks?: number; before_click_next?: number; after_click_next?: number };
  runtime?: { max_steps?: number; pause_on_popup?: boolean; pause_on_unknown?: boolean };
};

type ModelService = {
  api_type: string;
  base_url?: string;
  model_id?: string;
  api_key_env?: string;
};

type ModelServices = {
  selected?: { vision_model?: string; solver_model?: string; vision?: string; solver?: string };
  vision?: Record<string, ModelService> | ModelService;
  solver?: Record<string, ModelService> | ModelService;
};

function isModelService(section: Record<string, ModelService> | ModelService): section is ModelService {
  return typeof (section as ModelService).api_type === "string";
}

function activeModel(section: Record<string, ModelService> | ModelService | undefined, selectedKey?: string): { name: string; service?: ModelService } {
  if (!section) return { name: "未配置" };
  if (isModelService(section)) return { name: section.model_id ?? "单 provider", service: section };
  const keys = Object.keys(section);
  const key = selectedKey && section[selectedKey] ? selectedKey : keys[0];
  return { name: key ?? "未配置", service: key ? section[key] : undefined };
}

export function Config() {
  const { configData, setConfigData, modelServices, setModelServices } = useAppStore();
  const [cfg, setCfg] = useState<Config | null>((configData as Config | null) ?? null);
  const [services, setServices] = useState<ModelServices | null>((modelServices as ModelServices | null) ?? null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    if (configData) {
      setCfg(configData as Config);
    }
  }, [configData]);

  useEffect(() => {
    if (modelServices) {
      setServices(modelServices as ModelServices);
    }
  }, [modelServices]);

  useEffect(() => {
    if (cfg || services) {
      return;
    }
    Promise.all([api.getConfig() as Promise<Config>, api.getModelServices() as Promise<ModelServices>])
      .then(([c, s]) => {
        setCfg(c);
        setServices(s);
        setConfigData(c as Record<string, unknown>);
        setModelServices(s as Record<string, unknown>);
        setError(null);
      })
      .catch((e) => {
        const message = String(e);
        setError(message);
        setToast({ kind: "err", text: message });
      });
  }, [cfg, services, setConfigData, setModelServices]);

  function patch<T extends keyof Config>(key: T, value: Config[T]) {
    if (!cfg) return;
    setCfg({ ...cfg, [key]: value });
    setDirty(true);
  }

  function setThreshold(field: "vision_text_confidence" | "vision_layout_confidence" | "solver_confidence", v: number) {
    const t = cfg?.thresholds ?? {};
    patch("thresholds", { ...t, [field]: v });
  }

  function setTiming(field: "between_multi_select_clicks" | "before_click_next" | "after_click_next", v: number) {
    const t = cfg?.timing ?? {};
    patch("timing", { ...t, [field]: v });
  }

  function setRuntime<K extends keyof NonNullable<Config["runtime"]>>(
    field: K,
    v: NonNullable<Config["runtime"]>[K]
  ) {
    const r = cfg?.runtime ?? {};
    patch("runtime", { ...r, [field]: v });
  }

  async function save() {
    if (!cfg) return;
    setBusy(true);
    try {
      const result = await api.updateConfig({
        thresholds: cfg.thresholds,
        timing: cfg.timing,
        runtime: cfg.runtime,
      });
      setConfigData(cfg as Record<string, unknown>);
      setDirty(false);
      setToast({ kind: "ok", text: `已保存（热更字段：${result.hot_fields.join("、") || "无"}）` });
      setTimeout(() => setToast(null), 3000);
    } catch (e) {
      setToast({ kind: "err", text: `保存失败：${e}` });
    } finally {
      setBusy(false);
    }
  }

  function discard() {
    if (!cfg) return;
    api.getConfig().then((c) => {
      setCfg(c);
      setConfigData(c as Record<string, unknown>);
      setDirty(false);
    });
  }

  if (!cfg) {
    if (error) {
      return (
        <div className="p-8">
          <div className="text-err text-[13px] font-mono mb-3">配置加载失败：{error}</div>
          <button
            onClick={() => window.location.reload()}
            className="h-7 px-3 rounded border border-line bg-bg text-fg text-[12px] hover:bg-surface2 active:-translate-y-px"
          >
            重试
          </button>
        </div>
      );
    }
    return (
      <div className="p-8 text-dim text-[13px]">加载配置中</div>
    );
  }

  const t = cfg.thresholds ?? {};
  const ti = cfg.timing ?? {};
  const r = cfg.runtime ?? {};
  const selected = services?.selected ?? {};

  const vision = activeModel(services?.vision, selected.vision_model ?? selected.vision);
  const solver = activeModel(services?.solver, selected.solver_model ?? selected.solver);

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-auto p-8 max-w-[1200px] w-full mx-auto">
        <div className="text-[22px] font-semibold tracking-tight mb-1">配置</div>
        <div className="text-[13px] text-muted mb-6">运行时参数，热更字段下次 step 生效</div>

        <div className="grid grid-cols-2 gap-px bg-line border border-line rounded-lg overflow-hidden mb-6">
          {/* ===== 模型服务 ===== */}
          <div className="bg-bg p-6">
            <div className="flex items-baseline justify-between mb-4">
              <div className="text-[14px] font-semibold">模型服务</div>
              <button className="h-7 px-2.5 rounded border border-line bg-bg text-fg text-[12px] hover:bg-surface2 active:-translate-y-px">+ 添加</button>
            </div>

            <ModelRow
              role="vision"
              name={vision.name}
              meta={vision.service ? `${vision.service.api_type} / ${vision.service.model_id ?? "?"}` : "未配置"}
              onTest={async () => {
                try {
                  const r = await api.testModel("vision", vision.name === "未配置" ? "" : vision.name);
                  setToast({ kind: r.ok ? "ok" : "err", text: r.ok ? `连通 ${r.latency_ms}ms` : `失败：${r.error}` });
                  setTimeout(() => setToast(null), 3000);
                } catch (e) {
                  setToast({ kind: "err", text: String(e) });
                }
              }}
            />
            <div className="h-2" />
            <ModelRow
              role="solver"
              name={solver.name}
              meta={solver.service ? `${solver.service.api_type} / ${solver.service.model_id ?? "?"}` : "未配置"}
              onTest={async () => {
                try {
                  const r = await api.testModel("solver", solver.name === "未配置" ? "" : solver.name);
                  setToast({ kind: r.ok ? "ok" : "err", text: r.ok ? `连通 ${r.latency_ms}ms` : `失败：${r.error}` });
                  setTimeout(() => setToast(null), 3000);
                } catch (e) {
                  setToast({ kind: "err", text: String(e) });
                }
              }}
            />
          </div>

          {/* ===== 阈值 ===== */}
          <div className="bg-bg p-6">
            <div className="flex items-baseline justify-between mb-4">
              <div className="text-[14px] font-semibold">阈值</div>
              <span className="font-mono text-[11px] text-dim">0 到 1</span>
            </div>
            <SliderField label="vision_text_confidence" value={t.vision_text_confidence ?? 0.75} onChange={(v) => setThreshold("vision_text_confidence", v)} />
            <SliderField label="vision_layout_confidence" value={t.vision_layout_confidence ?? 0.75} onChange={(v) => setThreshold("vision_layout_confidence", v)} />
            <SliderField label="solver_confidence" value={t.solver_confidence ?? 0.70} onChange={(v) => setThreshold("solver_confidence", v)} />
          </div>

          {/* ===== 时序 ===== */}
          <div className="bg-bg p-6">
            <div className="flex items-baseline justify-between mb-4">
              <div className="text-[14px] font-semibold">时序</div>
              <span className="font-mono text-[11px] text-dim">秒</span>
            </div>
            <InputField label="between_multi_select_clicks" value={ti.between_multi_select_clicks ?? 0.2} onChange={(v) => setTiming("between_multi_select_clicks", v)} suffix="s" />
            <InputField label="before_click_next" value={ti.before_click_next ?? 0.2} onChange={(v) => setTiming("before_click_next", v)} suffix="s" />
            <InputField label="after_click_next" value={ti.after_click_next ?? 0.5} onChange={(v) => setTiming("after_click_next", v)} suffix="s" />
          </div>

          {/* ===== 运行时 ===== */}
          <div className="bg-bg p-6">
            <div className="flex items-baseline justify-between mb-4">
              <div className="text-[14px] font-semibold">运行时</div>
              <span className="font-mono text-[11px] text-dim">行为</span>
            </div>
            <InputField label="max_steps" value={r.max_steps ?? 200} onChange={(v) => setRuntime("max_steps", v)} mono={false} />
            <ReadOnlyField
              label="submit safety"
              sub="检测到交卷按钮时始终停止（不可关闭的安全边界）"
            />
            <ToggleField
              label="pause_on_popup"
              sub="检测到弹窗时暂停"
              on={r.pause_on_popup ?? true}
              onToggle={(v) => setRuntime("pause_on_popup", v)}
            />
            <ToggleField
              label="pause_on_unknown"
              sub="未知题型时暂停"
              on={r.pause_on_unknown ?? true}
              onToggle={(v) => setRuntime("pause_on_unknown", v)}
            />
          </div>
        </div>

        {toast && (
          <div
            className={`fixed bottom-20 right-8 px-3.5 py-2 rounded border font-mono text-[12px] ${
              toast.kind === "ok" ? "border-ok/40 bg-ok/10 text-ok" : "border-err/40 bg-err/10 text-err"
            }`}
          >
            {toast.text}
          </div>
        )}
      </div>

      {dirty && (
        <div className="sticky bottom-0 mx-8 mb-4 bg-surface2 border border-line rounded-lg p-2.5 px-4 flex items-center gap-3">
          <div className="text-[12px] text-muted flex-1">
            修改未保存。
            <span className="font-mono text-fg">热更字段：timing, thresholds, runtime</span>
            <span className="text-warn ml-2">窗口/标定变更需重启会话</span>
          </div>
          <button
            onClick={discard}
            className="h-7 px-3 rounded border border-line bg-bg text-fg text-[12px] hover:bg-surface2 active:-translate-y-px"
          >
            放弃
          </button>
          <button
            onClick={save}
            disabled={busy}
            className="h-7 px-3 rounded border border-accent bg-accent text-accent-fg text-[12px] font-medium hover:opacity-90 active:-translate-y-px disabled:opacity-50"
          >
            {busy ? "保存中" : "保存"}
          </button>
        </div>
      )}
    </div>
  );
}

function ModelRow({ role, name, meta, onTest }: { role: "vision" | "solver"; name: string; meta: string; onTest: () => void }) {
  const isVision = role === "vision";
  return (
    <div className="grid grid-cols-[auto_1fr_auto_auto] gap-2.5 items-center p-2.5 bg-surface1 border border-line rounded">
      <div className="w-7 h-7 rounded grid place-items-center font-mono text-[11px] font-semibold text-accent bg-accent-dim border border-accent/30">
        {isVision ? "视" : "答"}
      </div>
      <div>
        <div className="text-[13px] font-medium">{name}</div>
        <div className="font-mono text-[11px] text-dim">{meta}</div>
      </div>
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-accent-dim text-accent font-mono text-[10px] font-semibold tracking-wider rounded-sm">
        已启用
      </span>
      <button onClick={onTest} className="h-7 px-2.5 rounded border border-line bg-bg text-fg text-[12px] hover:bg-surface2 active:-translate-y-px">测试</button>
    </div>
  );
}

function SliderField({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div className="mb-3.5 last:mb-0">
      <div className="text-[12px] text-fg font-medium mb-1.5">{label}</div>
      <div className="grid grid-cols-[1fr_48px] gap-3 items-center">
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="w-full h-0.5 bg-line rounded-sm outline-none appearance-none cursor-pointer accent-accent"
        />
        <span className="font-mono text-[12px] text-accent text-right font-medium">{value.toFixed(2)}</span>
      </div>
    </div>
  );
}

function InputField({ label, value, onChange, suffix, mono = true }: { label: string; value: number; onChange: (v: number) => void; suffix?: string; mono?: boolean }) {
  return (
    <div className="mb-3.5 last:mb-0">
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="text-[12px] text-fg font-medium">{label}</span>
        {suffix && <span className="font-mono text-[11px] text-dim">{suffix}</span>}
      </div>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        className={`w-full h-8 px-2.5 ${mono ? "font-mono" : ""} text-[12px] bg-surface1 text-fg border border-line rounded focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent-dim`}
      />
    </div>
  );
}

function ReadOnlyField({ label, sub }: { label: string; sub: string }) {
  return (
    <div className="flex items-center justify-between py-2 border-t border-line first:border-t-0">
      <div>
        <div className="text-[12.5px] text-fg">{label}</div>
        <div className="font-mono text-[11px] text-dim mt-0.5">{sub}</div>
      </div>
      <span className="inline-flex items-center px-1.5 py-0.5 bg-warn/15 text-warn font-mono text-[10px] font-semibold tracking-wider rounded-sm">
        LOCKED
      </span>
    </div>
  );
}

function ToggleField({ label, sub, on, onToggle }: { label: string; sub: string; on: boolean; onToggle: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between py-2 border-t border-line first:border-t-0">
      <div>
        <div className="text-[12.5px] text-fg">{label}</div>
        <div className="font-mono text-[11px] text-dim mt-0.5">{sub}</div>
      </div>
      <button
        onClick={() => onToggle(!on)}
        className={`w-[30px] h-4 rounded-full relative transition-colors duration-150 active:-translate-y-px ${on ? "bg-accent" : "bg-surface3"}`}
      >
        <span
          className={`absolute top-0.5 w-3 h-3 rounded-full bg-accent-fg transition-transform duration-150 ${on ? "translate-x-[14px]" : "translate-x-0.5"}`}
        />
      </button>
    </div>
  );
}
