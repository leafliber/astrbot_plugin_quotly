const bridge = window.AstrBotPluginPage;

const state = {
  records: [],
  total: 0,
  limit: 20,
  offset: 0,
  groupId: null,
  keyword: null,
  selectedRecord: null,
  groups: [],
  dirty: false
};

// ---------- Response unwrapper ----------

function extractData(resp) {
  if (resp == null) throw new Error("服务器无响应");
  if (typeof resp !== "object") return resp;
  if (resp.success === true && "data" in resp) return resp.data;
  if (resp.success === false) throw new Error(resp.error || resp.message || "操作失败");
  return resp;
}

// ---------- Routing ----------

function navigate(hash) {
  location.hash = hash;
}

function switchView(name) {
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  const el = document.getElementById("view-" + name);
  if (el) el.classList.add("active");
}

function onRoute() {
  const hash = location.hash.slice(1);
  if (hash.startsWith("detail/")) {
    const id = parseInt(hash.split("/")[1]);
    if (id) {
      switchView("detail");
      showDetail(id);
      return;
    }
  }
  switchView("records");
}

// ---------- Skeleton helpers ----------

function showRecordsSkeleton() {
  const grid = document.getElementById("records-list");
  let html = "";
  for (let i = 0; i < 6; i++) {
    html += '<div class="skel-card"><div class="skel-thumb"></div><div class="skel-body">'
      + '<div class="skel-line" style="width:80%"></div>'
      + '<div class="skel-line" style="width:55%"></div>'
      + '</div></div>';
  }
  grid.innerHTML = html;
}

function showDetailSkeleton() {
  document.getElementById("detail-body").innerHTML =
    '<div class="skel-detail-row">'
    + '<div class="skel-detail-img"></div>'
    + '<div class="skel-detail-info">'
    + '<div class="skel-line" style="width:60%"></div>'
    + '<div class="skel-line" style="width:90%"></div>'
    + '<div class="skel-line" style="width:75%"></div>'
    + '<div class="skel-line" style="width:40%"></div>'
    + '</div></div>';
  document.getElementById("save-messages-btn").hidden = true;
}

// ---------- API ----------

async function loadStats() {
  try {
    const s = extractData(await bridge.apiGet("stats"));
    document.getElementById("stat-records").textContent = s.total_records + " 条记录";
    document.getElementById("stat-messages").textContent = s.total_messages + " 条消息";
    document.getElementById("stat-groups").textContent = s.total_groups + " 个群组";
  } catch {}
}

async function loadGroups() {
  try {
    const data = extractData(await bridge.apiGet("groups"));
    state.groups = data.groups || [];
    const targets = [
      document.getElementById("group-filter"),
      document.getElementById("upload-group"),
      document.getElementById("import-images-group")
    ];
    state.groups.forEach(g => {
      const text = g.group_id + " (" + g.count + ")";
      targets.forEach(el => {
        const opt = document.createElement("option");
        opt.value = g.group_id;
        opt.textContent = text;
        el.appendChild(opt);
      });
    });
  } catch {}
}

async function loadRecords() {
  showRecordsSkeleton();
  document.getElementById("empty-state").hidden = true;
  try {
    const params = { limit: state.limit, offset: state.offset };
    if (state.groupId) params.group_id = state.groupId;
    const data = extractData(await bridge.apiGet("records", params));
    state.records = data.records || [];
    state.total = data.total || 0;
    renderRecords(state.records);
    renderPagination();
    if (state.records.length === 0 && state.total === 0) {
      document.getElementById("empty-state").hidden = false;
    }
  } catch (e) {
    toast("加载失败: " + e.message);
  }
}

async function searchRecords(keyword) {
  showRecordsSkeleton();
  document.getElementById("empty-state").hidden = true;
  try {
    const params = { keyword, limit: state.limit, offset: state.offset };
    if (state.groupId) params.group_id = state.groupId;
    const data = extractData(await bridge.apiGet("search", params));
    state.records = data.results || [];
    state.total = data.total || 0;
    state.keyword = keyword;
    renderRecords(state.records, keyword);
    renderPagination();
    if (state.records.length === 0) {
      document.getElementById("empty-state").hidden = false;
    }
  } catch (e) {
    toast("搜索失败: " + e.message);
  }
}

