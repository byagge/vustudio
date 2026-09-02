/* ============================================================
   VU Studio — panel logic
   ============================================================ */

const STORE = {
  key: "vu.apiKey",
  job: "vu.activeJob",
  form: "vu.renderForm",
  started: "vu.startedHidden",
  interval: "vu.refreshMs",
  collapsed: "vu.collapsed",
};

const LABEL = {
  pending: "В очереди",
  processing: "Обрабатывается",
  done: "Готово",
  failed: "Ошибка",
};

const MOCKUPS = [
  { value: "hand", label: "Рука + фон", hint: "Документ в руке на сменном фоне", bg: true, portrait: true },
  { value: "original", label: "Оригинал", hint: "Тот же мокап без руки", bg: true, portrait: true },
  { value: "blank", label: "Бланк", hint: "Плоский бланк без фона и портрета", bg: false, portrait: false },
];

const BG_COLORS = [
  "#3b5bdb", "#2b8a3e", "#a61e4d", "#5f3dc4", "#0b7285",
  "#e8590c", "#495057", "#862e9c", "#1864ab", "#c92a2a",
];

const PAGES = [
  { id: "home", title: "Главная", hint: "Обзор и статус", icon: "house" },
  { id: "generate", title: "Генерация", hint: "Создать запись ВУ", icon: "sparkles" },
  { id: "render", title: "Отрисовка", hint: "Мокап в Photoshop", icon: "layers" },
  { id: "jobs", title: "Задачи", hint: "Очередь отрисовки", icon: "list-checks" },
  { id: "system", title: "Система", hint: "Сервер и обслуживание", icon: "server" },
  { id: "settings", title: "Настройки", hint: "Ключ доступа", icon: "settings" },
  { id: "help", title: "Помощь", hint: "Инструкции", icon: "circle-help" },
];

let lastResult = null;
let pollTimer = null;
let autoTimer = null;
let noteTimer = null;
let activeJob = null;
let lastLoadAt = 0;
let jobFilter = "";
let cachedJobs = [];
let selRegion, selMockup, selBackground;

const $ = (id) => document.getElementById(id);
const icon = (n, s) => (window.Icons ? Icons.svg(n, s || 16) : "");
const hydrate = (el) => window.Icons && Icons.hydrate(el);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const readJSON = (k, fb) => {
  try {
    const v = localStorage.getItem(k);
    return v ? JSON.parse(v) : fb;
  } catch {
    return fb;
  }
};
const writeJSON = (k, v) => localStorage.setItem(k, JSON.stringify(v));

/* ============ API ============ */
function apiKey() {
  return $("apiKey")?.value || localStorage.getItem(STORE.key) || "";
}

function headers(json = true) {
  const h = {};
  if (json) h["Content-Type"] = "application/json";
  const k = apiKey();
  if (k) h["X-API-Key"] = k;
  return h;
}

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: headers(opts.body != null), ...opts });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Ошибка ${res.status}`);
  return data;
}

/* ============ TOASTS ============ */
function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  const ic = kind === "bad" ? "circle-alert" : kind === "ok" ? "circle-check" : "info";
  el.innerHTML = `<span class="ic ${kind}">${icon(ic, 16)}</span><span>${esc(msg)}</span>`;
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), 3800);
}

/* ============ TOOLTIPS ============ */
const tipEl = () => $("tip");

function showTip(target) {
  const text = target.dataset.tip;
  if (!text) return;
  const t = tipEl();
  t.textContent = text;
  t.classList.add("show");
  const r = target.getBoundingClientRect();
  const tr = t.getBoundingClientRect();
  let left = r.left + r.width / 2 - tr.width / 2;
  let top = r.top - tr.height - 8;
  if (top < 8) top = r.bottom + 8;
  left = Math.max(8, Math.min(left, window.innerWidth - tr.width - 8));
  t.style.left = `${left}px`;
  t.style.top = `${top}px`;
}

const hideTip = () => tipEl().classList.remove("show");

document.addEventListener("mouseover", (e) => {
  const t = e.target.closest("[data-tip]");
  if (t) showTip(t);
});
document.addEventListener("mouseout", (e) => {
  if (e.target.closest("[data-tip]")) hideTip();
});
document.addEventListener("scroll", hideTip, true);

/* ============ MODAL ============ */
function openModal(title, bodyHtml, footHtml = "") {
  $("modalTitle").textContent = title;
  $("modalBody").innerHTML = bodyHtml;
  $("modalFoot").innerHTML = footHtml;
  $("modal").classList.remove("hidden");
  hydrate($("modalBody"));
  hydrate($("modalFoot"));
  bindDelegates($("modalBody"));
  bindDelegates($("modalFoot"));
}
const closeModal = () => $("modal").classList.add("hidden");

$("modalClose").addEventListener("click", closeModal);
$("modal").addEventListener("click", (e) => {
  if (e.target === $("modal")) closeModal();
});

const MODALS = {
  worker: () => {
    openModal(
      "Что происходит и что делать",
      `<p><strong>Ваши задачи не пропали.</strong> Они сохранены и стоят в очереди. Но собрать картинку пока некому: для этого нужен Photoshop, а он сейчас не подключён.</p>

       <p>Панель сама рисовать не умеет — она только готовит данные. Настоящую картинку собирает Photoshop на компьютере с Windows. Как только он подключится, все накопленные задачи выполнятся автоматически, ничего заново создавать не придётся.</p>

       <ol class="step-list">
         <li><strong>Нужен Windows с Photoshop</strong>
           Это может быть ваш компьютер или отдельный. Если Photoshop ещё не установлен, скачайте его с сайта Adobe — есть бесплатный пробный период.
           <div class="row-actions" style="margin-top:8px">
             <a class="btn secondary sm" href="https://www.adobe.com/products/photoshop/free-trial-download.html" target="_blank" rel="noopener">
               Скачать Photoshop (пробная версия)
             </a>
             <a class="btn ghost sm" href="https://creativecloud.adobe.com/apps/download/creative-cloud" target="_blank" rel="noopener">
               Creative Cloud
             </a>
           </div>
         </li>
         <li><strong>Включите обработчик на этом компьютере</strong>
           Это делается один раз: запускается небольшая программа, которая связывает панель и Photoshop. Если систему настраивал не вы — попросите того, кто её ставил, включить «render worker».
         </li>
         <li><strong>Дождитесь зелёной отметки</strong>
           Через несколько секунд карточка «Сервер отрисовки» на главной станет зелёной. Это значит, что всё готово.
         </li>
         <li><strong>Ничего больше не нужно</strong>
           Задачи из очереди начнут выполняться сами. Готовые файлы появятся в разделе «Задачи», их можно будет скачать.
         </li>
       </ol>

       <details class="tech">
         <summary>Показать техническую инструкцию</summary>
         <div class="tech-body">
           <p>В файле <code>.env</code> укажите путь к программе:</p>
           <pre class="code">PHOTOSHOP_EXE=C:\\Program Files\\Adobe\\Adobe Photoshop 2024\\Photoshop.exe</pre>
           <p>Затем запустите обработчик в PowerShell:</p>
           <pre class="code">cd D:\\codes\\otris
