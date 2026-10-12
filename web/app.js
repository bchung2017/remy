// remy — notebook-style recipe pages. Hash-routed, no build step.
// #/ browse · #/r/:id one notebook page (edited in place, autosaved)
const view = document.getElementById("view");

const api = {
  async req(method, path, body, isForm) {
    const r = await fetch("/api" + path, {
      method,
      headers: body && !isForm ? { "content-type": "application/json" } : undefined,
      body: isForm ? body : body ? JSON.stringify(body) : undefined,
    });
    if (r.status === 204) return null;
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || r.statusText);
    return data;
  },
  list: (params) => api.req("GET", "/recipes?" + new URLSearchParams(params)),
  tags: () => api.req("GET", "/tags"),
  get: (id) => api.req("GET", "/recipes/" + id),
  create: (b) => api.req("POST", "/recipes", b),
  update: (id, b) => api.req("PUT", "/recipes/" + id, b),
  remove: (id) => api.req("DELETE", "/recipes/" + id),
  upload: (id, file) => { const fd = new FormData(); fd.append("file", file, file.name || "image.jpg"); return api.req("POST", `/recipes/${id}/assets`, fd, true); },
  draft: (b) => api.req("POST", "/recipes/draft", b),
};
const health = api.req("GET", "/health").catch(() => ({}));
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;   // browser speech-to-text; Chrome, Edge, iOS Safari

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const when = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "");
const uid = () => (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "") : Date.now().toString(36) + Math.random().toString(36).slice(2));

// ---------- browse ----------
const browse = { q: "", tag: "", sort: "updated" };
try { Object.assign(browse, JSON.parse(sessionStorage.getItem("remy.browse") || "{}")); } catch {}
const saveBrowse = () => { try { sessionStorage.setItem("remy.browse", JSON.stringify(browse)); } catch {} };

function listHtml(recipes) {
  if (!recipes.length) return `<p class="empty">${browse.q || browse.tag ? "No matches." : "No recipes yet."}</p>`;
  return `<ul class="list">${recipes.map((r) => {
    const img = r.blocks.find((b) => b.type === "image");
    return `<li><a class="card" href="#/r/${r.id}">
      ${img ? `<img class="thumb" src="/api/assets/${esc(img.asset)}" alt="">` : ""}
      <div class="card-text">
        <h3>${esc(r.title)}</h3>
        ${r.body ? `<p>${esc(r.body.slice(0, 240))}</p>` : ""}
        <div class="meta"><span>${when(r.updatedAt)}</span>${r.tags.map((t) => `<span>#${esc(t)}</span>`).join("")}</div>
      </div></a></li>`; }).join("")}</ul>`;
}

async function renderBrowse() {
  const [recipes, tags] = await Promise.all([api.list(browse), api.tags()]);
  view.innerHTML = `
    <div class="toolbar">
      <input id="q" type="search" placeholder="Search" value="${esc(browse.q)}" aria-label="Search recipes">
      <select id="sort" aria-label="Sort">
        <option value="updated" ${browse.sort === "updated" ? "selected" : ""}>Recently updated</option>
        <option value="created" ${browse.sort === "created" ? "selected" : ""}>Newest</option>
        <option value="title" ${browse.sort === "title" ? "selected" : ""}>Title</option>
      </select>
    </div>
    ${tags.length ? `<div class="tags">${tags.map((t) =>
      `<button class="tag ${browse.tag === t.tag ? "on" : ""}" data-tag="${esc(t.tag)}">${esc(t.tag)} ${t.count}</button>`).join("")}</div>` : ""}
    <div id="list">${listHtml(recipes)}</div>`;
  const q = view.querySelector("#q");
  let timer;
  const refresh = async () => { view.querySelector("#list").innerHTML = listHtml(await api.list(browse)); };
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { browse.q = q.value; saveBrowse(); refresh(); }, 200); });
  view.querySelector("#sort").addEventListener("change", (e) => { browse.sort = e.target.value; saveBrowse(); refresh(); });
  view.querySelectorAll(".tag").forEach((b) => b.addEventListener("click", () => {
    browse.tag = browse.tag === b.dataset.tag ? "" : b.dataset.tag; saveBrowse(); renderBrowse();
  }));
}

// ---------- notebook page (Jupyter-style cells) ----------
const TYPE_LABEL = { text: "Text", image: "Image", ai: "AI" };

