// ShopLens storefront. All data comes from the local JSON API, which runs on the same search engine RootSight monitors.
"use strict";

const TEXT = {
  US: { lang: "en", deliver: "Deliver to", device: "Shopping on", all: "All", cart: "Cart", cartTitle: "Shopping Cart", search: "Search ShopLens",
        nav: ["☰ All", "Today's Deals", "Customer Service", "Registry", "Gift Cards", "Sell"], heroTitle: "Black Friday Week",
        heroText: "Deals on thousands of products, delivered fast.", popular: "Popular searches", picks: "Top picks for", results: "results for",
        over: "over", sort: ["Featured", "Price: Low to High", "Price: High to Low", "Avg. Customer Review"], add: "Add to Cart",
        unavailable: "Currently unavailable", inStock: "In Stock", left: n => `Only ${n} left in stock`, sponsored: "Sponsored",
        fast: "FREE delivery Tomorrow", standard: "Delivery in 3-5 days", noResults: "No results for", noHint: "Try checking your spelling or use more general terms.",
        fStock: "Availability", fInStock: "Include only in-stock items", fPrice: "Price", fGo: "Go", fRating: "Customer Reviews", fAny: "Any",
        fUp: "& Up", fDelivery: "Delivery", fFast: "Fast delivery", fBrand: "Brand", added: "Added to Cart", sorry: "Sorry, this item is currently unavailable.",
        priceChanged: p => `The price changed to €${p}.`, empty: "Your ShopLens Cart is empty.", subtotal: "Subtotal", checkout: "Proceed to checkout",
        ordered: "Thank you, your order has been placed (demo).", top: "Back to top", about: "About this item" },
  DE: { lang: "de", deliver: "Liefern nach", device: "Einkaufen über", all: "Alle", cart: "Einkaufswagen", cartTitle: "Einkaufswagen", search: "ShopLens durchsuchen",
        nav: ["☰ Alle", "Angebote", "Kundenservice", "Wunschlisten", "Gutscheine", "Verkaufen"], heroTitle: "Black-Friday-Woche",
        heroText: "Angebote für tausende Produkte, schnell geliefert.", popular: "Beliebte Suchen", picks: "Empfehlungen für", results: "Ergebnisse für",
        over: "mehr als", sort: ["Empfohlen", "Preis: aufsteigend", "Preis: absteigend", "Kundenbewertung"], add: "In den Einkaufswagen",
        unavailable: "Derzeit nicht verfügbar", inStock: "Auf Lager", left: n => `Nur noch ${n} auf Lager`, sponsored: "Gesponsert",
        fast: "GRATIS Lieferung morgen", standard: "Lieferung in 3-5 Tagen", noResults: "Keine Ergebnisse für", noHint: "Prüfe die Schreibweise oder verwende allgemeinere Begriffe.",
        fStock: "Verfügbarkeit", fInStock: "Nur Artikel auf Lager", fPrice: "Preis", fGo: "Los", fRating: "Kundenbewertung", fAny: "Alle",
        fUp: "& mehr", fDelivery: "Lieferung", fFast: "Schnelle Lieferung", fBrand: "Marke", added: "Zum Einkaufswagen hinzugefügt", sorry: "Dieser Artikel ist derzeit leider nicht verfügbar.",
        priceChanged: p => `Der Preis hat sich auf €${p} geändert.`, empty: "Dein Einkaufswagen ist leer.", subtotal: "Zwischensumme", checkout: "Zur Kasse gehen",
        ordered: "Vielen Dank, deine Bestellung wurde aufgegeben (Demo).", top: "Zurück zum Seitenanfang", about: "Über diesen Artikel" },
  ES: { lang: "es", deliver: "Enviar a", device: "Comprando en", all: "Todos", cart: "Cesta", cartTitle: "Cesta", search: "Buscar en ShopLens",
        nav: ["☰ Todo", "Ofertas", "Atención al cliente", "Listas", "Cheques regalo", "Vender"], heroTitle: "Semana del Black Friday",
        heroText: "Ofertas en miles de productos, con entrega rápida.", popular: "Búsquedas populares", picks: "Selección para", results: "resultados para",
        over: "más de", sort: ["Destacados", "Precio: de menor a mayor", "Precio: de mayor a menor", "Valoración media"], add: "Añadir a la cesta",
        unavailable: "No disponible", inStock: "En stock", left: n => `Solo quedan ${n} en stock`, sponsored: "Patrocinado",
        fast: "Entrega GRATIS mañana", standard: "Entrega en 3-5 días", noResults: "No hay resultados para", noHint: "Revisa la ortografía o usa términos más generales.",
        fStock: "Disponibilidad", fInStock: "Solo artículos en stock", fPrice: "Precio", fGo: "Ir", fRating: "Valoración", fAny: "Todas",
        fUp: "o más", fDelivery: "Entrega", fFast: "Entrega rápida", fBrand: "Marca", added: "Añadido a la cesta", sorry: "Lo sentimos, este artículo no está disponible.",
        priceChanged: p => `El precio ha cambiado a €${p}.`, empty: "Tu cesta está vacía.", subtotal: "Subtotal", checkout: "Tramitar pedido",
        ordered: "Gracias, tu pedido se ha realizado (demo).", top: "Volver arriba", about: "Sobre este artículo" },
  JP: { lang: "ja", deliver: "お届け先", device: "ご利用端末", all: "すべて", cart: "カート", cartTitle: "ショッピングカート", search: "ShopLensを検索",
        nav: ["☰ すべて", "タイムセール", "カスタマーサービス", "ほしい物リスト", "ギフトカード", "出品"], heroTitle: "ブラックフライデー",
        heroText: "数千点の商品がお買い得。お急ぎ便でお届け。", popular: "人気の検索", picks: "おすすめ:", results: "件の結果:",
        over: "", sort: ["おすすめ", "価格の安い順", "価格の高い順", "レビューの評価順"], add: "カートに入れる",
        unavailable: "現在お取り扱いできません", inStock: "在庫あり", left: n => `残り${n}点`, sponsored: "スポンサー",
        fast: "明日中に無料でお届け", standard: "3〜5日でお届け", noResults: "検索結果はありません:", noHint: "別のキーワードをお試しください。",
        fStock: "在庫状況", fInStock: "在庫ありのみ", fPrice: "価格", fGo: "検索", fRating: "カスタマーレビュー", fAny: "すべて",
        fUp: "以上", fDelivery: "配送", fFast: "お急ぎ便", fBrand: "ブランド", added: "カートに追加しました", sorry: "申し訳ありません。この商品は現在お取り扱いできません。",
        priceChanged: p => `価格が€${p}に変更されました。`, empty: "カートは空です。", subtotal: "小計", checkout: "レジに進む",
        ordered: "ご注文ありがとうございます(デモ)。", top: "トップへ戻る", about: "この商品について" },
};

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const params = new URLSearchParams(location.search);
const state = {
  market: TEXT[params.get("market")] ? params.get("market") : localStorage.getItem("market") || "DE",
  device: ["web", "android", "ios"].includes(params.get("device")) ? params.get("device") : "web",
  q: params.get("q") || "", sort: 0, inStock: false, min: "", max: "", rating: 0, fast: false, brands: new Set(),
  data: null, cart: [], sid: "s" + Math.random().toString(36).slice(2, 10),
};
const t = () => TEXT[state.market];

