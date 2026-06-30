const pdfFile = document.querySelector("#pdfFile");
const sourceLanguage = document.querySelector("#sourceLanguage");
const targetLanguage = document.querySelector("#targetLanguage");
const provider = document.querySelector("#provider");
const layoutEngine = document.querySelector("#layoutEngine");
const qualityMode = document.querySelector("#qualityMode");
const baseUrl = document.querySelector("#baseUrl");
const model = document.querySelector("#model");
const apiKey = document.querySelector("#apiKey");
const preserveToc = document.querySelector("#preserveToc");
const protectedPages = document.querySelector("#protectedPages");
const knowledgeSource = document.querySelector("#knowledgeSource");
const knowledgeProfile = document.querySelector("#knowledgeProfile");
const knowledgeProfileName = document.querySelector("#knowledgeProfileName");
const glossaryBody = document.querySelector("#glossaryBody");
const addGlossaryRow = document.querySelector("#addGlossaryRow");
const styleRules = document.querySelector("#styleRules");
const doNotTranslate = document.querySelector("#doNotTranslate");
const newKnowledgeProfile = document.querySelector("#newKnowledgeProfile");
const saveKnowledgeProfile = document.querySelector("#saveKnowledgeProfile");
const exportKnowledgeProfile = document.querySelector("#exportKnowledgeProfile");
const importKnowledgeProfile = document.querySelector("#importKnowledgeProfile");
const deleteKnowledgeProfile = document.querySelector("#deleteKnowledgeProfile");
const translateButton = document.querySelector("#translateButton");
const statusLine = document.querySelector("#statusLine");
const sourcePreview = document.querySelector("#sourcePreview");
const translatedPreview = document.querySelector("#translatedPreview");
const sourceMeta = document.querySelector("#sourceMeta");
const translatedMeta = document.querySelector("#translatedMeta");
const downloadLink = document.querySelector("#downloadLink");
const openPreviewLink = document.querySelector("#openPreviewLink");
const refreshJobs = document.querySelector("#refreshJobs");
const jobHistory = document.querySelector("#jobHistory");
const qualityReport = document.querySelector("#qualityReport");
const qualityMeta = document.querySelector("#qualityMeta");

let sourceObjectUrl = null;

[baseUrl, model, apiKey].forEach((input) => {
  input.addEventListener("input", () => {
    if (input.value.trim()) {
      provider.value = "openai_compatible";
    }
  });
});

initializeKnowledgeProfiles();
refreshJobHistory();

refreshJobs.addEventListener("click", refreshJobHistory);

knowledgeProfile.addEventListener("change", () => {
  loadProfileIntoEditor(knowledgeProfile.value);
});

addGlossaryRow.addEventListener("click", () => {
  appendGlossaryRow({ src: "", dst: "", note: "", case_sensitive: false });
});

newKnowledgeProfile.addEventListener("click", () => {
  knowledgeProfileName.value = uniqueProfileName("我的知识库");
  renderGlossary([{ src: "", dst: "", note: "", case_sensitive: false }]);
  styleRules.value = "写清楚你希望这类文档怎么翻译。";
  doNotTranslate.value = "品牌名、产品名、代码、变量、公式、引用";
  setStatus("已创建空白知识库草稿，编辑后点击保存。");
});