.\\scripts\\start_render_worker.ps1</pre>
         </div>
       </details>`,
      `<button type="button" class="btn secondary" data-copy="cd D:\\codes\\otris&#10;.\\scripts\\start_render_worker.ps1">Скопировать команды</button>
       <button type="button" class="btn primary" data-close-modal>Понятно</button>`
    );
  },
  about: () => {
    openModal(
      "О системе",
      `<p>VU Studio — панель управления генерацией записей и отрисовкой мокапов в Photoshop.</p>
       <ul>
         <li>Генерация тестовых записей ВУ с проверкой правил</li>
         <li>Очередь отрисовки: панель, Telegram-бот и API кладут задачи в одну очередь</li>
         <li>Photoshop worker на Windows подставляет текст, фон и портрет</li>
         <li>ИИ-портрет через OpenAI или офлайн-заглушку</li>
       </ul>
       <p class="note">Те же операции доступны в Telegram: <code>/status</code> и <code>/admin</code>.</p>

       <h4 class="sub-title">Горячие клавиши</h4>
       <table class="kv">
         <tr><th><kbd>Ctrl</kbd> + <kbd>K</kbd></th><td>Поиск по разделам, задачам и действиям</td></tr>
         <tr><th><kbd>/</kbd></th><td>Тот же поиск, без Ctrl</td></tr>
         <tr><th><kbd>?</kbd></th><td>Открыть раздел «Помощь»</td></tr>
         <tr><th><kbd>Esc</kbd></th><td>Закрыть поиск, окно или список</td></tr>
         <tr><th><kbd>↑</kbd> <kbd>↓</kbd> <kbd>Enter</kbd></th><td>Навигация в списках</td></tr>
       </table>

       <h4 class="sub-title">Поддержка</h4>
       <p>Систему обслуживает <a href="https://t.me/arxixx" target="_blank" rel="noopener">@arxixx</a> — по вопросам, доступам и сбоям пишите туда.</p>`,
      `<a class="btn secondary" href="https://t.me/arxixx" target="_blank" rel="noopener">Написать @arxixx</a>
       <button type="button" class="btn primary" data-close-modal>Закрыть</button>`
    );
  },
};

function bindDelegates(root) {
  root.querySelectorAll("[data-goto]").forEach((b) =>
    b.addEventListener("click", () => {
      closeModal();
      goto(b.dataset.goto);
    })
  );
  root.querySelectorAll("[data-modal]").forEach((b) =>
    b.addEventListener("click", () => MODALS[b.dataset.modal]?.())
  );
  root.querySelectorAll("[data-close-modal]").forEach((b) => b.addEventListener("click", closeModal));
  root.querySelectorAll("[data-copy]").forEach((b) =>
    b.addEventListener("click", async () => {
      await navigator.clipboard.writeText(b.dataset.copy);
      toast("Скопировано", "ok");
    })
  );
}

/* ============ CUSTOM SELECT ============ */
function VuSelect(host, cfg) {
  const state = {
    options: cfg.options || [],
    value: cfg.value ?? "",
    open: false,
    cursor: 0,
    query: "",
    disabled: false,
  };

  host.classList.add("sel");
  host.innerHTML = `
    <button type="button" class="sel-btn">
      <span class="sel-val"><span class="sel-val-text"></span></span>
      <span class="ic sel-chev">${icon("chevron-right", 14)}</span>
    </button>
    <div class="sel-pop hidden">
      ${cfg.searchable ? `<div class="sel-search"><span class="ic dim">${icon("search", 14)}</span><input type="text" placeholder="${esc(cfg.searchPlaceholder || "Поиск…")}"></div>` : ""}
      <div class="sel-list ${cfg.grid ? "grid" : ""}"></div>
      <div class="sel-empty hidden">Ничего не найдено</div>
    </div>
    <input type="hidden" name="${esc(cfg.name)}">
  `;

  const btn = host.querySelector(".sel-btn");
  const pop = host.querySelector(".sel-pop");
  const list = host.querySelector(".sel-list");
  const emptyEl = host.querySelector(".sel-empty");
  const search = host.querySelector(".sel-search input");
  const hidden = host.querySelector("input[type=hidden]");
  const valWrap = host.querySelector(".sel-val");
  const valText = host.querySelector(".sel-val-text");

  const current = () => state.options.find((o) => String(o.value) === String(state.value));
  const filtered = () => {
    const q = state.query.trim().toLowerCase();
    if (!q) return state.options;
    return state.options.filter((o) =>
      `${o.label} ${o.hint || ""} ${o.value}`.toLowerCase().includes(q)
    );
  };

  function paintValue() {
    const o = current();
    hidden.value = o ? o.value : "";
    valWrap.classList.toggle("empty", !o);
    valText.textContent = o ? o.label : cfg.placeholder || "Выберите";
    valWrap.querySelectorAll(".sel-swatch").forEach((n) => n.remove());
    if (o && cfg.grid) valWrap.insertAdjacentHTML("afterbegin", swatchHtml(o));
  }

  function swatchHtml(o) {
    if (o.thumb) return `<span class="sel-swatch"><img src="${esc(o.thumb)}" alt=""></span>`;
    return `<span class="sel-swatch" style="background:${o.color || "#333"}"></span>`;
  }

  function paintList() {
    const items = filtered();
    emptyEl.classList.toggle("hidden", items.length > 0);
    if (cfg.grid) {
      list.innerHTML = items
        .map((o, i) => {
          const on = String(o.value) === String(state.value);
          const inner = o.thumb
            ? `<img src="${esc(o.thumb)}" alt="" loading="lazy">`
            : `<span>${esc(o.short || o.value)}</span>`;
          const bg = o.thumb ? "" : `background:${o.color || "#333"}`;
          return `<div class="sel-tile ${on ? "sel-on" : ""} ${i === state.cursor ? "cursor" : ""}" data-v="${esc(o.value)}">
            <div class="sel-thumb" style="${bg}">${inner}</div>
            <div class="sel-tile-cap">${esc(o.label)}</div>
          </div>`;
        })
        .join("");
    } else {
      list.innerHTML = items
        .map((o, i) => {
          const on = String(o.value) === String(state.value);
          return `<div class="sel-opt ${on ? "sel-on" : ""} ${i === state.cursor ? "cursor" : ""}" data-v="${esc(o.value)}">
            <div class="sel-opt-main">
              <div class="sel-opt-label">${esc(o.label)}</div>
              ${o.hint ? `<div class="sel-opt-hint">${esc(o.hint)}</div>` : ""}
            </div>
            <span class="ic sel-check">${icon("circle-check", 14)}</span>
          </div>`;
        })
        .join("");
    }
    list.querySelectorAll("[data-v]").forEach((el) =>
      el.addEventListener("click", () => pick(el.dataset.v))
    );
  }

  function pick(v) {
    state.value = v;
    paintValue();
    close();
    cfg.onChange?.(v);
  }

  function open() {
    if (state.disabled) return;
    document.querySelectorAll(".sel.open").forEach((s) => s !== host && s._close?.());
    state.open = true;
    state.query = "";
    state.cursor = Math.max(0, filtered().findIndex((o) => String(o.value) === String(state.value)));
    if (search) search.value = "";
    host.classList.add("open");
    pop.classList.remove("hidden");
    paintList();
    const rect = pop.getBoundingClientRect();
    pop.classList.toggle("up", rect.bottom > window.innerHeight - 12);
    search?.focus();
  }

  function close() {
    state.open = false;
    host.classList.remove("open");
    pop.classList.add("hidden");
  }
  host._close = close;

  btn.addEventListener("click", () => (state.open ? close() : open()));

  search?.addEventListener("input", (e) => {
    state.query = e.target.value;
    state.cursor = 0;
    paintList();
  });

  host.addEventListener("keydown", (e) => {
    if (!state.open) return;
    const items = filtered();
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      state.cursor = (state.cursor + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      paintList();
      list.querySelector(".cursor")?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (items[state.cursor]) pick(items[state.cursor].value);
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
      btn.focus();
    }
  });

  document.addEventListener("click", (e) => {
    if (state.open && !host.contains(e.target)) close();
  });

  paintValue();

  return {
    setOptions(opts) {
      state.options = opts;
      if (!opts.some((o) => String(o.value) === String(state.value))) state.value = opts[0]?.value ?? "";
      paintValue();
      if (state.open) paintList();
    },
    setValue(v) {
      state.value = v;
      paintValue();
    },
    getValue: () => state.value,
    setDisabled(d) {
      state.disabled = d;
      btn.disabled = d;
      if (d) close();
    },
  };
}

