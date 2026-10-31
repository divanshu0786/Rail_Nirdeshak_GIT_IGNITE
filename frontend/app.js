// Rail Nirdeshak Dynamic API & WebSocket Resolver
function resolveApiBase() {
  if (typeof window === "undefined") return "http://127.0.0.1:8000";

  if (window.__API_BASE__) return window.__API_BASE__;
  if (window.localStorage && localStorage.getItem("rn_api_base")) {
    const saved = localStorage.getItem("rn_api_base");
    if (saved && !saved.startsWith("file:")) return saved;
  }

  const { protocol, hostname, origin, port } = window.location;

  // Direct file:// access
  if (protocol === "file:") {
    return "http://127.0.0.1:8000";
  }

  // Local development dev servers (Vite 5173, Webpack 3000, Live Server 5500, etc.)
  if ((hostname === "localhost" || hostname === "127.0.0.1") && port && !["8000", "8001", "8080", "10000"].includes(port)) {
    return "http://127.0.0.1:8000";
  }

  // Same-origin deployments (Render, Docker, Railway, FastAPI static mount)
  return origin;
}

let activeApiBase = resolveApiBase();

function getApiBase() {
  return activeApiBase;
}

function setApiBase(newBase) {
  if (!newBase || newBase.startsWith("file:")) return;
  activeApiBase = newBase;
  try {
    localStorage.setItem("rn_api_base", newBase);
  } catch (_) { }
}

function getWsBase() {
  const base = getApiBase();
  return base.startsWith("https://")
    ? base.replace(/^https:\/\//, "wss://")
    : base.replace(/^http:\/\//, "ws://");
}

// Global dynamic fetch with multi-port fallback support
async function dynamicFetch(path, options = {}) {
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return fetch(path, options);
  }

  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const origin = (typeof window !== "undefined" && window.location) ? window.location.origin : "http://127.0.0.1:8000";

  const candidates = Array.from(new Set([
    activeApiBase,
    origin,
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8001",
    "http://127.0.0.1:8080"
  ])).filter(b => b && !b.startsWith("file:"));

  let lastErr = null;
  for (const base of candidates) {
    const fullUrl = `${base}${cleanPath}`;
    try {
      const res = await fetch(fullUrl, options);
      if (res.status !== 404 && res.status !== 405) {
        setApiBase(base);
        return res;
      }
    } catch (err) {
      lastErr = err;
    }
  }

  if (lastErr) throw lastErr;
  return fetch(`${getApiBase()}${cleanPath}`, options);
}

const API_BASE = resolveApiBase();
const WS_BASE = getWsBase();

let state = {
  user: null,
  token: localStorage.getItem("rn_token") || null,
  controllerToken: localStorage.getItem("rn_ctrl_token") || null,
  controllerUser: (() => {
    try { return JSON.parse(localStorage.getItem("rn_ctrl_user") || "null"); } catch (_) { return null; }
  })(),
  controlWs: null,
  allTrains: [],
  currentTrain: null,
  savedTrains: [],
  controlData: null,
  ws: null,
  config: null,
  map: null,
  mapLayers: {
    polyline: null,
    trainMarker: null,
    stationMarkers: []
  }
};

// Document Init
document.addEventListener("DOMContentLoaded", () => {
  loadAppConfig();
  initAuth();
  loadInitialTrains();

  setupSearchDropdown();
  setupStationAutocomplete();
});

async function loadAppConfig() {
  try {
    const res = await dynamicFetch("/api/config");
    if (res.ok) {
      state.config = await res.json();
    }
  } catch (e) {
    console.debug("Config load note:", e);
  }
}

// ----------------- TAB NAVIGATION -----------------
function switchTab(tabId) {
  document.querySelectorAll(".tab-pane").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".nav-btn").forEach(el => el.classList.remove("active"));

  const targetTab = document.getElementById(`tab-${tabId}`);
  const targetNav = document.getElementById(`nav-${tabId}`);
  if (targetTab) targetTab.classList.add("active");
  if (targetNav) targetNav.classList.add("active");

  if (tabId === "map") {
    setTimeout(() => {
      initOrUpdateMap();
      if (state.map) {
        state.map.invalidateSize(true);
      }
    }, 100);
    setTimeout(() => {
      if (state.map) {
        state.map.invalidateSize(true);
      }
    }, 300);
  } else if (tabId === "saved") {
    loadSavedTrains();
  } else if (tabId === "control") {
    checkControlRoomAccess();
  }
}

// ----------------- AUTHENTICATION -----------------
async function initAuth() {
  if (state.token) {
    try {
      const res = await fetch(`${API_BASE}/auth/me`, {
        headers: { "Authorization": `Bearer ${state.token}` }
      });
      if (res.ok) {
        state.user = await res.json();
        updateUserUI();
      } else {
        logout();
      }
    } catch (e) {
      console.warn("Auth check error:", e);
    }
  }

  // Validate controller session or HttpOnly cookie
  if (state.controllerToken && state.controllerToken !== "cookie_session") {
    try {
      const res = await fetch(`${API_BASE}/api/auth/me`, {
        headers: { "Authorization": `Bearer ${state.controllerToken}` },
        credentials: "include"
      });
      if (res.ok) {
        state.controllerUser = await res.json();
        localStorage.setItem("rn_ctrl_user", JSON.stringify(state.controllerUser));
      } else {
        state.controllerToken = null;
        state.controllerUser = null;
        localStorage.removeItem("rn_ctrl_token");
        localStorage.removeItem("rn_ctrl_user");
      }
    } catch (e) {
      console.warn("Controller session validation error:", e);
    }
  } else {
    try {
      const res = await fetch(`${API_BASE}/api/auth/me`, {
        credentials: "include"
      });
      if (res.ok) {
        const u = await res.json();
        if (u && (u.role === "controller" || u.role === "admin")) {
          state.controllerUser = u;
          state.controllerToken = "cookie_session";
        }
      }
    } catch (_) { }
  }
}

function updateUserUI() {
  const profileBtn = document.getElementById("profile-btn");
  const profileIcon = document.getElementById("profile-nav-icon");
  if (!profileBtn) return;

  if (state.user) {
    profileBtn.setAttribute("title", `${state.user.full_name} (${state.user.role}) - Account Profile`);
    profileBtn.classList.add("logged-in");
    if (profileIcon) {
      profileIcon.className = "fa-solid fa-user-check";
    }
  } else {
    profileBtn.setAttribute("title", "Sign In / Guest Profile");
    profileBtn.classList.remove("logged-in");
    if (profileIcon) {
      profileIcon.className = "fa-solid fa-user";
    }
  }
}

function openProfileModal() {
  const modal = document.getElementById("auth-modal");
  const modalTitle = document.getElementById("modal-title");
  const profileView = document.getElementById("profile-view-section");
  const authTabs = document.getElementById("auth-tabs-section");
  const loginForm = document.getElementById("login-form");
  const regForm = document.getElementById("register-form");

  if (!modal) return;

  if (state.user) {
    // Logged in user profile
    if (modalTitle) modalTitle.innerHTML = `<i class="fa-solid fa-circle-user"></i> Account Profile`;
    if (profileView) profileView.classList.remove("hidden");
    if (authTabs) authTabs.classList.add("hidden");
    if (loginForm) loginForm.classList.add("hidden");
    if (regForm) regForm.classList.add("hidden");

    // Fill user info
    const nameEl = document.getElementById("profile-user-name");
    const emailEl = document.getElementById("profile-user-email");
    const roleEl = document.getElementById("profile-user-role");
    const savedEl = document.getElementById("profile-saved-count");

    if (nameEl) nameEl.textContent = state.user.full_name || "User";
    if (emailEl) emailEl.textContent = state.user.email || "";
    if (roleEl) roleEl.textContent = state.user.role === "controller" ? "Zone Controller" : "Passenger";
    if (savedEl) savedEl.textContent = `${state.savedTrains ? state.savedTrains.length : 0} Saved Trains`;
  } else {
    // Guest user -> show login/register
    if (modalTitle) modalTitle.innerHTML = `<i class="fa-solid fa-right-to-bracket"></i> Sign In to Rail Nirdeshak`;
    if (profileView) profileView.classList.add("hidden");
    if (authTabs) authTabs.classList.remove("hidden");
    switchAuthTab("login");
  }

  modal.classList.remove("hidden");
}

function openAuthModal() {
  openProfileModal();
}

function closeAuthModal() {
  const modal = document.getElementById("auth-modal");
  if (modal) modal.classList.add("hidden");
}

