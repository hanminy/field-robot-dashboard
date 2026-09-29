(() => {
  "use strict";
  const grid = document.getElementById("grid");
  const cards = [...grid.querySelectorAll(".card")];
  const q = document.getElementById("q");
  const year = document.getElementById("yearFilter");
  const kind = document.getElementById("kindFilter");
  const sort = document.getElementById("sort");
  const countInfo = document.getElementById("countInfo");
  const empty = document.getElementById("empty");
  const instButtons = [...document.querySelectorAll("#instFilters [data-inst]")];
  const techButtons = [...document.querySelectorAll("#techFilters [data-tech]")];
  const reset = document.getElementById("resetFilters");
  const lightbox = document.getElementById("lightbox");
  const lbimg = document.getElementById("lbimg");
  const collator = new Intl.Collator("ko", { numeric:true, sensitivity:"base" });
  const state = { q:"", inst:"all", tech:new Set(), year:"", kind:"", sort:"newest" };
  const normalize = value => (value || "").normalize("NFKC").toLocaleLowerCase("ko").trim();

  function validSort(value){ return ["newest","oldest","institution","title"].includes(value) ? value : "newest"; }
  function readHash(){
    const p = new URLSearchParams(location.hash.replace(/^#/, ""));
    state.q = p.get("q") || "";
    state.inst = ["all","ETH","SNU","Baidu","other"].includes(p.get("institution")) ? p.get("institution") : "all";
    state.tech = new Set(p.getAll("category").filter(Boolean));
    state.year = p.get("year") || "";
    state.kind = p.get("kind") || "";
    state.sort = validSort(p.get("sort") || "newest");
    q.value = state.q; year.value = state.year; kind.value = state.kind; sort.value = state.sort;
    instButtons.forEach(b => b.classList.toggle("active", b.dataset.inst === state.inst));
    techButtons.forEach(b => b.classList.toggle("active", state.tech.has(b.dataset.tech)));
  }
  function writeHash(){
    const p = new URLSearchParams();
    if(state.q) p.set("q", state.q);
    if(state.inst !== "all") p.set("institution", state.inst);
    [...state.tech].sort(collator.compare).forEach(v => p.append("category", v));
    if(state.year) p.set("year", state.year);
    if(state.kind) p.set("kind", state.kind);
    if(state.sort !== "newest") p.set("sort", state.sort);
    history.replaceState(null, "", `${location.pathname}${location.search}${p.size ? `#${p}` : ""}`);
  }
  function matches(card){
    const term = normalize(state.q);
    const categories = new Set((card.dataset.categories || "").split("|").filter(Boolean));
    return (!term || normalize(card.dataset.text).includes(term))
      && (state.inst === "all" || card.dataset.inst === state.inst)
      && (!state.tech.size || [...state.tech].some(v => categories.has(v)))
      && (!state.year || card.dataset.year === state.year)
      && (!state.kind || card.dataset.kind === state.kind);
  }
  function compare(a,b){
    const ya = Number(a.dataset.year) || -1, yb = Number(b.dataset.year) || -1;
    if(state.sort === "oldest") return (ya === -1) - (yb === -1) || ya-yb || Number(a.dataset.rank)-Number(b.dataset.rank);
    if(state.sort === "institution") return collator.compare(a.dataset.institution,b.dataset.institution) || yb-ya || Number(a.dataset.rank)-Number(b.dataset.rank);
    if(state.sort === "title") return collator.compare(a.querySelector(".title-ko").textContent,b.querySelector(".title-ko").textContent);
    return yb-ya || Number(a.dataset.rank)-Number(b.dataset.rank);
  }
  function apply(updateUrl=true){
    const shown = cards.filter(card => {
      const visible = matches(card); card.hidden = !visible; return visible;
    });
    shown.sort(compare).forEach(card => grid.insertBefore(card, empty));
    empty.hidden = shown.length !== 0;
    countInfo.textContent = `${shown.length}편 표시`;
    if(updateUrl) writeHash();
  }
  function chooseInstitution(button){
    state.inst = button.dataset.inst;
    instButtons.forEach(b => b.classList.toggle("active", b === button));
    apply();
  }
  function toggleTechnology(button){
    const value = button.dataset.tech;
    state.tech.has(value) ? state.tech.delete(value) : state.tech.add(value);
    button.classList.toggle("active", state.tech.has(value));
    apply();
  }
  function resetAll(){
    state.q=""; state.inst="all"; state.tech.clear(); state.year=""; state.kind=""; state.sort="newest";
    q.value=""; year.value=""; kind.value=""; sort.value="newest";
    instButtons.forEach(b => b.classList.toggle("active", b.dataset.inst === "all"));
    techButtons.forEach(b => b.classList.remove("active"));
    apply(); q.focus();
  }
  function openLightbox(img){
    lbimg.src = img.currentSrc || img.src; lbimg.alt = img.alt;
    lightbox.classList.add("open"); lightbox.setAttribute("aria-hidden","false");
  }
  function closeLightbox(){ lightbox.classList.remove("open"); lightbox.setAttribute("aria-hidden","true"); }
  q.addEventListener("input", () => { state.q=q.value.trim(); apply(); });
  instButtons.forEach(b => b.addEventListener("click", () => chooseInstitution(b)));
  techButtons.forEach(b => b.addEventListener("click", () => toggleTechnology(b)));
  year.addEventListener("change", () => { state.year=year.value; apply(); });
  kind.addEventListener("change", () => { state.kind=kind.value; apply(); });
  sort.addEventListener("change", () => { state.sort=validSort(sort.value); apply(); });
  reset.addEventListener("click", resetAll);
  document.querySelectorAll("img.thumb").forEach(img => {
    img.addEventListener("click", event => { event.stopPropagation(); openLightbox(img); });
    img.addEventListener("keydown", event => { if(event.key === "Enter" || event.key === " "){ event.preventDefault(); openLightbox(img); } });
  });
  cards.forEach(card => card.addEventListener("click", event => {
    if(event.target.closest("a") || event.target.closest("img")) return;
    location.href = card.dataset.detail;
  }));
  lightbox.addEventListener("click", closeLightbox);
  document.addEventListener("keydown", event => { if(event.key === "Escape") closeLightbox(); });
  window.addEventListener("hashchange", () => { readHash(); apply(false); });
  readHash(); apply(false);
})();