/* ============ NAVIGATION ============ */
function goto(page) {
  document.querySelectorAll(".nav-item[data-page]").forEach((b) =>
    b.classList.toggle("active", b.dataset.page === page)
  );
  document.querySelectorAll(".page").forEach((p) =>
    p.classList.toggle("active", p.id === `page-${page}`)
  );
  if (page === "home") loadHome();
  if (page === "system") loadAdmin();
  if (page === "jobs") loadJobs();
  window.scrollTo({ top: 0 });
}

document.querySelectorAll(".nav-item[data-page]").forEach((b) =>
  b.addEventListener("click", () => goto(b.dataset.page))
);
bindDelegates(document);

/* sidebar collapse */
function setCollapsed(on) {
  $("layout").classList.toggle("collapsed", on);
  localStorage.setItem(STORE.collapsed, on ? "1" : "0");
  $("collapseBtn").dataset.tip = on ? "Развернуть меню" : "Свернуть меню";

  // Подписи скрыты — без подсказок иконки не читаются.
  document.querySelectorAll(".nav-item[data-page]").forEach((b) => {
    const label = b.querySelector(".nav-label")?.textContent?.trim();
    if (on && label) b.dataset.tip = label;
    else delete b.dataset.tip;
  });
  const user = document.querySelector(".user-row");
  if (user) {
    if (on) user.dataset.tip = "Администратор";
    else delete user.dataset.tip;
  }
  hideTip();
}

$("collapseBtn").addEventListener("click", (e) => {
  e.stopPropagation();
  setCollapsed(!$("layout").classList.contains("collapsed"));
  hideTip();
});

/* brand menu */
const brandMenu = $("brandMenu");
$("orgSwitch").addEventListener("click", (e) => {
  e.stopPropagation();
  brandMenu.classList.toggle("hidden");
});
document.addEventListener("click", (e) => {
  if (!brandMenu.contains(e.target) && e.target !== $("orgSwitch")) brandMenu.classList.add("hidden");
});
brandMenu.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  brandMenu.classList.add("hidden");
  const act = btn.dataset.act;
  if (act === "refresh") {
    refreshAll();
    toast("Данные обновлены", "ok");
  }
  if (act === "collapse") setCollapsed(!$("layout").classList.contains("collapsed"));
  if (act === "search") openPalette();
  if (act === "settings") goto("settings");
  if (act === "about") MODALS.about();
});

/* ============ COMMAND PALETTE ============ */
const ACTIONS = [
  { title: "Отрисовать мокап", hint: "Открыть форму отрисовки", icon: "play", run: () => goto("render") },
  { title: "Сгенерировать запись", hint: "Новая запись ВУ", icon: "sparkles", run: () => goto("generate") },
  { title: "Восстановить зависшие задачи", hint: "Вернуть в очередь", icon: "refresh-cw", run: () => { goto("system"); $("recoverStale").click(); } },
  { title: "Проверить мокапы", hint: "Сверить PSB и шаблоны", icon: "wrench", run: () => { goto("system"); $("verifyScene").click(); } },
  { title: "Извлечь превью фонов", hint: "Картинки для выбора фона", icon: "image", run: () => { goto("system"); $("extractBg").click(); } },
  { title: "Как запустить worker", hint: "Инструкция", icon: "cpu", run: () => MODALS.worker() },
  { title: "Свернуть меню", hint: "Боковая панель", icon: "panel-left", run: () => setCollapsed(!$("layout").classList.contains("collapsed")) },
  { title: "Очистить сохранённые данные", hint: "Сбросить локальный кэш", icon: "x", run: () => { goto("settings"); $("clearLocal").click(); } },
];

let paletteItems = [];
let paletteCursor = 0;

function openPalette() {
  $("palette").classList.remove("hidden");
  $("paletteInput").value = "";
  fillPalette("");
  $("paletteInput").focus();
}
const closePalette = () => $("palette").classList.add("hidden");

function fillPalette(q) {
  const query = q.trim().toLowerCase();
  const match = (s) => !query || String(s).toLowerCase().includes(query);

  const groups = [];
  const pages = PAGES.filter((p) => match(`${p.title} ${p.hint}`)).map((p) => ({
    icon: p.icon,
    title: p.title,
    hint: p.hint,
    run: () => goto(p.id),
  }));
  if (pages.length) groups.push({ name: "Разделы", items: pages });

  const acts = ACTIONS.filter((a) => match(`${a.title} ${a.hint}`)).map((a) => ({
    icon: a.icon,
    title: a.title,
    hint: a.hint,
    run: a.run,
  }));
  if (acts.length) groups.push({ name: "Действия", items: acts });

  const jobHits = cachedJobs
    .filter((j) => match(`${j.job_id} ${j.title} ${LABEL[j.status] || j.status} ${j.mockup || ""}`))
    .slice(0, 6)
    .map((j) => ({
      icon: "list-checks",
      title: j.title ? `${j.title} · ${j.job_id.slice(0, 8)}` : j.job_id,
      hint: `${LABEL[j.status] || j.status}${j.mockup ? " · " + mockupLabel(j.mockup) : ""}`,
      run: () => {
        goto("jobs");
        openJobModal(j.job_id);
      },
    }));
  if (jobHits.length) groups.push({ name: "Задачи", items: jobHits });

  paletteItems = groups.flatMap((g) => g.items);
  paletteCursor = 0;

  const list = $("paletteList");
  if (!paletteItems.length) {
    list.innerHTML = `<div class="palette-empty">Ничего не найдено</div>`;
    return;
  }
  let idx = 0;
  list.innerHTML = groups
    .map(
      (g) =>
        `<div class="palette-group">${esc(g.name)}</div>` +
        g.items
          .map(
            (it) =>
              `<div class="palette-item ${idx === 0 ? "sel" : ""}" data-i="${idx++}">
                <span class="ic dim">${icon(it.icon, 15)}</span>
                <span class="pi-main"><div>${esc(it.title)}</div><div class="pi-hint">${esc(it.hint || "")}</div></span>
              </div>`
          )
          .join("")
    )
    .join("");

  list.querySelectorAll(".palette-item").forEach((el) =>
    el.addEventListener("click", () => {
      paletteItems[Number(el.dataset.i)]?.run();
      closePalette();
    })
  );
}