function switchAuthTab(type) {
  const loginForm = document.getElementById("login-form");
  const regForm = document.getElementById("register-form");
  const tabLogin = document.getElementById("tab-btn-login");
  const tabReg = document.getElementById("tab-btn-register");

  if (type === "login") {
    if (loginForm) loginForm.classList.remove("hidden");
    if (regForm) regForm.classList.add("hidden");
    if (tabLogin) tabLogin.classList.add("active");
    if (tabReg) tabReg.classList.remove("active");
  } else {
    if (loginForm) loginForm.classList.add("hidden");
    if (regForm) regForm.classList.remove("hidden");
    if (tabLogin) tabLogin.classList.remove("active");
    if (tabReg) tabReg.classList.add("active");
  }
}

async function handleLogin(e) {
  e.preventDefault();
  const email = document.getElementById("login-email").value;
  const password = document.getElementById("login-password").value;

  try {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password })
    });
    const data = await res.json();
    if (res.ok) {
      state.token = data.access_token;
      state.user = data.user;
      localStorage.setItem("rn_token", state.token);
      updateUserUI();
      closeAuthModal();
      showToast(`Welcome back, ${state.user.full_name}!`, "success");
      loadSavedTrains();
    } else {
      showToast(data.detail || "Login failed", "danger");
    }
  } catch (err) {
    showToast("Network error connecting to auth server", "danger");
  }
}

async function handleRegister(e) {
  e.preventDefault();
  const full_name = document.getElementById("reg-name").value;
  const email = document.getElementById("reg-email").value;
  const password = document.getElementById("reg-password").value;
  const role = document.getElementById("reg-role").value;

  try {
    const res = await fetch(`${API_BASE}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ full_name, email, password, role })
    });
    const data = await res.json();
    if (res.ok) {
      state.token = data.access_token;
      state.user = data.user;
      localStorage.setItem("rn_token", state.token);
      updateUserUI();
      closeAuthModal();
      showToast(`Account created for ${state.user.full_name}!`, "success");
      loadSavedTrains();
    } else {
      showToast(data.detail || "Registration failed", "danger");
    }
  } catch (err) {
    showToast("Registration request failed", "danger");
  }
}

function logout() {
  state.user = null;
  state.token = null;
  localStorage.removeItem("rn_token");
  updateUserUI();
  showToast("Signed out successfully", "info");
  loadSavedTrains();
}

// ----------------- DATA LOADING -----------------
async function loadInitialTrains() {
  try {
    const res = await fetch(`${API_BASE}/api/trains`);
    if (res.ok) {
      state.allTrains = await res.json();
      renderFeaturedTrains();
      // Auto track primary demo train 12497
      trackTrain("12497", false);
    }
  } catch (e) {
    console.error("Error loading trains:", e);
    showToast("Error connecting to Rail Nirdeshak backend", "danger");
  }
}

function renderFeaturedTrains() {
  const container = document.getElementById("home-featured-trains");
  if (!container) return;
  if (!state.allTrains || state.allTrains.length === 0) {
    container.innerHTML = "<p class='text-muted'>No active trains found.</p>";
    return;
  }

  container.innerHTML = state.allTrains.map(t => `
    <div class="train-summary-card" onclick="trackTrain('${t.train_number}')">
      <div class="train-card-top">
        <div>
          <span class="train-num-pill">${t.train_number}</span>
          <div class="train-name-title">${t.train_name}</div>
        </div>
        <span class="badge-tag" style="color:#38bdf8;">${t.train_type}</span>
      </div>
      <div class="train-route-text"><i class="fa-solid fa-arrow-right-arrow-left text-dim"></i> ${t.source} → ${t.destination}</div>
      <div class="train-stats-row">
        <span><i class="fa-solid fa-road text-cyan"></i> ${t.total_distance_km} km</span>
        <span class="text-success"><i class="fa-solid fa-circle-dot"></i> Telemetry Active</span>
        <span style="color:#f59e0b;"><i class="fa-solid fa-bolt"></i> View Dynamic ETA &rarr;</span>
      </div>
    </div>
  `).join("");
}

// ----------------- DUAL SEARCH & STATION AUTOCOMPLETE -----------------
function switchSearchMode(mode) {
  const tabStation = document.getElementById("tab-btn-station-search");
  const tabTrain = document.getElementById("tab-btn-train-search");
  const formStation = document.getElementById("station-search-form");
  const formTrain = document.getElementById("train-num-search-form");

  if (mode === "station") {
    tabStation.classList.add("active");
    tabTrain.classList.remove("active");
    formStation.classList.remove("hidden");
    formTrain.classList.add("hidden");
  } else {
    tabStation.classList.remove("active");
    tabTrain.classList.add("active");
    formStation.classList.add("hidden");
    formTrain.classList.remove("hidden");
  }
}

function setupStationAutocomplete() {
  const fromInput = document.getElementById("from-station-input");
  const toInput = document.getElementById("to-station-input");
  const fromDropdown = document.getElementById("from-station-dropdown");
  const toDropdown = document.getElementById("to-station-dropdown");

  async function handleStationInput(inputEl, dropdownEl) {
    const q = inputEl.value.trim();
    if (q.length < 1) {
      dropdownEl.classList.add("hidden");
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/api/stations?query=${encodeURIComponent(q)}`);
      if (!res.ok) return;
      const stations = await res.json();

      if (stations.length === 0) {
        dropdownEl.innerHTML = `<div class="search-dropdown-item text-muted">No station matches "${q}"</div>`;
      } else {
        dropdownEl.innerHTML = stations.slice(0, 8).map(s => `
          <div class="search-dropdown-item" onclick="selectStation('${inputEl.id}', '${s.name} (${s.code})', '${dropdownEl.id}')">
            <div>
              <strong>${s.name}</strong> <span style="color:#94a3b8; font-size:0.75rem;">(${s.code})</span>
              <div style="font-size:0.7rem; color:#64748b;">${s.zone} Zone • ${s.division} Div</div>
            </div>
            <span class="badge-tag" style="color:#38bdf8;">Select</span>
          </div>
        `).join("");
      }
      dropdownEl.classList.remove("hidden");
    } catch (e) {
      console.warn("Station autocomplete fetch error:", e);
    }
  }

  if (fromInput) {
    fromInput.addEventListener("input", () => handleStationInput(fromInput, fromDropdown));
  }
  if (toInput) {
    toInput.addEventListener("input", () => handleStationInput(toInput, toDropdown));
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".station-field-wrap")) {
      if (fromDropdown) fromDropdown.classList.add("hidden");
      if (toDropdown) toDropdown.classList.add("hidden");
    }
  });

  renderRecentSearches();
}

function selectStation(inputId, formattedVal, dropdownId) {
  const input = document.getElementById(inputId);
  const dropdown = document.getElementById(dropdownId);
  if (input) input.value = formattedVal;
  if (dropdown) dropdown.classList.add("hidden");
}

function swapStations() {
  const fromInput = document.getElementById("from-station-input");
  const toInput = document.getElementById("to-station-input");
  if (!fromInput || !toInput) return;

  const temp = fromInput.value;
  fromInput.value = toInput.value;
  toInput.value = temp;

  if (fromInput.value && toInput.value) {
    searchTrainsByStations();
  }
}

function setRouteAndSearch(fromCode, toCode) {
  switchSearchMode('station');
  const fromInput = document.getElementById("from-station-input");
  const toInput = document.getElementById("to-station-input");
  if (fromInput) fromInput.value = fromCode;
  if (toInput) toInput.value = toCode;
  searchTrainsByStations();
}