function cellHtml(b, n) {
  const gutter = `<div class="gutter"><span class="kind">${TYPE_LABEL[b.type] || "AI"}</span><span class="num">[${n}]</span></div>`;
  const tools = `<div class="cell-tools">
      <button data-act="up" title="Move up" aria-label="Move up">↑</button>
      <button data-act="down" title="Move down" aria-label="Move down">↓</button>
      <button data-act="del" title="Delete cell" aria-label="Delete cell">×</button>
    </div>`;
  let body;
  if (b.type === "image") body = `
    <div class="cell-in">
      <img src="/api/assets/${esc(b.asset)}" alt="${esc(b.caption)}">
      <input class="caption" placeholder="Caption" value="${esc(b.caption)}" aria-label="Caption">
    </div>`;
  else if (b.type === "ai" && b.draft) body = `
    <div class="cell-in ai-in">
      <div class="ai-row">
        ${SR ? `<button class="btn btn-sm dictate">● Dictate</button>` : `<span class="hint">No speech recognition in this browser. Type instead.</span>`}
        <span class="interim hint"></span>
        <button class="btn btn-sm btn-primary run" disabled>▶ Run</button>
      </div>
      <textarea class="transcript" rows="1" placeholder="Say the recipe the way you'd tell a friend. Edit here before running." aria-label="Transcript"></textarea>
    </div>
    <div class="cell-out hint" hidden></div>`;
  else if (b.type === "ai") body = `
    <div class="cell-in ai-in"><details class="transcript-view"><summary class="hint">Transcript</summary><p>${esc(b.transcript)}</p></details></div>
    <div class="cell-out"><textarea class="text" rows="1" aria-label="Formatted recipe">${esc(b.text)}</textarea></div>`;
  else body = `
    <div class="cell-in"><textarea class="text" rows="1" placeholder="Write here" aria-label="Text">${esc(b.text)}</textarea></div>`;
  return `<section class="cell cell-${b.type} ${b.draft ? "draft" : ""}" data-id="${esc(b.id)}" data-type="${b.type}" tabindex="-1">${gutter}<div class="cell-body">${body}</div>${tools}</section>`;
}

const grow = (ta) => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; };

// shrink camera photos before upload: max 1600px edge, JPEG
async function shrinkImage(file) {
  if (!file.type.startsWith("image/") || file.type === "image/gif") return file;
  const bmp = await createImageBitmap(file).catch(() => null);
  if (!bmp) return file;
  const max = 1600, scale = Math.min(1, max / Math.max(bmp.width, bmp.height));
  if (scale === 1 && file.size < 1.5e6) return file;
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * scale); c.height = Math.round(bmp.height * scale);
  c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
  const blob = await new Promise((res) => c.toBlob(res, "image/jpeg", 0.85));
  return blob ? new File([blob], (file.name || "photo").replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }) : file;
}

