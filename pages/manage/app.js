const bridge = window.AstrBotPluginPage;

const state = {
  records: [],
  total: 0,
  limit: 20,
  offset: 0,
  groupId: null,
  keyword: null,
  view: "list",
  selectedRecord: null,
  groups: [],
  dirty: false
};

// --- Init ---
async function init() {
  await bridge.ready();
  await loadStats();
  await loadGroups();
  await loadRecords();
  bindEvents();
}

// --- API helpers ---
function imageUrl(id) {
  return `records/image?id=${id}`;
}

async function loadStats() {
  try {
    const s = await bridge.apiGet("stats");
    document.getElementById("stat-records").textContent = `${s.total_records} 条记录`;
    document.getElementById("stat-messages").textContent = `${s.total_messages} 条消息`;
    document.getElementById("stat-groups").textContent = `${s.total_groups} 个群组`;
  } catch {}
}

async function loadGroups() {
  try {
    const data = await bridge.apiGet("groups");
    state.groups = data.groups || [];
    const filterEl = document.getElementById("group-filter");
    const uploadGroupEl = document.getElementById("upload-group");
    const importGroupEl = document.getElementById("import-images-group");
    state.groups.forEach(g => {
      const opt1 = document.createElement("option");
      opt1.value = g.group_id;
      opt1.textContent = `${g.group_id} (${g.count})`;
      filterEl.appendChild(opt1);
      uploadGroupEl.appendChild(opt1.cloneNode(true));
      importGroupEl.appendChild(opt1.cloneNode(true));
    });
  } catch {}
}

async function loadRecords() {
  showLoading(true);
  try {
    const params = { limit: state.limit, offset: state.offset };
    if (state.groupId) params.group_id = state.groupId;
    const data = await bridge.apiGet("records", params);
    state.records = data.records || [];
    state.total = data.total || 0;
    renderRecords(state.records);
    renderPagination();
    showEmpty(state.records.length === 0 && state.total === 0);
  } catch (e) {
    toast("加载失败: " + e.message);
  }
  showLoading(false);
}

async function searchRecords(keyword) {
  showLoading(true);
  try {
    const params = { keyword, limit: state.limit, offset: state.offset };
    if (state.groupId) params.group_id = state.groupId;
    const data = await bridge.apiGet("search", params);
    state.records = data.results || [];
    state.total = data.total || 0;
    state.keyword = keyword;
    renderRecords(state.records, keyword);
    renderPagination();
    showEmpty(state.records.length === 0);
  } catch (e) {
    toast("搜索失败: " + e.message);
  }
  showLoading(false);
}

// --- Render ---
function renderRecords(records, highlight) {
  const container = document.getElementById("records-list");
  container.innerHTML = "";

  records.forEach(r => {
    const card = document.createElement("div");
    card.className = "record-card";

    const img = document.createElement("img");
    img.className = "record-thumb";
    img.loading = "lazy";
    img.alt = "语录图片";
    if (r.image_exists) {
      img.src = imageUrl(r.id);
      img.onerror = () => { img.src = ""; img.alt = "图片加载失败"; };
    } else {
      img.alt = "图片不存在";
      img.style.background = "#e8e8ea";
    }

    const info = document.createElement("div");
    info.className = "record-info";

    const preview = document.createElement("div");
    preview.className = "record-preview";
    let previewText = r.preview_content || r.preview_nickname || "无预览";
    if (previewText.length > 80) previewText = previewText.slice(0, 80) + "...";
    if (highlight) {
      preview.innerHTML = escapeAndHighlight(previewText, highlight);
    } else {
      preview.textContent = previewText;
    }

    const meta = document.createElement("div");
    meta.className = "record-meta";
    const groupStr = r.group_id ? `群 ${r.group_id}` : "全局";
    const dateStr = r.created_at ? new Date(r.created_at * 1000).toLocaleDateString("zh-CN") : "";
    meta.innerHTML = `<span>${groupStr}</span><span>${dateStr}</span>`;

    info.appendChild(preview);
    info.appendChild(meta);

    const actions = document.createElement("div");
    actions.className = "record-actions";
    const viewBtn = document.createElement("button");
    viewBtn.className = "secondary";
    viewBtn.textContent = "查看";
    viewBtn.onclick = (e) => { e.stopPropagation(); showDetail(r.id); };
    const delBtn = document.createElement("button");
    delBtn.className = "danger";
    delBtn.textContent = "删除";
    delBtn.onclick = (e) => { e.stopPropagation(); confirmDelete(r.id); };
    actions.appendChild(viewBtn);
    actions.appendChild(delBtn);

    card.appendChild(img);
    card.appendChild(info);
    card.appendChild(actions);
    card.onclick = () => showDetail(r.id);
    container.appendChild(card);
  });
}

