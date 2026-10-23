<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  FileText,
  Plus,
  ArrowUpRight,
  UploadCloud,
  FlaskConical,
  Layers3,
  Download,
  ChevronRight,
  Check,
  LoaderCircle,
  Settings2,
  BookOpen,
  PanelLeftClose,
  PencilLine,
  AlertCircle,
  X,
  FolderOpen,
  RotateCcw,
  Save,
} from "@lucide/vue";
import {
  api,
  type Health,
  type Options,
  type Task,
  type MinerUStatus,
} from "./api";
import { renderMarkdown } from "./markdown";

const tasks = ref<Task[]>([]);
const active = ref<Task | null>(null);
const markdown = ref("");
const options = ref<Options>({
  separator: "<<<FASTGPT_CHUNK>>>",
  target_size: 800,
  include_source: false,
});
const health = ref<Health | null>(null);
const service = ref<MinerUStatus | null>(null);
const checkingService = ref(false);
const displayMode = computed(
  () => active.value?.mode || health.value?.mode || "mock",
);
const tab = ref<"reading" | "chunks">("reading");
const busy = ref(false);
const saving = ref(false);
const error = ref("");
const notice = ref("");
const dragging = ref(false);
const mobileNav = ref(false);
const fileInput = ref<HTMLInputElement>();
let timer: ReturnType<typeof setTimeout> | undefined;
let selection = 0;
let stopped = false;
const completed = computed(() => active.value?.status === "completed");
const dirty = computed(
  () =>
    completed.value &&
    (markdown.value !== active.value?.markdown ||
      JSON.stringify(options.value) !== JSON.stringify(active.value?.settings)),
);
const totalCharacters = computed(() => markdown.value.length);
const statusLabel = (task: Task) =>
  ({
    queued: "排队中",
    processing: "处理中",
    completed: "已完成",
    failed: "待重试",
  })[task.status];

