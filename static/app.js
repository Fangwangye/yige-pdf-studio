const pdfFile = document.querySelector("#pdfFile");
const sourceLanguage = document.querySelector("#sourceLanguage");
const targetLanguage = document.querySelector("#targetLanguage");
const provider = document.querySelector("#provider");
const layoutEngine = document.querySelector("#layoutEngine");
const baseUrl = document.querySelector("#baseUrl");
const model = document.querySelector("#model");
const apiKey = document.querySelector("#apiKey");
const preserveToc = document.querySelector("#preserveToc");
const protectedPages = document.querySelector("#protectedPages");
const knowledgeProfile = document.querySelector("#knowledgeProfile");
const knowledgeProfileName = document.querySelector("#knowledgeProfileName");
const knowledgeBase = document.querySelector("#knowledgeBase");
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

let sourceObjectUrl = null;
const knowledgeStorageKey = "pdfTranslateKnowledgeProfiles";
const defaultKnowledgeProfiles = {
  "学术论文": knowledgeBase.value,
  "技术文档": `术语：
API = API
SDK = SDK
latency = 延迟
throughput = 吞吐量
deployment = 部署

风格：
使用准确、简洁的技术中文。保留命令、代码、配置项、接口名和错误信息原文。
不要扩写原文没有的操作步骤。`,
  "商务合同": `术语：
party = 一方
agreement = 协议
liability = 责任
confidentiality = 保密
termination = 终止

风格：
使用正式、稳健的法律/商务中文。保持条款编号、金额、日期和主体名称完全一致。
不要弱化义务、限制、免责或条件。`,
};

[baseUrl, model, apiKey].forEach((input) => {
  input.addEventListener("input", () => {
    if (input.value.trim()) {
      provider.value = "openai_compatible";
    }
  });
});

initializeKnowledgeProfiles();

knowledgeProfile.addEventListener("change", () => {
  const profiles = loadKnowledgeProfiles();
  const name = knowledgeProfile.value;
  knowledgeProfileName.value = name;
  knowledgeBase.value = profiles[name] || "";
});

newKnowledgeProfile.addEventListener("click", () => {
  const baseName = "我的知识库";
  const profiles = loadKnowledgeProfiles();
  let name = baseName;
  let index = 2;
  while (profiles[name]) {
    name = `${baseName} ${index}`;
    index += 1;
  }
  knowledgeProfileName.value = name;
  knowledgeBase.value = `术语：
source term = 目标译法

风格：
写清楚你希望这类文档怎么翻译。

禁译：
品牌名、产品名、代码、变量、公式和引用不要擅自翻译。`;
  setStatus("已创建空白知识库草稿，编辑后点击保存。");
});

saveKnowledgeProfile.addEventListener("click", () => {
  const name = knowledgeProfileName.value.trim();
  if (!name) {
    setStatus("请输入知识库配置名称。", true);
    return;
  }
  const profiles = loadKnowledgeProfiles();
  profiles[name] = knowledgeBase.value.trim();
  saveKnowledgeProfiles(profiles);
  renderKnowledgeProfiles(name);
  setStatus(`知识库“${name}”已保存。`);
});

exportKnowledgeProfile.addEventListener("click", () => {
  const name = knowledgeProfileName.value.trim() || knowledgeProfile.value || "translation-knowledge";
  const payload = {
    name,
    content: knowledgeBase.value,
    exported_at: new Date().toISOString(),
    version: 1,
  };
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
    const name = String(payload.name || file.name.replace(/\.knowledge\.json$|\.json$/i, "") || "导入知识库").trim();
    const content = String(payload.content || payload.knowledge_base || "");
    if (!content.trim()) {
      throw new Error("导入文件里没有知识库内容。");
    }
    const profiles = loadKnowledgeProfiles();
    profiles[name] = content;
    saveKnowledgeProfiles(profiles);
    renderKnowledgeProfiles(name);
    setStatus(`知识库“${name}”已导入。`);
  } catch (error) {
    setStatus(error.message || "知识库导入失败。", true);
  } finally {
    importKnowledgeProfile.value = "";
  }
});

deleteKnowledgeProfile.addEventListener("click", () => {
  const name = knowledgeProfile.value;
  const profiles = loadKnowledgeProfiles();
  if (!name || !profiles[name]) {
    return;
  }
  delete profiles[name];
  saveKnowledgeProfiles(profiles);
  const nextName = Object.keys(profiles)[0] || "学术论文";
  if (!Object.keys(profiles).length) {
    saveKnowledgeProfiles({ "学术论文": defaultKnowledgeProfiles["学术论文"] });
  }
  renderKnowledgeProfiles(nextName);
  setStatus(`知识库“${name}”已删除。`);
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
  formData.append("source_language", sourceLanguage.value.trim() || "en");
  formData.append("target_language", targetLanguage.value.trim() || "zh");
  formData.append("base_url", baseUrl.value.trim());
  formData.append("model", model.value.trim());
  formData.append("api_key", apiKey.value.trim());
  formData.append("preserve_toc", preserveToc.checked ? "true" : "false");
  formData.append("protected_pages", protectedPages.value.trim());
  formData.append("knowledge_base", knowledgeBase.value.trim());

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

    await pollJob(
      data.status_url,
      data.attachment_url || data.download_url,
      data.preview_url || `/api/preview/${data.job_id}`,
    );
  } catch (error) {
    setStatus(error.message || "翻译失败", true);
  } finally {
    translateButton.disabled = false;
  }
});

async function pollJob(statusUrl, downloadUrl, previewUrl) {
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
      const previewTarget = previewUrl || job.preview_url || (job.job_id ? `/api/preview/${job.job_id}` : downloadUrl);
      const pdfUrl = `${previewTarget}?t=${Date.now()}`;
      translatedPreview.src = pdfUrl;
      openPreviewLink.href = pdfUrl;
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
      const knowledge = job.stats.knowledge_base_applied ? " · 已用知识库" : "";
      translatedMeta.textContent = `${job.stats.pages} 页 · ${job.stats.engine || "pdf2zh"}${preserved}${fallback}${pageBridges}${knowledge}${warningText}`;
      downloadLink.href = downloadUrl;
      downloadLink.classList.remove("is-disabled");
      if (warnings.length) {
        setStatus(`翻译完成。右侧已生成译文 PDF。\n自动质检发现疑似异常页：${warnings.map((item) => item.page).join(", ")}。`, true);
      } else {
        setStatus("翻译完成。右侧已生成译文 PDF。");
      }
      return;
    }
  }
}

function initializeKnowledgeProfiles() {
  const profiles = loadKnowledgeProfiles();
  if (!Object.keys(profiles).length) {
    saveKnowledgeProfiles(defaultKnowledgeProfiles);
    renderKnowledgeProfiles("学术论文");
    return;
  }
  renderKnowledgeProfiles(Object.keys(profiles)[0]);
}

function loadKnowledgeProfiles() {
  try {
    const raw = localStorage.getItem(knowledgeStorageKey);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveKnowledgeProfiles(profiles) {
  localStorage.setItem(knowledgeStorageKey, JSON.stringify(profiles));
}

function renderKnowledgeProfiles(selectedName) {
  const profiles = loadKnowledgeProfiles();
  knowledgeProfile.innerHTML = "";
  for (const name of Object.keys(profiles)) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    knowledgeProfile.append(option);
  }
  const actualName = profiles[selectedName] ? selectedName : Object.keys(profiles)[0];
  knowledgeProfile.value = actualName || "";
  knowledgeProfileName.value = actualName || "";
  knowledgeBase.value = actualName ? profiles[actualName] : "";
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