saveKnowledgeProfile.addEventListener("click", async () => {
  const name = knowledgeProfileName.value.trim();
  if (!name) {
    setStatus("请输入知识库配置名称。", true);
    return;
  }
  try {
    await fetch(`/api/knowledge/${encodeURIComponent(name)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readEditorProfile(name)),
    }).then(assertOk);
    await refreshKnowledgeProfiles(name);
    setStatus(`知识库“${name}”已保存。`);
  } catch (error) {
    setStatus(error.message || "知识库保存失败。", true);
  }
});

exportKnowledgeProfile.addEventListener("click", () => {
  const name = knowledgeProfileName.value.trim() || knowledgeProfile.value || "translation-knowledge";
  const payload = { ...readEditorProfile(name), exported_at: new Date().toISOString() };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${sanitizeFileName(name)}.knowledge.json`;
  link.click();
  URL.revokeObjectURL(url);
});

importKnowledgeProfile.addEventListener("change", async () => {
  const file = importKnowledgeProfile.files?.[0];
  if (!file) {
    return;
  }
  try {
    const payload = JSON.parse(await file.text());
    payload.name = String(
      payload.name || file.name.replace(/\.knowledge\.json$|\.json$/i, "") || "导入知识库",
    ).trim();
    const saved = await fetch("/api/knowledge/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(assertOk);
    await refreshKnowledgeProfiles(saved.name);
    setStatus(`知识库“${saved.name}”已导入。`);
  } catch (error) {
    setStatus(error.message || "知识库导入失败。", true);
  } finally {
    importKnowledgeProfile.value = "";
  }
});

deleteKnowledgeProfile.addEventListener("click", async () => {
  const name = knowledgeProfile.value;
  if (!name) {
    return;
  }
  try {
    await fetch(`/api/knowledge/${encodeURIComponent(name)}`, { method: "DELETE" }).then(assertOk);
    await refreshKnowledgeProfiles();
    setStatus(`知识库“${name}”已删除。`);
  } catch (error) {
    setStatus(error.message || "知识库删除失败。", true);
  }
});

pdfFile.addEventListener("change", () => {
  const file = pdfFile.files?.[0];
  translatedPreview.removeAttribute("src");
  translatedMeta.textContent = "未生成";
  downloadLink.classList.add("is-disabled");
  downloadLink.href = "#";
  openPreviewLink.classList.add("is-disabled");
  openPreviewLink.href = "#";

  if (sourceObjectUrl) {
    URL.revokeObjectURL(sourceObjectUrl);
    sourceObjectUrl = null;
  }

  if (!file) {
    sourcePreview.removeAttribute("src");
    sourceMeta.textContent = "未选择";
    setStatus("等待上传 PDF。");
    return;
  }

  sourceObjectUrl = URL.createObjectURL(file);
  sourcePreview.src = sourceObjectUrl;
  sourceMeta.textContent = `${file.name} · ${formatBytes(file.size)}`;
  setStatus("PDF 已载入，可以开始翻译。");
});

translateButton.addEventListener("click", async () => {
  const file = pdfFile.files?.[0];
  if (!file) {
    setStatus("请先选择一个 PDF 文件。", true);
    return;
  }

  const formData = new FormData();
  formData.append("file", file);
  formData.append("provider", provider.value);
  formData.append("layout_engine", layoutEngine.value);
  formData.append("quality_mode", qualityMode.value);
  formData.append("source_language", sourceLanguage.value.trim() || "en");
  formData.append("target_language", targetLanguage.value.trim() || "zh");
  formData.append("base_url", baseUrl.value.trim());
  formData.append("model", model.value.trim());
  formData.append("api_key", apiKey.value.trim());
  formData.append("preserve_toc", preserveToc.checked ? "true" : "false");
  formData.append("protected_pages", protectedPages.value.trim());
  formData.append("knowledge_name", knowledgeProfile.value || "");
  formData.append("knowledge_source", knowledgeSource.value || "local");

  translateButton.disabled = true;
  const statusText = provider.value === "mock"
    ? "正在复制 PDF 用于版式预览..."
    : "正在调用 pdf2zh/BabelDOC 翻译并重建 PDF，论文可能需要几分钟...";
  setStatus(statusText);

  try {
    const response = await fetch("/api/translate", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "翻译失败");
    }

    const completedJob = await pollJob(
      data.status_url,
      data.attachment_url || data.download_url,
      data.preview_url || `/api/preview/${data.job_id}`,
      data.source_url || `/api/source/${data.job_id}`,
    );
    await renderQualityReport(completedJob.job_id);
    await refreshJobHistory();
  } catch (error) {
    setStatus(error.message || "翻译失败", true);
  } finally {
    translateButton.disabled = false;
  }
});

async function pollJob(statusUrl, downloadUrl, previewUrl, sourceUrl) {
  while (true) {
    await wait(1600);
    const response = await fetch(`${statusUrl}?t=${Date.now()}`);
    const job = await response.json();

    if (!response.ok) {
      throw new Error(job.detail || "任务状态查询失败");
    }

    if (job.state === "queued") {
      setStatus("任务已排队，等待开始处理...");
      continue;
    }

    if (job.state === "running") {
      setStatus(job.log_tail ? `正在处理...\n${job.log_tail}` : "正在处理 PDF...");
      continue;
    }

    if (job.state === "failed") {
      throw new Error(job.error || "PDF 翻译失败");
    }

    if (job.state === "succeeded") {
      loadJobPreview(job, previewUrl, sourceUrl);
      openPreviewLink.classList.remove("is-disabled");
      const preserved = job.stats.preserved_pages?.length
        ? ` · 保留目录页 ${job.stats.preserved_pages.join(", ")}`
        : "";
      const fallback = job.stats.fallback_pages?.length
        ? ` · 回退修复 ${job.stats.fallback_pages.join(", ")} 页`
        : "";
      const warnings = job.stats.quality_warnings || [];
      const warningText = warnings.length
        ? ` · 质检提示 ${warnings.map((item) => item.page).join(", ")} 页`
        : "";
      const pageBridges = job.stats.page_bridges ? ` · 跨页上下文 ${job.stats.page_bridges} 处` : "";
      const sourceLabels = {
        mcp: "MCP",
        "mcp-fallback-local": "MCP→本地",
        local: "本地",
        legacy: "旧版",
      };
      const knowledge = job.stats.knowledge_base_applied
        ? ` · 知识库[${sourceLabels[job.stats.knowledge_source] || "本地"}]命中 ${job.stats.glossary_hits ?? 0} 术语`
        : "";
      translatedMeta.textContent = `${job.stats.pages} 页 · ${job.stats.engine || "pdf2zh"}${preserved}${fallback}${pageBridges}${knowledge}${warningText}`;
      downloadLink.href = downloadUrl;
      downloadLink.classList.remove("is-disabled");
      if (warnings.length) {
        setStatus(`翻译完成。右侧已生成译文 PDF。\n自动质检发现疑似异常页：${warnings.map((item) => item.page).join(", ")}。`, true);
      } else {
        setStatus("翻译完成。右侧已生成译文 PDF。");
      }
      return job;
    }
  }
}

function loadJobPreview(job, previewUrl, sourceUrl) {
  const previewTarget = previewUrl || job.preview_url || (job.job_id ? `/api/preview/${job.job_id}` : job.download_url);
  const sourceTarget = sourceUrl || job.source_url || (job.job_id ? `/api/source/${job.job_id}` : null);
  const cacheBust = Date.now();
  if (sourceTarget) {
    sourcePreview.src = `${sourceTarget}?t=${cacheBust}`;
    sourceMeta.textContent = job.source_filename || "历史源文 PDF";
  }
  if (previewTarget) {
    const pdfUrl = `${previewTarget}?t=${cacheBust}`;
    translatedPreview.src = pdfUrl;
    openPreviewLink.href = pdfUrl;
    openPreviewLink.classList.remove("is-disabled");
    downloadLink.href = job.attachment_url || job.download_url || previewTarget;
    downloadLink.classList.remove("is-disabled");
  }
}

async function refreshJobHistory() {
  try {
    const response = await fetch(`/api/jobs?t=${Date.now()}`);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "任务历史加载失败");
    }
    renderJobHistory(data.jobs || []);
  } catch (error) {
    jobHistory.innerHTML = `<div class="empty-state">${escapeHtml(error.message || "任务历史加载失败")}</div>`;
  }
}