async function renderRecipe(id) {
  let r;
  try { r = await api.get(id); } catch { view.innerHTML = `<p class="empty">Not found. <a href="#/">Back</a></p>`; return; }
  const h = await health;
  let saveTimer, saving = Promise.resolve();

  view.innerHTML = `
    <article class="nb">
      <header class="nb-head">
        <input class="title display-lg" id="title" value="${esc(r.title)}" placeholder="Untitled" aria-label="Title">
        <div class="nb-meta">
          <input class="tagsin" id="tags" value="${esc(r.tags.join(", "))}" placeholder="tags, comma separated" aria-label="Tags">
          <span class="status" id="status">${when(r.updatedAt)}</span>
        </div>
      </header>
      <div class="nb-toolbar" role="toolbar" aria-label="Cells">
        <button class="btn btn-sm" data-add="text">+ Text</button>
        <label class="btn btn-sm" for="add-image">+ Image</label>
        <input id="add-image" type="file" accept="image/*" hidden>
        ${h.draft ? `<button class="btn btn-sm" data-add="ai">+ AI</button>` : `<button class="btn btn-sm" disabled title="Set ANTHROPIC_API_KEY to enable">+ AI</button>`}
        <span class="sep"></span>
        <button class="btn btn-sm btn-ghost" id="t-up" title="Move cell up">↑</button>
        <button class="btn btn-sm btn-ghost" id="t-down" title="Move cell down">↓</button>
        <button class="btn btn-sm btn-ghost" id="t-del" title="Delete cell">× cell</button>
      </div>
      <div class="cells" id="cells">${r.blocks.map((b, i) => cellHtml(b, i + 1)).join("")}</div>
      <p class="empty" id="nocells" ${r.blocks.length ? "hidden" : ""}>Empty notebook. Add a cell above.</p>
      <p class="error" id="err" hidden></p>
      <footer class="nb-foot">
        <button class="btn btn-danger" id="del">Delete recipe</button>
        <a class="btn btn-ghost" href="#/">Back</a>
      </footer>
    </article>`;

  const cellsEl = view.querySelector("#cells");
  const status = view.querySelector("#status");
  const err = (msg) => { const el = view.querySelector("#err"); el.textContent = msg; el.hidden = !msg; };
  const transcripts = Object.fromEntries(r.blocks.filter((b) => b.type === "ai").map((b) => [b.id, b.transcript || ""]));

  // --- state lives in the DOM; blocks are read back in order on save (draft AI cells are skipped) ---
  const readBlocks = () => [...cellsEl.querySelectorAll(".cell:not(.draft)")].map((el) => {
    const id = el.dataset.id, type = el.dataset.type;
    if (type === "image") return { id, type, asset: el.querySelector("img").getAttribute("src").split("/").pop(), caption: el.querySelector(".caption").value };
    if (type === "ai") return { id, type, text: el.querySelector(".text").value, transcript: transcripts[id] || "" };
    return { id, type, text: el.querySelector(".text").value };
  });
  const renumber = () => {
    const cells = cellsEl.querySelectorAll(".cell");
    cells.forEach((el, i) => { el.querySelector(".num").textContent = `[${i + 1}]`; });
    view.querySelector("#nocells").hidden = cells.length > 0;
  };
  const save = () => {
    clearTimeout(saveTimer);
    status.textContent = "Saving…";
    saving = saving.then(async () => {
      try {
        r = await api.update(id, { title: view.querySelector("#title").value, tags: view.querySelector("#tags").value, blocks: readBlocks() });
        status.textContent = "Saved"; err("");
      } catch (e) { status.textContent = "Not saved"; err(e.message); }
    });
    return saving;
  };
  const saveSoon = () => { clearTimeout(saveTimer); status.textContent = "Editing"; saveTimer = setTimeout(save, 700); };

  // --- selection ---
  let selected = null;
  const select = (el) => { selected?.classList.remove("selected"); selected = el; el?.classList.add("selected"); };
  cellsEl.addEventListener("focusin", (e) => { const c = e.target.closest(".cell"); if (c) select(c); });
  cellsEl.addEventListener("mousedown", (e) => { const c = e.target.closest(".cell"); if (c) select(c); });

  const move = (el, dir) => {
    if (!el) return;
    const sib = dir < 0 ? el.previousElementSibling : el.nextElementSibling;
    if (!sib) return;
    dir < 0 ? sib.before(el) : sib.after(el);
    renumber(); el.focus({ preventScroll: true }); el.scrollIntoView({ block: "nearest" }); save();
  };
  const remove = (el) => {
    if (!el) return;
    const next = el.nextElementSibling || el.previousElementSibling;
    el.remove(); renumber(); select(next); next?.focus({ preventScroll: true });
    if (!el.classList.contains("draft")) save();
  };

  // --- wiring per cell ---
  const wire = (el) => {
    el.querySelectorAll("textarea").forEach((ta) => { grow(ta); ta.addEventListener("input", () => { grow(ta); saveSoon(); }); ta.addEventListener("blur", save); });
    el.querySelectorAll("input.caption").forEach((i) => { i.addEventListener("input", saveSoon); i.addEventListener("blur", save); });
    el.querySelectorAll(".cell-tools button").forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation();
      const act = b.dataset.act;
      if (act === "up") move(el, -1); else if (act === "down") move(el, 1); else remove(el);
    }));
    const run = el.querySelector(".run");
    if (run) {
      const ta = el.querySelector(".transcript"), out = el.querySelector(".cell-out"), mic = el.querySelector(".dictate"), interim = el.querySelector(".interim");
      let rec = null;
      const refresh = () => { run.disabled = !ta.value.trim(); grow(ta); };
      ta.addEventListener("input", refresh);
      if (mic) mic.addEventListener("click", () => {
        if (rec) { rec.stop(); return; }
        rec = new SR(); rec.continuous = true; rec.interimResults = true; rec.lang = navigator.language || "en-US";
        rec.onresult = (e) => {
          let live = "";
          for (let i = e.resultIndex; i < e.results.length; i++) {
            const t = e.results[i][0].transcript;
            if (e.results[i].isFinal) ta.value = (ta.value.trimEnd() + " " + t.trim()).trim(); else live += t;
          }
          interim.textContent = live; refresh();
        };
        rec.onerror = (e) => { if (e.error !== "no-speech" && e.error !== "aborted") err("Microphone: " + e.error); };
        rec.onend = () => { rec = null; mic.textContent = "● Dictate"; mic.classList.remove("live"); interim.textContent = ""; };
        rec.start(); mic.textContent = "■ Stop"; mic.classList.add("live"); err("");
      });
      run.addEventListener("click", async () => {
        if (rec) rec.stop();
        const transcript = ta.value.trim(); if (!transcript) return;
        run.disabled = true; run.textContent = "Running…"; out.hidden = false; out.textContent = "Formatting with Claude…"; err("");
        const title = view.querySelector("#title").value.trim();
        try {
          const d = await api.draft({ transcript, title: title === "Untitled" ? "" : title });
          const blk = { id: uid(), type: "ai", text: d.body, transcript };
          transcripts[blk.id] = transcript;
          el.insertAdjacentHTML("afterend", cellHtml(blk, 0));
          const real = el.nextElementSibling; wire(real); el.remove(); renumber(); select(real);
          if (!title || title === "Untitled") view.querySelector("#title").value = d.title;
          if (!view.querySelector("#tags").value.trim()) view.querySelector("#tags").value = d.tags.join(", ");
          await save();
        } catch (ex) {
          err(ex.message); out.textContent = "Failed: " + ex.message; run.disabled = false; run.textContent = "▶ Run";
        }
      });
    }
  };
  cellsEl.querySelectorAll(".cell").forEach(wire);
  ["#title", "#tags"].forEach((sel) => { const i = view.querySelector(sel); i.addEventListener("input", saveSoon); i.addEventListener("blur", save); });

  // insert after the selected cell, else at the end
  const insert = (b) => {
    const html = cellHtml(b, 0);
    if (selected && selected.parentElement === cellsEl) selected.insertAdjacentHTML("afterend", html);
    else cellsEl.insertAdjacentHTML("beforeend", html);
    const el = selected?.parentElement === cellsEl ? selected.nextElementSibling : cellsEl.lastElementChild;
    wire(el); renumber(); select(el);
    (el.querySelector("textarea.text, textarea.transcript") || el).focus({ preventScroll: true }); el.scrollIntoView({ block: "nearest" });
    return el;
  };
  view.querySelectorAll("[data-add]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.add === "text") { insert({ id: uid(), type: "text", text: "" }); save(); }
    else insert({ id: "draft-" + uid(), type: "ai", draft: true });
  }));
  view.querySelector("#add-image").addEventListener("change", async (e) => {
    const file = e.target.files[0]; e.target.value = ""; if (!file) return;
    status.textContent = "Uploading…"; err("");
    try {
      const a = await api.upload(id, await shrinkImage(file));
      insert({ id: uid(), type: "image", asset: a.id, caption: "" });
      await save();
    } catch (ex) { status.textContent = "Not saved"; err(ex.message); }
  });
  view.querySelector("#t-up").addEventListener("click", () => move(selected, -1));
  view.querySelector("#t-down").addEventListener("click", () => move(selected, 1));
  view.querySelector("#t-del").addEventListener("click", () => remove(selected));

  // keyboard: with a cell selected and no field focused, j/k or arrows move selection, shift+arrows move the cell, d deletes
  view.querySelector(".nb").addEventListener("keydown", (e) => {
    const inField = /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName);
    if (e.key === "Escape" && inField) { document.activeElement.blur(); selected?.focus(); return; }
    if (inField || !selected) return;
    if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); e.shiftKey ? move(selected, -1) : (selected.previousElementSibling && (select(selected.previousElementSibling), selected.focus())); }
    else if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); e.shiftKey ? move(selected, 1) : (selected.nextElementSibling && (select(selected.nextElementSibling), selected.focus())); }
    else if (e.key === "Enter") { e.preventDefault(); (selected.querySelector("textarea, input.caption") || selected).focus(); }
    else if (e.key === "d" || e.key === "Delete") { e.preventDefault(); remove(selected); }
  });

  const del = view.querySelector("#del");
  del.addEventListener("click", () => {
    del.outerHTML = `<span class="confirm">Delete this recipe? <button class="btn btn-danger" id="yes">Delete</button><button class="btn btn-ghost" id="no">Keep</button></span>`;
    view.querySelector("#yes").addEventListener("click", async () => { await api.remove(id); location.hash = "#/"; });
    view.querySelector("#no").addEventListener("click", () => renderRecipe(id));
  });

  if (r.title === "Untitled" && !r.blocks.length) view.querySelector("#title").select();
}

async function newRecipe() {
  const r = await api.create({});
  location.replace("#/r/" + r.id);
}

function route() {
  const h = location.hash || "#/";
  let m;
  if (h === "#/" || h === "#") return renderBrowse();
  if (h === "#/new") return newRecipe();
  if ((m = h.match(/^#\/r\/(\d+)$/))) return renderRecipe(m[1]);
  location.hash = "#/";
}
window.addEventListener("hashchange", route);
route();