function movePaletteCursor(delta) {
  const els = $("paletteList").querySelectorAll(".palette-item");
  if (!els.length) return;
  paletteCursor = (paletteCursor + delta + els.length) % els.length;
  els.forEach((e, i) => e.classList.toggle("sel", i === paletteCursor));
  els[paletteCursor].scrollIntoView({ block: "nearest" });
}

$("searchBox").addEventListener("click", openPalette);
$("paletteInput").addEventListener("input", (e) => fillPalette(e.target.value));
$("palette").addEventListener("click", (e) => {
  if (e.target === $("palette")) closePalette();
});

const isTyping = (el) =>
  !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);

document.addEventListener("keydown", (e) => {
  // e.code вместо e.key: при русской раскладке Ctrl+K приходит как «л».
  if ((e.ctrlKey || e.metaKey) && e.code === "KeyK") {
    e.preventDefault();
    e.stopPropagation();
    openPalette();
    return;
  }
  if (e.key === "Escape") {
    closePalette();
    closeModal();
    brandMenu.classList.add("hidden");
    document.querySelectorAll(".sel.open").forEach((s) => s._close?.());
    hideTip();
    return;
  }
  // «/» и «?» — быстрый поиск и помощь, но не когда пользователь печатает.
  if (!isTyping(e.target) && $("palette").classList.contains("hidden")) {
    if (e.key === "/") {
      e.preventDefault();
      openPalette();
      return;
    }
    if (e.key === "?") {
      e.preventDefault();
      goto("help");
      return;
    }
  }
  if ($("palette").classList.contains("hidden")) return;
  if (e.key === "ArrowDown") {
    e.preventDefault();
    movePaletteCursor(1);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    movePaletteCursor(-1);
  } else if (e.key === "Enter") {
    e.preventDefault();
    paletteItems[paletteCursor]?.run();
    closePalette();
  }
});

/* ============ METRICS ============ */
function spark(color, mode = "") {
  return `<div class="spark ${mode}" style="--c:${color}"><i></i></div>`;
}

function metricCard(m) {
  const body = m.action
    ? `<div class="metric-act">${m.action}</div>`
    : `<div class="metric-spark">${m.spark || ""}</div>`;
  const attrs = [
    `class="metric ${m.tone || ""} ${m.onClick ? "clickable" : ""}"`,
    m.tip ? `data-tip="${esc(m.tip)}"` : "",
    m.onClick ? `data-metric="${esc(m.onClick)}"` : "",
  ].join(" ");
  return `<div ${attrs}>
    <div class="metric-top"><span>${esc(m.label)}</span>${m.onClick ? `<span class="ic">${icon("chevron-right", 13)}</span>` : ""}</div>
    <div class="metric-value">${m.value}</div>
    ${body}
  </div>`;
}

function buildMetrics(data) {
  const s = data.server || {};
  const q = data.queue || {};
  const online = !!s.worker_alive;
  const cards = [];

  cards.push({
    label: "Сервер отрисовки",
    value: `<span class="ic ${online ? "ok" : "bad"}">${icon(online ? "circle-check" : "circle-alert", 18)}</span>${online ? "Подключён" : "Не подключён"}`,
    spark: spark(online ? "#10a37f" : "#f0565b", online ? "" : "flat"),
    tip: online
      ? "Photoshop worker на связи и разбирает очередь автоматически."
      : "Photoshop worker не отвечает. Пока он не запущен, задачи будут копиться в очереди.",
    onClick: online ? "page:system" : "modal:worker",
  });

  if (!online) {
    cards.push({
      label: "Требуется действие",
      tone: "amber",
      value: "Запустите worker",
      tip: "Пошаговая инструкция: где взять Photoshop, что вписать в .env и какую команду выполнить.",
      onClick: "modal:worker",
      action: `<button type="button" class="btn tiny amber" data-modal="worker">
        <span class="ic">${icon("wrench", 13)}</span> Что делать</button>`,
    });
  } else {
    cards.push({
      label: "Photoshop",
      value: s.photoshop_available ? "Доступен" : "Не найден",
      spark: spark(s.photoshop_available ? "#10a37f" : "#e0b341", "flat"),
      tip: s.photoshop_available
        ? "Photoshop найден на сервере отрисовки и готов открывать мокапы."
        : "Путь к Photoshop не задан в .env — worker не сможет открыть мокап.",
      onClick: "page:system",
    });
  }

  const pending = q.pending ?? 0;
  const processing = q.processing ?? 0;
  const done = q.done ?? 0;
  const failed = q.failed ?? 0;

  cards.push({
    label: "В очереди",
    value: String(pending),
    spark: spark("#e0b341", pending ? "" : "dashed"),
    tip: pending
      ? `${pending} задач ждут свободного Photoshop. Нажмите, чтобы посмотреть список.`
      : "Здесь считаются задачи, которые созданы, но ещё не начали обрабатываться.",
    onClick: "jobs:pending",
  });

  cards.push({
    label: "В работе",
    value: String(processing),
    spark: spark("#6a9dff", processing ? "" : "dashed"),
    tip: processing
      ? `${processing} задач прямо сейчас обрабатываются в Photoshop.`
      : "Здесь считаются задачи, которые Photoshop открыл и отрисовывает прямо сейчас.",
    onClick: "jobs:processing",
  });

  cards.push({
    label: "Готово",
    value: String(done),
    spark: spark("#10a37f", done ? "" : "dashed"),
    tip: done
      ? `Успешно отрисовано задач: ${done}. Нажмите, чтобы скачать результаты.`
      : "Здесь считаются завершённые задачи — у них можно скачать JPG и PSD.",
    onClick: "jobs:done",
  });

  cards.push({
    label: "Ошибки",
    value: String(failed),
    spark: spark("#f0565b", failed ? "" : "dashed"),
    tip: failed
      ? `${failed} задач завершились неудачно. Нажмите, чтобы увидеть причину.`
      : "Здесь считаются задачи, которые не удалось отрисовать. Сейчас таких нет.",
    onClick: "jobs:failed",
  });

  return cards;
}

function renderMetrics(container, data) {
  container.innerHTML = buildMetrics(data).map(metricCard).join("");
  hydrate(container);
  bindDelegates(container);
  container.querySelectorAll("[data-metric]").forEach((el) =>
    el.addEventListener("click", (e) => {
      if (e.target.closest("[data-modal]")) return;
      const [kind, arg] = el.dataset.metric.split(":");
      if (kind === "page") goto(arg);
      if (kind === "modal") MODALS[arg]?.();
      if (kind === "jobs") {
        jobFilter = arg;
        syncFilterChips();
        goto("jobs");
      }
    })
  );
}

