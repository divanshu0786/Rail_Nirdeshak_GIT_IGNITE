// Rail Nirdeshak Frontend Core Controller
const API_BASE = window.location.origin.includes(":8000") || window.location.origin.includes(":3000") || window.location.origin.includes(":5173")
  ? window.location.origin
  : "http://127.0.0.1:8000";

const WS_BASE = API_BASE.replace(/^http/, 'ws');

let state = {
  user: null,
  token: localStorage.getItem("rn_token") || null,
  allTrains: [],
  currentTrain: null,
  savedTrains: [],
  controlData: null,
  ws: null,
  map: null,
  mapLayers: {
    polyline: null,
    trainMarker: null,
    stationMarkers: []
  }
};

// Document Init
document.addEventListener("DOMContentLoaded", () => {
  initAuth();
  loadInitialTrains();
  loadControlRoom();
  setupSearchDropdown();
});

// ----------------- TAB NAVIGATION -----------------
function switchTab(tabId) {
  document.querySelectorAll(".tab-pane").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".nav-btn").forEach(el => el.classList.remove("active"));

  const targetTab = document.getElementById(`tab-${tabId}`);
  const targetNav = document.getElementById(`nav-${tabId}`);
  if (targetTab) targetTab.classList.add("active");
  if (targetNav) targetNav.classList.add("active");

  if (tabId === "map") {
    setTimeout(initOrUpdateMap, 200);
  } else if (tabId === "saved") {
    loadSavedTrains();
  } else if (tabId === "control") {
    loadControlRoom();
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
}

function updateUserUI() {
  const authSection = document.getElementById("user-auth-section");
  if (state.user) {
    authSection.innerHTML = `
      <div class="user-logged-box" style="display:flex; align-items:center; gap:0.6rem;">
        <span style="font-size:0.85rem; font-weight:600;"><i class="fa-solid fa-user-check text-cyan"></i> ${state.user.full_name}</span>
        <button class="btn btn-sm btn-outline" onclick="logout()"><i class="fa-solid fa-arrow-right-from-bracket"></i></button>
      </div>
    `;
  } else {
    authSection.innerHTML = `
      <button class="btn btn-outline" id="auth-btn" onclick="openAuthModal()">
        <i class="fa-solid fa-user"></i> <span>Sign In</span>
      </button>
    `;
  }
}

function openAuthModal() {
  document.getElementById("auth-modal").classList.remove("hidden");
}

function closeAuthModal() {
  document.getElementById("auth-modal").classList.add("hidden");
}