function renderPagination() {
  const el = document.getElementById("pagination");
  const totalPages = Math.max(1, Math.ceil(state.total / state.limit));
  const currentPage = Math.floor(state.offset / state.limit) + 1;
  document.getElementById("page-info").textContent = `${currentPage} / ${totalPages} (共 ${state.total} 条)`;
  document.getElementById("prev-btn").disabled = state.offset <= 0;
  document.getElementById("next-btn").disabled = state.offset + state.limit >= state.total;
  el.hidden = state.total <= 0;
}

function escapeAndHighlight(text, keyword) {
  const escaped = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  if (!keyword) return escaped;
  const words = keyword.split(/\s+/).filter(Boolean).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`(${words.join("|")})`, "gi");
  return escaped.replace(re, "<mark>$1</mark>");
}

// --- Detail view ---
async function showDetail(id) {
  state.view = "detail";
  document.getElementById("records-list").hidden = true;
  document.getElementById("pagination").hidden = true;
  document.getElementById("record-detail").hidden = false;

  try {
    const record = await bridge.apiGet("records/detail", { id });
    state.selectedRecord = record;
    state.dirty = false;

    const img = document.getElementById("detail-image");
    if (record.image_exists) {
      img.src = imageUrl(record.id);
      img.hidden = false;
      document.getElementById("detail-image-wrap").hidden = false;
    } else {
      img.hidden = true;
      document.getElementById("detail-image-wrap").hidden = true;
    }

    const groupStr = record.group_id ? `群 ${record.group_id}` : "全局";
    const dateStr = record.created_at ? new Date(record.created_at * 1000).toLocaleString("zh-CN") : "";
    document.getElementById("detail-meta").textContent = `ID: ${record.id} | ${groupStr} | ${dateStr}`;

    const editor = document.getElementById("messages-editor");
    editor.innerHTML = "";

    (record.messages || []).forEach(msg => {
      const item = document.createElement("div");
      item.className = "msg-edit-item";

      const header = document.createElement("div");
      header.className = "msg-edit-header";
      const name = msg.card || msg.nickname || `用户${msg.user_id || ""}`;
      const time = msg.time_str || "";
      header.textContent = `${name}${time ? " " + time : ""} (seq ${msg.seq})`;
      item.appendChild(header);

      const contentLabel = document.createElement("label");
      contentLabel.textContent = "内容";
      item.appendChild(contentLabel);
      const contentTa = document.createElement("textarea");
      contentTa.value = msg.content || "";
      contentTa.dataset.seq = msg.seq;
      contentTa.dataset.field = "content";
      contentTa.oninput = () => { state.dirty = true; };
      item.appendChild(contentTa);

      const ocrLabel = document.createElement("label");
      ocrLabel.textContent = "OCR 文本";
      ocrLabel.style.marginTop = "8px";
      item.appendChild(ocrLabel);
      const ocrTa = document.createElement("textarea");
      ocrTa.value = msg.ocr_text || "";
      ocrTa.dataset.seq = msg.seq;
      ocrTa.dataset.field = "ocr_text";
      ocrTa.oninput = () => { state.dirty = true; };
      item.appendChild(ocrTa);

      editor.appendChild(item);
    });

    document.getElementById("save-messages-btn").hidden = (record.messages || []).length === 0;
  } catch (e) {
    toast("加载详情失败: " + e.message);
  }
}

function hideDetail() {
  state.view = "list";
  state.selectedRecord = null;
  state.dirty = false;
  document.getElementById("record-detail").hidden = true;
  document.getElementById("records-list").hidden = false;
  document.getElementById("pagination").hidden = false;
}

