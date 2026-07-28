(() => {
  "use strict";

  const STORAGE_KEY = "fantasy-draft-free-v1";
  const USER_FIELDS = ["rank","drafted","draftedBy","overallPick","rosterSlot","notes","categories","tier"];
  const TABS = ["Available","Drafted","All","QB","RB","WR","TE","K","DST","News"];
  const WEIGHTS = {talent:.25,volume:.20,offense:.10,floor:.15,ceiling:.15,safety:.10,schedule:.05};
  const SORT_DEFAULTS = {
    rank:"asc", name:"asc", pos:"asc", team:"asc", bye:"asc", tier:"asc",
    market:"asc", espn:"asc", yahoo:"asc", sleeper:"asc", underdog:"asc",
    proj2026:"desc", ppg2025:"desc", ppg2024:"desc", news:"desc", drafted:"asc"
  };

  let state = {
    activeTab: "Available",
    query: "",
    position: "",
    compact: false,
    sortKey: "rank",
    sortDir: "asc",
    players: [],
    news: [],
    meta: {},
    drawerKey: null
  };
  let dragKey = null;

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const numberOrBlank = (v) => (v === "" || v == null || Number.isNaN(Number(v))) ? "" : Number(v);
  const fmt = (v, digits=1) => v === "" || v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(digits).replace(/\.0$/,"");
  const nowIso = () => new Date().toISOString();

  function load() {
    const source = window.FANTASY_DATA || {players:[],news:[],meta:{}};
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); } catch (_) {}
    const savedByKey = new Map((saved.players || []).map(p => [p.key,p]));
    const merged = source.players.map((p, i) => {
      const old = savedByKey.get(p.key) || {};
      const next = structuredClone(p);
      USER_FIELDS.forEach(field => {
        if (old[field] !== undefined) next[field] = structuredClone(old[field]);
      });
      next.rank = Number(next.rank) || i + 1;
      next.drafted = Boolean(next.drafted);
      return next;
    });
    for (const p of saved.players || []) {
      if (!merged.some(x => x.key === p.key)) merged.push(p);
    }
    merged.sort((a,b) => a.rank - b.rank || a.name.localeCompare(b.name));
    renumber(merged);
    state.players = merged;
    state.news = source.news || [];
    state.meta = source.meta || {};
    state.compact = Boolean(saved.compact);
    state.sortKey = SORT_DEFAULTS[saved.sortKey] ? saved.sortKey : "rank";
    state.sortDir = saved.sortDir === "desc" ? "desc" : "asc";
    $("compactToggle").checked = state.compact;
    save();
  }

  function save() {
    const userPlayers = state.players.map(p => {
      const out = {key:p.key,name:p.name,pos:p.pos,team:p.team};
      USER_FIELDS.forEach(f => out[f] = structuredClone(p[f]));
      return out;
    });
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      players:userPlayers,
      compact:state.compact,
      sortKey:state.sortKey,
      sortDir:state.sortDir
    }));
  }

  function renumber(list = state.players) {
    list.sort((a,b) => Number(a.rank)-Number(b.rank) || a.name.localeCompare(b.name));
    list.forEach((p,i) => p.rank = i + 1);
  }

  function getCounts() {
    const counts = {Available:0,Drafted:0,All:state.players.length,QB:0,RB:0,WR:0,TE:0,K:0,DST:0,News:state.news.length};
    state.players.forEach(p => {
      if (p.drafted) counts.Drafted++; else counts.Available++;
      if (counts[p.pos] != null) counts[p.pos]++;
    });
    return counts;
  }

  function autoScore(p) {
    let total = 0, used = 0;
    for (const [k,w] of Object.entries(WEIGHTS)) {
      const n = Number(p.categories?.[k]);
      if (n) { total += n*w; used += w; }
    }
    return used ? total / used : "";
  }

  function marketAverage(p) {
    // Average only individual sources. Do not double-count the existing aggregate "market" field.
    const sourceKeys = ["fantasyPros","fantasyData","espn","yahoo","sleeper","cbs","nfl","underdog"];
    const ranks = sourceKeys
      .map(key => Number(p.sourceRanks?.[key]))
      .filter(n => Number.isFinite(n) && n > 0);
    return ranks.length ? ranks.reduce((a,b)=>a+b,0)/ranks.length : "";
  }

  function sortValue(p, key) {
    switch (key) {
      case "rank": return Number(p.rank);
      case "name": return String(p.name || "").toLowerCase();
      case "pos": return String(p.pos || "").toLowerCase();
      case "team": return String(p.team || "").toLowerCase();
      case "bye": return numberOrBlank(p.bye);
      case "tier": return numberOrBlank(p.tier);
      case "market": return marketAverage(p);
      case "espn": return numberOrBlank(p.sourceRanks?.espn);
      case "yahoo": return numberOrBlank(p.sourceRanks?.yahoo);
      case "sleeper": return numberOrBlank(p.sourceRanks?.sleeper);
      case "underdog": return numberOrBlank(p.sourceRanks?.underdog);
      case "proj2026": return numberOrBlank(p.proj2026);
      case "ppg2025": return numberOrBlank(p.stats2025?.ppg);
      case "ppg2024": return numberOrBlank(p.stats2024?.ppg);
      case "drafted": return p.drafted ? 1 : 0;
      case "news": {
        const flag = String(p.newsFlag || "").toUpperCase();
        const priority = flag === "NEW" ? 3 : flag === "RECENT" ? 2 : flag ? 1 : 0;
        const timestamp = p.newsDate ? new Date(p.newsDate).getTime() || 0 : 0;
        return priority * 1e15 + timestamp;
      }
      default: return Number(p.rank);
    }
  }

  function comparePlayers(a, b) {
    const av = sortValue(a, state.sortKey);
    const bv = sortValue(b, state.sortKey);
    const aBlank = av === "" || av == null || (typeof av === "number" && Number.isNaN(av));
    const bBlank = bv === "" || bv == null || (typeof bv === "number" && Number.isNaN(bv));

    // Missing rankings/stats always stay at the bottom in either direction.
    if (aBlank && !bBlank) return 1;
    if (!aBlank && bBlank) return -1;

    let result = 0;
    if (typeof av === "string" || typeof bv === "string") {
      result = String(av).localeCompare(String(bv), undefined, {numeric:true, sensitivity:"base"});
    } else {
      result = Number(av) - Number(bv);
    }
    if (state.sortDir === "desc") result *= -1;
    return result || Number(a.rank) - Number(b.rank) || a.name.localeCompare(b.name);
  }

  function setSort(key, forceDirection) {
    if (!SORT_DEFAULTS[key]) return;
    if (state.sortKey === key && !forceDirection) {
      state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
    } else {
      state.sortKey = key;
      state.sortDir = forceDirection || SORT_DEFAULTS[key];
    }
    save();
    render();
  }

  function visiblePlayers() {
    if (state.activeTab === "News") return [];
    let list = state.players.slice();
    if (state.activeTab === "Available") list = list.filter(p => !p.drafted);
    else if (state.activeTab === "Drafted") list = list.filter(p => p.drafted);
    else if (["QB","RB","WR","TE","K","DST"].includes(state.activeTab)) list = list.filter(p => p.pos === state.activeTab);
    if (state.position) list = list.filter(p => p.pos === state.position);
    const q = state.query.trim().toLowerCase();
    if (q) list = list.filter(p => [p.name,p.team,p.pos].some(v => String(v).toLowerCase().includes(q)));
    return list.sort(comparePlayers);
  }

  function render() {
    renderSummary();
    renderTabs();
    $("boardView").classList.toggle("hidden", state.activeTab === "News");
    $("newsView").classList.toggle("hidden", state.activeTab !== "News");
    if (state.activeTab === "News") renderNews(); else renderTable();
    updateSortUi();
    $("playerTable").classList.toggle("compact", state.compact);
    const updated = state.meta.updatedAt ? new Date(state.meta.updatedAt).toLocaleString() : "Using imported seed data";
    $("updatedAt").textContent = `Data: ${updated}`;
  }

  function renderSummary() {
    const counts = getCounts();
    const targets = state.players.filter(p => {
      const m = marketAverage(p);
      return m && m - p.rank >= 15 && !p.drafted;
    }).length;
    const newNews = state.players.filter(p => p.newsFlag === "NEW").length;
    $("summary").innerHTML = [
      ["Available",counts.Available],["Drafted",counts.Drafted],["Targets",targets],
      ["New news",newNews],["Player pool",counts.All]
    ].map(([label,value]) => `<div class="stat"><div class="label">${label}</div><div class="value">${value}</div></div>`).join("");
  }

  function renderTabs() {
    const counts = getCounts();
    $("tabs").innerHTML = TABS.map(tab =>
      `<button class="tab ${tab===state.activeTab?"active":""}" data-tab="${tab}">
        ${tab}<span class="badge">${counts[tab] ?? 0}</span>
      </button>`).join("");
    $("tabs").querySelectorAll("[data-tab]").forEach(btn => btn.addEventListener("click", () => {
      state.activeTab = btn.dataset.tab;
      render();
    }));
  }

  function updateSortUi() {
    if ($("sortSelect")) $("sortSelect").value = state.sortKey;
    if ($("sortDirBtn")) {
      $("sortDirBtn").textContent = state.sortDir === "asc" ? "↑ Ascending" : "↓ Descending";
      $("sortDirBtn").title = "Reverse the current sort";
    }
    document.querySelectorAll("th[data-sort]").forEach(th => {
      const active = th.dataset.sort === state.sortKey;
      th.classList.toggle("active-sort", active);
      const indicator = th.querySelector(".sort-indicator");
      if (indicator) indicator.textContent = active ? (state.sortDir === "asc" ? "▲" : "▼") : "";
      th.setAttribute("aria-sort", active ? (state.sortDir === "asc" ? "ascending" : "descending") : "none");
    });
  }

  function renderTable() {
    const list = visiblePlayers();
    $("emptyState").classList.toggle("hidden", list.length !== 0);
    $("playerBody").innerHTML = list.map(p => {
      const market = marketAverage(p);
      const news = p.newsFlag ? `<span class="news-pill">${esc(p.newsFlag)}</span>` : "—";
      const rankMode = state.sortKey === "rank" && state.sortDir === "asc";
      return `<tr draggable="${rankMode}" data-key="${esc(p.key)}" class="${p.drafted?"drafted":""}">
        <td><span class="drag-handle ${rankMode?"":"disabled"}" title="${rankMode?"Drag entire row to change your ranking":"Switch sorting to My rank · Ascending to drag rows"}">⋮⋮</span></td>
        <td><input class="draft-check" type="checkbox" ${p.drafted?"checked":""} aria-label="Mark ${esc(p.name)} drafted"></td>
        <td><input class="rank-input" type="number" min="1" max="${state.players.length}" value="${p.rank}"></td>
        <td><div class="player-cell"><span class="player-name">${esc(p.name)}</span></div></td>
        <td><span class="pos-pill">${esc(p.pos)}</span></td>
        <td><span class="team-pill">${esc(p.team)}</span></td>
        <td>${fmt(p.bye,0)}</td>
        <td>${fmt(p.tier,0)}</td>
        <td>${fmt(market,1)}</td>
        <td>${fmt(p.sourceRanks?.espn,1)}</td>
        <td>${fmt(p.sourceRanks?.yahoo,1)}</td>
        <td>${fmt(p.sourceRanks?.sleeper,1)}</td>
        <td>${fmt(p.sourceRanks?.underdog,1)}</td>
        <td>${fmt(p.proj2026,1)}</td>
        <td>${fmt(p.stats2025?.ppg,1)}</td>
        <td>${fmt(p.stats2024?.ppg,1)}</td>
        <td>${news}</td>
      </tr>`;
    }).join("");

    $("playerBody").querySelectorAll("tr").forEach(row => {
      const key = row.dataset.key;
      row.addEventListener("dragstart", e => {
        if (!(state.sortKey === "rank" && state.sortDir === "asc")) {
          e.preventDefault();
          return;
        }
        dragKey = key;
        row.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", key);
      });
      row.addEventListener("dragover", e => {
        e.preventDefault();
        if (!dragKey || dragKey === key) return;
        clearDropClasses();
        const rect = row.getBoundingClientRect();
        row.classList.add(e.clientY < rect.top + rect.height/2 ? "drop-before" : "drop-after");
      });
      row.addEventListener("drop", e => {
        e.preventDefault();
        const rect = row.getBoundingClientRect();
        moveBeforeAfter(dragKey, key, e.clientY >= rect.top + rect.height/2);
        dragKey = null;
        clearDropClasses();
      });
      row.addEventListener("dragend", () => {
        dragKey = null;
        clearDropClasses();
      });

      row.querySelector(".draft-check").addEventListener("change", e => {
        const p = findPlayer(key);
        p.drafted = e.target.checked;
        p.draftTimestamp = p.drafted ? nowIso() : "";
        if (!p.drafted) {
          p.draftedBy = ""; p.overallPick = ""; p.rosterSlot = "";
        }
        save(); render(); toast(p.drafted ? `${p.name} marked drafted` : `${p.name} returned to available`);
      });

      row.querySelector(".rank-input").addEventListener("change", e => {
        moveToRank(key, Number(e.target.value));
      });

      row.querySelector(".player-name").addEventListener("click", () => openDrawer(key));
    });
  }

  function clearDropClasses() {
    document.querySelectorAll(".dragging,.drop-before,.drop-after").forEach(el => el.classList.remove("dragging","drop-before","drop-after"));
  }

  function findPlayer(key) {
    return state.players.find(p => p.key === key);
  }

  function moveBeforeAfter(sourceKey, targetKey, after) {
    if (!sourceKey || sourceKey === targetKey) return;
    const ordered = state.players.slice().sort((a,b)=>a.rank-b.rank);
    const sourceIndex = ordered.findIndex(p => p.key === sourceKey);
    const [moved] = ordered.splice(sourceIndex, 1);
    let targetIndex = ordered.findIndex(p => p.key === targetKey);
    if (after) targetIndex++;
    ordered.splice(targetIndex, 0, moved);
    ordered.forEach((p,i) => p.rank = i+1);
    state.players = ordered;
    save(); render();
  }

  function moveToRank(key, requested) {
    if (!Number.isFinite(requested)) return render();
    const target = Math.max(1, Math.min(state.players.length, Math.round(requested)));
    const ordered = state.players.slice().sort((a,b)=>a.rank-b.rank);
    const i = ordered.findIndex(p => p.key === key);
    const [moved] = ordered.splice(i,1);
    ordered.splice(target-1,0,moved);
    ordered.forEach((p,n)=>p.rank=n+1);
    state.players=ordered;
    save();render();
  }

  function renderNews() {
    if (!state.news.length) {
      $("newsList").innerHTML = `<div class="empty">No linked news has been loaded yet. The free daily updater fills this tab.</div>`;
      return;
    }
    $("newsList").innerHTML = state.news.map(n => `
      <article class="news-card">
        <h3>${esc(n.headline || "NFL update")}</h3>
        <p>${esc(n.summary || "")}</p>
        <div class="meta">${esc(n.player || "")} ${n.team ? "· "+esc(n.team) : ""} ${n.published ? "· "+new Date(n.published).toLocaleString() : ""}
          ${n.url ? `· <a href="${esc(n.url)}" target="_blank" rel="noopener">Open source</a>` : ""}
        </div>
      </article>`).join("");
  }

  function openDrawer(key) {
    state.drawerKey = key;
    const p = findPlayer(key);
    $("drawerName").textContent = p.name;
    $("drawerMeta").textContent = `${p.pos} · ${p.team} · Overall rank ${p.rank}`;
    $("drawerContent").innerHTML = drawerHtml(p);
    $("drawer").classList.add("open");
    $("drawer").setAttribute("aria-hidden","false");
    $("drawerBackdrop").classList.remove("hidden");
    bindDrawer(p);
  }

  function closeDrawer() {
    state.drawerKey = null;
    $("drawer").classList.remove("open");
    $("drawer").setAttribute("aria-hidden","true");
    $("drawerBackdrop").classList.add("hidden");
  }

  function drawerHtml(p) {
    const sliders = [
      ["talent","Talent"],["volume","Role / volume"],["offense","Offense"],
      ["floor","Floor"],["ceiling","Ceiling"],["safety","Health / safety"],["schedule","Schedule"]
    ].map(([key,label]) => {
      const value = Number(p.categories?.[key]) || 5;
      return `<div class="slider-row"><span>${label}</span><input data-cat="${key}" type="range" min="1" max="10" value="${value}"><b data-cat-value="${key}">${value}</b></div>`;
    }).join("");
    const sourceCards = Object.entries(p.sourceRanks || {}).map(([k,v]) => metricCard(k,v)).join("");
    const y25 = p.stats2025 || {}, y24 = p.stats2024 || {};
    return `
      <section class="drawer-section">
        <h3>Draft controls</h3>
        <div class="form-grid">
          <label>My rank<input id="dRank" type="number" value="${p.rank}" min="1" max="${state.players.length}"></label>
          <label>Tier<input id="dTier" type="number" value="${esc(p.tier || "")}" min="1"></label>
          <label>Drafted by<input id="dTeam" value="${esc(p.draftedBy || "")}" placeholder="Team 1"></label>
          <label>Overall pick<input id="dPick" type="number" value="${esc(p.overallPick || "")}" min="1"></label>
          <label>Roster slot<select id="dSlot"><option value="">—</option>${["QB","RB","WR","TE","FLEX","K","DST","BENCH"].map(x=>`<option ${p.rosterSlot===x?"selected":""}>${x}</option>`).join("")}</select></label>
          <label>Drafted<select id="dDrafted"><option value="false" ${!p.drafted?"selected":""}>Available</option><option value="true" ${p.drafted?"selected":""}>Drafted</option></select></label>
        </div>
      </section>
      <section class="drawer-section">
        <h3>Your evaluation · score <span id="autoScore">${fmt(autoScore(p),2)}</span></h3>
        ${sliders}
      </section>
      <section class="drawer-section">
        <h3>Internet rankings</h3>
        <div class="metric-grid">${sourceCards}</div>
      </section>
      <section class="drawer-section">
        <h3>2026 status</h3>
        <div class="metric-grid">
          ${metricCard("Projected PPR",p.proj2026)}
          ${metricCard("Injury",p.injuryStatus)}
          ${metricCard("Bye",p.bye)}
        </div>
        ${p.newsSummary ? `<p>${esc(p.newsSummary)}</p>` : ""}
      </section>
      <section class="drawer-section">
        <h3>2025 metrics</h3>
        <div class="metric-grid">
          ${metricCard("Games",y25.gp)}${metricCard("PPR",y25.ppr)}${metricCard("PPG",y25.ppg)}
          ${metricCard("Targets",y25.targets)}${metricCard("Carries",y25.carries)}${metricCard("TD",y25.td)}
        </div>
      </section>
      <section class="drawer-section">
        <h3>2024 metrics</h3>
        <div class="metric-grid">
          ${metricCard("Games",y24.gp)}${metricCard("PPR",y24.ppr)}${metricCard("PPG",y24.ppg)}
          ${metricCard("Targets",y24.targets)}${metricCard("Carries",y24.carries)}${metricCard("TD",y24.td)}
        </div>
      </section>
      <section class="drawer-section">
        <label class="full-field">Notes<textarea id="dNotes">${esc(p.notes || "")}</textarea></label>
      </section>`;
  }

  function metricCard(label,value) {
    const pretty = label.replace(/([A-Z])/g," $1").replace(/^./,c=>c.toUpperCase());
    return `<div class="metric-card"><div class="k">${esc(pretty)}</div><div class="v">${fmt(value,1)}</div></div>`;
  }

  function bindDrawer(p) {
    $("dRank").addEventListener("change", e => { moveToRank(p.key,Number(e.target.value)); openDrawer(p.key); });
    $("dTier").addEventListener("change", e => { p.tier=numberOrBlank(e.target.value); save();render(); });
    $("dTeam").addEventListener("input", e => { p.draftedBy=e.target.value; save(); });
    $("dPick").addEventListener("input", e => { p.overallPick=numberOrBlank(e.target.value); save(); });
    $("dSlot").addEventListener("change", e => { p.rosterSlot=e.target.value; save(); });
    $("dDrafted").addEventListener("change", e => { p.drafted=e.target.value==="true"; save();render(); });
    $("dNotes").addEventListener("input", e => { p.notes=e.target.value; save(); });
    document.querySelectorAll("[data-cat]").forEach(slider => slider.addEventListener("input", e => {
      p.categories = p.categories || {};
      p.categories[e.target.dataset.cat] = Number(e.target.value);
      document.querySelector(`[data-cat-value="${e.target.dataset.cat}"]`).textContent=e.target.value;
      $("autoScore").textContent=fmt(autoScore(p),2);
      save();
    }));
  }

  function addPlayer() {
    const name = prompt("Player name");
    if (!name) return;
    const pos = (prompt("Position: QB, RB, WR, TE, K or DST","RB") || "").toUpperCase();
    if (!["QB","RB","WR","TE","K","DST"].includes(pos)) return toast("Invalid position");
    const team = (prompt("NFL team abbreviation","") || "").toUpperCase();
    const key = name.toLowerCase().replace(/\b(jr|sr|ii|iii|iv)\.?\b/g,"").replace(/[^a-z0-9]+/g,"")+"|"+pos;
    if (findPlayer(key)) return toast("That player already exists");
    state.players.push({key,name,pos,team,rank:state.players.length+1,drafted:false,tier:"",categories:{},sourceRanks:{},stats2025:{},stats2024:{}});
    save();render();toast(`${name} added`);
  }

  function exportData() {
    const payload = {
      exportedAt: nowIso(),
      meta: state.meta,
      players: state.players,
      news: state.news
    };
    download("fantasy-draft-backup.json", JSON.stringify(payload,null,2), "application/json");
  }

  function importData(file) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        if (file.name.toLowerCase().endsWith(".json")) {
          const obj = JSON.parse(reader.result);
          const imported = obj.players || obj;
          if (!Array.isArray(imported)) throw new Error("JSON must contain a players array");
          state.players = imported;
        } else {
          state.players = importCsv(reader.result);
        }
        renumber(); save();render();toast("Import complete");
      } catch (err) {
        toast("Import failed: "+err.message);
      }
    };
    reader.readAsText(file);
  }

  function importCsv(text) {
    const lines = text.split(/\r?\n/).filter(Boolean);
    const head = csvLine(lines.shift()).map(x=>x.trim().toLowerCase());
    const col = name => head.indexOf(name);
    const nameCol = Math.max(col("player"),col("name"));
    if (nameCol < 0) throw new Error("CSV needs a Player or Name column");
    return lines.map((line,i) => {
      const a=csvLine(line), name=a[nameCol], pos=(a[col("pos")]||a[col("position")]||"").toUpperCase();
      const key=name.toLowerCase().replace(/[^a-z0-9]+/g,"")+"|"+pos;
      return {key,name,pos,team:a[col("team")]||"",rank:Number(a[col("rank")]||i+1),drafted:/true|yes|1/i.test(a[col("drafted")]||""),categories:{},sourceRanks:{},stats2025:{},stats2024:{}};
    });
  }

  function csvLine(line) {
    const out=[]; let cur="", quote=false;
    for (let i=0;i<line.length;i++) {
      const c=line[i];
      if (c==='"' && line[i+1]==='"') {cur+='"';i++;}
      else if (c==='"') quote=!quote;
      else if (c===','&&!quote){out.push(cur);cur="";}
      else cur+=c;
    }
    out.push(cur); return out;
  }

  function download(name,text,type) {
    const a=document.createElement("a");
    a.href=URL.createObjectURL(new Blob([text],{type}));
    a.download=name; a.click(); URL.revokeObjectURL(a.href);
  }

  function reset() {
    if (!confirm("Reset rankings and drafted status to the latest source data?")) return;
    localStorage.removeItem(STORAGE_KEY);
    load();render();toast("Board reset");
  }

  let toastTimer;
  function toast(message) {
    clearTimeout(toastTimer);
    $("toast").textContent=message;
    $("toast").classList.remove("hidden");
    toastTimer=setTimeout(()=>$("toast").classList.add("hidden"),2600);
  }

  $("searchInput").addEventListener("input", e => {state.query=e.target.value;render();});
  $("positionFilter").addEventListener("change", e => {state.position=e.target.value;render();});
  $("sortSelect").addEventListener("change", e => setSort(e.target.value, SORT_DEFAULTS[e.target.value]));
  $("sortDirBtn").addEventListener("click", () => {
    state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
    save();
    render();
  });
  document.querySelectorAll("th[data-sort]").forEach(th => {
    const activate = () => setSort(th.dataset.sort);
    th.addEventListener("click", activate);
    th.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        activate();
      }
    });
  });
  $("compactToggle").addEventListener("change", e => {state.compact=e.target.checked;save();render();});
  $("addPlayerBtn").addEventListener("click",addPlayer);
  $("exportBtn").addEventListener("click",exportData);
  $("importBtn").addEventListener("click",()=>$("importFile").click());
  $("importFile").addEventListener("change",e=>{if(e.target.files[0])importData(e.target.files[0]);e.target.value="";});
  $("resetBtn").addEventListener("click",reset);
  $("closeDrawer").addEventListener("click",closeDrawer);
  $("drawerBackdrop").addEventListener("click",closeDrawer);
  document.addEventListener("keydown",e=>{if(e.key==="Escape")closeDrawer();});

  load();
  render();
})();
