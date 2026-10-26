const bridge = window.AstrBotPluginView;

const els = {
  search: document.getElementById("search"),
  language: document.getElementById("language"),
  refresh: document.getElementById("refresh"),
  status: document.getElementById("status"),
  list: document.getElementById("list"),
  currentVoice: document.getElementById("currentVoice"),
};

const state = {
  voices: [],
  selected: "",
  loading: false,
};

function setStatus(message, isError = false) {
  els.status.textContent = message;
  els.status.classList.toggle("error", isError);
}

function setLoading(loading) {
  state.loading = loading;
  els.refresh.disabled = loading;
  els.refresh.textContent = loading ? "获取中…" : "获取音色";
}

function describe(voice) {
  const bits = [
    voice.language_code,
    voice.gender,
    voice.age,
    voice.accent,
    ...(Array.isArray(voice.tone) ? voice.tone : []),
  ].filter(Boolean);
  return bits.join(" · ");
}

function makeButton(label, className, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

function render() {
  els.list.replaceChildren();

  if (!state.voices.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "没有找到音色。可以换个关键词，或点击“获取音色”重新加载。";
    els.list.append(empty);
    return;
  }

  for (const voice of state.voices) {
    const isSelected = voice.voice_id === state.selected;
    const card = document.createElement("article");
    card.className = `voice${isSelected ? " selected" : ""}`;

    const info = document.createElement("div");
    info.className = "voice-info";

    const title = document.createElement("div");
    title.className = "voice-title";
    const name = document.createElement("strong");
    name.textContent = voice.name || "未命名";
    title.append(name);

    if (isSelected) {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = "当前默认";
      title.append(badge);
    }

    const id = document.createElement("code");
    id.className = "voice-id";
    id.textContent = voice.voice_id || "";

    const meta = document.createElement("span");
    meta.className = "muted voice-meta";
    meta.textContent = describe(voice) || "无更多信息";

    info.append(title, id, meta);

    const action = makeButton(
      isSelected ? "当前默认" : "设为默认",
      isSelected ? "secondary" : "primary",
      () => selectVoice(voice.voice_id),
    );
    action.disabled = isSelected || state.loading;

    card.append(info, action);
    els.list.append(card);
  }
}

async function loadVoices() {
  if (!bridge) {
    setStatus("未检测到 AstrBot Plugin View bridge，请从 AstrBot 插件详情页打开。", true);
    return;
  }
  if (state.loading) {
    return;
  }

  setLoading(true);
  setStatus("正在向 Breeze Blue 获取音色…");
  try {
    const data = await bridge.apiGet("voices", {
      search: els.search.value.trim(),
      language_code: els.language.value,
    });
    state.voices = Array.isArray(data.voices) ? data.voices : [];
    state.selected = data.selected_voice_id || "";
    els.currentVoice.textContent = state.selected || "未设置";
    render();

    const shown = state.voices.length;
    const total = Number.isFinite(Number(data.total)) ? Number(data.total) : shown;
    setStatus(
      total > shown
        ? `共 ${total} 个音色，当前显示前 ${shown} 个；可以输入关键词缩小范围。`
        : `已获取 ${shown} 个音色。`,
    );
  } catch (error) {
    setStatus(`获取失败：${error.message || error}`, true);
  } finally {
    setLoading(false);
  }
}

async function selectVoice(voiceId) {
  if (!bridge || !voiceId || state.loading) {
    return;
  }
  state.loading = true;
  setStatus(`正在保存 ${voiceId}…`);
  try {
    const result = await bridge.apiPost("voices/select", { voice_id: voiceId });
    state.selected = result.voice_id || voiceId;
    els.currentVoice.textContent = state.selected;
    render();
    setStatus(`已将 ${state.selected} 设为全局默认音色。`);
  } catch (error) {
    setStatus(`保存失败：${error.message || error}`, true);
  } finally {
    state.loading = false;
    render();
  }
}

els.refresh.addEventListener("click", loadVoices);
els.search.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    loadVoices();
  }
});
els.language.addEventListener("change", loadVoices);

async function init() {
  if (!bridge) {
    setStatus("未检测到 AstrBot Plugin View bridge，请从 AstrBot 插件详情页打开。", true);
    return;
  }
  await bridge.ready();
  await loadVoices();
}

init();
