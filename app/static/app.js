const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const KIND = {
  thesis: { label: "核心主张" },
  claim: { label: "分论点" },
  evidence: { label: "论据" },
  assumption: { label: "隐含假设" },
  counter: { label: "反方观点" },
  question: { label: "追问" },
  fallacy: { label: "逻辑谬误" },
};

const FILTERABLE = ["evidence", "assumption", "counter", "question", "fallacy"];

const QUICK_PROMPTS = {
  thesis: ["这个主张是否过于宽泛？", "它成立需要哪些前提？"],
  claim: ["这个分论点最薄弱的环节是什么？", "有没有反例可以检验它？"],
  evidence: ["这条论据能代表整体吗？", "它还有没有别的解释？"],
  assumption: ["这个假设一定成立吗？", "如果它不成立，结论会怎样？"],
  counter: ["这个反驳本身站得住脚吗？", "作者可以如何回应？"],
  question: ["这个问题为什么关键？", "可以从哪里寻找答案？"],
  fallacy: ["这里具体犯了哪种谬误？", "如何改写才更严谨？"],
};

const state = {
  analysis: null,
  analysisId: null,
  createdAt: null,
  sourceText: "",
  chats: {},
  activeNode: null,
  hiddenKinds: new Set(),
  history: [],
  examples: [],
  health: null,
  minChars: 30,
  busy: false,
  chatBusy: false,
  analyzeController: null,
  chatController: null,
  edgeTimer: null,
  toastTimer: null,
};

const els = {
  composerView: $("#composerView"),
  loadingView: $("#loadingView"),
  mapView: $("#mapView"),
  sourceInput: $("#sourceInput"),
  charCount: $("#charCount"),
  analyzeBtn: $("#analyzeBtn"),
  examples: $("#examples"),
  historyList: $("#historyList"),
  historyCount: $("#historyCount"),
  modeBadge: $("#modeBadge"),
  modeText: $("#modeText"),
  newBtn: $("#newBtn"),
  aboutBtn: $("#aboutBtn"),
  aboutDialog: $("#aboutDialog"),
  cancelAnalyze: $("#cancelAnalyze"),
  backBtn: $("#backBtn"),
  exportBtn: $("#exportBtn"),
  deleteBtn: $("#deleteBtn"),
  mapTitle: $("#mapTitle"),
  mapSummary: $("#mapSummary"),
  mapMeta: $("#mapMeta"),
  stanceBadge: $("#stanceBadge"),
  filters: $("#filters"),
  mapScroll: $("#mapScroll"),
  mapBoard: $("#mapBoard"),
  edges: $("#edges"),
  thesisCard: $("#thesisCard"),
  claimStack: $("#claimStack"),
  supportStack: $("#supportStack"),
  counterStack: $("#counterStack"),
  verdictText: $("#verdictText"),
  scrim: $("#scrim"),
  drawer: $("#drawer"),
  drawerKind: $("#drawerKind"),
  drawerClose: $("#drawerClose"),
  drawerText: $("#drawerText"),
  drawerDetail: $("#drawerDetail"),
  drawerQuote: $("#drawerQuote"),
  drawerStrength: $("#drawerStrength"),
  drawerScroll: $("#drawerScroll"),
  quickPrompts: $("#quickPrompts"),
  chatLog: $("#chatLog"),
  chatForm: $("#chatForm"),
  chatInput: $("#chatInput"),
  chatSend: $("#chatSend"),
  toast: $("#toast"),
};

init();

async function init() {
  bindEvents();
  updateCharCount();

  const shortcutKbd = els.analyzeBtn.querySelector("kbd");
  if (shortcutKbd && /Mac|iPhone|iPad/.test(navigator.platform)) {
    shortcutKbd.textContent = "⌘↵";
  }

  await Promise.all([loadHealth(), loadExamples(), loadHistory()]);

  const params = new URLSearchParams(window.location.search);
  if (params.has("demo") && state.examples.length) {
    els.sourceInput.value = state.examples[0].text;
    updateCharCount();
    startAnalysis();
    return;
  }

  const requestedId = params.get("id");
  if (requestedId) {
    await openAnalysis(requestedId);
    const requestedNode = params.get("node");
    if (requestedNode && state.analysis) {
      const target =
        requestedNode === "thesis"
          ? thesisTarget()
          : state.analysis.nodes.find((node) => node.id === requestedNode);
      if (target) openNode(target);
    }
    return;
  }

  if (window.matchMedia("(min-width: 981px)").matches) {
    els.sourceInput.focus();
  }
}