async function saveMessages() {
  if (!state.selectedRecord) return;
  const editor = document.getElementById("messages-editor");
  const textareas = editor.querySelectorAll("textarea");
  const msgMap = {};
  textareas.forEach(ta => {
    const seq = parseInt(ta.dataset.seq);
    const field = ta.dataset.field;
    if (!msgMap[seq]) msgMap[seq] = { seq };
    msgMap[seq][field] = ta.value;
  });
  const messages = Object.values(msgMap);

  try {
    const result = await bridge.apiPost("records/messages", {
      record_id: state.selectedRecord.id,
      messages
    });
    if (result.success) {
      toast("保存成功");
      state.dirty = false;
    } else {
      toast("保存失败");
    }
  } catch (e) {
    toast("保存失败: " + e.message);
  }
}

// --- Delete ---
let pendingDeleteId = null;
function confirmDelete(id) {
  pendingDeleteId = id;
  document.getElementById("delete-modal").hidden = false;
}

async function doDelete() {
  if (!pendingDeleteId) return;
  try {
    const result = await bridge.apiPost("records/delete", { id: pendingDeleteId });
    if (result.success) {
      toast("已删除");
      if (state.view === "detail" && state.selectedRecord && state.selectedRecord.id === pendingDeleteId) {
        hideDetail();
      }
      loadRecords();
      loadStats();
    }
  } catch (e) {
    toast("删除失败: " + e.message);
  }
  pendingDeleteId = null;
  document.getElementById("delete-modal").hidden = true;
}

// --- Upload ---
async function doUpload() {
  const fileInput = document.getElementById("upload-files");
  const files = fileInput.files;
  if (!files.length) return;

  const groupId = document.getElementById("upload-group").value;
  const enableOcr = document.getElementById("upload-ocr").checked;
  const progressEl = document.getElementById("upload-progress");
  progressEl.hidden = false;

  let success = 0;
  let failed = 0;

  for (let i = 0; i < files.length; i++) {
    progressEl.textContent = `上传中 ${i + 1}/${files.length}...`;
    try {
      const b64 = await fileToBase64(files[i]);
      const body = { image_data: b64 };
      if (groupId) body.group_id = parseInt(groupId);
      if (enableOcr) body.enable_ocr = true;

      const result = await bridge.apiPost("upload", body);
      if (result.success) {
        success++;
      } else {
        failed++;
      }
    } catch {
      failed++;
    }
  }

  progressEl.textContent = `完成: ${success} 成功${failed > 0 ? `, ${failed} 失败` : ""}`;
  toast(`上传完成: ${success} 成功${failed > 0 ? `, ${failed} 失败` : ""}`);

  setTimeout(() => {
    document.getElementById("upload-modal").hidden = true;
    progressEl.hidden = true;
    fileInput.value = "";
    loadRecords();
    loadStats();
  }, 1500);
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result;
      resolve(dataUrl.split(",").pop());
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// --- Lightbox ---
function showLightbox(src) {
  const lb = document.getElementById("lightbox");
  document.getElementById("lightbox-img").src = src;
  lb.hidden = false;
}

function hideLightbox() {
  document.getElementById("lightbox").hidden = true;
}

// --- Helpers ---
function showLoading(show) {
  document.getElementById("loading").hidden = !show;
}

function showEmpty(show) {
  document.getElementById("empty-state").hidden = !show;
}

let toastTimer;
function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3000);
}