async function api(path, body) {
  const options = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined;
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
  return response.json();
}
const track = (event, extra = {}) => api("/api/event", { event, market: state.market, device: state.device, query: state.q, sid: state.sid, ...extra }).catch(() => {});

function toast(message, bad = false) {
  const el = $("toast");
  el.textContent = message;
  el.className = bad ? "toast bad" : "toast";
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.hidden = true), 2600);
}

const stars = r => "★".repeat(Math.round(r)) + "☆".repeat(5 - Math.round(r));
const priceHtml = p => { const [e, c] = p.toFixed(2).split("."); return `<span class="price"><sup>€</sup>${e}<sup>${c}</sup></span>`; };
const stockHtml = i => i.stock <= 0 ? `<span class="stock out">${t().unavailable}</span>`
  : i.stock <= 5 ? `<span class="stock out">${t().left(i.stock)}</span>` : `<span class="stock in">${t().inStock}</span>`;
const deliveryHtml = i => `<span class="delivery">${i.fast ? `<b>fast</b> ${t().fast}` : t().standard}</span>`;

function cardHtml(i, sponsored = false) {
  return `<article class="card" data-doc="${i.doc}">
    <div class="spons">${sponsored ? t().sponsored : ""}</div>
    <div class="pic" data-open="${i.doc}">${i.emoji}</div>
    <div class="title" data-open="${i.doc}">${esc(i.title)}</div>
    <div class="stars">${stars(i.rating)}<small>${i.reviews.toLocaleString()}</small></div>
    ${priceHtml(i.price)}${deliveryHtml(i)}${stockHtml(i)}
    <button class="buy" data-add="${i.doc}" ${i.stock <= 0 ? "disabled" : ""}>${i.stock <= 0 ? t().unavailable : t().add}</button>
  </article>`;
}

function visibleItems() {
  let items = state.data.items.filter(i => i.rating >= state.rating && (!state.fast || i.fast) && (!state.brands.size || state.brands.has(i.brand)));
  const sorters = [null, (a, b) => a.price - b.price, (a, b) => b.price - a.price, (a, b) => b.rating - a.rating];
  if (sorters[state.sort]) items = [...items].sort(sorters[state.sort]);
  return items;
}