function renderJobHistory(jobs) {
  if (!jobs.length) {
    jobHistory.innerHTML = `<div class="empty-state">还没有翻译任务。</div>`;
    return;
  }
  jobHistory.innerHTML = "";
  for (const job of jobs) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `job-item state-${job.state || "unknown"}`;
    item.innerHTML = `
      <span class="job-title">${escapeHtml(job.source_filename || job.job_id)}</span>
      <span class="job-subtitle">${escapeHtml(formatJobSubtitle(job))}</span>
    `;
    item.addEventListener("click", async () => {
      const statusResponse = await fetch(`${job.status_url}?t=${Date.now()}`);
      const fullJob = await statusResponse.json();
      loadJobPreview(fullJob, fullJob.preview_url, fullJob.source_url);
      await renderQualityReport(fullJob.job_id);
      setStatus(`已载入历史任务：${fullJob.source_filename || fullJob.job_id}`);
    });
    jobHistory.append(item);
  }
}

function formatJobSubtitle(job) {
  const parts = [
    job.state,
    job.pages ? `${job.pages} 页` : "",
    job.model || "",
    job.quality_warnings_count ? `质检 ${job.quality_warnings_count}` : "",
  ].filter(Boolean);
  return parts.join(" · ");
}

async function renderQualityReport(jobId) {
  if (!jobId) {
    qualityMeta.textContent = "暂无任务";
    qualityReport.innerHTML = "";
    return;
  }
  const response = await fetch(`/api/jobs/${jobId}/report?t=${Date.now()}`);
  const report = await response.json();
  if (!response.ok) {
    throw new Error(report.detail || "质量报告加载失败");
  }
  qualityMeta.textContent = report.source_filename || jobId;
  qualityReport.innerHTML = "";
  for (const check of report.checks || []) {
    const row = document.createElement("div");
    row.className = `quality-check status-${check.status}`;
    row.innerHTML = `
      <span class="check-name">${escapeHtml(check.name)}</span>
      <span class="check-detail">${escapeHtml(check.detail)}</span>
    `;
    qualityReport.append(row);
  }
  if (report.warnings?.length) {
    const warningBlock = document.createElement("div");
    warningBlock.className = "warning-block";
    warningBlock.innerHTML = `<strong>需复查页：</strong>${report.warnings.map((item) => `第 ${item.page} 页`).join("、")}`;
    qualityReport.append(warningBlock);
  }
  if (report.error) {
    const errorBlock = document.createElement("div");
    errorBlock.className = "warning-block is-error";
    errorBlock.textContent = report.error;
    qualityReport.append(errorBlock);
  }
}