function renderUpdates(data) {
  const s = data.server || {};
  const q = data.queue || {};
  const scene = data.scene_verify || {};
  const rows = [
    {
      tone: s.worker_alive ? "ok" : "warn",
      ic: s.worker_alive ? "circle-check" : "triangle-alert",
      title: s.worker_alive ? "Сервер отрисовки на связи" : "Сервер отрисовки не отвечает",
      text: s.worker_alive
        ? "Задачи из очереди обрабатываются автоматически."
        : "Запустите Photoshop worker на Windows — до этого задачи будут ждать в очереди.",
    },
    scene.status === "scanning" || scene.ok == null
      ? {
          tone: "",
          ic: "loader-circle",
          title: "Проверяем мокапы",
          text: "Читаем PSB-шаблоны в фоне, это может занять минуту.",
        }
      : {
          tone: scene.ok ? "ok" : "warn",
          ic: scene.ok ? "image" : "triangle-alert",
          title: scene.ok ? "Мокапы настроены" : "Проверьте мокапы",
          text: scene.ok
            ? "Все слои и фоны найдены в PSB-шаблонах."
            : "Часть слоёв не найдена — откройте раздел «Система».",
        },
    {
      tone: (q.failed ?? 0) > 0 ? "bad" : "",
      ic: (q.failed ?? 0) > 0 ? "circle-alert" : "list-checks",
      title: (q.failed ?? 0) > 0 ? `Ошибок: ${q.failed}` : "Ошибок нет",
      text:
        (q.failed ?? 0) > 0
          ? "Часть задач завершилась неудачно."
          : `Всего обработано задач: ${q.done ?? 0}.`,
    },
  ];

  const el = $("homeUpdates");
  el.innerHTML = rows
    .map(
      (r) => `<li><span class="u-ic ${r.tone}">${icon(r.ic, 14)}</span>
        <span><strong>${esc(r.title)}</strong><small>${esc(r.text)}</small></span></li>`
    )
    .join("");
  hydrate(el);
}

/* ============ HOME ============ */
function markLoaded() {
  lastLoadAt = Date.now();
  paintRefreshNote();
}

function paintRefreshNote() {
  const el = $("refreshNote");
  if (!el || !lastLoadAt) return;
  const sec = Math.round((Date.now() - lastLoadAt) / 1000);
  el.textContent = sec < 5 ? "обновлено только что" : `обновлено ${sec} с назад`;
}

async function loadHome() {
  try {
    const data = await api("/api/v1/admin/dashboard");
    renderMetrics($("homeMetrics"), data);
    renderUpdates(data);
    const offline = !data.server?.worker_alive;
    $("promoCard").hidden = !offline;
    $("navSystemDot").classList.toggle("hidden", !offline);
    updateQueueCounts(data.queue || {});
    markLoaded();
  } catch (e) {
    $("homeMetrics").innerHTML = metricCard({
      label: "Статус",
      value: "Нет связи",
      tip: e.message,
    });
    hydrate($("homeMetrics"));
    $("homeUpdates").innerHTML = `<li><span class="u-ic bad">${icon("circle-alert", 14)}</span>
      <span><strong>Сервер недоступен</strong><small>${esc(e.message)}</small></span></li>`;
    hydrate($("homeUpdates"));
  }
}

function updateQueueCounts(q) {
  const active = (q.pending ?? 0) + (q.processing ?? 0);
  const badge = $("navJobsCount");
  badge.textContent = String(active);
  badge.classList.toggle("hidden", active === 0);
  document.querySelectorAll(".chip-n").forEach((el) => {
    el.textContent = String(q[el.dataset.n] ?? 0);
  });
}

$("promoClose").addEventListener("click", () => ($("promoCard").hidden = true));

$("dismissStart").addEventListener("click", () => {
  $("getStarted").classList.add("hidden");
  $("startHead").classList.add("hidden");
  localStorage.setItem(STORE.started, "1");
});

/* ============ AUTO REFRESH ============ */
function refreshAll() {
  const page = document.querySelector(".page.active")?.id || "";
  if (page === "page-home") loadHome();
  else if (page === "page-system") loadAdmin();
  else if (page === "page-jobs") loadJobs();
  else loadHome();
}

function setAutoRefresh(ms) {
  clearInterval(autoTimer);
  clearInterval(noteTimer);
  localStorage.setItem(STORE.interval, String(ms));
  if (ms > 0) {
    autoTimer = setInterval(refreshAll, ms);
    noteTimer = setInterval(paintRefreshNote, 1000);
  } else {
    $("refreshNote").textContent = "автообновление выключено";
  }
}

$("refreshRange").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  $("refreshRange").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === btn));
  const ms = Number(btn.dataset.ms);
  setAutoRefresh(ms);
  if (ms > 0) {
    refreshAll();
    toast(`Обновление каждые ${btn.textContent.trim()}`, "ok");
  }
});

/* ============ GENERATE ============ */
async function loadRegions() {
  try {
    const items = await api("/api/v1/regions");
    selRegion.setOptions([
      { value: "", label: "Любой регион", hint: "Выбирается случайно" },
      ...items.map((r) => ({ value: r.code, label: `${r.code} — ${r.name}`, hint: r.name })),
    ]);
  } catch {}
}

function showTab(name) {
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  $("textOut").classList.toggle("hidden", name !== "text");
  $("debugOut").classList.toggle("hidden", name !== "debug");
}
document.querySelectorAll(".tab").forEach((b) =>
  b.addEventListener("click", () => showTab(b.dataset.tab))
);

$("genForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const body = { me: fd.get("me"), valid_now: fd.get("valid_now") === "on" };
  if (fd.get("region_code")) body.region_code = fd.get("region_code");
  try {
    const data = await api("/api/v1/generate", { method: "POST", body: JSON.stringify(body) });
    lastResult = data;
    $("result").hidden = false;
    $("textOut").textContent = data.text_block;
    $("debugOut").textContent = data.debug_block;
    const ok = data.validation_status === "green";
    const badge = $("statusBadge");
    badge.className = `pill ${ok ? "ok" : "failed"}`;
    badge.innerHTML = `<span class="ic">${icon(ok ? "circle-check" : "circle-alert", 13)}</span>${ok ? "Проверка пройдена" : "Есть замечания"}`;
    showTab("text");
  } catch (err) {
    toast(err.message, "bad");
  }
});

$("useForRender").addEventListener("click", () => {
  if (!lastResult) return;
  $("renderText").value = lastResult.text_block;
  saveForm();
  goto("render");
});

$("copyText").addEventListener("click", async () => {
  if (!lastResult) return;
  await navigator.clipboard.writeText(lastResult.text_block);
  toast("Скопировано", "ok");
});

/* ============ RENDER FORM ============ */
const mockupLabel = (v) => MOCKUPS.find((m) => m.value === v)?.label || v || "—";