function renderNotes(notes) {
  $("notes").hidden = !notes.length;
  $("notes").innerHTML = `<b>Demo note</b>what a monitoring system should notice here:<ul>${notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>`;
}

function renderResults() {
  const d = state.data, items = visibleItems(), tx = t();
  const brands = [...new Set(d.items.map(i => i.brand).filter(Boolean))].slice(0, 10);
  const filters = `<aside class="filters">
    <h3>${tx.fStock}</h3><label><input type="checkbox" id="f-stock" ${state.inStock ? "checked" : ""}>${tx.fInStock}</label>
    <h3>${tx.fPrice}</h3><div class="price"><input type="number" id="f-min" placeholder="€ min" value="${esc(state.min)}">
      <input type="number" id="f-max" placeholder="€ max" value="${esc(state.max)}"><button class="go" id="f-go">${tx.fGo}</button></div>
    <h3>${tx.fRating}</h3>${[0, 4, 3].map(r => `<label><input type="radio" name="f-rating" value="${r}" ${state.rating === r ? "checked" : ""}>
      ${r ? `<span class="stars">${stars(r)}</span> ${tx.fUp}` : tx.fAny}</label>`).join("")}
    <h3>${tx.fDelivery}</h3><label><input type="checkbox" id="f-fast" ${state.fast ? "checked" : ""}>${tx.fFast}</label>
    ${brands.length ? `<h3>${tx.fBrand}</h3>${brands.map(b => `<label><input type="checkbox" data-brand="${esc(b)}" ${state.brands.has(b) ? "checked" : ""}>${esc(b)}</label>`).join("")}` : ""}
  </aside>`;
  const sponsored = d.sponsored ? `<section class="sponsored-slot" data-doc="${d.sponsored.doc}">
      <div class="pic" data-open="${d.sponsored.doc}">${d.sponsored.emoji}</div>
      <div><div class="tag">${tx.sponsored}</div><div class="title" data-open="${d.sponsored.doc}">${esc(d.sponsored.title)}</div>
        <div class="stars">${stars(d.sponsored.rating)}<small>${d.sponsored.reviews.toLocaleString()}</small></div>${priceHtml(d.sponsored.price)}</div>
      <button class="buy" data-add="${d.sponsored.doc}">${tx.add}</button></section>` : "";
  const body = items.length ? `<div class="grid">${items.map(i => cardHtml(i)).join("")}</div>`
    : `<div class="empty"><h2>${tx.noResults} “${esc(state.q)}”</h2><p>${tx.noHint}</p></div>`;
  $("main").innerHTML = `<div class="results">${filters}<section>
    <div class="bar"><span>1-${items.length} ${tx.over} ${d.total.toLocaleString()} ${tx.results} <span class="q">“${esc(state.q)}”</span>
      <small> · ${d.latency_ms} ms</small></span>
      <select id="sort">${tx.sort.map((s, n) => `<option value="${n}" ${state.sort === n ? "selected" : ""}>${s}</option>`).join("")}</select></div>
    ${sponsored}${body}</section></div>`;
  renderNotes(d.notes);
}