let knowledgeNames = [];

async function initializeKnowledgeProfiles() {
  await refreshKnowledgeProfiles();
}

async function assertOk(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "请求失败");
  }
  return data;
}

async function refreshKnowledgeProfiles(preferredName) {
  let profiles = [];
  try {
    const data = await assertOk(await fetch(`/api/knowledge?t=${Date.now()}`));
    profiles = data.profiles || [];
  } catch (error) {
    setStatus(error.message || "知识库加载失败。", true);
  }
  knowledgeNames = profiles.map((item) => item.name);
  knowledgeProfile.innerHTML = "";
  for (const item of profiles) {
    const option = document.createElement("option");
    option.value = item.name;
    option.textContent = `${item.name}（${item.glossary_count || 0} 术语）`;
    knowledgeProfile.append(option);
  }
  const target = knowledgeNames.includes(preferredName) ? preferredName : knowledgeNames[0];
  if (target) {
    knowledgeProfile.value = target;
    await loadProfileIntoEditor(target);
  } else {
    knowledgeProfileName.value = "";
    renderGlossary([]);
    styleRules.value = "";
    doNotTranslate.value = "";
  }
}

async function loadProfileIntoEditor(name) {
  if (!name) {
    return;
  }
  try {
    const profile = await assertOk(await fetch(`/api/knowledge/${encodeURIComponent(name)}?t=${Date.now()}`));
    knowledgeProfileName.value = profile.name || name;
    renderGlossary(profile.glossary || []);
    styleRules.value = (profile.style_rules || []).join("\n");
    doNotTranslate.value = (profile.do_not_translate || []).join("、");
  } catch (error) {
    setStatus(error.message || "知识库读取失败。", true);
  }
}

function renderGlossary(entries) {
  glossaryBody.innerHTML = "";
  if (!entries.length) {
    appendGlossaryRow({ src: "", dst: "", note: "", case_sensitive: false });
    return;
  }
  for (const entry of entries) {
    appendGlossaryRow(entry);
  }
}