async function loadBackgrounds() {
  let items = Array.from({ length: 10 }, (_, i) => ({ id: i + 1, layer_name: `Вариант ${i + 1}`, has_preview: false }));
  try {
    const data = await api("/api/v1/mockups/backgrounds");
    if (data.backgrounds?.length) items = data.backgrounds;
  } catch {}

  const withPreview = items.filter((b) => b.has_preview).length;
  $("bgHint").textContent = withPreview
    ? ""
    : "— превью не извлечены";
  $("bgHint").dataset.tip = withPreview
    ? ""
    : "Чтобы видеть картинки фонов, извлеките их в разделе «Система».";

  selBackground.setOptions(
    items.map((b) => ({
      value: String(b.id),
      label: `Фон ${b.id}`,
      short: String(b.id),
      hint: b.layer_name,
      color: BG_COLORS[(b.id - 1) % BG_COLORS.length],
      thumb: b.has_preview ? `/api/v1/mockups/backgrounds/${b.id}/preview` : null,
    }))
  );
  const saved = readJSON(STORE.form, null);
  if (saved?.background) selBackground.setValue(String(saved.background));
}

function saveForm() {
  writeJSON(STORE.form, {
    text: $("renderText").value || "",
    mockup: selMockup?.getValue() || "hand",
    background: selBackground?.getValue() || "1",
    portrait: $("genPortrait").checked,
  });
}

function syncMockup() {
  const spec = MOCKUPS.find((m) => m.value === selMockup.getValue());
  const supportsBg = spec ? spec.bg : true;
  selBackground.setDisabled(!supportsBg);
  $("genPortrait").disabled = !(spec ? spec.portrait : true);
  $("bgField").style.opacity = supportsBg ? "1" : "0.5";
}

$("renderText").addEventListener("input", saveForm);
$("genPortrait").addEventListener("change", saveForm);

$("portraitFile").addEventListener("change", (e) => {
  const f = e.target.files?.[0];
  $("fileName").textContent = f ? f.name : "Перетащите файл или нажмите для выбора";
  $("fileDrop").classList.toggle("has-file", !!f);
});

/* ============ JOBS ============ */
function syncFilterChips() {
  document.querySelectorAll("#jobFilters .chip").forEach((c) =>
    c.classList.toggle("on", (c.dataset.status || "") === jobFilter)
  );
}

$("jobFilters").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  jobFilter = chip.dataset.status || "";
  syncFilterChips();
  loadJobs();
});

$("refreshJobs").addEventListener("click", () => loadJobs());

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

async function loadJobs() {
  const body = $("jobsBody");
  try {
    const q = jobFilter ? `?status=${jobFilter}&limit=100` : "?limit=100";
    const data = await api(`/api/v1/render/queue/jobs${q}`);
    cachedJobs = data.jobs || [];
    renderJobsTable(cachedJobs);
    markLoaded();
  } catch (e) {
    body.innerHTML = `<tr><td colspan="5" class="td-empty">${esc(e.message)}</td></tr>`;
  }
}

function renderJobsTable(rows) {
  const body = $("jobsBody");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5" class="td-empty">${
      jobFilter ? "В этой категории задач нет" : "Задач пока нет"
    }</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map((j) => {
      const p = pillFor(j.status);
      const bg = j.background ? ` · фон ${j.background}` : "";
      return `<tr data-job="${esc(j.job_id)}">
        <td>
          <div>${esc(j.title || "Без имени")}</div>
          <span class="mono-id">${esc(j.job_id)}</span>
        </td>
        <td>${esc(mockupLabel(j.mockup))}${bg}</td>
        <td>${esc(fmtTime(j.updated_at || j.created_at))}</td>
        <td><span class="pill ${p.cls}">${p.label}</span>${
        j.error ? `<div class="tl-desc">${esc(String(j.error).slice(0, 80))}</div>` : ""
      }</td>
        <td style="text-align:right">
          <button class="btn ghost sm" data-watch="${esc(j.job_id)}">Открыть</button>
        </td>
      </tr>`;
    })
    .join("");

  body.querySelectorAll("[data-watch]").forEach((b) =>
    b.addEventListener("click", () => openJobModal(b.dataset.watch))
  );
}

/* ---------- job details ---------- */
const FIELD_LABELS = [
  ["surname_ru", "Фамилия"],
  ["given_ru", "Имя и отчество"],
  ["birth_date", "Дата рождения"],
  ["birth_place_ru", "Место рождения"],
  ["issue_date", "Дата выдачи"],
  ["expiry_date", "Действительно до"],
  ["authority", "Кем выдано"],
  ["series", "Серия"],
  ["number", "Номер"],
  ["residence_ru", "Регион"],
  ["categories", "Категории"],
  ["back_number", "Номер (оборот)"],
];

function fieldRows(fields) {
  if (!fields || !Object.keys(fields).length) {
    return `<p class="note">Данные задачи недоступны.</p>`;
  }
  const rows = FIELD_LABELS.map(([key, label]) => {
    let v = fields[key];
    if (Array.isArray(v)) v = v.join(", ");
    if (v == null || v === "") return "";
    return `<tr><th>${esc(label)}</th><td>${esc(v)}</td></tr>`;
  })
    .filter(Boolean)
    .join("");
  return rows ? `<table class="kv">${rows}</table>` : `<p class="note">Поля не распознаны.</p>`;
}

async function openJobModal(jobId) {
  const row = cachedJobs.find((j) => j.job_id === jobId) || {};
  openModal("Задача", `<p class="note">Загружаем данные…</p>`);

  let data = {};
  try {
    data = await api(`/api/v1/render/${jobId}`);
  } catch (e) {
    data = { status: row.status, message: e.message, fields: {} };
  }

  const status = data.status || row.status || "pending";
  const p = pillFor(status);
  const pct = { pending: 25, processing: 65, done: 100, failed: 100 }[status] || 10;

  const explain =
    status === "pending"
      ? "Задача ждёт своей очереди. Отрисовка начнётся, когда подключится Photoshop."
      : status === "processing"
      ? "Photoshop сейчас собирает изображение."
      : status === "done"
      ? "Готово — файлы можно скачать."
      : data.message || row.error || "Отрисовка не удалась.";

  const meta = `<table class="kv">
      <tr><th>Идентификатор</th><td><span class="mono-id">${esc(jobId)}</span></td></tr>
      <tr><th>Мокап</th><td>${esc(mockupLabel(row.mockup || data.mockup))}${
    row.background ? ` · фон ${esc(row.background)}` : ""
  }</td></tr>
      <tr><th>Создана</th><td>${esc(fmtTime(row.created_at))}</td></tr>
      <tr><th>Обновлена</th><td>${esc(fmtTime(row.updated_at))}</td></tr>
    </table>`;

  const body = `
    <div class="job-modal-head">
      <span class="pill ${p.cls}">${p.label}</span>
      <span class="note">${esc(explain)}</span>
    </div>
    <div class="track"><div class="track-fill ${status === "failed" ? "failed" : ""}" style="width:${pct}%"></div></div>
    ${row.error || (status === "failed" && data.message) ? `<div class="inline-result bad">${esc(row.error || data.message)}</div>` : ""}
    <h4 class="sub-title">Данные документа</h4>
    ${fieldRows(data.fields)}
    <h4 class="sub-title">О задаче</h4>
    ${meta}
    ${data.jpg_path ? `<div class="preview" id="jobPreview"><img id="jobPreviewImg" alt="Превью"></div>` : ""}
  `;

  const foot =
    status === "done"
      ? `<button type="button" class="btn secondary" id="jobDlPsd">Скачать PSD</button>
         <button type="button" class="btn primary" id="jobDlJpg">Скачать JPG</button>`
      : `<button type="button" class="btn secondary" id="jobWatch">Следить за выполнением</button>
         <button type="button" class="btn primary" data-close-modal>Закрыть</button>`;

  openModal("Задача", body, foot);

  if (data.jpg_path) {
    fetch(`/api/v1/render/download/jpg?path=${encodeURIComponent(data.jpg_path)}`, {
      headers: headers(false),
    })
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => {
        if (b && $("jobPreviewImg")) $("jobPreviewImg").src = URL.createObjectURL(b);
      })
      .catch(() => {});
  }

  $("jobDlJpg")?.addEventListener("click", () => downloadFile(data.jpg_path, "jpg", "preview.jpg"));
  $("jobDlPsd")?.addEventListener("click", () => downloadFile(data.psd_path, "psb", "vu.psb"));
  $("jobWatch")?.addEventListener("click", () => {
    closeModal();
    startPolling(jobId);
    goto("render");
  });
}