function hydrate(task: Task) {
  active.value = task;
  markdown.value = task.markdown || "";
  options.value = { ...task.settings };
}
async function refreshTasks() {
  tasks.value = await api<Task[]>("/tasks");
}
async function checkService() {
  if (checkingService.value) return;
  checkingService.value = true;
  try {
    service.value = await api<MinerUStatus>("/mineru/status");
  } catch (e) {
    service.value = {
      available: false,
      mode: "remote",
      message: (e as Error).message,
    };
  } finally {
    checkingService.value = false;
  }
}
async function poll() {
  try {
    await refreshTasks();
    if (active.value && !completed.value) {
      const id = active.value.id;
      const task = await api<Task>("/tasks/" + id);
      if (active.value?.id === id && !saving.value) hydrate(task);
    }
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    if (!stopped) timer = setTimeout(poll, 1200);
  }
}
function allowLeave() {
  return !dirty.value || window.confirm("当前修改尚未保存，确定离开吗？");
}
async function openTask(id: string) {
  if (busy.value || saving.value || !allowLeave()) return;
  const token = ++selection;
  try {
    const task = await api<Task>("/tasks/" + id);
    if (token === selection) {
      hydrate(task);
      error.value = "";
      notice.value = "";
      mobileNav.value = false;
    }
  } catch (e) {
    error.value = (e as Error).message;
  }
}
function newTask() {
  if (busy.value || saving.value || !allowLeave()) return;
  selection++;
  active.value = null;
  error.value = "";
  notice.value = "";
  mobileNav.value = false;
}
async function createTask(file?: File) {
  if (busy.value || saving.value || !allowLeave()) return;
  if (file && !file.name.toLowerCase().endsWith(".pdf")) {
    error.value = "请选择 PDF 文件。";
    return;
  }
  if (
    file &&
    health.value &&
    file.size > health.value.max_upload_mb * 1024 * 1024
  ) {
    error.value = `文件不能超过 ${health.value.max_upload_mb} MB。`;
    return;
  }
  busy.value = true;
  error.value = "";
  notice.value = "";
  const token = ++selection;
  try {
    const body = new FormData();
    if (file) body.append("file", file);
    const task = await api<Task>(file ? "/tasks" : "/tasks/demo", {
      method: "POST",
      ...(file ? { body } : {}),
    });
    if (token === selection) hydrate(task);
    await refreshTasks();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
    if (fileInput.value) fileInput.value.value = "";
  }
}
function chooseFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (file) void createTask(file);
}
function dropFile(event: DragEvent) {
  dragging.value = false;
  const files = event.dataTransfer?.files;
  if (files && files.length > 1) {
    error.value = "每次请选择一份 PDF。";
    return;
  }
  if (files?.[0]) void createTask(files[0]);
}
async function save() {
  if (!active.value || saving.value) return false;
  saving.value = true;
  error.value = "";
  notice.value = "";
  const id = active.value.id;
  const draft = markdown.value;
  const settings = { ...options.value };
  try {
    const task = await api<Task>("/tasks/" + id, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        markdown: draft,
        ...settings,
        revision: active.value.revision,
      }),
    });
    // Keep edits typed while the request was in flight; only update the saved baseline.
    if (active.value?.id === id) {
      active.value = task;
      if (markdown.value === draft) markdown.value = task.markdown || "";
      if (JSON.stringify(options.value) === JSON.stringify(settings))
        options.value = { ...task.settings };
    }
    notice.value = "已保存并更新分块";
    await refreshTasks();
    return true;
  } catch (e) {
    error.value = (e as Error).message;
    return false;
  } finally {
    saving.value = false;
  }
}
async function download(variant: "reading" | "chunked") {
  if (!active.value || saving.value) return;
  if (dirty.value && !(await save())) return;
  if (dirty.value) {
    error.value = "保存期间内容发生变化，请再次点击下载。";
    return;
  }
  const link = document.createElement("a");
  link.href = "/api/tasks/" + active.value.id + "/download?variant=" + variant;
  link.download =
    active.value.filename.replace(/\.pdf$/i, "") +
    (variant === "chunked" ? ".chunked.md" : ".md");
  document.body.append(link);
  link.click();
  link.remove();
}
async function retry() {
  if (!active.value) return;
  const needsConfirmation =
    active.value.submission_started ||
    active.value.error_code === "upstream_expired";
  if (
    needsConfirmation &&
    !window.confirm(
      "上游可能已接收文件，或原任务已过期。重新提交可能产生重复任务，确定继续吗？",
    )
  )
    return;
  try {
    hydrate(
      await api<Task>("/tasks/" + active.value.id + "/retry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ allow_resubmit: needsConfirmation }),
      }),
    );
    error.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  }
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value) {
    event.preventDefault();
    event.returnValue = "";
  }
}
onMounted(async () => {
  window.addEventListener("beforeunload", beforeUnload);
  try {
    health.value = await api<Health>("/health");
    if (health.value.mode === "remote") void checkService();
    await refreshTasks();
  } catch (e) {
    error.value = (e as Error).message;
  }
  if (!stopped) timer = setTimeout(poll, 1200);
});
onUnmounted(() => {
  stopped = true;
  clearTimeout(timer);
  window.removeEventListener("beforeunload", beforeUnload);
});
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar" :class="{ 'is-open': mobileNav }">
      <a class="brand" href="/" @click.prevent="newTask"
        ><span class="brand-mark"><FileText :size="23" /></span
        ><span
          >纸页<span class="brand-dot">.</span
          ><small>PDF TO MARKDOWN</small></span
        ></a
      >
      <button class="new-button" @click="newTask">
        <Plus :size="17" /> 新建转换 <span>⌘</span>
      </button>
      <div class="nav-label">工作空间</div>
      <button class="nav-item active" @click="newTask">
        <FolderOpen :size="17" /> 文档转换 <ChevronRight :size="15" />
      </button>
      <div class="history-heading">
        <span>最近文档</span
        ><span>{{ tasks.length.toString().padStart(2, "0") }}</span>
      </div>
      <div class="history-list">
        <p v-if="!tasks.length" class="empty-history">
          第一份文档，从这里开始。
        </p>
        <button
          v-for="task in tasks"
          :key="task.id"
          class="history-item"
          :class="{ selected: active?.id === task.id }"
          @click="openTask(task.id)"
        >
          <FileText :size="16" /><span
            ><strong>{{ task.filename }}</strong
            ><small
              >{{ task.pages }} 页 <i>·</i> {{ statusLabel(task) }} <i>·</i>
              {{ task.mode === "remote" ? "MinerU" : "Mock" }}</small
            ></span
          ><span class="status-dot" :class="task.status"></span>
        </button>
      </div>
      <div class="sidebar-bottom">
        <span class="local-dot"></span
        ><span>本地工作空间<small>文件保存在这台电脑</small></span
        ><span class="version">M2</span>
      </div>
    </aside>
    <button
      v-if="mobileNav"
      class="sidebar-scrim"
      aria-label="关闭导航"
      @click="mobileNav = false"
    ></button>
    <main>
      <header class="topbar">
        <div>
          <button
            class="icon-button nav-toggle"
            aria-label="切换导航"
            @click="mobileNav = !mobileNav"
          >
            <PanelLeftClose :size="18" /></button
          ><span>工作空间</span><ChevronRight :size="13" /><strong
            >文档转换</strong
          >
        </div>
        <span class="top-status"
          ><span class="local-dot"></span>
          {{ health ? "本机服务已连接" : "正在连接服务" }}</span
        >
      </header>
      <div class="content">
        <div
          class="mock-banner"
          :class="{ 'remote-banner': displayMode === 'remote' }"
        >
          <FlaskConical :size="17" /><span
            ><strong>{{
              displayMode === "remote"
                ? "M2 · MinerU 远程解析"
                : "M2 · Mock 演示模式"
            }}</strong
            ><span class="banner-detail">{{
              displayMode === "remote"
                ? "上传的 PDF 将交给解析服务处理；失败时不会使用演示内容替代。"
                : "使用固定示例验证操作流程，未调用 MinerU，不识别上传 PDF 正文。"
            }}</span></span
          ><span class="outline-tag">开发预览</span>
        </div>
        <div
          v-if="health?.mode === 'remote'"
          class="service-box"
          :class="{ unavailable: service && !service.available }"
          role="status"
        >
          <span
            ><strong>{{
              checkingService
                ? "正在核实解析服务…"
                : service?.available
                  ? "解析接口已核实"
                  : "解析服务尚不可用"
            }}</strong
            ><small
              >{{ service?.message || "正在检查服务接口契约。"
              }}<template v-if="service?.available">
                · {{ service.version }} ·
                {{
                  service.style === "async" ? "异步任务" : "同步解析"
                }}</template
              ></small
            ></span
          >
          <button
            class="button secondary"
            :disabled="checkingService"
            @click="checkService"
          >
            <LoaderCircle
              v-if="checkingService"
              class="spin"
              :size="14"
            /><RotateCcw v-else :size="14" /> 检测解析服务
          </button>
        </div>
        <div v-if="error" class="message error" role="alert">
          <AlertCircle :size="17" /><span>{{ error }}</span
          ><button aria-label="关闭错误" @click="error = ''">
            <X :size="15" />
          </button>
        </div>
        <div v-if="notice" class="message success" role="status">
          <Check :size="17" /><span>{{ notice }}</span>
        </div>

        <template v-if="!active">
          <section class="page-heading">
            <div class="eyebrow"><span></span> DOCUMENT WORKBENCH</div>
            <h1>从 PDF，<br class="mobile-break" />到可用的知识。</h1>
            <p>上传、整理、分块。让文档成为清晰、易读的 Markdown。</p>
          </section>
          <div class="start-grid">
            <section
              class="upload-card"
              :class="{ dragging }"
              @dragover.prevent="dragging = true"
              @dragleave.prevent="dragging = false"
              @drop.prevent="dropFile"
            >
              <div class="upload-illustration">
                <div class="paper paper-back"></div>
                <div class="paper paper-front">
                  <span class="pdf-label">PDF</span><i></i><i></i><i></i
                  ><span class="paper-corner"></span>
                </div>
                <span class="upload-circle"><UploadCloud :size="23" /></span>
              </div>
              <h2>把 PDF 放在这里</h2>
              <p>拖拽文件到此处，或从电脑中选择</p>
              <button
                class="button primary upload-button"
                :disabled="busy"
                @click="fileInput?.click()"
              >
                <LoaderCircle v-if="busy" class="spin" :size="17" /><Plus
                  v-else
                  :size="17"
                />{{ busy ? "正在上传…" : "选择 PDF 文件" }}
              </button>
              <input
                ref="fileInput"
                class="visually-hidden"
                type="file"
                accept=".pdf,application/pdf"
                aria-label="上传 PDF"
                @change="chooseFile"
              />
              <small
                >单文件最多 {{ health?.max_upload_mb ?? 20 }} MB <span>·</span>
                {{ health?.max_pdf_pages ?? 200 }} 页以内</small
              >
              <div class="upload-bottom">
                <span><Check :size="13" /> 文件保存在本机</span
                ><span><Check :size="13" /> 无需登录</span>
              </div>
            </section>
            <section class="intro-card">
              <div class="intro-number">01 — 03</div>
              <h2>少一点整理，<br />多一点清晰。</h2>
              <p class="intro-description">
                一个专注于文档的轻量工作台，<br />从原始文件到可复用的内容。
              </p>
              <div class="steps">
                <div>
                  <span>01</span>
                  <p>
                    <strong>上传文档</strong
                    ><small>选择一份 PDF，创建转换任务</small>
                  </p>
                </div>
                <div>
                  <span>02</span>
                  <p>
                    <strong>预览与编辑</strong
                    ><small>调整内容，查看知识分块</small>
                  </p>
                </div>
                <div>
                  <span>03</span>
                  <p>
                    <strong>下载 Markdown</strong
                    ><small>阅读版或带分隔符的知识库版</small>
                  </p>
                </div>
              </div>
              <button
                class="sample-link"
                :disabled="busy"
                @click="createTask()"
              >
                先用示例体验一下 <ArrowUpRight :size="17" />
              </button>
            </section>
          </div>
          <button
            class="sample-link mobile-demo"
            :disabled="busy"
            @click="createTask()"
          >
            先用示例体验一下 <ArrowUpRight :size="17" />
          </button>
          <div class="feature-row">
            <div>
              <PencilLine :size="20" /><span
                ><strong>边看边编辑</strong
                ><small>Markdown 源码与渲染预览</small></span
              >
            </div>
            <div>
              <Layers3 :size="20" /><span
                ><strong>让分块有上下文</strong
                ><small>保留章节路径，自定义分隔符</small></span
              >
            </div>
            <div>
              <Download :size="20" /><span
                ><strong>两种方式导出</strong
                ><small>连续阅读，或整理为知识块</small></span
              >
            </div>
          </div>
        </template>

        <template v-else>
          <section class="document-heading">
            <div>
              <button class="back-link" @click="newTask">
                文档转换 <ChevronRight :size="13" />
              </button>
              <h1>{{ active.filename }}</h1>
              <p>
                {{ active.pages }} 页 <span>·</span>
                {{ (active.size / 1024).toFixed(1) }} KB <span>·</span>
                <strong class="mock-text">{{
                  active.mode === "remote"
                    ? completed
                      ? "MinerU 实际输出"
                      : "MinerU 远程任务"
                    : "Mock 示例输出"
                }}</strong
                ><span v-if="active.edited"> · 已人工编辑</span>
                <span v-if="active.metadata?.cached"> · 复用解析缓存</span>
              </p>
            </div>
            <a
              class="button secondary source-button"
              :href="'/api/tasks/' + active.id + '/source'"
              target="_blank"
              rel="noopener"
              ><FileText :size="16" /> 原始 PDF <ArrowUpRight :size="14"
            /></a>
          </section>
          <section v-if="!completed" class="processing-card">
            <LoaderCircle
              v-if="active.status !== 'failed'"
              :size="35"
              class="spin"
            /><AlertCircle v-else :size="35" />
            <h2>{{ active.stage }}</h2>
            <p>
              {{
                active.error ||
                (active.mode === "remote"
                  ? "PDF 正在交由解析服务处理，请保留此任务。"
                  : "演示 Worker 正在准备固定示例内容，上传的 PDF 不会被识别。")
              }}
            </p>
            <div class="progress-track">
              <div :style="{ width: active.progress + '%' }"></div>
            </div>
            <span>{{ active.progress }}%</span
            ><button
              v-if="active.status === 'failed'"
              class="button primary"
              @click="retry"
            >
              <RotateCcw :size="16" />
              {{
                active.submission_started ||
                active.error_code === "upstream_expired"
                  ? "确认重新提交"
                  : active.upstream_id &&
                      active.error_code !== "upstream_task_failed"
                    ? "继续查询结果"
                    : "重试任务"
              }}</button
            ><small v-else>长时间排队？请确认已运行本地 Worker。</small>
          </section>
          <template v-else>
            <div v-if="active.mode === 'remote'" class="result-info">
              <span
                >MinerU {{ active.metadata?.producer_version || "版本未知" }} ·
                {{ active.metadata?.backend || "后端未知" }} ·
                {{
                  active.metadata?.structured
                    ? "结构化结果已保留"
                    : "仅 Markdown"
                }}<template v-if="active.metadata?.block_count">
                  · {{ active.metadata.block_count }} 个结构块</template
                ></span
              >
              <p
                v-for="warning in active.metadata?.warnings || []"
                :key="warning"
              >
                {{ warning }}
              </p>
            </div>
            <div class="editor-toolbar">
              <div class="editor-state">
                <span class="local-dot" :class="{ unsaved: dirty }"></span
                >{{ dirty ? "有未保存修改" : "全部修改已保存"
                }}<span class="editor-count">{{ totalCharacters }} 字符</span>
              </div>
              <div class="toolbar-actions">
                <button
                  class="button secondary"
                  :disabled="saving || !dirty"
                  @click="save"
                >
                  <Save :size="15" />{{
                    saving ? "保存中…" : "保存并更新分块"
                  }}</button
                ><button
                  class="button secondary"
                  :disabled="saving"
                  @click="download('reading')"
                >
                  <Download :size="15" /> 阅读版</button
                ><button
                  class="button primary"
                  :disabled="saving"
                  @click="download('chunked')"
                >
                  <Download :size="15" /> 知识库版
                </button>
              </div>
            </div>
            <div class="workspace">
              <section class="editor-panel">
                <div class="panel-heading">
                  <span><PencilLine :size="15" /> Markdown 源码</span
                  ><small>可直接编辑</small>
                </div>
                <textarea
                  v-model="markdown"
                  class="markdown-editor"
                  aria-label="Markdown 源码"
                  spellcheck="false"
                ></textarea>
              </section>
              <section class="preview-panel">
                <div class="preview-tabs">
                  <button
                    :class="{ selected: tab === 'reading' }"
                    @click="tab = 'reading'"
                  >
                    <BookOpen :size="15" /> 阅读预览</button
                  ><button
                    :class="{ selected: tab === 'chunks' }"
                    @click="tab = 'chunks'"
                  >
                    <Layers3 :size="15" /> 分块预览
                    <span>{{ active.chunks?.length }}</span>
                  </button>
                </div>
                <div
                  v-if="tab === 'reading'"
                  class="rendered markdown-body"
                  v-html="renderMarkdown(markdown)"
                ></div>
                <div v-else class="chunks-list">
                  <div v-if="dirty" class="draft-hint">
                    当前分块来自已保存版本。点击“保存并更新分块”应用修改。
                  </div>
                  <div v-if="!active.chunks?.length" class="draft-hint">
                    正文为空，暂无知识块。
                  </div>
                  <article
                    v-for="chunk in active.chunks"
                    :key="chunk.index"
                    class="chunk-card"
                  >
                    <div class="chunk-top">
                      <span>块 {{ String(chunk.index).padStart(2, "0") }}</span
                      ><small>{{ chunk.characters }} 字符</small>
                    </div>
                    <div class="chunk-section">{{ chunk.section }}</div>
                    <div
                      class="markdown-body"
                      v-html="renderMarkdown(chunk.markdown)"
                    ></div>
                    <p v-if="chunk.oversized" class="oversized">
                      完整段落或表格超过软目标，当前保留其完整性。
                    </p>
                  </article>
                </div>
              </section>
            </div>
            <section class="settings-bar">
              <div class="settings-title">
                <Settings2 :size="17" /><strong>分块设置</strong
                ><small>按章节与完整段落打包</small>
              </div>
              <div class="settings-fields">
                <label
                  >分隔符<input
                    v-model="options.separator"
                    aria-label="分隔符"
                    maxlength="100" /></label
                ><label
                  >目标字符数<input
                    v-model.number="options.target_size"
                    aria-label="目标字符数"
                    type="number"
                    min="100"
                    max="6000"
                    step="100" /></label
                ><label class="checkbox-label"
                  ><input v-model="options.include_source" type="checkbox" />
                  {{
                    active.mode === "remote"
                      ? "添加来源文件说明"
                      : "添加 Mock 来源说明"
                  }}</label
                >
              </div>
              <p>
                目标大小为软限制；当前知识块未验证精确页码，语义细分与跨页表格复核留待
                M3。
              </p>
            </section>
          </template>
        </template>
        <footer>
          <span>纸页，让文档回归内容。</span
          ><span>本地优先 <i>·</i> M2 开发预览</span>
        </footer>
      </div>
    </main>
  </div>
</template>