async function searchTrainsByStations() {
  const fromVal = document.getElementById("from-station-input").value.trim();
  const toVal = document.getElementById("to-station-input").value.trim();
  const resultsBox = document.getElementById("station-search-results-box");
  const resultsList = document.getElementById("station-search-results-list");
  const resultsTitle = document.getElementById("search-results-title");

  // Validation
  if (!fromVal || !toVal) {
    showToast("Please select both Origin (From) and Destination (To) stations.", "danger");
    return;
  }

  if (fromVal.toLowerCase() === toVal.toLowerCase()) {
    showToast("Origin and destination stations cannot be the same.", "danger");
    return;
  }

  resultsBox.classList.remove("hidden");
  resultsList.innerHTML = `<div class="card panel-card text-center" style="padding:1.5rem;"><p class="text-muted"><i class="fa-solid fa-spinner fa-spin text-cyan"></i> Searching available direct trains between ${fromVal} and ${toVal}...</p></div>`;

  try {
    const res = await fetch(`${API_BASE}/api/trains/search?from_station=${encodeURIComponent(fromVal)}&to_station=${encodeURIComponent(toVal)}`);
    const data = await res.json();

    if (!res.ok) {
      resultsList.innerHTML = `
        <div class="card panel-card text-center" style="padding:1.5rem;">
          <p style="color:#fb7185;"><i class="fa-solid fa-circle-exclamation"></i> ${data.detail || "Error searching trains"}</p>
        </div>
      `;
      return;
    }

    // Save recent search
    saveRecentSearch(fromVal, toVal);

    if (data.count === 0 || !data.trains || data.trains.length === 0) {
      resultsTitle.innerHTML = `<i class="fa-solid fa-ban text-amber"></i> Direct Trains (${fromVal} → ${toVal})`;
      resultsList.innerHTML = `
        <div class="card panel-card text-center" style="padding:2rem;">
          <h4 style="color:#f59e0b; margin-bottom:0.5rem;"><i class="fa-solid fa-triangle-exclamation"></i> No Direct Trains Found</h4>
          <p class="text-muted">No scheduled train operates directly from ${data.from_station.name} (${data.from_station.code}) to ${data.to_station.name} (${data.to_station.code}) in this route sequence.</p>
        </div>
      `;
      return;
    }

    resultsTitle.innerHTML = `<i class="fa-solid fa-train-subway text-cyan"></i> Direct Trains: ${data.from_station.name} (${data.from_station.code}) → ${data.to_station.name} (${data.to_station.code}) <span class="badge-tag" style="color:#38bdf8; margin-left:0.5rem;">${data.count} Train(s) Found</span>`;

    resultsList.innerHTML = data.trains.map(t => {
      const isDelayed = t.current_delay_min > 0;
      return `
        <div class="station-result-card">
          <div class="result-card-main">
            <div class="result-train-header">
              <span class="result-train-num">${t.train_number}</span>
              <span class="result-train-name">${t.train_name}</span>
              <span class="badge-tag" style="color:#38bdf8;">${t.train_type}</span>
            </div>

            <div class="result-timing-row">
              <div class="timing-block">
                <div class="time-lbl">DEPARTURE (${t.origin_station.code})</div>
                <div class="time-val">${t.origin_station.departure}</div>
                <div style="font-size:0.7rem; color:#94a3b8;">${t.origin_station.name} (PF ${t.origin_station.platform})</div>
              </div>

              <div style="font-size:1.2rem; color:#64748b;"><i class="fa-solid fa-arrow-right"></i></div>

              <div class="timing-block">
                <div class="time-lbl">SCH. ARRIVAL (${t.destination_station.code})</div>
                <div class="time-val">${t.destination_station.scheduled_arrival}</div>
                <div style="font-size:0.7rem; color:#94a3b8;">${t.destination_station.name} (PF ${t.destination_station.platform})</div>
              </div>

              <div class="result-dynamic-box">
                <div>
                  <div class="time-lbl">DYNAMIC PREDICTED ETA</div>
                  <div class="time-val text-cyan">${t.destination_station.dynamic_eta}</div>
                </div>
                <div>
                  <div class="time-lbl">CURRENT DELAY</div>
                  <span class="delay-pill ${isDelayed ? 'delayed' : 'ontime'}">
                    ${isDelayed ? `+${t.current_delay_min} min` : 'On Time'}
                  </span>
                </div>
              </div>
            </div>

            <div style="font-size:0.75rem; color:#64748b; margin-top:0.4rem;">
              <i class="fa-solid fa-road"></i> Inter-station Distance: ${t.distance_km} km • Status: <strong style="color:${t.live_status === 'RUNNING' ? '#10b981' : '#f59e0b'}">${t.live_status}</strong>
            </div>
          </div>

          <div>
            <button class="btn btn-primary" onclick="trackTrain('${t.train_number}')">
              <i class="fa-solid fa-bolt"></i> TRACK TRAIN
            </button>
          </div>
        </div>
      `;
    }).join("");

  } catch (err) {
    console.error("Route search error:", err);
    resultsList.innerHTML = `<div class="card panel-card text-center" style="padding:1.5rem;"><p class="text-danger">Network error connecting to search service.</p></div>`;
  }
}

function closeSearchResults() {
  const box = document.getElementById("station-search-results-box");
  if (box) box.classList.add("hidden");
}

function saveRecentSearch(fromSt, toSt) {
  try {
    let recent = JSON.parse(localStorage.getItem("rn_recent_searches") || "[]");
    recent = recent.filter(r => !(r.from === fromSt && r.to === toSt));
    recent.unshift({ from: fromSt, to: toSt, timestamp: new Date().toISOString() });
    recent = recent.slice(0, 4); // Keep top 4
    localStorage.setItem("rn_recent_searches", JSON.stringify(recent));
    renderRecentSearches();
  } catch (e) {
    console.warn("Error saving recent search:", e);
  }
}

function renderRecentSearches() {
  const container = document.getElementById("recent-searches-list");
  const wrap = document.getElementById("recent-searches-wrap");
  if (!container || !wrap) return;

  try {
    const recent = JSON.parse(localStorage.getItem("rn_recent_searches") || "[]");
    if (!recent || recent.length === 0) {
      wrap.classList.add("hidden");
      return;
    }

    wrap.classList.remove("hidden");
    container.innerHTML = recent.map(r => `
      <span class="route-pill" onclick="setRouteAndSearch('${r.from}', '${r.to}')">
        ${r.from} → ${r.to}
      </span>
    `).join("");
  } catch (e) {
    wrap.classList.add("hidden");
  }
}

// ----------------- TRAIN NUMBER SEARCH & AUTOCOMPLETE -----------------
function setupSearchDropdown() {
  const input = document.getElementById("train-search-input");
  const dropdown = document.getElementById("search-results-dropdown");
  if (!input || !dropdown) return;

  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    if (!q) {
      dropdown.classList.add("hidden");
      return;
    }
    const filtered = state.allTrains.filter(t =>
      t.train_number.toLowerCase().includes(q) ||
      t.train_name.toLowerCase().includes(q) ||
      t.source.toLowerCase().includes(q) ||
      t.destination.toLowerCase().includes(q)
    );

    if (filtered.length === 0) {
      dropdown.innerHTML = `<div class="search-dropdown-item text-muted">No trains match "${q}"</div>`;
    } else {
      dropdown.innerHTML = filtered.map(t => `
        <div class="search-dropdown-item" onclick="selectSearchTrain('${t.train_number}')">
          <div>
            <strong>${t.train_number}</strong> – ${t.train_name}
            <div style="font-size:0.75rem; color:#94a3b8;">${t.source} → ${t.destination}</div>
          </div>
          <span class="badge-tag" style="color:#38bdf8;">Track</span>
        </div>
      `).join("");
    }
    dropdown.classList.remove("hidden");
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".search-box-card")) {
      dropdown.classList.add("hidden");
    }
  });
}

function handleSearchKey(e) {
  if (e.key === "Enter") searchTrains();
}

function searchTrains() {
  const query = document.getElementById("train-search-input").value.trim();
  if (query) {
    trackTrain(query);
    document.getElementById("search-results-dropdown").classList.add("hidden");
  }
}

function selectSearchTrain(trainNo) {
  trackTrain(trainNo);
  document.getElementById("search-results-dropdown").classList.add("hidden");
}

// ----------------- TRACK TRAIN & DYNAMIC ETA -----------------
async function trackTrain(trainIdent, navigate = true) {
  try {
    const res = await fetch(`${API_BASE}/api/trains/${trainIdent}`);
    if (!res.ok) {
      showToast(`Train ${trainIdent} not found`, "danger");
      return;
    }
    const data = await res.json();
    state.currentTrain = data;
    renderTrackView(data);
    initOrUpdateMap();
    connectTrainWebSocket(data.id);

    if (navigate) {
      switchTab("track");
    }
  } catch (err) {
    console.error("Error fetching train details:", err);
    showToast("Error retrieving train telemetry", "danger");
  }
}

function refreshCurrentTrain() {
  if (state.currentTrain) {
    trackTrain(state.currentTrain.train_number, false);
    showToast("Recalculated Dynamic ETA from latest telemetry", "success");
  }
}