async function downloadFile(path, kind, filename) {
  if (!path) return toast("Файл недоступен", "bad");
  try {
    const r = await fetch(`/api/v1/render/download/${kind}?path=${encodeURIComponent(path)}`, {
      headers: headers(false),
    });
    if (!r.ok) throw new Error("Не удалось скачать");
    const b = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(b);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (e) {
    toast(e.message, "bad");
  }
}

/* ============ RENDER STATUS ============ */
function pillFor(status) {
  const label = LABEL[status] || status || "—";
  const cls =
    status === "done" ? "ok" : status === "failed" ? "failed" : status === "processing" ? "processing" : "pending";
  return { label, cls };
}

function paintStatus(data) {
  const status = data.status || "pending";
  const { label, cls } = pillFor(status);
  const pct = { pending: 25, processing: 65, done: 100, failed: 100 }[status] || 10;

  const badge = $("renderBadge");
  badge.className = `pill ${cls}`;
  badge.innerHTML = `<span class="ic">${icon(
    status === "done" ? "circle-check" : status === "failed" ? "circle-alert" : "clock",
    13
  )}</span>${label}`;

  const fill = $("renderTrackFill");
  fill.style.width = pct + "%";
  fill.classList.toggle("failed", status === "failed");

  const steps = [
    { title: "Задача создана", desc: "Данные приняты", state: "done" },
    {
      title: status === "pending" ? "Ожидание сервера отрисовки" : "Передано в Photoshop",
      desc: status === "pending" ? "Задача в очереди" : "Задача взята в работу",
      state: status === "pending" ? "active" : "done",
    },
    {
      title: "Отрисовка мокапа",
      desc: status === "processing" ? "Photoshop подставляет текст и фон…" : "",
      state: status === "processing" ? "active" : status === "done" ? "done" : "",
    },
    {
      title: status === "failed" ? "Не удалось" : "Готово к скачиванию",
      desc: status === "done" ? "JPG и PSD сохранены" : status === "failed" ? data.message || "" : "",
      state: status === "done" ? "done" : status === "failed" ? "failed" : "",
    },
  ];

  $("renderSteps").innerHTML = steps
    .map(
      (s) =>
        `<div class="tl ${s.state}"><div><div class="tl-title">${esc(s.title)}</div>${
          s.desc ? `<div class="tl-desc">${esc(s.desc)}</div>` : ""
        }</div></div>`
    )
    .join("");

  const msg =
    status === "pending"
      ? "Задача в очереди. Отрисовка начнётся, когда подключится Photoshop worker."
      : status === "processing"
      ? "Photoshop обрабатывает мокап, подождите…"
      : status === "done"
      ? "Готово. Скачайте файлы ниже."
      : data.message || "Произошла ошибка при отрисовке.";
  $("renderMessage").textContent = msg;

  $("homeJobEmpty").hidden = true;
  $("homeJobBody").hidden = false;
  $("homeJobId").textContent = (activeJob || "").slice(0, 16);
  const hb = $("homeJobBadge");
  hb.className = `pill ${cls}`;
  hb.textContent = label;
  $("homeTrackFill").style.width = pct + "%";
  $("homeTrackFill").classList.toggle("failed", status === "failed");
  $("homeJobNote").textContent = msg;
}

function bindDownload(id, path, kind, filename) {
  const el = $(id);
  if (!el || !path) return;
  const url = `/api/v1/render/download/${kind}?path=${encodeURIComponent(path)}`;
  el.onclick = async (ev) => {
    ev.preventDefault();
    try {
      const r = await fetch(url, { headers: headers(false) });
      if (!r.ok) throw new Error("Не удалось скачать");
      const b = await r.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(b);
      a.download = filename;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      toast(e.message, "bad");
    }
  };
}

async function showPreview(path) {
  if (!path) return;
  try {
    const r = await fetch(`/api/v1/render/download/jpg?path=${encodeURIComponent(path)}`, {
      headers: headers(false),
    });
    if (!r.ok) return;
    $("renderPreviewImg").src = URL.createObjectURL(await r.blob());
    $("renderPreview").hidden = false;
  } catch {}
}

async function poll(jobId) {
  try {
    const data = await api(`/api/v1/render/${jobId}`);
    paintStatus(data);

    if (data.status === "done") {
      clearInterval(pollTimer);
      $("renderDownloads").hidden = false;
      $("homeJobActions").hidden = false;
      bindDownload("dlJpg", data.jpg_path, "jpg", "preview.jpg");
      bindDownload("dlPsd", data.psd_path, "psb", "vu.psb");
      bindDownload("homeDlJpg", data.jpg_path, "jpg", "preview.jpg");
      bindDownload("homeDlPsd", data.psd_path, "psb", "vu.psb");
      await showPreview(data.jpg_path);
      toast("Отрисовка завершена", "ok");
      localStorage.removeItem(STORE.job);
    } else if (data.status === "failed") {
      clearInterval(pollTimer);
      $("renderDownloads").hidden = true;
      localStorage.removeItem(STORE.job);
      toast("Отрисовка не удалась", "bad");
    }
  } catch (e) {
    $("renderMessage").textContent = "Не удалось получить статус: " + e.message;
  }
}

function startPolling(jobId) {
  clearInterval(pollTimer);
  activeJob = jobId;
  localStorage.setItem(STORE.job, jobId);
  $("renderStatus").hidden = false;
  $("renderDownloads").hidden = true;
  $("renderPreview").hidden = true;
  poll(jobId);
  pollTimer = setInterval(() => poll(jobId), 2000);
}

$("renderForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  saveForm();
  const btn = $("renderSubmit");
  btn.disabled = true;

  try {
    let portraitPath = null;
    const file = $("portraitFile").files?.[0];
    if (file) {
      const form = new FormData();
      form.append("file", file);
      const h = {};
      const k = apiKey();
      if (k) h["X-API-Key"] = k;
      const up = await fetch("/api/v1/portrait/upload", { method: "POST", headers: h, body: form });
      const ud = await up.json();
      if (!up.ok) throw new Error(ud.detail || "Ошибка загрузки портрета");
      portraitPath = ud.portrait_path;
    }

    const body = {
      text_block: $("renderText").value,
      mockup: selMockup.getValue(),
      background: Number(selBackground.getValue() || 1),
      generate_portrait: $("genPortrait").checked,
      portrait_path: portraitPath,
      wait: false,
    };

    $("renderStatus").hidden = false;
    $("homeJobActions").hidden = true;
    paintStatus({ status: "pending", message: "Отправка задачи…" });

    const data = await api("/api/v1/render", { method: "POST", body: JSON.stringify(body) });
    startPolling(data.job_id);
    toast("Задача поставлена в очередь");
  } catch (err) {
    paintStatus({ status: "failed", message: err.message });
    toast(err.message, "bad");
  } finally {
    btn.disabled = false;
  }
});

