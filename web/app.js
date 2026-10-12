// remy — tiny hash-routed recipe app. No build step, no framework.
const view = document.getElementById("view");

const api = {
  async req(method, path, body) {
    const r = await fetch("/api" + path, {
      method,
      headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
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
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const when = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "");

// browse state survives navigation within the session
const browse = { q: "", tag: "", sort: "updated" };
try { Object.assign(browse, JSON.parse(sessionStorage.getItem("remy.browse") || "{}")); } catch {}
const saveBrowse = () => { try { sessionStorage.setItem("remy.browse", JSON.stringify(browse)); } catch {} };

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
    ${recipes.length ? `<ul class="list">${recipes.map((r) => `
      <li><a class="card" href="#/r/${r.id}">
        <h3>${esc(r.title)}</h3>
        ${r.body ? `<p>${esc(r.body.slice(0, 240))}</p>` : ""}
        <div class="meta"><span>${when(r.updatedAt)}</span>${r.tags.map((t) => `<span>#${esc(t)}</span>`).join("")}</div>
      </a></li>`).join("")}</ul>`
      : `<p class="empty">${browse.q || browse.tag ? "No matches." : "No recipes yet."}</p>`}
  `;
  const q = view.querySelector("#q");
  let timer;
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { browse.q = q.value; saveBrowse(); refreshList(); }, 200); });
  view.querySelector("#sort").addEventListener("change", (e) => { browse.sort = e.target.value; saveBrowse(); refreshList(); });
  view.querySelectorAll(".tag").forEach((b) => b.addEventListener("click", () => {
    browse.tag = browse.tag === b.dataset.tag ? "" : b.dataset.tag; saveBrowse(); renderBrowse();
  }));
}

// re-render only the list + tag states, keeping focus in the search box
async function refreshList() {
  const recipes = await api.list(browse);
  const old = view.querySelector(".list, .empty");
  const tmp = document.createElement("div");
  tmp.innerHTML = recipes.length ? `<ul class="list">${recipes.map((r) => `
      <li><a class="card" href="#/r/${r.id}">
        <h3>${esc(r.title)}</h3>
        ${r.body ? `<p>${esc(r.body.slice(0, 240))}</p>` : ""}
        <div class="meta"><span>${when(r.updatedAt)}</span>${r.tags.map((t) => `<span>#${esc(t)}</span>`).join("")}</div>
      </a></li>`).join("")}</ul>`
    : `<p class="empty">${browse.q || browse.tag ? "No matches." : "No recipes yet."}</p>`;
  old.replaceWith(tmp.firstElementChild);
}

async function renderRecipe(id) {
  let r;
  try { r = await api.get(id); } catch { view.innerHTML = `<p class="empty">Not found. <a href="#/">Back</a></p>`; return; }
  view.innerHTML = `
    <article class="recipe">
      <h1>${esc(r.title)}</h1>
      <div class="meta"><span>updated ${when(r.updatedAt)}</span>${r.tags.map((t) => `<a class="tag" href="#/" data-tag="${esc(t)}">${esc(t)}</a>`).join("")}</div>
      <pre>${esc(r.body)}</pre>
      <div class="actions">
        <a class="btn" href="#/r/${r.id}/edit">Edit</a>
        <button class="btn btn-danger" id="del">Delete</button>
        <a class="btn btn-ghost" href="#/">Back</a>
      </div>
    </article>`;
  view.querySelectorAll(".meta .tag").forEach((a) => a.addEventListener("click", () => { browse.tag = a.dataset.tag; browse.q = ""; saveBrowse(); }));
  const del = view.querySelector("#del");
  del.addEventListener("click", () => {
    del.outerHTML = `<span class="confirm">Delete this recipe? <button class="btn btn-danger" id="yes">Delete</button><button class="btn btn-ghost" id="no">Keep</button></span>`;
    view.querySelector("#yes").addEventListener("click", async () => { await api.remove(r.id); location.hash = "#/"; });
    view.querySelector("#no").addEventListener("click", () => renderRecipe(id));
  });
}

async function renderForm(id) {
  let r = { title: "", body: "", tags: [] };
  if (id) { try { r = await api.get(id); } catch { view.innerHTML = `<p class="empty">Not found. <a href="#/">Back</a></p>`; return; } }
  view.innerHTML = `
    <form class="form" id="f">
      <div class="row"><label for="title">Title</label><input id="title" required maxlength="200" value="${esc(r.title)}"></div>
      <div class="row"><label for="body">Recipe</label><textarea id="body">${esc(r.body)}</textarea></div>
      <div class="row"><label for="tags">Tags</label><input id="tags" value="${esc(r.tags.join(", "))}" placeholder="comma separated"><span class="hint">Optional.</span></div>
      <p class="error" id="err" hidden></p>
      <div class="actions" style="margin-top:0;border:0;padding:0">
        <button class="btn btn-primary" type="submit">${id ? "Save" : "Create"}</button>
        <a class="btn btn-ghost" href="${id ? `#/r/${id}` : "#/"}">Cancel</a>
      </div>
    </form>`;
  const f = view.querySelector("#f");
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { title: f.title.value, body: f.body.value, tags: f.tags.value };
    try {
      const saved = id ? await api.update(id, body) : await api.create(body);
      location.hash = `#/r/${saved.id}`;
    } catch (err) {
      const el = view.querySelector("#err"); el.textContent = err.message; el.hidden = false;
    }
  });
  f.title.focus();
}

function route() {
  const h = location.hash || "#/";
  let m;
  if (h === "#/" || h === "#") return renderBrowse();
  if (h === "#/new") return renderForm(null);
  if ((m = h.match(/^#\/r\/(\d+)\/edit$/))) return renderForm(m[1]);
  if ((m = h.match(/^#\/r\/(\d+)$/))) return renderRecipe(m[1]);
  location.hash = "#/";
}
window.addEventListener("hashchange", route);
route();