function renderTrackView(t) {
  // Train Header Info
  document.getElementById("track-number").textContent = t.train_number;
  document.getElementById("track-name").textContent = t.train_name;
  document.getElementById("track-route").textContent = `${t.source} → ${t.destination}`;

  // Live Metrics
  if (t.live_state) {
    document.getElementById("track-status").innerHTML = `<i class="fa-solid fa-circle-dot"></i> ${t.live_state.status}`;
    document.getElementById("track-speed").textContent = `${t.live_state.speed_kmh} km/h`;
    document.getElementById("track-current-delay").textContent = `+${t.live_state.current_delay_min} min`;
    document.getElementById("track-pole").textContent = t.live_state.reference_pole || "KM 42/18";

    // Side card metrics
    document.getElementById("track-section-val").textContent = t.live_state.track_section;
    document.getElementById("pole-ref-val").textContent = t.live_state.reference_pole || "KM 42/18";
    if (t.live_state.weather_info) {
      const w = t.live_state.weather_info;
      const icon = w.condition === 'RAIN' ? 'fa-cloud-showers-heavy text-cyan' : (w.condition === 'FOG' ? 'fa-smog text-muted' : (w.condition === 'CLOUDS' ? 'fa-cloud text-steel' : 'fa-sun text-amber'));
      document.getElementById("weather-val").innerHTML = `<i class="fa-solid ${icon}"></i> ${w.description} (${w.temp_c}°C)`;
      document.getElementById("weather-val").title = `OpenWeatherMap Live: ${w.temp_c}°C, Humidity ${w.humidity}%, Visibility ${w.visibility_meters}m | ${w.caution_note}`;
    } else {
      document.getElementById("weather-val").innerHTML = `<i class="fa-solid fa-sun text-amber"></i> ${t.live_state.weather_condition}`;
    }
    document.getElementById("gps-val").textContent = `${t.live_state.latitude.toFixed(4)} N, ${t.live_state.longitude.toFixed(4)} E`;
    document.getElementById("remaining-dist-val").textContent = `${t.live_state.remaining_distance_km} km`;
  }

  // Propagation Banner Check
  const banner = document.getElementById("propagation-alert-banner");
  const firstPred = t.predictions && t.predictions.length > 0 ? t.predictions[0] : null;
  if (firstPred && (firstPred.propagation_risk === "HIGH" || firstPred.propagation_risk === "MODERATE")) {
    banner.classList.remove("hidden");
    document.getElementById("propagation-alert-text").textContent =
      `High headway risk detected on section ${t.live_state?.track_section || "Shared Track"} due to preceding traffic. ${firstPred.reason_summary}`;
  } else {
    banner.classList.add("hidden");
  }

  // Dynamic ETA Predictions for 3-5 Upcoming Stations
  renderDynamicETAs(t.predictions || []);

  // Explainable Delay Breakdown
  renderDelayBreakdown(firstPred);

  // Full Route Table
  renderFullRouteTable(t.route_stops || []);

  // Corridor Field Observations
  loadCorridorObservations(t.live_state?.track_section);
}

function renderDynamicETAs(predictions) {
  const container = document.getElementById("predictions-container");
  if (!predictions || predictions.length === 0) {
    container.innerHTML = "<p class='text-muted'>No upcoming station predictions available.</p>";
    return;
  }

  container.innerHTML = predictions.map((p, idx) => {
    const isDelayed = p.predicted_delay_min > 0;
    return `
      <div class="eta-station-item">
        <div class="station-left">
          <div class="station-seq-badge">${idx + 1}</div>
          <div class="station-names">
            <h4>${p.station_name}</h4>
            <span>${p.station_code} • Sch: ${p.scheduled_arrival}</span>
          </div>
        </div>
        <div class="station-times">
          <div class="time-row">
            <span class="sch-time">${p.scheduled_arrival}</span>
            <span class="dyn-time">${p.predicted_arrival}</span>
            <span class="delay-pill ${isDelayed ? 'delayed' : 'ontime'}">
              ${isDelayed ? `+${p.predicted_delay_min}m delay` : 'On Time'}
            </span>
          </div>
          <div style="font-size:0.75rem; color:#94a3b8; margin-top:0.25rem;">
            <i class="fa-solid fa-code-branch text-cyan"></i> ${p.reason_summary}
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function renderDelayBreakdown(pred) {
  const container = document.getElementById("delay-breakdown-details");
  if (!pred) {
    container.innerHTML = "<p class='text-muted'>No active delay evolution data.</p>";
    return;
  }

  const signal = pred.signal_delay_min || 0;
  const congestion = pred.congestion_delay_min || 0;
  const weather = pred.weather_delay_min || 0;
  const recovery = pred.recovery_min || 0;

  const total = Math.max(1, signal + congestion + weather);

  container.innerHTML = `
    <div class="breakdown-item">
      <div class="breakdown-header">
        <span><i class="fa-solid fa-traffic-light text-danger"></i> Signal & Interlocking Delays</span>
        <strong class="text-danger">+${signal} min</strong>
      </div>
      <div class="breakdown-bar-track">
        <div class="breakdown-bar-fill fill-signal" style="width: ${(signal / total) * 100}%;"></div>
      </div>
    </div>

    <div class="breakdown-item">
      <div class="breakdown-header">
        <span><i class="fa-solid fa-train-track text-amber"></i> Section Congestion & Headway</span>
        <strong class="text-amber">+${congestion} min</strong>
      </div>
      <div class="breakdown-bar-track">
        <div class="breakdown-bar-fill fill-congestion" style="width: ${(congestion / total) * 100}%;"></div>
      </div>
    </div>

    <div class="breakdown-item">
      <div class="breakdown-header">
        <span><i class="fa-solid fa-cloud-sun text-cyan"></i> Weather & Environmental Impact</span>
        <strong class="text-cyan">+${weather} min</strong>
      </div>
      <div class="breakdown-bar-track">
        <div class="breakdown-bar-fill fill-weather" style="width: ${(weather / total) * 100}%;"></div>
      </div>
    </div>

    <div class="breakdown-item">
      <div class="breakdown-header">
        <span><i class="fa-solid fa-shield-halved text-success"></i> Section Scheduled Recovery Buffer</span>
        <strong class="text-success">-${recovery} min</strong>
      </div>
      <div class="breakdown-bar-track">
        <div class="breakdown-bar-fill fill-recovery" style="width: ${Math.min(100, (recovery / total) * 100)}%;"></div>
      </div>
    </div>

    <div class="breakdown-summary-banner">
      <strong>Formula Evaluation:</strong> ETA = Scheduled Time (${pred.scheduled_arrival}) + Signal (${signal}m) + Congestion (${congestion}m) + Weather (${weather}m) - Recovery Buffer (${recovery}m) = <strong>Predicted Arrival ${pred.predicted_arrival} (+${pred.predicted_delay_min}m)</strong>.
    </div>
  `;
}

function renderFullRouteTable(stops) {
  const tbody = document.getElementById("full-route-tbody");
  if (!stops || stops.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-muted">No route stops recorded.</td></tr>`;
    return;
  }

  tbody.innerHTML = stops.map(s => `
    <tr>
      <td><span class="station-seq-badge" style="width:24px; height:24px; font-size:0.75rem;">${s.stop_sequence}</span></td>
      <td><strong>${s.station.name}</strong> <span style="color:#94a3b8; font-size:0.75rem;">(${s.station.code})</span></td>
      <td class="font-mono">${s.scheduled_arrival || '—'}</td>
      <td class="font-mono">${s.scheduled_departure || '—'}</td>
      <td>${s.distance_from_source_km} km</td>
      <td>PF ${s.platform}</td>
      <td>${s.halt_minutes} min</td>
    </tr>
  `).join("");
}

async function loadCorridorObservations(section) {
  const container = document.getElementById("corridor-obs-list");
  try {
    const res = await fetch(`${API_BASE}/api/field-observations?limit=10`);
    if (res.ok) {
      const obs = await res.json();
      if (!obs || obs.length === 0) {
        container.innerHTML = "<p class='text-muted'>No active survey warnings on this corridor.</p>";
        return;
      }
      const top10 = obs.slice(0, 10);
      container.innerHTML = top10.map(o => `
        <div class="field-obs-item">
          <div class="obs-top">
            <span class="obs-type-tag">${o.observation_type}</span>
            <span class="delay-pill delayed">+${o.impact_delay_min}m</span>
          </div>
          <div class="obs-desc">${o.description}</div>
          <div style="font-size:0.7rem; color:#64748b; margin-top:0.3rem;">
            Section: ${o.track_section} • Ref: ${o.pole_reference || 'N/A'}
          </div>
        </div>
      `).join("");
    }
  } catch (e) {
    container.innerHTML = "<p class='text-muted'>Unable to fetch survey observations.</p>";
  }
}

// ----------------- WEBSOCKET REAL-TIME SYNC -----------------
function connectTrainWebSocket(trainId) {
  if (state.ws) {
    state.ws.close();
  }

  const wsUrl = `${WS_BASE}/ws/trains/${trainId}`;
  state.ws = new WebSocket(wsUrl);

  const statusBadge = document.getElementById("ws-indicator");
  const statusText = document.getElementById("ws-status-text");

  state.ws.onopen = () => {
    statusBadge.style.borderColor = "rgba(16, 185, 129, 0.4)";
    statusText.textContent = "Live Telemetry Connected";
  };

  state.ws.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data);
      if (data.type === "TELEMETRY_UPDATE" || data.type === "SIMULATION_STEP") {
        if (state.currentTrain && state.currentTrain.id === trainId) {
          // Re-fetch current train state to reflect recalculated predictions
          trackTrain(state.currentTrain.train_number, false);
          showToast(`⚡ Real-time Telemetry Update: Delay now +${data.current_delay_min}m`, "info");
        }
      }
    } catch (e) {
      console.warn("WebSocket parse error:", e);
    }
  };

  state.ws.onclose = () => {
    statusText.textContent = "Offline (Reconnecting...)";
    setTimeout(() => {
      if (state.currentTrain) connectTrainWebSocket(state.currentTrain.id);
    }, 5000);
  };
}