function appendGlossaryRow(entry) {
  const row = document.createElement("tr");
  row.innerHTML = `
    <td><input class="g-src" type="text" value="${escapeAttr(entry.src)}" placeholder="source term" /></td>
    <td><input class="g-dst" type="text" value="${escapeAttr(entry.dst)}" placeholder="目标译法" /></td>
    <td><input class="g-note" type="text" value="${escapeAttr(entry.note)}" placeholder="备注（可选）" /></td>
    <td class="cell-center"><input class="g-cs" type="checkbox" ${entry.case_sensitive ? "checked" : ""} /></td>
    <td class="cell-center"><button class="g-del btn btn-ghost btn-sm" type="button" title="删除">✕</button></td>
  `;
  row.querySelector(".g-del").addEventListener("click", () => row.remove());
  glossaryBody.append(row);
}

function readEditorProfile(name) {
  const glossary = [];
  for (const row of glossaryBody.querySelectorAll("tr")) {
    const src = row.querySelector(".g-src").value.trim();
    if (!src) {
      continue;
    }
    glossary.push({
      src,
      dst: row.querySelector(".g-dst").value.trim(),
      note: row.querySelector(".g-note").value.trim(),
      case_sensitive: row.querySelector(".g-cs").checked,
    });
  }
  return {
    name,
    glossary,
    style_rules: styleRules.value.split("\n").map((s) => s.trim()).filter(Boolean),
    do_not_translate: doNotTranslate.value.split(/[、,，\n]/).map((s) => s.trim()).filter(Boolean),
  };
}

function uniqueProfileName(base) {
  let name = base;
  let index = 2;
  while (knowledgeNames.includes(name)) {
    name = `${base} ${index}`;
    index += 1;
  }
  return name;
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function sanitizeFileName(value) {
  return value.replace(/[\\/:*?"<>|]+/g, "-").replace(/\s+/g, "-").slice(0, 80) || "knowledge";
}

function setStatus(message, isError = false) {
  statusLine.textContent = message;
  statusLine.classList.toggle("is-error", isError);
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}


function formatBytes(value) {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

/* ============ 视图导航 ============ */
const viewMeta = {
  workspace: { title: "翻译工作台", hint: "上传 PDF，选择语言与服务商，左右对照预览译文。" },
  knowledge: { title: "知识库", hint: "维护术语、风格与禁译规则，翻译时按优先级注入提示词。" },
  jobs: { title: "任务与质检", hint: "查看历史任务、占位符/乱码扫描与异常页回退情况。" },
  settings: { title: "接入设置", hint: "配置翻译服务商、密钥、版式引擎与质量模式。" },
  help: { title: "帮助", hint: "快速上手与能力路线图。" },
};
const navItems = document.querySelectorAll(".nav-item");
const views = document.querySelectorAll(".view");
const viewTitle = document.querySelector("#viewTitle");
const viewHint = document.querySelector("#viewHint");

function switchView(name) {
  if (!viewMeta[name]) {
    return;
  }
  navItems.forEach((btn) => btn.classList.toggle("is-active", btn.dataset.view === name));
  views.forEach((view) => view.classList.toggle("is-active", view.dataset.panel === name));
  viewTitle.textContent = viewMeta[name].title;
  viewHint.textContent = viewMeta[name].hint;
}

navItems.forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});
document.querySelectorAll("[data-view]:not(.nav-item)").forEach((el) => {
  el.addEventListener("click", (event) => {
    event.preventDefault();
    switchView(el.dataset.view);
  });
});

/* ============ 连接状态指示 ============ */
const connDot = document.querySelector("#connDot");
const connText = document.querySelector("#connText");

function refreshConnState() {
  const isMock = provider.value === "mock";
  const hasKey = Boolean(apiKey.value.trim());
  if (isMock) {
    connDot.classList.remove("is-live");
    connText.textContent = "Mock 版式测试";
  } else if (hasKey) {
    connDot.classList.add("is-live");
    connText.textContent = `${model.value.trim() || "已配置"} · 已连接`;
  } else {
    connDot.classList.remove("is-live");
    connText.textContent = "未配置 API Key";
  }
}

[provider, apiKey, model].forEach((el) => el.addEventListener("input", refreshConnState));
provider.addEventListener("change", refreshConnState);
refreshConnState();