// --- Event bindings ---
function bindEvents() {
  document.getElementById("group-filter").onchange = (e) => {
    state.groupId = e.target.value ? parseInt(e.target.value) : null;
    state.offset = 0;
    if (state.keyword) {
      searchRecords(state.keyword);
    } else {
      loadRecords();
    }
  };

  document.getElementById("search-btn").onclick = () => {
    const kw = document.getElementById("search-input").value.trim();
    if (!kw) return;
    state.offset = 0;
    searchRecords(kw);
    document.getElementById("clear-search-btn").hidden = false;
  };

  document.getElementById("search-input").onkeydown = (e) => {
    if (e.key === "Enter") document.getElementById("search-btn").click();
  };

  document.getElementById("clear-search-btn").onclick = () => {
    state.keyword = null;
    state.offset = 0;
    document.getElementById("search-input").value = "";
    document.getElementById("clear-search-btn").hidden = true;
    loadRecords();
  };

  document.getElementById("prev-btn").onclick = () => {
    state.offset = Math.max(0, state.offset - state.limit);
    if (state.keyword) searchRecords(state.keyword);
    else loadRecords();
  };

  document.getElementById("next-btn").onclick = () => {
    state.offset += state.limit;
    if (state.keyword) searchRecords(state.keyword);
    else loadRecords();
  };

  document.getElementById("back-btn").onclick = hideDetail;
  document.getElementById("save-messages-btn").onclick = saveMessages;

  document.getElementById("detail-image").onclick = (e) => {
    showLightbox(e.target.src);
  };

  document.getElementById("lightbox").onclick = hideLightbox;

  document.getElementById("upload-btn").onclick = () => {
    document.getElementById("upload-modal").hidden = false;
  };

  document.getElementById("upload-cancel").onclick = () => {
    document.getElementById("upload-modal").hidden = true;
  };

  document.getElementById("upload-submit").onclick = doUpload;

  document.getElementById("delete-cancel").onclick = () => {
    pendingDeleteId = null;
    document.getElementById("delete-modal").hidden = true;
  };

  document.getElementById("delete-confirm").onclick = doDelete;

  // Export
  document.getElementById("export-btn").onclick = async () => {
    toast("正在生成导出文件...");
    try {
      await bridge.download("export", {}, "quotly_export.zip");
      toast("导出文件已下载");
    } catch (e) {
      toast("导出失败: " + e.message);
    }
  };

  // Import modal open
  document.getElementById("import-btn").onclick = () => {
    document.getElementById("import-modal").hidden = false;
  };

  // Import tab switching
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.hidden = true);
      btn.classList.add("active");
      document.getElementById(btn.dataset.tab).hidden = false;
    };
  });

  // Import ZIP
  document.getElementById("import-zip-cancel").onclick = () => {
    document.getElementById("import-modal").hidden = true;
  };

  document.getElementById("import-zip-submit").onclick = doImportZip;

  // Import images
  document.getElementById("import-images-cancel").onclick = () => {
    document.getElementById("import-modal").hidden = true;
  };

  document.getElementById("import-images-submit").onclick = doImportImages;
}

// --- Import ZIP ---
async function doImportZip() {
  const fileInput = document.getElementById("import-zip-file");
  const file = fileInput.files[0];
  if (!file) { toast("请选择备份文件"); return; }

  const progressEl = document.getElementById("import-zip-progress");
  progressEl.hidden = false;
  progressEl.textContent = "导入中...";

  try {
    const result = await bridge.upload("import/zip", file);
    if (result.success) {
      progressEl.textContent = `完成: ${result.imported} 导入, ${result.skipped} 跳过(重复), ${result.errors} 失败`;
      toast(`导入完成: ${result.imported} 条`);
      loadRecords();
      loadStats();
    } else {
      progressEl.textContent = "失败: " + (result.error || "未知错误");
    }
  } catch (e) {
    progressEl.textContent = "导入失败: " + e.message;
  }

  setTimeout(() => {
    document.getElementById("import-modal").hidden = true;
    progressEl.hidden = true;
    fileInput.value = "";
  }, 2000);
}

// --- Import images ---
async function doImportImages() {
  const fileInput = document.getElementById("import-images-files");
  const files = fileInput.files;
  if (!files.length) { toast("请选择图片"); return; }

  const groupId = document.getElementById("import-images-group").value;
  const enableOcr = document.getElementById("import-images-ocr").checked;
  const progressEl = document.getElementById("import-images-progress");
  progressEl.hidden = false;

  let success = 0, failed = 0;
  for (let i = 0; i < files.length; i++) {
    progressEl.textContent = `导入中 ${i + 1}/${files.length}...`;
    try {
      const b64 = await fileToBase64(files[i]);
      const body = { image_data: b64 };
      if (groupId) body.group_id = parseInt(groupId);
      if (enableOcr) body.enable_ocr = true;
      const result = await bridge.apiPost("upload", body);
      if (result.success) success++;
      else failed++;
    } catch { failed++; }
  }

  progressEl.textContent = `完成: ${success} 成功${failed > 0 ? `, ${failed} 失败` : ""}`;
  toast(`图片导入完成: ${success} 成功`);
  loadRecords();
  loadStats();

  setTimeout(() => {
    document.getElementById("import-modal").hidden = true;
    progressEl.hidden = true;
    fileInput.value = "";
  }, 2000);
}

// --- Start ---
init();