// ---------- Render ----------

function renderRecords(records, highlight) {
  const container = document.getElementById("records-list");
  container.innerHTML = "";
  records.forEach(r => {
    const card = document.createElement("div");
    card.className = "record-card";

    const img = document.createElement("img");
    img.className = "record-thumb";
    img.alt = "语录图片";
    if (r.thumbnail) {
      img.src = r.thumbnail;
    } else {
      img.alt = "图片不存在";
    }

    const info = document.createElement("div");
    info.className = "record-info";

    const preview = document.createElement("div");
    preview.className = "record-preview";
    let text = r.preview_content || r.preview_nickname || "无预览";
    if (text.length > 80) text = text.slice(0, 80) + "...";
    preview[highlight ? "innerHTML" : "textContent"] =
      highlight ? escapeAndHighlight(text, highlight) : text;

    const meta = document.createElement("div");
    meta.className = "record-meta";
    const groupStr = r.group_id ? "群 " + r.group_id : "全局";
    const dateStr = r.created_at ? new Date(r.created_at * 1000).toLocaleDateString("zh-CN") : "";
    meta.innerHTML = "<span>" + groupStr + "</span><span>" + dateStr + "</span>";

    info.appendChild(preview);
    info.appendChild(meta);

    const actions = document.createElement("div");
    actions.className = "record-actions";

    const viewBtn = document.createElement("button");
    viewBtn.className = "btn-ghost";
    viewBtn.textContent = "查看";
    viewBtn.onclick = (e) => { e.stopPropagation(); navigate("detail/" + r.id); };

    const delBtn = document.createElement("button");
    delBtn.className = "btn-danger";
    delBtn.textContent = "删除";
    delBtn.onclick = (e) => { e.stopPropagation(); confirmDelete(r.id); };

    actions.appendChild(viewBtn);
    actions.appendChild(delBtn);

    card.appendChild(img);
    card.appendChild(info);
    card.appendChild(actions);
    card.onclick = () => navigate("detail/" + r.id);
    container.appendChild(card);
  });
}

function renderPagination() {
  const el = document.getElementById("pagination");
  const totalPages = Math.max(1, Math.ceil(state.total / state.limit));
  const currentPage = Math.floor(state.offset / state.limit) + 1;
  document.getElementById("page-info").textContent = currentPage + " / " + totalPages + " (共 " + state.total + " 条)";
  document.getElementById("prev-btn").disabled = state.offset <= 0;
  document.getElementById("next-btn").disabled = state.offset + state.limit >= state.total;
  el.hidden = state.total <= 0;
}

function escapeAndHighlight(text, keyword) {
  const escaped = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  if (!keyword) return escaped;
  const words = keyword.split(/\s+/).filter(Boolean).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp("(" + words.join("|") + ")", "gi");
  return escaped.replace(re, "<mark>$1</mark>");
}

// ---------- Detail view ----------