function switchAuthTab(type) {
  const loginForm = document.getElementById("login-form");
  const regForm = document.getElementById("register-form");
  const tabLogin = document.getElementById("tab-btn-login");
  const tabReg = document.getElementById("tab-btn-register");

  if (type === "login") {
    loginForm.classList.remove("hidden");
    regForm.classList.add("hidden");
    tabLogin.classList.add("active");
    tabReg.classList.remove("active");
  } else {
    loginForm.classList.add("hidden");
    regForm.classList.remove("hidden");
    tabLogin.classList.remove("active");
    tabReg.classList.add("active");
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

// ----------------- SEARCH & AUTOCOMPLETE -----------------
function setupSearchDropdown() {
  const input = document.getElementById("train-search-input");
  const dropdown = document.getElementById("search-results-dropdown");

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
    document.getElementById("weather-val").innerHTML = `<i class="fa-solid fa-sun text-amber"></i> ${t.live_state.weather_condition}`;
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
    const res = await fetch(`${API_BASE}/api/field-observations`);
    if (res.ok) {
      const obs = await res.json();
      if (!obs || obs.length === 0) {
        container.innerHTML = "<p class='text-muted'>No active survey warnings on this corridor.</p>";
        return;
      }
      container.innerHTML = obs.map(o => `
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
    state.map = L.map('live-leaflet-map').setView([29.5, 76.5], 7);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; OpenStreetMap &copy; CARTO',
      subdomains: 'abcd',
      maxZoom: 19
    }).addTo(state.map);
  }

  // Clear previous layers
  if (state.mapLayers.polyline) state.map.removeLayer(state.mapLayers.polyline);
  if (state.mapLayers.trainMarker) state.map.removeLayer(state.mapLayers.trainMarker);
  state.mapLayers.stationMarkers.forEach(m => state.map.removeLayer(m));
  state.mapLayers.stationMarkers = [];

  if (!state.currentTrain || !state.currentTrain.route_stops) return;

  const latlngs = [];
  state.currentTrain.route_stops.forEach(s => {
    const lat = s.station.latitude;
    const lng = s.station.longitude;
    latlngs.push([lat, lng]);

    // Station marker
    const marker = L.circleMarker([lat, lng], {
      radius: 6,
      fillColor: "#38bdf8",
      color: "#ffffff",
      weight: 2,
      opacity: 1,
      fillOpacity: 0.9
    }).bindPopup(`<b>${s.station.name} (${s.station.code})</b><br>Sch. Arr: ${s.scheduled_arrival || 'Source'}`);
    marker.addTo(state.map);
    state.mapLayers.stationMarkers.push(marker);
  });

  // Polyline for track route
  state.mapLayers.polyline = L.polyline(latlngs, {
    color: '#2563eb',
    weight: 4,
    opacity: 0.8,
    dashArray: '8, 6'
  }).addTo(state.map);

  // Train live position marker
  if (state.currentTrain.live_state) {
    const tLat = state.currentTrain.live_state.latitude;
    const tLng = state.currentTrain.live_state.longitude;
    
    const trainIcon = L.divIcon({
      className: 'train-map-marker',
      html: `<div style="background:#10b981; border:2px solid #ffffff; width:16px; height:16px; border-radius:50%; box-shadow:0 0 10px #10b981;"></div>`,
      iconSize: [16, 16],
      iconAnchor: [8, 8]
    });

    state.mapLayers.trainMarker = L.marker([tLat, tLng], { icon: trainIcon })
      .bindPopup(`<b>Train ${state.currentTrain.train_number}</b><br>Speed: ${state.currentTrain.live_state.speed_kmh} km/h<br>Delay: +${state.currentTrain.live_state.current_delay_min} min`)
      .addTo(state.map);

    state.map.setView([tLat, tLng], 8);
  } else if (latlngs.length > 0) {
    state.map.fitBounds(latlngs);
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

// ----------------- CONTROL ROOM -----------------
async function loadControlRoom() {
  try {
    const res = await fetch(`${API_BASE}/api/control-room/overview`);
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

  document.getElementById("kpi-active-trains").textContent = ctrl.active_trains_count;
  document.getElementById("kpi-delayed-trains").textContent = ctrl.delayed_trains_count;
  document.getElementById("kpi-prop-risks").textContent = ctrl.high_risk_propagations;
  document.getElementById("kpi-field-alerts").textContent = ctrl.active_field_alerts;

  const tbody = document.getElementById("control-trains-tbody");
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
  const section = document.getElementById("obs-section").value;
  const pole = document.getElementById("obs-pole").value;
  const type = document.getElementById("obs-type").value;
  const delay = parseInt(document.getElementById("obs-delay").value, 10);
  const desc = document.getElementById("obs-desc").value;

  try {
    const res = await fetch(`${API_BASE}/api/field-observations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        track_section: section,
        pole_reference: pole,
        observation_type: type,
        impact_delay_min: delay,
        description: desc
      })
    });
    if (res.ok) {
      showToast("Survey observation logged & propagated across corridor!", "success");
      loadControlRoom();
      if (state.currentTrain) trackTrain(state.currentTrain.train_number, false);
    }
  } catch (err) {
    showToast("Failed to dispatch survey observation", "danger");
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