// ----------------- SIMULATION STEPPER -----------------
let historicalCursor = 0;

async function replayNextHistoricalPoint() {
  if (!state.currentTrain) return;
  try {
    const res = await fetch(`${API_BASE}/api/telemetry/apply-history-point/${state.currentTrain.train_number}?point_idx=${historicalCursor}`, {
      method: "POST"
    });
    if (res.ok) {
      const data = await res.json();
      historicalCursor = (historicalCursor + 1) % 50;
      showToast(`📊 6-Month Log Replay (Pt #${historicalCursor}): ${data.applied_point.current_station} | Speed: ${data.applied_point.speed_kmh}km/h | Delay: +${data.applied_point.delay_min}m`, "success");
    } else {
      showToast("No historical log samples available for this train", "info");
    }
  } catch (e) {
    showToast("Historical replay request failed", "danger");
  }
}

async function triggerSimulateStep(delayDelta, speed) {
  if (!state.currentTrain) return;
  try {
    const res = await fetch(`${API_BASE}/api/telemetry/simulate-step/${state.currentTrain.id}?delay_delta=${delayDelta}&speed=${speed}`, {
      method: "POST"
    });
    if (res.ok) {
      const data = await res.json();
      showToast(`Simulated step injected! New delay: +${data.new_delay} min`, "success");
    }
  } catch (e) {
    showToast("Simulation injection failed", "danger");
  }
}