function bindEvents() {
  els.analyzeBtn.addEventListener("click", startAnalysis);
  els.newBtn.addEventListener("click", newAnalysis);
  els.backBtn.addEventListener("click", backToComposer);
  els.cancelAnalyze.addEventListener("click", () => state.analyzeController?.abort());
  els.exportBtn.addEventListener("click", exportMarkdown);
  els.deleteBtn.addEventListener("click", deleteCurrent);
  els.aboutBtn.addEventListener("click", () => els.aboutDialog.showModal());
  els.aboutDialog.addEventListener("click", (event) => {
    if (event.target === els.aboutDialog) els.aboutDialog.close();
  });

  els.sourceInput.addEventListener("input", updateCharCount);
  els.sourceInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      startAnalysis();
    }
  });

  els.thesisCard.addEventListener("click", () => openNode(thesisTarget()));
  els.thesisCard.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openNode(thesisTarget());
    }
  });

  els.drawerClose.addEventListener("click", closeDrawer);
  els.scrim.addEventListener("click", closeDrawer);
  els.chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (state.chatBusy) {
      state.chatController?.abort();
      return;
    }
    const message = els.chatInput.value.trim();
    if (message) sendChat(message);
  });
  els.chatInput.addEventListener("keydown", (event) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.isComposing &&
      event.keyCode !== 229
    ) {
      event.preventDefault();
      if (!state.chatBusy) {
        const message = els.chatInput.value.trim();
        if (message) sendChat(message);
      }
    }
  });

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && els.drawer.classList.contains("is-open")) {
      closeDrawer();
      return;
    }
    const typing =
      event.target instanceof HTMLElement &&
      (["INPUT", "TEXTAREA"].includes(event.target.tagName) ||
        event.target.isContentEditable);
    if (
      event.key.toLowerCase() === "n" &&
      !typing &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.altKey &&
      !els.drawer.classList.contains("is-open") &&
      !els.aboutDialog.open
    ) {
      event.preventDefault();
      newAnalysis();
    }
  });

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => drawEdges(false), 140);
  });

  if (document.fonts?.ready) {
    document.fonts.ready.then(() => {
      if (!els.mapView.hidden) drawEdges(false);
    });
  }
}

/* Data loading ----------------------------------------------------- */

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error("health check failed");
    const data = await response.json();
    state.health = data;
    state.minChars = data.limits?.min_chars ?? 30;
    if (data.limits?.max_chars) els.sourceInput.maxLength = data.limits.max_chars;

    const isMock = data.mode === "mock";
    els.modeBadge.classList.toggle("is-mock", isMock);
    els.modeText.textContent = isMock
      ? "演示模式 · 离线可玩"
      : `${data.provider} · ${data.model}`;
    els.modeBadge.title = isMock
      ? "未检测到 API Key，正在使用本地演示引擎"
      : "已连接真实模型";
    updateCharCount();
  } catch {
    els.modeBadge.classList.add("is-mock");
    els.modeText.textContent = "后端未连接";
    els.modeBadge.title = "无法连接本地服务，请确认 python run.py 正在运行";
  }
}

async function loadExamples() {
  try {
    const response = await fetch("/api/examples");
    if (!response.ok) throw new Error("examples failed");
    const data = await response.json();
    state.examples = data.examples || [];
    $$(".example-chip", els.examples).forEach((chip) => chip.remove());

    for (const example of state.examples) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "example-chip";
      button.title = example.blurb || "";
      const dot = document.createElement("span");
      dot.className = "dot";
      const label = document.createElement("span");
      label.textContent = example.title;
      button.append(dot, label);
      button.addEventListener("click", () => {
        els.sourceInput.value = example.text;
        updateCharCount();
        els.sourceInput.focus();
      });
      els.examples.appendChild(button);
    }
  } catch {
    /* 示例加载失败不影响主流程 */
  }
}

async function loadHistory() {
  try {
    const response = await fetch("/api/analyses");
    if (!response.ok) throw new Error("history failed");
    const data = await response.json();
    state.history = data.items || [];
    renderHistory();
  } catch {
    /* 历史记录是增强功能，失败时保持安静 */
  }
}