async function showDetail(id) {
  showDetailSkeleton();
  try {
    const record = extractData(await bridge.apiGet("records/detail", { id }));
    state.selectedRecord = record;
    state.dirty = false;

    const body = document.getElementById("detail-body");
    let html = '<div class="detail-layout">';

    // Image
    if (record.image_data) {
      html += '<div class="detail-image-wrap">'
        + '<img id="detail-image" src="' + record.image_data + '" alt="语录图片" />'
        + '</div>';
    }

    // Info
    html += '<div class="detail-info">';
    const groupStr = record.group_id ? "群 " + record.group_id : "全局";
    const dateStr = record.created_at ? new Date(record.created_at * 1000).toLocaleString("zh-CN") : "";
    html += '<p class="detail-meta">ID: ' + record.id + " | " + groupStr + " | " + dateStr + "</p>";

    html += '<div class="messages-editor">';
    (record.messages || []).forEach(msg => {
      const name = msg.card || msg.nickname || "用户" + (msg.user_id || "");
      const time = msg.time_str || "";
      html += '<div class="msg-edit-item">'
        + '<div class="msg-edit-header">' + name + (time ? " " + time : "") + " (seq " + msg.seq + ")</div>"
        + '<label>内容</label>'
        + '<textarea data-seq="' + msg.seq + '" data-field="content">' + (msg.content || "") + '</textarea>'
        + '<label style="margin-top:8px">OCR 文本</label>'
        + '<textarea data-seq="' + msg.seq + '" data-field="ocr_text">' + (msg.ocr_text || "") + '</textarea>'
        + '</div>';
    });
    html += '</div></div></div>';

    body.innerHTML = html;

    // Dirty tracking
    body.querySelectorAll("textarea").forEach(ta => {
      ta.oninput = () => {
        state.dirty = true;
        document.getElementById("save-messages-btn").hidden = false;
      };
    });

    document.getElementById("save-messages-btn").hidden = (record.messages || []).length === 0;

    // Lightbox
    const detailImg = document.getElementById("detail-image");
    if (detailImg) {
      detailImg.onclick = () => showLightbox(detailImg.src);
    }
  } catch (e) {
    document.getElementById("detail-body").innerHTML =
      '<p style="color:var(--text-2);text-align:center;padding:40px">加载失败: ' + e.message + '</p>';
  }
}