// ----------------- LIVE INTERACTIVE LEAFLET MAP -----------------
function initOrUpdateMap() {
  const mapElement = document.getElementById("live-leaflet-map");
  if (!mapElement) return;

  if (!state.map) {
    state.map = L.map('live-leaflet-map', {
      center: [29.5, 76.5],
      zoom: 7,
      zoomControl: true
    });

    const maptilerKey = (state.config && (state.config.map_api_key || state.config.maptiler_api_key))
      ? (state.config.map_api_key || state.config.maptiler_api_key)
      : 'p9vc6beu2V8LQJ818lck';

    const maptilerHybrid = L.tileLayer(`https://api.maptiler.com/maps/hybrid/{z}/{x}/{y}.jpg?key=${maptilerKey}`, {
      attribution: '&copy; <a href="https://www.maptiler.com/">MapTiler</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 20,
      tileSize: 512,
      zoomOffset: -1
    });

    const maptilerOutdoor = L.tileLayer(`https://api.maptiler.com/maps/outdoor-v2/{z}/{x}/{y}.png?key=${maptilerKey}`, {
      attribution: '&copy; <a href="https://www.maptiler.com/">MapTiler</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 20,
      tileSize: 512,
      zoomOffset: -1
    });

    const maptilerStreets = L.tileLayer(`https://api.maptiler.com/maps/streets-v2/{z}/{x}/{y}.png?key=${maptilerKey}`, {
      attribution: '&copy; <a href="https://www.maptiler.com/">MapTiler</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 20,
      tileSize: 512,
      zoomOffset: -1
    });

    const darkLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; <a href="https://carto.com/">CARTO</a> &copy; OpenStreetMap',
      subdomains: 'abcd',
      maxZoom: 20
    });

    const osmStandard = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/">OpenStreetMap</a> contributors',
      maxZoom: 19
    });

    // Set MapTiler Satellite Hybrid as the active default map layer
    maptilerHybrid.addTo(state.map);

    const baseMaps = {
      "🛰️ MapTiler Satellite Hybrid": maptilerHybrid,
      "🚂 MapTiler Railways & Outdoors": maptilerOutdoor,
      "🗺️ MapTiler Streets": maptilerStreets,
      "🌙 Tactical Dark": darkLayer,
      "🌐 OpenStreetMap": osmStandard
    };

    L.control.layers(baseMaps, null, { position: 'topright' }).addTo(state.map);

    // Auto-invalidate map size whenever window resizes
    window.addEventListener('resize', () => {
      if (state.map) state.map.invalidateSize();
    });
  }

  // Ensure map is properly sized in case tab was previously hidden
  state.map.invalidateSize();

  // Clear previous layers
  if (state.mapLayers.polyline) state.map.removeLayer(state.mapLayers.polyline);
  if (state.mapLayers.trainMarker) state.map.removeLayer(state.mapLayers.trainMarker);
  state.mapLayers.stationMarkers.forEach(m => state.map.removeLayer(m));
  state.mapLayers.stationMarkers = [];

  // Update map header subtitle
  const sub = document.getElementById("map-status-sub");
  if (state.currentTrain) {
    if (sub) sub.textContent = `Tracking Train ${state.currentTrain.train_number} (${state.currentTrain.train_name}) • ${state.currentTrain.source} → ${state.currentTrain.destination}`;
  }

  if (!state.currentTrain || !state.currentTrain.route_stops || state.currentTrain.route_stops.length === 0) {
    // If no train is selected yet, show all active trains across corridor
    if (state.allTrains && state.allTrains.length > 0) {
      state.allTrains.forEach(t => {
        if (t.live_state) {
          const lat = t.live_state.latitude;
          const lng = t.live_state.longitude;
          const marker = L.circleMarker([lat, lng], {
            radius: 8,
            fillColor: "#10b981",
            color: "#ffffff",
            weight: 2,
            opacity: 1,
            fillOpacity: 0.9
          }).bindPopup(`
            <b>Train ${t.train_number} - ${t.train_name}</b><br>
            Speed: ${t.live_state.speed_kmh} km/h | Delay: +${t.live_state.current_delay_min}m<br>
            <button class="btn btn-primary btn-sm mt-2" onclick="trackTrain('${t.train_number}')">Track Train</button>
          `);
          marker.addTo(state.map);
          state.mapLayers.stationMarkers.push(marker);
        }
      });
    }
    return;
  }

  const latlngs = [];
  state.currentTrain.route_stops.forEach(s => {
    const lat = s.station.latitude;
    const lng = s.station.longitude;
    latlngs.push([lat, lng]);

    // Station circle marker
    const marker = L.circleMarker([lat, lng], {
      radius: 6,
      fillColor: "#38bdf8",
      color: "#ffffff",
      weight: 2,
      opacity: 1,
      fillOpacity: 0.95
    }).bindPopup(`
      <div style="font-family:inherit; min-width:140px;">
        <strong style="color:#0f172a; font-size:0.95rem;">${s.station.name}</strong> 
        <span style="color:#64748b; font-size:0.8rem;">(${s.station.code})</span><br>
        <span style="color:#334155; font-size:0.8rem;">Seq #${s.stop_sequence} • PF ${s.platform}</span><br>
        <div style="margin-top:4px; font-weight:600; color:#0284c7;">Sch. Arr: ${s.scheduled_arrival || 'Origin'}</div>
      </div>
    `);
    marker.addTo(state.map);
    state.mapLayers.stationMarkers.push(marker);
  });

  // Polyline for track route
  state.mapLayers.polyline = L.polyline(latlngs, {
    color: '#0284c7',
    weight: 4,
    opacity: 0.85,
    dashArray: '8, 6'
  }).addTo(state.map);

  // Train live position marker with pulse
  if (state.currentTrain.live_state) {
    const tLat = state.currentTrain.live_state.latitude;
    const tLng = state.currentTrain.live_state.longitude;

    const trainIcon = L.divIcon({
      className: 'train-map-marker-pulse',
      html: `<div class="pulse-wave"></div><div class="pulse-core"></div>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12]
    });

    const isDelayed = state.currentTrain.live_state.current_delay_min > 0;
    state.mapLayers.trainMarker = L.marker([tLat, tLng], { icon: trainIcon })
      .bindPopup(`
        <div style="font-family:inherit; padding:4px; min-width:180px;">
          <div style="font-weight:700; color:#0f172a; font-size:1rem;">Train ${state.currentTrain.train_number}</div>
          <div style="color:#64748b; font-size:0.8rem; margin-bottom:6px;">${state.currentTrain.train_name}</div>
          <div style="font-size:0.85rem; margin-bottom:2px;">⚡ Speed: <strong>${state.currentTrain.live_state.speed_kmh} km/h</strong></div>
          <div style="font-size:0.85rem; margin-bottom:2px;">⏱️ Delay: <strong style="color:${isDelayed ? '#e11d48' : '#16a34a'};">+${state.currentTrain.live_state.current_delay_min} min</strong></div>
          <div style="font-size:0.8rem; color:#64748b;">📍 Section: ${state.currentTrain.live_state.track_section || 'Main Line'} (${state.currentTrain.live_state.reference_pole || 'KM Ref'})</div>
        </div>
      `)
      .addTo(state.map);

    state.map.setView([tLat, tLng], 8);
  } else if (latlngs.length > 0) {
    state.map.fitBounds(latlngs, { padding: [30, 30] });
  }
}

// ----------------- MY SAVED TRAINS -----------------
async function loadSavedTrains() {
  if (!state.token) {
    document.getElementById("saved-trains-list").innerHTML = `
      <div class="card panel-card text-center" style="padding:2rem;">
        <p class="text-muted">Please sign in to save and monitor your favorite trains.</p>
        <button class="btn btn-primary mt-3" onclick="openAuthModal()">Sign In</button>
      </div>
    `;
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/saved-trains`, {
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (res.ok) {
      state.savedTrains = await res.json();
      document.getElementById("saved-count-badge").textContent = `${state.savedTrains.length} Trains Saved`;
      renderSavedTrains();
    }
  } catch (e) {
    console.warn("Failed loading saved trains:", e);
  }
}

function renderSavedTrains() {
  const container = document.getElementById("saved-trains-list");
  if (!state.savedTrains || state.savedTrains.length === 0) {
    container.innerHTML = `
      <div class="card panel-card text-center" style="grid-column: 1/-1; padding:2rem;">
        <p class="text-muted">You have not saved any trains yet. Click "Save Train" while tracking to bookmark.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = state.savedTrains.map(s => `
    <div class="train-summary-card">
      <div class="train-card-top">
        <div>
          <span class="train-num-pill">${s.train_number}</span>
          <div class="train-name-title">${s.train_name}</div>
        </div>
        <button class="btn btn-sm btn-danger" onclick="removeSavedTrain(${s.train_id})">
          <i class="fa-solid fa-trash"></i>
        </button>
      </div>
      <div class="train-route-text">${s.source} → ${s.destination}</div>
      <div class="train-stats-row">
        <span>Delay: <strong style="color:#f59e0b;">+${s.current_delay_min}m</strong></span>
        <button class="btn btn-sm btn-primary" onclick="trackTrain('${s.train_number}')">
          <i class="fa-solid fa-bolt"></i> Live Track
        </button>
      </div>
    </div>
  `).join("");
}

async function toggleSaveCurrentTrain() {
  if (!state.token) {
    openAuthModal();
    showToast("Please sign in to save trains", "info");
    return;
  }
  if (!state.currentTrain) return;

  try {
    const res = await fetch(`${API_BASE}/api/saved-trains/${state.currentTrain.id}`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (res.ok) {
      showToast(`Train ${state.currentTrain.train_number} saved to your watchlist!`, "success");
      loadSavedTrains();
    }
  } catch (e) {
    showToast("Failed to save train", "danger");
  }
}

async function removeSavedTrain(trainId) {
  if (!state.token) return;
  try {
    const res = await fetch(`${API_BASE}/api/saved-trains/${trainId}`, {
      method: "DELETE",
      headers: { "Authorization": `Bearer ${state.token}` }
    });
    if (res.ok) {
      showToast("Train removed from watchlist", "info");
      loadSavedTrains();
    }
  } catch (e) {
    showToast("Failed to remove saved train", "danger");
  }
}

// ----------------- CONTROL ROOM AUTH & MANAGEMENT -----------------
function isControllerAuthenticated() {
  const token = state.controllerToken || (state.token && state.user && (state.user.role === "controller" || state.user.role === "admin") ? state.token : null);
  const user = state.controllerUser || (state.user && (state.user.role === "controller" || state.user.role === "admin") ? state.user : null);
  if (!token || !user) return false;
  const role = (user.role || "").toLowerCase();
  return role === "controller" || role === "admin";
}

function getControllerToken() {
  if (state.controllerToken) return state.controllerToken;
  if (state.token && state.user && (state.user.role === "controller" || state.user.role === "admin")) {
    return state.token;
  }
  return null;
}

function getControllerUser() {
  return state.controllerUser || (state.user && (state.user.role === "controller" || state.user.role === "admin") ? state.user : null);
}

function checkControlRoomAccess() {
  const gate = document.getElementById("control-auth-gate");
  const dash = document.getElementById("control-dashboard-view");

  if (isControllerAuthenticated()) {
    if (gate) gate.classList.add("hidden");
    if (dash) dash.classList.remove("hidden");
    const user = getControllerUser();
    const userBadge = document.getElementById("ctrl-logged-in-user");
    const roleBadge = document.getElementById("ctrl-logged-in-role");
    if (userBadge) userBadge.textContent = user.full_name || user.username;
    if (roleBadge) roleBadge.textContent = user.role || "controller";
    loadControlRoom();
    connectControlWebSocket();
  } else {
    if (gate) gate.classList.remove("hidden");
    if (dash) dash.classList.add("hidden");
    if (state.controlWs) {
      try { state.controlWs.close(); } catch (_) { }
      state.controlWs = null;
    }
    const railwayIdInput = document.getElementById("control-railway-id");
    if (railwayIdInput) setTimeout(() => railwayIdInput.focus(), 150);
  }
}

// ----------------- CONTROL ROOM FIREBASE PHONE OTP 2FA AUTH -----------------
let otpTimerInterval = null;
let isControlOtpSending = false;

function getFirebaseConfig() {
  if (state.config && state.config.firebase && state.config.firebase.apiKey) {
    return state.config.firebase;
  }
  return {
    apiKey: "AIzaSyC8fLIyVIZcOB1wMMM11FDY7mOsafs8NEo",
    authDomain: "rail-nirdeshak-47387.firebaseapp.com",
    projectId: "rail-nirdeshak-47387",
    storageBucket: "rail-nirdeshak-47387.firebasestorage.app",
    messagingSenderId: "925306774424",
    appId: "1:925306774424:web:083fa5dc4f22b5e2ef81ed",
    measurementId: "G-K9TGP73Q0F"
  };
}

function initFirebaseClient() {
  if (typeof firebase === "undefined") {
    console.error("[Firebase] Firebase Compat SDK is not available in window.");
    return null;
  }
  if (!firebase.apps || firebase.apps.length === 0) {
    const config = getFirebaseConfig();
    try {
      firebase.initializeApp(config);
      console.log("[Firebase] Initialized Firebase App for project:", config.projectId);
    } catch (e) {
      console.error("[Firebase] Initialization error:", e);
    }
  }
  return firebase.auth();
}

function getControlRecaptchaVerifier() {
  if (window.controlRecaptchaVerifier) {
    return window.controlRecaptchaVerifier;
  }
  if (typeof firebase === "undefined") return null;

  initFirebaseClient();

  const container = document.getElementById("recaptcha-container");
  if (!container) return null;

  try {
    window.controlRecaptchaVerifier = new firebase.auth.RecaptchaVerifier("recaptcha-container", {
      size: "invisible",
      callback: () => {
        console.log("[Firebase Auth] reCAPTCHA solved");
      },
      "expired-callback": () => {
        console.warn("[Firebase Auth] reCAPTCHA expired, resetting");
        if (window.controlRecaptchaVerifier) {
          try {
            window.controlRecaptchaVerifier.render().then((widgetId) => {
              if (typeof grecaptcha !== "undefined") grecaptcha.reset(widgetId);
            });
          } catch (_) { }
        }
      }
    });
    return window.controlRecaptchaVerifier;
  } catch (err) {
    console.error("[Firebase Auth] RecaptchaVerifier creation error:", err);
    return null;
  }
}

function quickFillRailwayId(id) {
  const input = document.getElementById("control-railway-id");
  if (input) {
    input.value = id;
    input.focus();
  }
  hideControlLoginError();
}

function showControlLoginError(msg) {
  const errBox = document.getElementById("control-login-error");
  const errText = document.getElementById("control-login-error-text");
  if (errText) errText.textContent = msg;
  if (errBox) errBox.classList.remove("hidden");
}

function hideControlLoginError() {
  const errBox = document.getElementById("control-login-error");
  if (errBox) errBox.classList.add("hidden");
}

function showControlOtpError(msg) {
  const errBox = document.getElementById("control-otp-error");
  const errText = document.getElementById("control-otp-error-text");
  if (errText) errText.textContent = msg;
  if (errBox) errBox.classList.remove("hidden");
}

function hideControlOtpError() {
  const errBox = document.getElementById("control-otp-error");
  if (errBox) errBox.classList.add("hidden");
}

function resetToPhoneStep() {
  if (otpTimerInterval) {
    clearInterval(otpTimerInterval);
    otpTimerInterval = null;
  }
  isControlOtpSending = false;

  const phoneStep = document.getElementById("control-phone-step");
  const verifyStep = document.getElementById("control-verify-step");
  const otpInput = document.getElementById("control-otp-code");
  const sendBtn = document.getElementById("btn-send-control-otp");
  const btnText = document.getElementById("send-otp-btn-text");
  const btnLoader = document.getElementById("send-otp-btn-loader");

  hideControlLoginError();
  hideControlOtpError();

  if (phoneStep) phoneStep.classList.remove("hidden");
  if (verifyStep) verifyStep.classList.add("hidden");
  if (otpInput) otpInput.value = "";
  if (sendBtn) sendBtn.disabled = false;
  if (btnLoader) btnLoader.classList.add("hidden");
  if (btnText) {
    btnText.classList.remove("hidden");
    btnText.innerHTML = `<i class="fa-solid fa-paper-plane"></i> Verify Clearance &amp; Send SMS OTP`;
  }

  const railwayIdInput = document.getElementById("control-railway-id");
  if (railwayIdInput) setTimeout(() => railwayIdInput.focus(), 150);
}

// Backward compatibility alias
function switchBackToPasswordLogin() {
  resetToPhoneStep();
}

function handleControlFormSubmit(e) {
  if (e && e.preventDefault) e.preventDefault();
  const phoneStep = document.getElementById("control-phone-step");
  if (phoneStep && !phoneStep.classList.contains("hidden")) {
    sendControlPhoneVerification();
  } else {
    handleControlOtpSubmit(e);
  }
}

async function sendControlPhoneVerification() {
  if (isControlOtpSending) return;

  hideControlLoginError();
  hideControlOtpError();

  const idInput = document.getElementById("control-railway-id");
  const sendBtn = document.getElementById("btn-send-control-otp");
  const btnText = document.getElementById("send-otp-btn-text");
  const btnLoader = document.getElementById("send-otp-btn-loader");

  const rawInput = (idInput ? idInput.value : "").trim();

  if (!rawInput || rawInput.length < 3) {
    showControlLoginError("Please enter your 12-digit Railway ID or registered mobile number.");
    if (idInput) idInput.focus();
    return;
  }

  isControlOtpSending = true;
  if (sendBtn) sendBtn.disabled = true;
  if (btnText) btnText.classList.add("hidden");
  if (btnLoader) btnLoader.classList.remove("hidden");

  try {
    // 1. Verify Railway ID or Mobile against trusted backend registry
    let res = null;
    let data = {};
    try {
      res = await dynamicFetch("/api/auth/request-phone-verification", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ railway_id: rawInput })
      });
      data = await res.json().catch(() => ({}));
    } catch (netErr) {
      console.warn("dynamicFetch phone request err:", netErr);
    }

    if (!res || !res.ok) {
      let errorMsg = "Verification failed. Please check your Railway ID.";
      if (res && res.status === 405) {
        errorMsg = "Server returned Method Not Allowed. Please ensure the backend is started via `python backend/main.py`.";
      } else if (data && data.detail) {
        errorMsg = data.detail;
      } else if (!res) {
        errorMsg = "Cannot connect to Rail Nirdeshak backend. Please start the server (`python backend/main.py`).";
      }
      showControlLoginError(errorMsg);
      isControlOtpSending = false;
      if (sendBtn) sendBtn.disabled = false;
      if (btnText) btnText.classList.remove("hidden");
      if (btnLoader) btnLoader.classList.add("hidden");
      return;
    }

    // Backend returned authorized officer record and 10-minute session challenge
    state.pendingChallenge = data;

    // Update Step 2 banner
    const maskedPhoneEl = document.getElementById("ctrl-masked-phone");
    const officerNameEl = document.getElementById("ctrl-officer-banner-name");
    const officerRoleEl = document.getElementById("ctrl-officer-banner-role");

    if (maskedPhoneEl) maskedPhoneEl.textContent = data.masked_phone || data.phone_number;
    if (officerNameEl) officerNameEl.textContent = data.officer_name || "Authorized Officer";
    if (officerRoleEl) officerRoleEl.textContent = data.role || "controller";

    // 2. Initiate Firebase Phone Authentication using the registered official phone number
    const authInstance = initFirebaseClient();
    if (!authInstance) {
      throw new Error("Firebase Authentication SDK is not initialized. Please refresh.");
    }

    const appVerifier = getControlRecaptchaVerifier();
    if (!appVerifier) {
      throw new Error("Could not initialize reCAPTCHA security verifier.");
    }

    console.log(`[Firebase Phone Auth] Triggering SMS OTP for registered phone: ${data.phone_number}`);
    const confirmationResult = await authInstance.signInWithPhoneNumber(data.phone_number, appVerifier);
    window.controlConfirmationResult = confirmationResult;

    // 3. Switch UI to Step 2: OTP verification
    const phoneStep = document.getElementById("control-phone-step");
    const verifyStep = document.getElementById("control-verify-step");
    if (phoneStep) phoneStep.classList.add("hidden");
    if (verifyStep) verifyStep.classList.remove("hidden");

    showToast(`SMS OTP dispatched to registered mobile ${data.masked_phone}.`, "success");

    const otpInput = document.getElementById("control-otp-code");
    if (otpInput) {
      otpInput.value = "";
      setTimeout(() => otpInput.focus(), 150);
    }

    startOtpCountdown();
  } catch (err) {
    console.error("[Firebase Phone Auth] Dispatch Error:", err);
    let msg = err.message || "Failed to dispatch SMS OTP.";
    if (err.code === "auth/invalid-phone-number") {
      msg = "Registered phone number is invalid for international SMS dispatch.";
    } else if (err.code === "auth/quota-exceeded") {
      msg = "SMS quota exceeded for today. Please contact system administrator.";
    } else if (err.code === "auth/too-many-requests") {
      msg = "Too many attempts from this IP. Please wait a few minutes before retrying.";
    } else if (err.code === "auth/operation-not-allowed") {
      msg = "SMS not enabled for this region by Firebase. Please add +919876543210 under Firebase Console -> Authentication -> Sign-in method -> Phone -> 'Phone numbers for testing' (with OTP 123456), or enable India (+91) under Settings -> SMS Region Policy.";
    }
    showControlLoginError(msg);

    // Reset reCAPTCHA on failure so user can retry
    if (window.controlRecaptchaVerifier) {
      try { window.controlRecaptchaVerifier.clear(); } catch (_) { }
      window.controlRecaptchaVerifier = null;
    }
  } finally {
    isControlOtpSending = false;
    if (sendBtn) sendBtn.disabled = false;
    if (btnText) btnText.classList.remove("hidden");
    if (btnLoader) btnLoader.classList.add("hidden");
  }
}

function startOtpCountdown() {
  if (otpTimerInterval) clearInterval(otpTimerInterval);
  let timeLeft = 30;
  const timerText = document.getElementById("otp-timer-text");
  const countdownEl = document.getElementById("otp-countdown");
  const resendBtn = document.getElementById("btn-resend-otp");

  if (timerText) timerText.classList.remove("hidden");
  if (resendBtn) resendBtn.classList.add("hidden");
  if (countdownEl) countdownEl.textContent = timeLeft;

  otpTimerInterval = setInterval(() => {
    timeLeft--;
    if (countdownEl) countdownEl.textContent = timeLeft;
    if (timeLeft <= 0) {
      clearInterval(otpTimerInterval);
      otpTimerInterval = null;
      if (timerText) timerText.classList.add("hidden");
      if (resendBtn) resendBtn.classList.remove("hidden");
    }
  }, 1000);
}

async function handleControlOtpSubmit(e) {
  e.preventDefault();
  hideControlOtpError();

  const otpInput = document.getElementById("control-otp-code");
  const btnText = document.getElementById("verify-otp-btn-text");
  const btnLoader = document.getElementById("verify-otp-btn-loader");
  const verifyBtn = document.getElementById("btn-verify-control-otp");

  const otp = (otpInput ? otpInput.value : "").trim();
  if (!otp || !/^\d{6}$/.test(otp)) {
    showControlOtpError("Please enter the 6-digit SMS OTP received on your mobile.");
    if (otpInput) otpInput.focus();
    return;
  }

  if (!window.controlConfirmationResult || !state.pendingChallenge) {
    showControlOtpError("OTP session expired or missing. Please change Railway ID and restart verification.");
    return;
  }

  if (btnText) btnText.classList.add("hidden");
  if (btnLoader) btnLoader.classList.remove("hidden");
  if (verifyBtn) verifyBtn.disabled = true;

  try {
    // 1. Confirm OTP with Firebase client SDK
    const userCredential = await window.controlConfirmationResult.confirm(otp);
    const fbUser = userCredential.user;

    // 2. Obtain real Firebase ID token
    const idToken = await fbUser.getIdToken(true);

    // 3. Submit Firebase ID token and challenge session ID to FastAPI backend
    let res = null;
    let result = {};
    try {
      res = await dynamicFetch("/api/auth/verify-firebase-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          id_token: idToken,
          session_id: state.pendingChallenge.session_id,
          railway_id: state.pendingChallenge.railway_id
        })
      });
      result = await res.json().catch(() => ({}));
    } catch (vErr) {
      console.warn("dynamicFetch verify error:", vErr);
    }

    if (!res.ok) {
      const errDetail = result.detail || "Backend security check rejected session.";
      showControlOtpError(errDetail);
      return;
    }

    // 4. Session established: store token & user info
    state.controllerToken = result.access_token;
    state.controllerUser = result.user;
    localStorage.setItem("rn_ctrl_token", result.access_token);
    localStorage.setItem("rn_ctrl_user", JSON.stringify(result.user));

    showToast(`Access Granted: Welcome ${result.user.full_name} (${result.user.role.toUpperCase()})!`, "success");

    // Clean up temporary challenge state
    state.pendingChallenge = null;
    window.controlConfirmationResult = null;

    resetToPhoneStep();
    checkControlRoomAccess();
  } catch (err) {
    console.error("[Firebase OTP Verify] Error:", err);
    let msg = err.message || "Invalid or expired OTP code.";
    if (err.code === "auth/invalid-verification-code") {
      msg = "Invalid 6-digit OTP code. Please check your SMS and try again.";
    } else if (err.code === "auth/code-expired") {
      msg = "The OTP code has expired. Please click 'Resend OTP'.";
    }
    showControlOtpError(msg);
  } finally {
    if (btnText) btnText.classList.remove("hidden");
    if (btnLoader) btnLoader.classList.add("hidden");
    if (verifyBtn) verifyBtn.disabled = false;
  }
}

function toggleControlPasswordVisibility() {
  const pwInput = document.getElementById("control-password");
  const eyeIcon = document.getElementById("control-pw-eye");
  if (!pwInput) return;
  if (pwInput.type === "password") {
    pwInput.type = "text";
    if (eyeIcon) {
      eyeIcon.classList.remove("fa-eye");
      eyeIcon.classList.add("fa-eye-slash");
    }
  } else {
    pwInput.type = "password";
    if (eyeIcon) {
      eyeIcon.classList.remove("fa-eye-slash");
      eyeIcon.classList.add("fa-eye");
    }
  }
}

async function handleControlLogout() {
  const token = getControllerToken();
  try {
    if (token && token !== "cookie_session") {
      await fetch(`${API_BASE}/api/auth/logout`, {
        method: "POST",
        credentials: "include",
        headers: { "Authorization": `Bearer ${token}` }
      }).catch(() => { });
    } else {
      await fetch(`${API_BASE}/api/auth/logout`, {
        method: "POST",
        credentials: "include"
      }).catch(() => { });
    }
  } catch (_) { }

  state.controllerToken = null;
  state.controllerUser = null;
  state.pendingChallenge = null;
  window.controlConfirmationResult = null;
  localStorage.removeItem("rn_ctrl_token");
  localStorage.removeItem("rn_ctrl_user");

  if (state.controlWs) {
    try { state.controlWs.close(); } catch (_) { }
    state.controlWs = null;
  }

  // Clear rendered dashboard tables and KPIs
  const tbody = document.getElementById("control-trains-tbody");
  if (tbody) tbody.innerHTML = "<tr><td colspan='8' class='text-center text-muted py-4'><i class='fa-solid fa-lock'></i> Console locked. Authenticate to view live telemetry.</td></tr>";
  const elActive = document.getElementById("kpi-active-trains");
  const elDelayed = document.getElementById("kpi-delayed-trains");
  const elProp = document.getElementById("kpi-prop-risks");
  const elField = document.getElementById("kpi-field-alerts");
  if (elActive) elActive.textContent = "0";
  if (elDelayed) elDelayed.textContent = "0";
  if (elProp) elProp.textContent = "0";
  if (elField) elField.textContent = "0";

  showToast("Control Room console locked and logged out.", "info");
  resetToPhoneStep();
  checkControlRoomAccess();
}

async function loadControlRoom() {
  if (!isControllerAuthenticated()) {
    checkControlRoomAccess();
    return;
  }

  const token = getControllerToken();
  const headers = {};
  if (token && token !== "cookie_session") {
    headers["Authorization"] = `Bearer ${token}`;
  }
  try {
    const res = await dynamicFetch("/api/control-room/overview", {
      headers: headers,
      credentials: "include"
    });

    if (res.status === 401 || res.status === 403) {
      showToast("Control session expired or unauthorized. Please sign in again.", "danger");
      handleControlLogout();
      return;
    }

    if (res.ok) {
      state.controlData = await res.json();
      renderControlRoom(state.controlData);
    }
  } catch (e) {
    console.warn("Failed loading control room overview:", e);
  }
}

function renderControlRoom(ctrl) {
  if (!ctrl) return;

  const elActive = document.getElementById("kpi-active-trains");
  const elDelayed = document.getElementById("kpi-delayed-trains");
  const elProp = document.getElementById("kpi-prop-risks");
  const elField = document.getElementById("kpi-field-alerts");
  if (elActive) elActive.textContent = ctrl.active_trains_count;
  if (elDelayed) elDelayed.textContent = ctrl.delayed_trains_count;
  if (elProp) elProp.textContent = ctrl.high_risk_propagations;
  if (elField) elField.textContent = ctrl.active_field_alerts;

  const tbody = document.getElementById("control-trains-tbody");
  if (!tbody || !ctrl.trains) return;

  tbody.innerHTML = ctrl.trains.map(t => {
    const isPropHigh = t.propagation_risk === "HIGH";
    return `
      <tr>
        <td class="font-mono"><strong>${t.train_number}</strong></td>
        <td>${t.train_name}</td>
        <td style="font-size:0.75rem; color:#94a3b8;">${t.source} → ${t.destination}</td>
        <td class="font-mono text-cyan">${t.track_section}</td>
        <td>${t.speed_kmh} km/h</td>
        <td><span class="delay-pill ${t.current_delay_min > 0 ? 'delayed' : 'ontime'}">+${t.current_delay_min}m</span></td>
        <td>
          <span class="badge-tag" style="color: ${isPropHigh ? '#fb7185' : '#34d399'}; font-weight:700;">
            ${t.propagation_risk}
          </span>
        </td>
        <td>
          <button class="btn btn-sm btn-action" onclick="trackTrain('${t.train_number}')">Inspect</button>
        </td>
      </tr>
    `;
  }).join("");
}

async function submitFieldObservation(e) {
  e.preventDefault();
  if (!isControllerAuthenticated()) {
    showToast("Authentication required to dispatch survey observations", "danger");
    checkControlRoomAccess();
    return;
  }

  const section = document.getElementById("obs-section").value;
  const pole = document.getElementById("obs-pole").value;
  const type = document.getElementById("obs-type").value;
  const delay = parseInt(document.getElementById("obs-delay").value, 10);
  const desc = document.getElementById("obs-desc").value;
  const token = getControllerToken();
  const headers = { "Content-Type": "application/json" };
  if (token && token !== "cookie_session") {
    headers["Authorization"] = `Bearer ${token}`;
  }

  try {
    const res = await dynamicFetch("/api/field-observations", {
      method: "POST",
      headers: headers,
      credentials: "include",
      body: JSON.stringify({
        track_section: section,
        pole_reference: pole,
        observation_type: type,
        impact_delay_min: delay,
        description: desc
      })
    });

    if (res.status === 401 || res.status === 403) {
      showToast("Access forbidden: Controller privileges required", "danger");
      handleControlLogout();
      return;
    }

    if (res.ok) {
      showToast("Survey observation logged & propagated across corridor!", "success");
      loadControlRoom();
      if (state.currentTrain) trackTrain(state.currentTrain.train_number, false);
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || "Failed to dispatch survey observation", "danger");
    }
  } catch (err) {
    showToast("Failed to dispatch survey observation", "danger");
  }
}

function connectControlWebSocket() {
  if (!isControllerAuthenticated()) return;
  if (state.controlWs && state.controlWs.readyState === WebSocket.OPEN) return;

  const token = getControllerToken();
  const tokenParam = (token && token !== "cookie_session") ? `?token=${encodeURIComponent(token)}` : "";
  const ctrlWsUrl = `${getWsBase()}/ws/control-room${tokenParam}`;
  try {
    state.controlWs = new WebSocket(ctrlWsUrl);
    state.controlWs.onopen = () => {
      console.log("Control Room telemetry WebSocket connected.");
    };
    state.controlWs.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        if (data.type === "TELEMETRY_UPDATE" || data.type === "SIMULATION_STEP") {
          loadControlRoom();
        }
      } catch (_) { }
    };
    state.controlWs.onclose = (evt) => {
      if (evt.code === 1008) {
        console.warn("Control WebSocket rejected: Unauthorized or Forbidden");
      }
    };
  } catch (e) {
    console.warn("Could not initiate control WebSocket:", e);
  }
}

// ----------------- TOAST MESSAGES -----------------
function showToast(msg, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast`;

  let icon = "fa-circle-info text-cyan";
  if (type === "success") icon = "fa-circle-check text-success";
  if (type === "danger") icon = "fa-circle-exclamation text-danger";

  toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${msg}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}