/* Composer / analysis ---------------------------------------------- */

function updateCharCount() {
  const length = els.sourceInput.value.trim().length;
  els.charCount.textContent = `${length} 字`;
  els.charCount.classList.toggle(
    "is-warning",
    length > 0 && length < state.minChars
  );
  els.analyzeBtn.disabled = state.busy || length < state.minChars;
  els.analyzeBtn.title =
    length < state.minChars
      ? `至少需要 ${state.minChars} 个字符`
      : "把这段文字拆成论证地图";
}

async function startAnalysis() {
  const text = els.sourceInput.value.trim();
  if (state.busy) return;
  if (text.length < state.minChars) {
    toast(`文本太短了，至少需要 ${state.minChars} 个字符。`);
    return;
  }

  closeDrawer();
  state.busy = true;
  state.sourceText = text;
  updateCharCount();
  els.sourceInput.blur();
  showView("loading");
  resetLoading();

  const controller = new AbortController();
  state.analyzeController = controller;
  let result = null;
  let errorMessage = null;

  try {
    await streamNDJSON(
      "/api/analyze",
      { text },
      (event) => {
        if (event.type === "stage") setLoadingStage(event);
        else if (event.type === "result") result = event;
        else if (event.type === "error") errorMessage = event.message;
      },
      controller.signal
    );
  } catch (error) {
    if (error.name !== "AbortError") {
      errorMessage = error.message || "请求失败，请稍后重试。";
    }
  } finally {
    state.busy = false;
    state.analyzeController = null;
    updateCharCount();
  }

  if (controller.signal.aborted) {
    showView("composer");
    return;
  }
  if (errorMessage) {
    showView("composer");
    toast(errorMessage);
    return;
  }
  if (!result) {
    showView("composer");
    toast("没有得到完整结果，请再试一次。");
    return;
  }

  state.analysis = result.analysis;
  state.analysisId = result.id;
  state.createdAt = result.created_at;
  state.chats = {};
  state.hiddenKinds.clear();
  state.activeNode = null;

  renderMap();
  showView("map");
  els.mapScroll.scrollTop = 0;
  syncUrl();
  await loadHistory();
}

function resetLoading() {
  $$(".load-step", els.loadingView).forEach((step, index) => {
    step.classList.toggle("is-active", index === 0);
    step.classList.remove("is-done");
    const message = step.querySelector(".load-msg");
    if (message?.dataset.default) message.textContent = message.dataset.default;
  });
}

function setLoadingStage(event) {
  const order = ["reading", "mapping", "weaving"];
  const current = order.indexOf(event.stage);
  if (current < 0) return;
  $$(".load-step", els.loadingView).forEach((step) => {
    const index = order.indexOf(step.dataset.stage);
    step.classList.toggle("is-done", index < current);
    step.classList.toggle("is-active", index === current);
    if (index === current) {
      const message = step.querySelector(".load-msg");
      if (message && event.message) message.textContent = event.message;
    }
  });
}

function showView(view) {
  els.composerView.hidden = view !== "composer";
  els.loadingView.hidden = view !== "loading";
  els.mapView.hidden = view !== "map";
  document.body.dataset.view = view;
  if (view !== "map") closeDrawer();
}

function newAnalysis() {
  state.analyzeController?.abort();
  state.analysis = null;
  state.analysisId = null;
  state.createdAt = null;
  state.sourceText = "";
  state.chats = {};
  state.hiddenKinds.clear();
  els.sourceInput.value = "";
  updateCharCount();
  showView("composer");
  renderHistory();
  els.sourceInput.focus();
}

function backToComposer() {
  state.analyzeController?.abort();
  els.sourceInput.value = state.sourceText || "";
  updateCharCount();
  showView("composer");
  els.sourceInput.focus();
}