/* ============ SYSTEM ============ */
async function loadAdmin() {
  const alert = $("systemAlert");
  try {
    const data = await api("/api/v1/admin/dashboard");
    renderMetrics($("adminCards"), data);
    updateQueueCounts(data.queue || {});
    if (!data.server?.worker_alive) {
      alert.className = "banner warn";
      alert.innerHTML = `<span class="ic">${icon("triangle-alert", 16)}</span>
        <span>Сервер отрисовки не подключён. Запустите Photoshop worker на компьютере с Windows — до этого задачи будут ждать в очереди.</span>`;
      hydrate(alert);
      alert.classList.remove("hidden");
    } else {
      alert.classList.add("hidden");
    }
    markLoaded();
  } catch (e) {
    alert.className = "banner bad";
    alert.innerHTML = `<span class="ic">${icon("circle-alert", 16)}</span><span>${esc(e.message)}</span>`;
    hydrate(alert);
    alert.classList.remove("hidden");
  }
}

$("refreshAdmin").addEventListener("click", loadAdmin);

$("recoverStale").addEventListener("click", async () => {
  try {
    const d = await api("/api/v1/admin/recover-stale", { method: "POST" });
    toast(`Восстановлено задач: ${d.recovered ?? 0}`, "ok");
    loadAdmin();
  } catch (e) {
    toast(e.message, "bad");
  }
});

$("verifyScene").addEventListener("click", async () => {
  const box = $("sceneResult");
  const btn = $("verifyScene");
  box.hidden = false;
  box.className = "inline-result";
  box.textContent = "Читаем PSB-шаблоны, это может занять минуту…";
  btn.disabled = true;

  const deadline = Date.now() + 5 * 60 * 1000;
  try {
    let d = await api("/api/v1/render/scene/verify?refresh=true");
    while (d.status === "scanning" && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 2500));
      d = await api("/api/v1/render/scene/verify");
    }
    if (d.status === "scanning") {
      box.textContent = "Проверка ещё идёт. Загляните сюда чуть позже.";
    } else if (d.ok) {
      box.className = "inline-result ok";
      box.textContent = "Все мокапы и фоны настроены правильно.";
    } else {
      box.className = "inline-result bad";
      const bad = Object.values(d.templates || {})
        .filter((t) => !t.ok)
        .map((t) => t.mockup || t.template);
      box.textContent = "Есть проблемы: " + (bad.join(", ") || "проверьте PSB-файлы");
    }
  } catch (e) {
    box.className = "inline-result bad";
    box.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
});

$("extractBg").addEventListener("click", async () => {
  const box = $("extractResult");
  const btn = $("extractBg");
  box.hidden = false;
  box.className = "inline-result";
  box.textContent = "Извлекаем слои фонов из PSB…";
  btn.disabled = true;

  const deadline = Date.now() + 10 * 60 * 1000;
  try {
    const started = await api("/api/v1/mockups/backgrounds/extract", { method: "POST" });
    if (!started.started) {
      box.textContent = started.message || "Извлечение уже идёт";
    }
    let st = await api("/api/v1/mockups/backgrounds/extract/status");
    while (st.running && Date.now() < deadline) {
      box.textContent = `Извлекаем фоны… сохранено ${st.done || 0}${st.total ? " из " + st.total : ""}`;
      await new Promise((r) => setTimeout(r, 2000));
      st = await api("/api/v1/mockups/backgrounds/extract/status");
    }
    await loadBackgrounds();
    const data = await api("/api/v1/mockups/backgrounds");
    const n = (data.backgrounds || []).filter((b) => b.has_preview).length;
    if (n > 0) {
      box.className = "inline-result ok";
      box.textContent = `Готово. Превью доступно для ${n} фонов — откройте «Отрисовка» и выберите фон.`;
    } else {
      box.className = "inline-result bad";
      box.textContent =
        "Не удалось извлечь превью. Проверьте, что PSB на месте и установлен psd_tools, либо положите файлы 1.jpg…10.jpg в assets/backgrounds/.";
    }
  } catch (e) {
    box.className = "inline-result bad";
    box.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
});

/* ============ SETTINGS ============ */
$("saveKey").addEventListener("click", () => {
  localStorage.setItem(STORE.key, $("apiKey").value || "");
  toast("Ключ сохранён", "ok");
  refreshAll();
});

$("clearLocal").addEventListener("click", () => {
  Object.values(STORE).forEach((k) => localStorage.removeItem(k));
  toast("Сохранённые данные очищены", "ok");
  setTimeout(() => location.reload(), 600);
});

/* ============ INIT ============ */
(function init() {
  hydrate(document);

  selRegion = VuSelect($("selRegion"), {
    name: "region_code",
    searchable: true,
    searchPlaceholder: "Код или название региона…",
    placeholder: "Любой регион",
    value: "",
    options: [{ value: "", label: "Любой регион", hint: "Выбирается случайно" }],
  });

  selMockup = VuSelect($("selMockup"), {
    name: "mockup",
    placeholder: "Выберите мокап",
    value: "hand",
    options: MOCKUPS.map((m) => ({ value: m.value, label: m.label, hint: m.hint })),
    onChange: () => {
      syncMockup();
      saveForm();
    },
  });

  selBackground = VuSelect($("selBackground"), {
    name: "background",
    grid: true,
    searchable: true,
    searchPlaceholder: "Номер фона…",
    placeholder: "Выберите фон",
    value: "1",
    options: [],
    onChange: saveForm,
  });

  const savedKey = localStorage.getItem(STORE.key);
  if (savedKey) $("apiKey").value = savedKey;

  const f = readJSON(STORE.form, null);
  if (f) {
    if (f.text) $("renderText").value = f.text;
    if (f.mockup) selMockup.setValue(f.mockup);
    $("genPortrait").checked = !!f.portrait;
  }

  if (localStorage.getItem(STORE.collapsed) === "1") setCollapsed(true);

  if (localStorage.getItem(STORE.started) === "1") {
    $("getStarted").classList.add("hidden");
    $("startHead").classList.add("hidden");
  }

  const ms = Number(localStorage.getItem(STORE.interval) ?? 15000);
  $("refreshRange")
    .querySelectorAll("button")
    .forEach((b) => b.classList.toggle("on", Number(b.dataset.ms) === ms));
  setAutoRefresh(ms);

  loadRegions();
  loadBackgrounds().then(syncMockup);
  loadHome();
  loadJobs();
  syncFilterChips();

  const saved = localStorage.getItem(STORE.job);
  if (saved) startPolling(saved);
})();
