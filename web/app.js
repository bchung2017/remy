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
  voice: (id, file) => { const fd = new FormData(); fd.append("file", file, file.name || "memo.webm"); return api.req("POST", `/recipes/${id}/voice`, fd, true); },
};
const health = api.req("GET", "/health").catch(() => ({}));

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

// ---------- notebook page ----------
function blockHtml(b) {
  if (b.type === "image") return `
    <figure class="block block-image" data-id="${esc(b.id)}">
      <img src="/api/assets/${esc(b.asset)}" alt="${esc(b.caption)}">
      <figcaption><input class="caption" placeholder="Caption" value="${esc(b.caption)}" aria-label="Caption"></figcaption>
      <button class="x" title="Remove" aria-label="Remove block">×</button>
    </figure>`;
  if (b.type === "ai") return `
    <div class="block block-ai" data-id="${esc(b.id)}">
      <div class="ai-head"><span class="label">AI</span>${b.asset ? `<audio controls preload="none" src="/api/assets/${esc(b.asset)}"></audio>` : ""}</div>
      <textarea class="text" rows="1" aria-label="Recipe text">${esc(b.text)}</textarea>
      <button class="x" title="Remove" aria-label="Remove block">×</button>
    </div>`;
  if (b.type === "pending") return `
    <div class="block block-ai pending" data-id="${esc(b.id)}">
      <div class="ai-head"><span class="label">AI</span><span class="hint">${esc(b.note)}</span></div>
    </div>`;
  return `
    <div class="block block-text" data-id="${esc(b.id)}">
      <textarea class="text" rows="1" placeholder="Write here" aria-label="Text">${esc(b.text)}</textarea>
      <button class="x" title="Remove" aria-label="Remove block">×</button>
    </div>`;
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
    <article class="page">
      <header class="page-head">
        <input class="title display-lg" id="title" value="${esc(r.title)}" placeholder="Untitled" aria-label="Title">
        <div class="page-meta">
          <input class="tagsin" id="tags" value="${esc(r.tags.join(", "))}" placeholder="tags, comma separated" aria-label="Tags">
          <span class="status" id="status">${when(r.updatedAt)}</span>
        </div>
      </header>
      <div class="blocks" id="blocks">${r.blocks.map(blockHtml).join("")}</div>
      <div class="adders">
        <button class="btn" id="add-text">Text</button>
        <label class="btn" for="add-image">Image</label>
        <input id="add-image" type="file" accept="image/*" hidden>
        ${h.voice ? `<label class="btn" for="add-ai">AI</label><input id="add-ai" type="file" accept="audio/*,video/mp4,.m4a" hidden>` : ""}
      </div>
      <p class="error" id="err" hidden></p>
      <footer class="page-foot">
        <button class="btn btn-danger" id="del">Delete recipe</button>
        <a class="btn btn-ghost" href="#/">Back</a>
      </footer>
    </article>`;

  const blocksEl = view.querySelector("#blocks");
  const status = view.querySelector("#status");
  const err = (msg) => { const el = view.querySelector("#err"); el.textContent = msg; el.hidden = !msg; };

  // the page's state is the DOM; read blocks back out of it on save
  const readBlocks = () => [...blocksEl.querySelectorAll(".block")].map((el) => {
    const id = el.dataset.id;
    if (el.classList.contains("pending")) return null;
    if (el.classList.contains("block-image")) return { id, type: "image", asset: el.querySelector("img").getAttribute("src").split("/").pop(), caption: el.querySelector(".caption").value };
    if (el.classList.contains("block-ai")) { const a = el.querySelector("audio"); return { id, type: "ai", text: el.querySelector(".text").value, asset: a ? a.getAttribute("src").split("/").pop() : null, transcript: el.dataset.transcript || "" }; }
    return { id, type: "text", text: el.querySelector(".text").value };
  }).filter(Boolean);
  blocksEl.querySelectorAll(".block-ai[data-id]").forEach((el) => { const b = r.blocks.find((x) => x.id === el.dataset.id); if (b) el.dataset.transcript = b.transcript || ""; });

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

  const wire = (el) => {
    el.querySelectorAll("textarea").forEach((ta) => { grow(ta); ta.addEventListener("input", () => { grow(ta); saveSoon(); }); ta.addEventListener("blur", save); });
    el.querySelectorAll("input.caption").forEach((i) => { i.addEventListener("input", saveSoon); i.addEventListener("blur", save); });
    el.querySelectorAll(".x").forEach((x) => x.addEventListener("click", () => { x.closest(".block").remove(); save(); }));
  };
  wire(blocksEl);
  ["#title", "#tags"].forEach((sel) => { const i = view.querySelector(sel); i.addEventListener("input", saveSoon); i.addEventListener("blur", save); });

  const append = (b) => { blocksEl.insertAdjacentHTML("beforeend", blockHtml(b)); const el = blocksEl.lastElementChild; wire(el); return el; };

  view.querySelector("#add-text").addEventListener("click", () => { append({ id: uid(), type: "text", text: "" }).querySelector("textarea").focus(); save(); });

  view.querySelector("#add-image").addEventListener("change", async (e) => {
    const file = e.target.files[0]; e.target.value = ""; if (!file) return;
    status.textContent = "Uploading…"; err("");
    try {
      const a = await api.upload(id, await shrinkImage(file));
      append({ id: uid(), type: "image", asset: a.id, caption: "" });
      await save();
    } catch (ex) { status.textContent = "Not saved"; err(ex.message); }
  });

  const ai = view.querySelector("#add-ai");
  if (ai) ai.addEventListener("change", async (e) => {
    const file = e.target.files[0]; e.target.value = ""; if (!file) return;
    await save();   // flush edits first; the server appends to the stored page
    const ph = append({ id: "pending-" + uid(), type: "pending", note: "Transcribing and formatting…" });
    err("");
    try {
      r = await api.voice(id, file);
      ph.remove();
      const blk = r.blocks[r.blocks.length - 1];
      const el = append(blk); el.dataset.transcript = blk.transcript || "";
      view.querySelector("#title").value = r.title; view.querySelector("#tags").value = r.tags.join(", ");
      status.textContent = "Saved";
    } catch (ex) { ph.remove(); err(ex.message); }
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
