(() => {
  const STAGE_DEFS = [
    { key: "original", label: "原圖" },
    { key: "single_gauss", label: "單高斯" },
    { key: "rectangle", label: "大矩形" },
    { key: "four_gauss", label: "四重高斯" },
    { key: "binary", label: "反轉二值" },
    { key: "overlay", label: "黑線標號" },
  ];

  const state = {
    templates: [],
    paramValues: {},
    imagePath: "",
    imageName: "",
    stageImages: null,
    activeStage: "overlay",
    lastResult: null,
    view: {
      scale: 1,
      tx: 0,
      ty: 0,
      resetOnLoad: true,
      dragging: false,
      lastX: 0,
      lastY: 0,
    },
  };

  const $ = (id) => document.getElementById(id);

  function setStatus(text, kind) {
    $("workspaceStatusMirror").textContent = text;
    const el = $("workspaceStatusIndicator");
    el.className = "status-indicator " + (kind === "busy" ? "is-busy" : kind === "ok" ? "is-ok" : kind === "err" ? "is-err" : "is-neutral");
  }

  function closeMenus() {
    document.querySelectorAll(".toolbar-menu").forEach((m) => { m.hidden = true; });
    document.querySelectorAll(".toolbar-btn").forEach((b) => b.setAttribute("aria-expanded", "false"));
  }

  function showDialog(title, html) {
    $("dialogTitle").textContent = title;
    $("dialogBody").innerHTML = html;
    const layer = $("dialogLayer");
    layer.hidden = false;
    layer.classList.add("is-open");
    layer.setAttribute("aria-hidden", "false");
  }

  function hideDialog() {
    const layer = $("dialogLayer");
    layer.classList.remove("is-open");
    layer.hidden = true;
    layer.setAttribute("aria-hidden", "true");
  }

  function defaultParams() {
    const values = {};
    for (const t of state.templates) {
      values[t.key] = t.default;
    }
    return values;
  }

  function renderParams() {
    const form = $("paramsForm");
    form.innerHTML = "";
    for (const t of state.templates) {
      const wrap = document.createElement("label");
      wrap.className = "field" + (t.type === "boolean" ? " field-bool" : "");
      wrap.title = t.description || "";
      const name = document.createElement("span");
      name.textContent = t.label;
      wrap.appendChild(name);
      const value = state.paramValues[t.key];
      if (t.type === "boolean") {
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = Boolean(value);
        input.addEventListener("change", () => { state.paramValues[t.key] = input.checked; });
        wrap.appendChild(input);
      } else if (t.type === "color") {
        const input = document.createElement("input");
        input.type = "color";
        input.value = String(value || "#e23b3b");
        input.addEventListener("input", () => { state.paramValues[t.key] = input.value; });
        wrap.appendChild(input);
      } else {
        const input = document.createElement("input");
        input.type = t.type === "number" ? "number" : "text";
        if (t.type === "number") input.step = "any";
        input.value = value == null ? "" : value;
        input.addEventListener("input", () => {
          if (t.type === "number") {
            const raw = String(input.value).trim();
            const num = Number(raw);
            state.paramValues[t.key] = raw === "" || Number.isNaN(num) ? t.default : num;
          } else {
            state.paramValues[t.key] = input.value;
          }
        });
        wrap.appendChild(input);
      }
      form.appendChild(wrap);
    }
  }

  function renderStageTabs() {
    const tabs = $("stageTabs");
    tabs.innerHTML = "";
    for (const st of STAGE_DEFS) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = st.label;
      btn.className = st.key === state.activeStage ? "is-active" : "";
      btn.addEventListener("click", () => {
        state.activeStage = st.key;
        renderStageTabs();
        renderPreview();
      });
      tabs.appendChild(btn);
    }
  }

  function fmtDirCounts(obj) {
    return `左上 ${obj?.tl ?? 0}／左下 ${obj?.bl ?? 0}／右上 ${obj?.tr ?? 0}／右下 ${obj?.br ?? 0}`;
  }

  function applyView() {
    const img = $("previewImage");
    const label = $("zoomLabel");
    if (label) label.textContent = Math.round(state.view.scale * 100) + "%";
    if (!img) return;
    img.style.transform = `translate(${state.view.tx}px, ${state.view.ty}px) scale(${state.view.scale})`;
  }

  function fitToView() {
    const vp = $("previewViewport");
    const img = $("previewImage");
    if (!vp || !img || !img.naturalWidth) return;
    const pad = 16;
    const vw = Math.max(1, vp.clientWidth - pad);
    const vh = Math.max(1, vp.clientHeight - pad);
    state.view.scale = Math.max(0.05, Math.min(vw / img.naturalWidth, vh / img.naturalHeight));
    state.view.tx = (vp.clientWidth - img.naturalWidth * state.view.scale) / 2;
    state.view.ty = (vp.clientHeight - img.naturalHeight * state.view.scale) / 2;
    applyView();
  }

  function zoomToActual() {
    const vp = $("previewViewport");
    const img = $("previewImage");
    if (!vp || !img || !img.naturalWidth) return;
    state.view.scale = 1;
    state.view.tx = (vp.clientWidth - img.naturalWidth) / 2;
    state.view.ty = (vp.clientHeight - img.naturalHeight) / 2;
    applyView();
  }

  function zoomAt(newScale, cx, cy) {
    const next = Math.min(16, Math.max(0.05, newScale));
    const ix = (cx - state.view.tx) / state.view.scale;
    const iy = (cy - state.view.ty) / state.view.scale;
    state.view.scale = next;
    state.view.tx = cx - ix * next;
    state.view.ty = cy - iy * next;
    applyView();
  }

  function zoomBy(factor) {
    const vp = $("previewViewport");
    if (!vp) return;
    zoomAt(state.view.scale * factor, vp.clientWidth / 2, vp.clientHeight / 2);
  }

  function renderPreview() {
    const box = $("previewBox");
    const label = $("zoomLabel");
    if (!state.stageImages) {
      box.innerHTML = '<p class="preview-placeholder">載入影像並執行處理後，各階段結果會顯示於此。滾輪放大、拖曳平移。</p>';
      if (label) label.textContent = "—";
      return;
    }
    const b64 = state.stageImages[state.activeStage] || state.stageImages.overlay;
    if (!b64) {
      box.innerHTML = '<p class="preview-placeholder">此階段沒有影像。</p>';
      if (label) label.textContent = "—";
      return;
    }
    let img = $("previewImage");
    if (!img) {
      box.innerHTML = "";
      img = document.createElement("img");
      img.id = "previewImage";
      img.alt = "階段預覽";
      img.draggable = false;
      img.addEventListener("load", () => {
        if (state.view.resetOnLoad) {
          fitToView();
          state.view.resetOnLoad = false;
        } else {
          applyView();
        }
      });
      box.appendChild(img);
    }
    img.alt = state.activeStage;
    img.src = "data:image/png;base64," + b64;
  }

  function wirePreviewZoom() {
    const vp = $("previewViewport");
    if (!vp) return;
    vp.addEventListener("wheel", (ev) => {
      if (!$("previewImage")) return;
      ev.preventDefault();
      const rect = vp.getBoundingClientRect();
      const factor = ev.deltaY < 0 ? 1.12 : 1 / 1.12;
      zoomAt(state.view.scale * factor, ev.clientX - rect.left, ev.clientY - rect.top);
    }, { passive: false });
    vp.addEventListener("pointerdown", (ev) => {
      if (!$("previewImage") || ev.button !== 0) return;
      state.view.dragging = true;
      state.view.lastX = ev.clientX;
      state.view.lastY = ev.clientY;
      vp.classList.add("is-dragging");
      vp.setPointerCapture(ev.pointerId);
    });
    vp.addEventListener("pointermove", (ev) => {
      if (!state.view.dragging) return;
      state.view.tx += ev.clientX - state.view.lastX;
      state.view.ty += ev.clientY - state.view.lastY;
      state.view.lastX = ev.clientX;
      state.view.lastY = ev.clientY;
      applyView();
    });
    const stopDrag = (ev) => {
      if (!state.view.dragging) return;
      state.view.dragging = false;
      vp.classList.remove("is-dragging");
      if (vp.hasPointerCapture(ev.pointerId)) vp.releasePointerCapture(ev.pointerId);
    };
    vp.addEventListener("pointerup", stopDrag);
    vp.addEventListener("pointercancel", stopDrag);
    vp.addEventListener("dblclick", (ev) => {
      if (!$("previewImage")) return;
      ev.preventDefault();
      fitToView();
    });
    $("zoomFitBtn").addEventListener("click", fitToView);
    $("zoomOneBtn").addEventListener("click", zoomToActual);
    $("zoomInBtn").addEventListener("click", () => zoomBy(1.2));
    $("zoomOutBtn").addEventListener("click", () => zoomBy(1 / 1.2));
  }

  function fmt(n, digits) {
    if (typeof n !== "number" || Number.isNaN(n)) return "—";
    return n.toFixed(digits);
  }

  function renderMetrics(metrics) {
    const list = $("metricsList");
    if (!metrics) {
      list.innerHTML = "<div><dt>狀態</dt><dd>尚未處理</dd></div>";
      return;
    }
    const rect = metrics.rect || {};
    const mu = (metrics.muPrime || []).map((v) => fmt(v, 3)).join(", ");
    const missing = (metrics.missingRegions || []).join(", ") || "無";
    const warning = escapeHtml(String(metrics.warning || "無"));
    const counts = metrics.lineCounts || metrics.lineCountsPass || {};
    const rows = [
      ["A", fmt(metrics.A, 3)],
      ["r", fmt(metrics.r, 5)],
      ["μ'", escapeHtml(mu)],
      ["T'", fmt(metrics.Tprime, 3)],
      ["矩形", escapeHtml(`${fmt(rect.w, 1)} × ${fmt(rect.h, 1)}`)],
      ["角度", `${fmt(metrics.angle ?? rect.angle, 3)}°`],
      ["長寬比", fmt(metrics.aspect, 3)],
      ["候選數", String(metrics.candidateCount ?? "—")],
      ["邊界分", fmt(metrics.edgeScore, 3)],
      ["中心", `${fmt(metrics.center?.x, 2)}, ${fmt(metrics.center?.y, 2)}`],
      ["裁剪", `${metrics.crop?.w} × ${metrics.crop?.h}`],
      ["黑線數", escapeHtml(fmtDirCounts(counts))],
      ["缺區", escapeHtml(missing)],
      ["警告", warning],
    ];
    list.innerHTML = rows.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
  }

  async function apiGet(url) {
    const res = await fetch(url, { cache: "no-store" });
    return res.json();
  }

  async function apiPost(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return res.json();
  }

  function setImageMeta(name, extra) {
    state.imageName = name;
    $("workspaceImageName").textContent = name || "尚未載入影像";
    $("workspaceImageMeta").textContent = extra || "尚未處理";
    $("imageStatus").textContent = name ? "已載入" : "尚未載入";
  }

  async function uploadFile(file) {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/upload-image", { method: "POST", body: fd });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "上傳失敗");
    state.imagePath = data.path;
    setImageMeta(data.originalName, "已上傳，尚未處理");
    setStatus("已載入影像", "ok");
  }

  async function loadSample() {
    const samples = await apiGet("/api/samples");
    if (!samples.ok || !samples.files?.length) throw new Error("工作區沒有範例影像");
    const preferred = samples.files.find((f) => f.name.indexOf("原始") >= 0) || samples.files[0];
    const data = await apiPost("/api/use-sample", { name: preferred.name });
    if (!data.ok) throw new Error(data.error || "無法載入範例");
    state.imagePath = data.path;
    setImageMeta(data.originalName, "已載入範例，尚未處理");
    setStatus("已載入範例", "ok");
  }

  async function processImage() {
    if (!state.imagePath) {
      setStatus("請先載入影像", "err");
      return;
    }
    $("processBtn").disabled = true;
    setStatus("處理中…", "busy");
    try {
      const data = await apiPost("/api/process", {
        imagePath: state.imagePath,
        paramValues: state.paramValues,
      });
      if (!data.ok) throw new Error(data.error || "處理失敗");
      state.stageImages = data.stageImages;
      state.lastResult = data;
      state.activeStage = "overlay";
      state.view.resetOnLoad = true;
      renderStageTabs();
      renderPreview();
      renderMetrics(data.metrics);
      $("workspaceImageMeta").textContent = data.savedPath || "處理完成";
      const warn = data.metrics?.warning;
      setStatus(warn ? "完成（有警告）" : "完成", warn ? "err" : "ok");
    } catch (err) {
      setStatus(err.message || "處理失敗", "err");
      showDialog("處理失敗", `<p>${escapeHtml(err.message || String(err))}</p>`);
    } finally {
      $("processBtn").disabled = false;
    }
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function downloadOverlay() {
    const b64 = state.stageImages?.overlay;
    if (!b64) {
      setStatus("尚無疊圖可下載", "err");
      return;
    }
    const name = state.lastResult?.filename || "overlay.png";
    const a = document.createElement("a");
    a.href = "data:image/png;base64," + b64;
    a.download = name;
    a.click();
  }

  function exportParams() {
    const blob = new Blob([JSON.stringify(state.paramValues, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "xray_params.json";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function importParamsFile(file) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const data = JSON.parse(String(reader.result || "{}"));
        state.paramValues = { ...defaultParams(), ...data };
        renderParams();
        setStatus("已匯入參數", "ok");
      } catch (err) {
        setStatus("參數 JSON 無效", "err");
      }
    };
    reader.readAsText(file, "utf-8");
  }

  function focusSection(which) {
    const map = { image: "imageBlock", params: "paramsBlock", preview: "previewPanel" };
    const el = $(map[which] || "imageBlock");
    if (!el) return;
    document.querySelectorAll(".ribbon-stages button").forEach((b) => {
      b.classList.toggle("is-active", b.getAttribute("data-workspace-focus") === which);
    });
    el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function wireToolbar() {
    document.querySelectorAll(".toolbar-btn").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const item = btn.parentElement;
        const menu = item.querySelector(".toolbar-menu");
        const open = menu.hidden;
        closeMenus();
        menu.hidden = !open;
        btn.setAttribute("aria-expanded", open ? "true" : "false");
      });
    });
    document.addEventListener("click", closeMenus);
    document.querySelectorAll("[data-action]").forEach((el) => {
      el.addEventListener("click", () => {
        const action = el.getAttribute("data-action");
        closeMenus();
        if (action === "importParams") $("paramFileInput").click();
        if (action === "exportParams") exportParams();
        if (action === "resetParams") {
          state.paramValues = defaultParams();
          renderParams();
          setStatus("已重設參數", "ok");
        }
        if (action === "downloadOverlay") downloadOverlay();
        if (action === "openHelp") {
          showDialog("處理流程", `
            <ol>
              <li>載入單通道灰階 X-ray（多通道只取第一通道）。</li>
              <li>對整張原圖做單高斯 μ=172、σ²=25，不隨 A 縮放、不做色階量化。</li>
              <li>在單高斯結果上找可傾斜的大矩形（最小外接矩形，不限制長寬比）。</li>
              <li>以四邊形外部均值 A 縮放四重高斯 μ 與門檻 T。</li>
              <li>繞矩形中心把原圖旋轉到長邊水平，再裁剪中央 0.5W × 0.5H，只在裁剪後的原圖灰階做四重高斯與反轉二值化。</li>
              <li>左右起點為中心 ± Wc/4。略過起點那一整段黑帶後，向外各取 3 條視覺黑帶（橫向黑比例與至少 3 px 厚，用來略過碎點）。這 3 條全部標綠色。本版不組封閉輪廓。</li>
            </ol>
            <p>預覽：原圖 → 單高斯 → 大矩形（傾斜四邊形）→ 四重高斯 → 反轉二值 → 黑線標號。後三張在旋轉後的圖上。滾輪放大（對準游標）、拖曳平移、雙擊回到適合視窗。切換階段會保留同一視窗。</p>
          `);
        }
        if (action === "openVersion") {
          showDialog("版本資訊", `<p>X-ray 單高斯找矩形 / 四重高斯找黑線 v0.1</p><p>本機 HTTP：127.0.0.1:8767</p><p>每向標 1–3 條視覺黑帶。本版不組封閉膠囊輪廓；面積與焊錫率判定尚未納入。</p>`);
        }
      });
    });
    document.querySelectorAll("[data-workspace-focus]").forEach((el) => {
      el.addEventListener("click", () => focusSection(el.getAttribute("data-workspace-focus")));
    });
  }

  async function boot() {
    try {
      renderStageTabs();
      wireToolbar();
      wirePreviewZoom();
      $("dialogCloseBtn").addEventListener("click", hideDialog);
      $("dialogLayer").addEventListener("click", (ev) => {
        if (ev.target === $("dialogLayer")) hideDialog();
      });
      $("imageFileInput").addEventListener("change", async (ev) => {
        const file = ev.target.files && ev.target.files[0];
        if (!file) return;
        try {
          await uploadFile(file);
        } catch (err) {
          setStatus(err.message, "err");
        }
      });
      $("loadSampleBtn").addEventListener("click", async () => {
        try { await loadSample(); } catch (err) { setStatus(err.message, "err"); }
      });
      $("processBtn").addEventListener("click", processImage);
      $("downloadBtn").addEventListener("click", downloadOverlay);
      $("paramFileInput").addEventListener("change", (ev) => {
        const file = ev.target.files && ev.target.files[0];
        if (file) importParamsFile(file);
        ev.target.value = "";
      });
      document.addEventListener("keydown", (ev) => {
        if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") {
          ev.preventDefault();
          processImage();
        }
      });
    } catch (err) {
      setStatus("介面初始化失敗", "err");
      console.error(err);
    }

    try {
      const health = await apiGet("/api/health");
      if (health.appVersion) $("appVersionBadge").textContent = "v" + health.appVersion;
      const missing = Object.entries(health.packages || {})
        .filter(([, v]) => !v.ok)
        .map(([k]) => k);
      if (missing.length) setStatus("缺少套件：" + missing.join(", "), "err");
      else setStatus("待機", "neutral");
    } catch (err) {
      setStatus("後端未連線", "err");
    }

    try {
      const tpl = await apiGet("/api/param-templates");
      if (!tpl.ok) throw new Error(tpl.error || "參數模板無效");
      state.templates = tpl.templates || [];
      state.paramValues = defaultParams();
      renderParams();
    } catch (err) {
      setStatus("無法載入參數模板", "err");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