async function saveMessages() {
  if (!state.selectedRecord) return;
  const editor = document.querySelector(".messages-editor");
  if (!editor) return;
  const textareas = editor.querySelectorAll("textarea");
  const msgMap = {};
  textareas.forEach(ta => {
    const seq = parseInt(ta.dataset.seq);
    const field = ta.dataset.field;
    if (!msgMap[seq]) msgMap[seq] = { seq };
    msgMap[seq][field] = ta.value;
  });
  try {
    const result = extractData(await bridge.apiPost("records/messages", {
      record_id: state.selectedRecord.id,
      messages: Object.values(msgMap)
    }));
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

// ---------- Delete ----------

let pendingDeleteId = null;

function confirmDelete(id) {
  pendingDeleteId = id;
  document.getElementById("delete-modal").hidden = false;
}

async function doDelete() {
  if (!pendingDeleteId) return;
  try {
    const result = extractData(await bridge.apiPost("records/delete", { id: pendingDeleteId }));
    if (result.success) {
      toast("已删除");
      if (state.selectedRecord && state.selectedRecord.id === pendingDeleteId) {
        navigate("records");
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

// ---------- Upload ----------

async function doUpload() {
  const fileInput = document.getElementById("upload-files");
  const files = fileInput.files;
  if (!files.length) return;

  const groupId = document.getElementById("upload-group").value;
  const enableOcr = document.getElementById("upload-ocr").checked;
  const progressEl = document.getElementById("upload-progress");
  progressEl.hidden = false;

  let success = 0, failed = 0;
  for (let i = 0; i < files.length; i++) {
    progressEl.textContent = "上传中 " + (i + 1) + "/" + files.length + "...";
    try {
      const b64 = await fileToBase64(files[i]);
      const body = { image_data: b64 };
      if (groupId) body.group_id = parseInt(groupId);
      if (enableOcr) body.enable_ocr = true;
      const result = extractData(await bridge.apiPost("upload", body));
      if (result.success) success++;
      else failed++;
    } catch { failed++; }
  }

  progressEl.textContent = "完成: " + success + " 成功" + (failed > 0 ? ", " + failed + " 失败" : "");
  toast("上传完成: " + success + " 成功" + (failed > 0 ? ", " + failed + " 失败" : ""));

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
    reader.onload = () => resolve(reader.result.split(",").pop());
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// ---------- Lightbox ----------

function showLightbox(src) {
  document.getElementById("lightbox-img").src = src;
  document.getElementById("lightbox").hidden = false;
}

function hideLightbox() {
  document.getElementById("lightbox").hidden = true;
}

// ---------- Import ----------

async function doImportZip() {
  const fileInput = document.getElementById("import-zip-file");
  const file = fileInput.files[0];
  if (!file) { toast("请选择备份文件"); return; }

  const progressEl = document.getElementById("import-zip-progress");
  progressEl.hidden = false;
  progressEl.textContent = "导入中...";

  try {
    const result = extractData(await bridge.upload("import/zip", file));
    if (result.success) {
      progressEl.textContent = "完成: " + result.imported + " 导入, " + result.skipped + " 跳过(重复), " + result.errors + " 失败";
      toast("导入完成: " + result.imported + " 条");
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
    progressEl.textContent = "导入中 " + (i + 1) + "/" + files.length + "...";
    try {
      const b64 = await fileToBase64(files[i]);
      const body = { image_data: b64 };
      if (groupId) body.group_id = parseInt(groupId);
      if (enableOcr) body.enable_ocr = true;
      const result = extractData(await bridge.apiPost("upload", body));
      if (result.success) success++;
      else failed++;
    } catch { failed++; }
  }

  progressEl.textContent = "完成: " + success + " 成功" + (failed > 0 ? ", " + failed + " 失败" : "");
  toast("图片导入完成: " + success + " 成功");
  loadRecords();
  loadStats();

  setTimeout(() => {
    document.getElementById("import-modal").hidden = true;
    progressEl.hidden = true;
    fileInput.value = "";
  }, 2000);
}

// ---------- Toast ----------

let toastTimer;
function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3000);
}

// ---------- Event bindings ----------

function bindEvents() {
  // Group filter
  document.getElementById("group-filter").onchange = (e) => {
    state.groupId = e.target.value ? parseInt(e.target.value) : null;
    state.offset = 0;
    state.keyword ? searchRecords(state.keyword) : loadRecords();
  };

  // Search
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

  // Pagination
  document.getElementById("prev-btn").onclick = () => {
    state.offset = Math.max(0, state.offset - state.limit);
    state.keyword ? searchRecords(state.keyword) : loadRecords();
  };

  document.getElementById("next-btn").onclick = () => {
    state.offset += state.limit;
    state.keyword ? searchRecords(state.keyword) : loadRecords();
  };

  // Detail
  document.getElementById("back-btn").onclick = () => navigate("records");
  document.getElementById("save-messages-btn").onclick = saveMessages;

  // Lightbox
  document.getElementById("lightbox").onclick = hideLightbox;

  // Upload modal
  document.getElementById("upload-btn").onclick = () => {
    document.getElementById("upload-modal").hidden = false;
  };
  document.getElementById("upload-cancel").onclick = () => {
    document.getElementById("upload-modal").hidden = true;
  };
  document.getElementById("upload-submit").onclick = doUpload;

  // Delete modal
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

  // Import modal
  document.getElementById("import-btn").onclick = () => {
    document.getElementById("import-modal").hidden = false;
  };

  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.hidden = true);
      btn.classList.add("active");
      document.getElementById(btn.dataset.tab).hidden = false;
    };
  });

  document.getElementById("import-zip-cancel").onclick = () => {
    document.getElementById("import-modal").hidden = true;
  };
  document.getElementById("import-zip-submit").onclick = doImportZip;

  document.getElementById("import-images-cancel").onclick = () => {
    document.getElementById("import-modal").hidden = true;
  };
  document.getElementById("import-images-submit").onclick = doImportImages;

  // Unload warning
  window.addEventListener("beforeunload", (e) => {
    if (state.dirty) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
}

// ---------- Init ----------

async function init() {
  await bridge.ready();
  window.addEventListener("hashchange", onRoute);
  if (!location.hash) location.hash = "#records";
  else onRoute();

  await Promise.all([loadStats(), loadGroups()]);
  await loadRecords();
  bindEvents();
}

init();