async function openAnalysis(id) {
  if (state.busy || id === state.analysisId) return;
  try {
    const response = await fetch(`/api/analyses/${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error("找不到这次拆解。");
    const record = await response.json();

    state.analysis = record.analysis;
    state.analysisId = record.id;
    state.createdAt = record.created_at;
    state.sourceText = record.source_text || "";
    state.chats = record.chats || {};
    state.hiddenKinds.clear();
    state.activeNode = null;

    closeDrawer();
    renderMap();
    showView("map");
    els.mapScroll.scrollTop = 0;
    renderHistory();
    syncUrl();
  } catch (error) {
    toast(error.message || "打开失败，请稍后重试。");
  }
}

/* Map rendering ---------------------------------------------------- */

function renderMap() {
  const analysis = state.analysis;
  if (!analysis) return;

  els.mapTitle.textContent = analysis.title || "未命名拆解";
  els.mapSummary.textContent = analysis.summary || "";
  els.verdictText.textContent = analysis.verdict || "";

  const stance = analysis.stance || "不明确";
  els.stanceBadge.textContent = `作者立场 · ${stance}`;
  els.stanceBadge.dataset.stance = stance;

  els.mapMeta.replaceChildren();
  for (const line of [
    `共 ${analysis.nodes.length} 个节点`,
    `生成于 ${fmtDateTime(state.createdAt)}`,
  ]) {
    const span = document.createElement("span");
    span.textContent = line;
    els.mapMeta.appendChild(span);
  }

  renderThesis(analysis);
  renderFilters(analysis.nodes);

  const claims = analysis.nodes.filter((node) => node.kind === "claim");
  const supports = analysis.nodes.filter(
    (node) => node.kind === "evidence" || node.kind === "assumption"
  );
  const counters = analysis.nodes.filter((node) =>
    ["counter", "question", "fallacy"].includes(node.kind)
  );

  renderStack(els.claimStack, claims, "claim");
  renderStack(els.supportStack, supports, "support");
  renderStack(els.counterStack, counters, "counter");

  requestAnimationFrame(() => drawEdges(true));
}

function renderThesis(analysis) {
  els.thesisCard.replaceChildren();

  const label = document.createElement("div");
  label.className = "thesis-label";
  label.textContent = "核心主张 · THESIS";

  const text = document.createElement("p");
  text.className = "thesis-text";
  text.textContent = analysis.thesis;

  const foot = document.createElement("div");
  foot.className = "thesis-foot";
  const stance = document.createElement("span");
  stance.textContent = analysis.stance;
  const hint = document.createElement("span");
  hint.textContent = "单击追问 →";
  foot.append(stance, hint);

  els.thesisCard.append(label, text, foot);
}

function renderStack(container, nodes, group) {
  container.replaceChildren();
  if (!nodes.length) {
    const empty = document.createElement("p");
    empty.className = "col-empty";
    empty.textContent =
      group === "support"
        ? "没有找到明确的论据或假设。没有支撑的主张，往往是悬空的。"
        : "没有找到明显的反驳或追问。这本身也值得警惕：论证可能没有被充分检验。";
    container.appendChild(empty);
    return;
  }

  nodes.forEach((node, index) => {
    container.appendChild(createNodeCard(node, index, group));
  });
}

function createNodeCard(node, index, group) {
  const card = document.createElement("article");
  card.className = `node node-${node.kind}`;
  card.dataset.id = node.id;
  card.dataset.parent = node.parent || "thesis";
  card.dataset.kind = node.kind;
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.setAttribute("aria-label", `追问：${node.text}`);
  card.style.animationDelay = `${Math.min(index, 8) * 38}ms`;

  const head = document.createElement("div");
  head.className = "node-head";

  const kind = document.createElement("span");
  kind.className = "node-kind";
  kind.textContent =
    group === "claim"
      ? `${KIND[node.kind].label} · ${String(index + 1).padStart(2, "0")}`
      : KIND[node.kind].label;

  const strength = document.createElement("span");
  strength.className = "node-strength";
  strength.setAttribute("aria-hidden", "true");
  for (let point = 1; point <= 5; point += 1) {
    const pip = document.createElement("i");
    if (point <= node.strength) pip.className = "on";
    strength.appendChild(pip);
  }
  head.append(kind, strength);

  const text = document.createElement("p");
  text.className = "node-text";
  text.textContent = node.text;

  const foot = document.createElement("div");
  foot.className = "node-foot";

  const parentNode =
    node.parent === "thesis"
      ? null
      : state.analysis?.nodes.find((item) => item.id === node.parent);
  const parent = document.createElement("span");
  parent.className = "node-parent";
  parent.textContent =
    node.parent === "thesis"
      ? "→ 核心主张"
      : `→ ${clip(parentNode?.text || node.parent, 12)}`;
  parent.title = parentNode?.text || node.parent;

  const hint = document.createElement("span");
  hint.className = "node-hint";
  hint.textContent = "追问 →";

  foot.append(parent, hint);
  card.append(head, text, foot);

  card.addEventListener("click", () => openNode(node));
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openNode(node);
    }
  });

  return card;
}

function renderFilters(nodes) {
  els.filters.replaceChildren();
  for (const kind of FILTERABLE) {
    const count = nodes.filter((node) => node.kind === kind).length;
    if (!count) continue;

    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "filter-chip";
    chip.dataset.kind = kind;
    chip.setAttribute(
      "aria-pressed",
      String(!state.hiddenKinds.has(kind))
    );
    if (state.hiddenKinds.has(kind)) chip.classList.add("is-off");

    const swatch = document.createElement("span");
    swatch.className = "swatch";
    const label = document.createElement("span");
    label.textContent = KIND[kind].label;
    const number = document.createElement("span");
    number.className = "count";
    number.textContent = String(count);

    chip.append(swatch, label, number);
    chip.addEventListener("click", () => {
      if (state.hiddenKinds.has(kind)) state.hiddenKinds.delete(kind);
      else state.hiddenKinds.add(kind);
      applyFilters();
    });
    els.filters.appendChild(chip);
  }
}

function applyFilters() {
  $$(".node[data-kind]", els.mapBoard).forEach((card) => {
    card.classList.toggle(
      "is-hidden",
      state.hiddenKinds.has(card.dataset.kind)
    );
  });
  $$(".filter-chip", els.filters).forEach((chip) => {
    const off = state.hiddenKinds.has(chip.dataset.kind);
    chip.classList.toggle("is-off", off);
    chip.setAttribute("aria-pressed", String(!off));
  });
  clearTimeout(state.edgeTimer);
  state.edgeTimer = setTimeout(() => drawEdges(false), 60);
}

/* Edges ------------------------------------------------------------ */

function rectInBoard(element, boardRect) {
  const rect = element.getBoundingClientRect();
  return {
    left: rect.left - boardRect.left,
    top: rect.top - boardRect.top,
    right: rect.right - boardRect.left,
    bottom: rect.bottom - boardRect.top,
    width: rect.width,
    height: rect.height,
    cx: rect.left - boardRect.left + rect.width / 2,
    cy: rect.top - boardRect.top + rect.height / 2,
  };
}

function drawEdges(animate) {
  if (els.mapView.hidden) return;
  const svg = els.edges;
  const board = els.mapBoard;
  const boardRect = board.getBoundingClientRect();
  const width = board.scrollWidth;
  const height = board.scrollHeight;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.replaceChildren();

  const cards = [els.thesisCard, ...$$(".node", board)];
  const byId = new Map(cards.map((card) => [card.dataset.id, card]));
  const NS = "http://www.w3.org/2000/svg";

  for (const card of $$(".node[data-parent]", board)) {
    if (card.classList.contains("is-hidden")) continue;
    const parent = byId.get(card.dataset.parent) || els.thesisCard;
    if (!parent || parent.classList.contains("is-hidden")) continue;

    const a = rectInBoard(parent, boardRect);
    const b = rectInBoard(card, boardRect);
    let startX;
    let startY;
    let endX;
    let endY;
    let pathData;

    const sameColumn = Math.abs(a.cx - b.cx) < Math.min(a.width, b.width) * 0.85;

    if (sameColumn) {
      startX = a.cx;
      startY = a.bottom;
      endX = b.cx;
      endY = b.top;
      const bend = Math.max(18, (endY - startY) * 0.38);
      pathData = `M ${startX} ${startY} C ${startX} ${startY + bend}, ${endX} ${endY - bend}, ${endX} ${endY}`;
    } else if (b.cx < a.cx) {
      startX = a.left;
      startY = a.cy;
      endX = b.right;
      endY = b.cy;
      const bend = Math.max(28, (startX - endX) * 0.42);
      pathData = `M ${startX} ${startY} C ${startX - bend} ${startY}, ${endX + bend} ${endY}, ${endX} ${endY}`;
    } else {
      startX = a.right;
      startY = a.cy;
      endX = b.left;
      endY = b.cy;
      const bend = Math.max(28, (endX - startX) * 0.42);
      pathData = `M ${startX} ${startY} C ${startX + bend} ${startY}, ${endX - bend} ${endY}, ${endX} ${endY}`;
    }

    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", pathData);
    path.setAttribute("class", `edge edge-${card.dataset.kind}`);
    if (animate) {
      path.setAttribute("pathLength", "1");
      path.classList.add("is-animated");
    }
    svg.appendChild(path);

    const dot = document.createElementNS(NS, "circle");
    dot.setAttribute("cx", endX);
    dot.setAttribute("cy", endY);
    dot.setAttribute("r", "2.4");
    dot.setAttribute("class", `edge-dot edge-dot-${card.dataset.kind}`);
    svg.appendChild(dot);
  }
}

/* Drawer & chat ---------------------------------------------------- */

function thesisTarget() {
  return {
    id: "thesis",
    kind: "thesis",
    text: state.analysis?.thesis || "",
    detail: state.analysis?.summary || "",
    quote: "",
    strength: 0,
  };
}

function openNode(node) {
  if (!state.analysis) return;
  if (state.chatController) {
    state.chatController.abort();
    state.chatController = null;
    state.chatBusy = false;
    els.chatSend.textContent = "发送";
    els.chatSend.classList.remove("is-stop");
  }

  state.activeNode = node;
  state.chats[node.id] ||= [];

  const meta = KIND[node.kind] || KIND.claim;
  els.drawerKind.textContent = meta.label;
  els.drawerKind.dataset.kind = node.kind;
  els.drawerText.textContent = node.text;
  els.drawerDetail.textContent = node.detail || "";
  els.drawerQuote.textContent = node.quote ? `“${node.quote}”` : "";
  els.drawerQuote.classList.toggle("is-empty", !node.quote);
  renderStrength(node);
  renderQuickPrompts(node);
  renderChat(node.id);
  highlightCard(node.id);

  els.drawerScroll.scrollTop = 0;
  els.drawer.classList.add("is-open");
  els.drawer.setAttribute("aria-hidden", "false");
  els.scrim.classList.add("is-open");
  document.body.classList.add("no-scroll");
  syncUrl();
}

function closeDrawer() {
  if (state.chatController) {
    state.chatController.abort();
    state.chatController = null;
    state.chatBusy = false;
    els.chatSend.textContent = "发送";
    els.chatSend.classList.remove("is-stop");
  }
  els.drawer.classList.remove("is-open");
  els.drawer.setAttribute("aria-hidden", "true");
  els.scrim.classList.remove("is-open");
  document.body.classList.remove("no-scroll");
  state.activeNode = null;
  $$(".is-active", els.mapBoard).forEach((element) =>
    element.classList.remove("is-active")
  );
  syncUrl();
}

function highlightCard(id) {
  for (const card of [els.thesisCard, ...$$(".node", els.mapBoard)]) {
    card.classList.toggle("is-active", card.dataset.id === id);
  }
}

function renderStrength(node) {
  els.drawerStrength.replaceChildren();
  if (node.kind === "thesis") {
    els.drawerStrength.hidden = true;
    return;
  }
  els.drawerStrength.hidden = false;

  const label = document.createElement("span");
  label.textContent = "论证强度";
  const bars = document.createElement("div");
  bars.className = "strength-bars";
  for (let point = 1; point <= 5; point += 1) {
    const bar = document.createElement("i");
    if (point <= node.strength) bar.className = "on";
    bars.appendChild(bar);
  }
  const value = document.createElement("span");
  value.textContent = `${node.strength} / 5`;
  els.drawerStrength.append(label, bars, value);
}

function renderQuickPrompts(node) {
  els.quickPrompts.replaceChildren();
  const prompts = QUICK_PROMPTS[node.kind] || QUICK_PROMPTS.claim;
  for (const prompt of prompts) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "quick-prompt";
    button.textContent = prompt;
    button.addEventListener("click", () => {
      if (!state.chatBusy) sendChat(prompt);
    });
    els.quickPrompts.appendChild(button);
  }
}

function renderChat(nodeId) {
  els.chatLog.replaceChildren();
  const messages = state.chats[nodeId] || [];
  if (!messages.length) {
    const empty = document.createElement("div");
    empty.className = "chat-empty";
    empty.textContent =
      "选一个角度，向 AI 追问这个节点。它的回答会围绕当前节点，而不是泛泛复述全文。";
    els.chatLog.appendChild(empty);
    return;
  }
  for (const message of messages) {
    appendChatBubble(message.role, message.content);
  }
}

function appendChatBubble(role, content) {
  const bubble = document.createElement("div");
  bubble.className = `chat-msg ${role}`;
  if (role === "assistant") setRichText(bubble, content);
  else bubble.textContent = content;
  els.chatLog.appendChild(bubble);
  return bubble;
}

function setRichText(element, text) {
  element.replaceChildren();
  const pattern = /\*\*([^*]+)\*\*/g;
  let cursor = 0;
  let match = pattern.exec(text);
  while (match) {
    if (match.index > cursor) {
      element.appendChild(
        document.createTextNode(text.slice(cursor, match.index))
      );
    }
    const strong = document.createElement("strong");
    strong.textContent = match[1];
    element.appendChild(strong);
    cursor = pattern.lastIndex;
    match = pattern.exec(text);
  }
  if (cursor < text.length) {
    element.appendChild(document.createTextNode(text.slice(cursor)));
  }
}

async function sendChat(message) {
  if (!state.analysisId || !state.activeNode || state.chatBusy) return;
  const target = state.activeNode;
  const log = (state.chats[target.id] ||= []);
  const history = log.slice(-12).map(({ role, content }) => ({ role, content }));

  $$(".chat-empty", els.chatLog).forEach((element) => element.remove());
  log.push({ role: "user", content: message });
  appendChatBubble("user", message);
  els.chatInput.value = "";

  state.chatBusy = true;
  els.chatSend.textContent = "停止";
  els.chatSend.classList.add("is-stop");
  const bubble = appendChatBubble("assistant", "");
  bubble.classList.add("is-streaming");
  scrollChat(true);

  const controller = new AbortController();
  state.chatController = controller;
  let answer = "";
  let errorMessage = null;

  try {
    await streamNDJSON(
      "/api/challenge",
      {
        analysis_id: state.analysisId,
        node_id: target.id,
        message,
        history,
      },
      (event) => {
        if (event.type === "delta") {
          answer += event.text;
          setRichText(bubble, answer);
          scrollChat(false);
        } else if (event.type === "error") {
          errorMessage = event.message;
        }
      },
      controller.signal
    );
  } catch (error) {
    if (error.name !== "AbortError") {
      errorMessage = error.message || "追问失败，请稍后重试。";
    }
  }

  if (answer.trim()) {
    log.push({ role: "assistant", content: answer.trim() });
    bubble.classList.remove("is-streaming");
  } else {
    bubble.remove();
  }

  state.chatBusy = false;
  state.chatController = null;
  els.chatSend.textContent = "发送";
  els.chatSend.classList.remove("is-stop");
  if (errorMessage) toast(errorMessage);
}

function scrollChat(force) {
  const element = els.drawerScroll;
  const nearBottom =
    element.scrollHeight - element.scrollTop - element.clientHeight < 180;
  if (force || nearBottom) {
    element.scrollTop = element.scrollHeight;
  }
}

/* History ---------------------------------------------------------- */

function renderHistory() {
  els.historyList.replaceChildren();
  els.historyCount.textContent = state.history.length
    ? String(state.history.length).padStart(2, "0")
    : "";

  if (!state.history.length) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = "还没有拆解记录。\n从一段你不太确定的文字开始吧。";
    els.historyList.appendChild(empty);
    return;
  }

  for (const item of state.history) {
    const button = document.createElement("button");
    button.type = "button";
    button.className =
      "history-item" + (item.id === state.analysisId ? " is-active" : "");

    const title = document.createElement("span");
    title.className = "history-title";
    title.textContent = item.title;

    const meta = document.createElement("span");
    meta.className = "history-meta";
    const dot = document.createElement("i");
    dot.className = "stance-dot";
    dot.dataset.stance = item.stance;
    const text = document.createElement("span");
    text.textContent = `${fmtDate(item.created_at)} · ${item.node_count} 节点`;
    meta.append(dot, text);

    button.append(title, meta);
    button.addEventListener("click", () => openAnalysis(item.id));
    els.historyList.appendChild(button);
  }
}

/* Export / delete -------------------------------------------------- */

function exportMarkdown() {
  if (!state.analysis) return;
  const analysis = state.analysis;
  const lines = [
    `# ${analysis.title}`,
    "",
    `> ${analysis.thesis}`,
    "",
    `**作者立场**：${analysis.stance}`,
    "",
    analysis.summary,
    "",
    "## 分论点与支撑",
    "",
  ];

  const claims = analysis.nodes.filter((node) => node.kind === "claim");
  claims.forEach((claim, index) => {
    lines.push(`### ${index + 1}. ${claim.text}`, "");
    if (claim.detail) lines.push(claim.detail, "");
    if (claim.quote) lines.push(`> 原文：“${claim.quote}”`, "");
    const children = analysis.nodes.filter(
      (node) =>
        node.parent === claim.id &&
        ["evidence", "assumption", "counter", "question", "fallacy"].includes(
          node.kind
        )
    );
    for (const child of children) {
      lines.push(
        `- **${KIND[child.kind].label}**：${child.text}${
          child.detail ? ` —— ${child.detail}` : ""
        }`
      );
    }
    lines.push("");
  });

  const globals = analysis.nodes.filter(
    (node) => node.parent === "thesis" && node.kind !== "claim"
  );
  if (globals.length) {
    lines.push("## 针对核心主张", "");
    for (const node of globals) {
      lines.push(
        `- **${KIND[node.kind].label}**：${node.text}${
          node.detail ? ` —— ${node.detail}` : ""
        }`
      );
    }
    lines.push("");
  }

  lines.push(
    "## 总评",
    "",
    analysis.verdict,
    "",
    "---",
    `由「论点地图 · Argument Atlas」生成于 ${new Date().toLocaleString("zh-CN")}`
  );

  const blob = new Blob([lines.join("\n")], {
    type: "text/markdown;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `论点地图-${safeFilename(analysis.title)}.md`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function deleteCurrent() {
  if (!state.analysisId) return;
  if (!window.confirm("删除这次拆解？相关追问也会一起删除，且无法撤销。")) {
    return;
  }
  try {
    const response = await fetch(
      `/api/analyses/${encodeURIComponent(state.analysisId)}`,
      { method: "DELETE" }
    );
    if (!response.ok) throw new Error("删除失败，请稍后重试。");
    closeDrawer();
    state.analysis = null;
    state.analysisId = null;
    state.createdAt = null;
    state.sourceText = "";
    state.chats = {};
    els.sourceInput.value = "";
    updateCharCount();
    showView("composer");
    await loadHistory();
    toast("已删除。", "ok");
  } catch (error) {
    toast(error.message);
  }
}

/* Utilities -------------------------------------------------------- */

async function streamNDJSON(url, body, onEvent, signal) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    let detail = "";
    try {
      const data = await response.json();
      detail = data.detail || "";
    } catch {
      /* ignore malformed error bodies */
    }
    throw new Error(detail || `请求失败（HTTP ${response.status}）`);
  }
  if (!response.body) throw new Error("当前浏览器不支持流式响应。");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline = buffer.indexOf("\n");
    while (newline >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) onEvent(JSON.parse(line));
      newline = buffer.indexOf("\n");
    }
  }

  buffer += decoder.decode();
  const tail = buffer.trim();
  if (tail) onEvent(JSON.parse(tail));
}

function toast(message, kind = "error") {
  clearTimeout(state.toastTimer);
  els.toast.textContent = message;
  els.toast.classList.remove("error", "ok");
  els.toast.classList.add("is-show", kind);
  state.toastTimer = setTimeout(() => {
    els.toast.classList.remove("is-show");
  }, 4600);
}

function syncUrl() {
  const url = new URL(window.location.href);
  if (state.analysisId && !els.mapView.hidden) {
    url.searchParams.set("id", state.analysisId);
  } else {
    url.searchParams.delete("id");
  }
  if (state.activeNode && els.drawer.classList.contains("is-open")) {
    url.searchParams.set("node", state.activeNode.id);
  } else {
    url.searchParams.delete("node");
  }
  url.searchParams.delete("demo");
  window.history.replaceState(null, "", url);
}

function clip(value, limit) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

function safeFilename(value) {
  return String(value || "未命名").replace(/[\\/:*?"<>|]/g, "-").slice(0, 60);
}

const dateFmt = new Intl.DateTimeFormat("zh-CN", {
  month: "short",
  day: "numeric",
});

const dateTimeFmt = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

function fmtDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : dateFmt.format(date);
}

function fmtDateTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "刚刚" : dateTimeFmt.format(date);
}