async function renderHome() {
  const tx = t();
  $("main").innerHTML = `<section class="hero"><h1>${tx.heroTitle}</h1><p>${tx.heroText}</p></section>`;
  renderNotes([]);
  const home = await api(`/api/home?market=${state.market}`);
  state.data = { items: home.rows.flatMap(r => r.items) };
  $("main").innerHTML += `<h3>${tx.popular}</h3><div class="chips">${home.popular.map(q => `<button class="chip" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>`
    + home.rows.map(r => `<section class="panel"><h2>${tx.picks} “${esc(r.query)}”</h2><div class="row">${r.items.map(i => cardHtml(i)).join("")}</div></section>`).join("");
}

async function load() {
  const tx = t();
  document.documentElement.lang = tx.lang;
  $("t-deliver").textContent = tx.deliver; $("t-device").textContent = tx.device; $("t-all").textContent = tx.all;
  $("t-cart").textContent = tx.cart; $("t-cart2").textContent = tx.cartTitle; $("t-top").textContent = tx.top;
  $("checkout").textContent = tx.checkout; $("q").placeholder = tx.search; $("q").value = state.q;
  $("sub").innerHTML = tx.nav.map(n => `<span>${n}</span>`).join("");
  $("market").value = state.market; $("device").value = state.device;
  const url = new URLSearchParams({ market: state.market, device: state.device, ...(state.q ? { q: state.q } : {}) });
  history.replaceState(null, "", `/?${url}`);
  try {
    if (!state.q) return await renderHome();
    const query = new URLSearchParams({ q: state.q, market: state.market, device: state.device, sid: state.sid, in_stock: state.inStock ? "1" : "", min: state.min, max: state.max });
    state.data = await api(`/api/search?${query}`);
    renderResults();
  } catch (error) {
    $("main").innerHTML = `<div class="empty"><h2>ShopLens is not responding</h2><p>${esc(error.message)}</p></div>`;
  }
}

function search(q) { state.q = q.trim(); state.brands.clear(); state.sort = 0; load(); window.scrollTo(0, 0); }
const find = doc => [state.data.sponsored, ...state.data.items].find(i => i && i.doc === Number(doc));

function renderCart() {
  const tx = t(), total = state.cart.reduce((sum, i) => sum + i.price, 0);
  $("cart-count").textContent = state.cart.length;
  $("cart-items").innerHTML = state.cart.length ? state.cart.map(i => `<div class="line"><span>${esc(i.title.slice(0, 60))}</span><b>€${i.price.toFixed(2)}</b></div>`).join("") : `<p>${tx.empty}</p>`;
  $("subtotal").textContent = `${tx.subtotal}: €${total.toFixed(2)}`;
  $("checkout").disabled = !state.cart.length;
}

async function addToCart(doc) {
  const item = find(doc);
  const answer = await api("/api/cart", { market: state.market, device: state.device, doc: item.doc, price: item.price, rank: item.rank, query: state.q, sid: state.sid });
  if (!answer.ok) return toast(t().sorry, true);
  if (answer.changed) toast(t().priceChanged(answer.price.toFixed(2)), true); else toast(t().added);
  state.cart.push({ title: item.title, price: answer.price });
  renderCart();
}

function openProduct(doc) {
  const i = find(doc), tx = t();
  track("click", { rank: i.rank });
  $("modal-box").innerHTML = `<div class="pic">${i.emoji}</div><div><h2>${esc(i.title)}</h2>
    <div class="stars">${stars(i.rating)}<small>${i.reviews.toLocaleString()}</small></div>${priceHtml(i.price)}<br>${deliveryHtml(i)}<br>${stockHtml(i)}
    <h4>${tx.about}</h4><p>${esc(i.bullet || i.title)}</p>
    <button class="buy" data-add="${i.doc}" ${i.stock <= 0 ? "disabled" : ""}>${i.stock <= 0 ? tx.unavailable : tx.add}</button></div>`;
  $("modal").hidden = false;
}

document.addEventListener("click", event => {
  const el = event.target.closest("[data-add],[data-open],[data-q]");
  if (event.target === $("modal")) $("modal").hidden = true;
  if (!el) return;
  if (el.dataset.add) addToCart(el.dataset.add);
  else if (el.dataset.open) openProduct(el.dataset.open);
  else search(el.dataset.q);
});
document.addEventListener("change", event => {
  const el = event.target;
  if (el.id === "market") { state.market = el.value; localStorage.setItem("market", el.value); state.q = ""; load(); }
  else if (el.id === "device") { state.device = el.value; load(); }
  else if (el.id === "sort") { state.sort = Number(el.value); renderResults(); }
  else if (el.id === "f-stock") { state.inStock = el.checked; load(); }
  else if (el.id === "f-fast") { state.fast = el.checked; renderResults(); }
  else if (el.name === "f-rating") { state.rating = Number(el.value); renderResults(); }
  else if (el.dataset.brand) { el.checked ? state.brands.add(el.dataset.brand) : state.brands.delete(el.dataset.brand); renderResults(); }
});
document.addEventListener("click", event => {
  if (event.target.id === "f-go") { state.min = $("f-min").value; state.max = $("f-max").value; load(); }
});
$("search-form").addEventListener("submit", event => { event.preventDefault(); search($("q").value); });
$("logo").addEventListener("click", event => { event.preventDefault(); search(""); });
$("cart-btn").addEventListener("click", () => ($("drawer").hidden = false));
$("drawer-close").addEventListener("click", () => ($("drawer").hidden = true));
$("checkout").addEventListener("click", () => { track("checkout"); state.cart = []; renderCart(); $("drawer").hidden = true; toast(t().ordered); });
$("t-top").addEventListener("click", event => { event.preventDefault(); window.scrollTo({ top: 0, behavior: "smooth" }); });
document.addEventListener("keydown", event => { if (event.key === "Escape") { $("modal").hidden = true; $("drawer").hidden = true; } });

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("theme", theme);
  $("theme").textContent = theme === "dark" ? "☀️" : "🌙";
}
$("theme").addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
setTheme(params.get("theme") || localStorage.getItem("theme") || "light");
renderCart();
load();
