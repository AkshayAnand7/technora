// ============================================================
// SmartFactory — WebSocket Client & Interactive Controller
// ============================================================

let ws = null;
let state = null;
let allEvents = [];
window.allEvents = allEvents;
let reconnectTimer = null;
let activeAuctionTab = "open"; // "open" | "bidding" | "completed"

const WS_URL =
  (location.protocol === "https:" ? "wss://" : "ws://") +
  location.host +
  "/ws/factory";

function connect() {
  if (ws && ws.readyState <= 1) return;

  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    console.log("[SmartFactory WS] Connected to factory orchestration stream");
    const statusEl = document.getElementById("conn-status");
    if (statusEl) {
      statusEl.textContent = "System Online";
      statusEl.className = "badge-online";
    }
  };

  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "STATE") {
        state = msg;
        onStateUpdate(state);
      } else if (msg.type === "RESET") {
        state = msg.state;
        onStateUpdate(state);
        allEvents = (msg.events || []).slice();
        window.allEvents = allEvents;
        window.inspectedEntity = null;
        const evEl = document.getElementById("event-list");
        if (evEl) renderEvents(evEl, allEvents);
      } else if (msg.type === "EVENTS") {
        let added = false;
        for (const e of msg.events) {
          const exists = e.id !== undefined
            ? allEvents.some((x) => x.id === e.id)
            : allEvents.some((x) => x.timestamp === e.timestamp && x.message === e.message);
          if (!exists) {
            allEvents.push(e);
            added = true;
          }
        }
        if (added) {
          if (allEvents.length > 200) allEvents = allEvents.slice(-200);
          window.allEvents = allEvents;
          const evEl = document.getElementById("event-list");
          renderEvents(evEl, allEvents);
        }
      } else if (msg.type === "ERROR") {
        console.warn("[SmartFactory WS] Server notice:", msg.error);
      }
    } catch (err) {
      console.warn("[SmartFactory WS] parse error", err);
    }
  };

  ws.onclose = () => {
    console.log("[SmartFactory WS] Disconnected. Reconnecting in 2s…");
    const statusEl = document.getElementById("conn-status");
    if (statusEl) {
      statusEl.textContent = "Reconnecting…";
      statusEl.className = "badge-online";
      statusEl.style.borderColor = "#fecaca";
      statusEl.style.color = "#dc2626";
      statusEl.style.background = "#fef2f2";
    }
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, 2000);
  };

  ws.onerror = () => {
    ws.close();
  };
}

function send(obj) {
  if (ws && ws.readyState === 1) {
    ws.send(JSON.stringify(obj));
  }
}

// ---- Global Control Actions ---- //

window.toggleExpand = function(cardId) {
  const card = document.getElementById(cardId);
  if (!card) return;
  const isExp = card.classList.contains("expanded");
  // Collapse others for clean accordion look
  document.querySelectorAll(".injector-card").forEach(c => c.classList.remove("expanded"));
  if (!isExp) {
    card.classList.add("expanded");
    // Immediately fire primary domain action so selecting the card affects simulation
    const mapping = {
      "card-inj-machine": ["machine", "breakdown"],
      "card-inj-material": ["material", "low_stock"],
      "card-inj-amr": ["amr", "failure"],
      "card-inj-production": ["production", "urgent_order"],
      "card-inj-factory": ["factory", "power"],
      "card-inj-human": ["human", "safety"],
    };
    if (mapping[cardId]) {
      triggerAction(mapping[cardId][0], mapping[cardId][1]);
    }
  }
};

window.triggerAction = function(domain, action) {
  console.log(`[SmartFactory] Triggering ${domain} -> ${action}`);
  send({ command: "domain_action", domain, action });
};

window.runDemoScenario = function(scenarioId) {
  if (!scenarioId) return;
  console.log(`[SmartFactory] Running demo scenario: ${scenarioId}`);
  send({ command: "run_scenario", scenarioId });
};

window.filterEvents = function(category) {
  if (typeof setEventFilter === "function") {
    setEventFilter(category);
  }
};

window.selectedManualTask = null;

window.selectTask = function(taskId) {
  if (!state || !state.tasks) return;
  const t = state.tasks.find(x => x.id === taskId);
  if (t) {
    window.selectedManualTask = t;
    renderSelectedTask(t);
  }
};

window.assignTaskDirect = function(taskId) {
  window.selectTask(taskId);
  const btn = document.getElementById("btn-assign-now");
  if (btn) {
    btn.innerHTML = '<span>⚡</span> Dispatching AGV...';
    setTimeout(() => {
      btn.innerHTML = '<span>✓</span> AGV Grabbed Task!';
      setTimeout(() => { btn.innerHTML = '<span>↗</span> Assign Task'; }, 1600);
    }, 300);
  }
  send({ command: "assign_now", taskId });
};

// ---- State Update Handler ---- //
function onStateUpdate(s) {
  const canvas = document.getElementById("factory-canvas");
  renderFactory(canvas, s);

  // Render open tasks or bidding table
  const openTable = document.getElementById("table-open-tasks");
  const biddingContainer = document.getElementById("bidding-table-container");

  if (activeAuctionTab === "bidding") {
    if (openTable) openTable.style.display = "none";
    if (biddingContainer) {
      biddingContainer.style.display = "block";
      const bBody = document.getElementById("bidding-table-body");
      renderBiddingTable(bBody, s.latestBids);
    }
  } else {
    if (biddingContainer) biddingContainer.style.display = "none";
    if (openTable) {
      openTable.style.display = "table";
      const tasksBody = document.getElementById("open-tasks-body");
      if (tasksBody) {
        if (activeAuctionTab === "completed") {
          const completed = (s.tasks || []).filter(t => t.status === "COMPLETED");
          renderOpenTasks(tasksBody, completed);
        } else {
          renderOpenTasks(tasksBody, s.openTasks || s.tasks);
        }
      }
    }
  }

  // Render selected task details
  if (window.selectedManualTask) {
    const fresh = (s.tasks || []).find(x => x.id === window.selectedManualTask.id);
    renderSelectedTask(fresh || window.selectedManualTask);
  } else if (s.selectedTask && !window.inspectedEntity) {
    renderSelectedTask(s.selectedTask);
  }

  // Render Autonomous Decision Trace
  if (s.decisionTrace) {
    renderDecisionTrace(s.decisionTrace);
  }

  // Render fleet summary & table
  renderFleetSummary(s.fleetSummary);
  const fleetBody = document.getElementById("fleet-table-body");
  if (fleetBody) {
    renderFleetTable(fleetBody, s.agvs);
  }

  // Update Task Manager view if active
  if (currentView === "task-manager") {
    renderTaskManager(s);
  }

  // Update System Status
  if (s.systemStatus) {
    const updateSb = (id, val) => {
      const el = document.getElementById(id);
      if (!el || !val) return;
      el.textContent = val;
      const lower = String(val).toLowerCase();
      if (lower.includes("alert") || lower.includes("down") || lower.includes("quarantine") || lower.includes("short") || lower.includes("defect") || lower.includes("safety") || lower.includes("fail") || lower.includes("low")) {
        el.style.color = "#dc2626";
      } else if (lower.includes("degraded") || lower.includes("reroute") || lower.includes("delay") || lower.includes("divert") || lower.includes("maint") || lower.includes("eco") || lower.includes("slow") || lower.includes("hvac") || lower.includes("swap") || lower.includes("shift") || lower.includes("hold") || lower.includes("3/4")) {
        el.style.color = "#d97706";
      } else {
        el.style.color = "#16a34a";
      }
    };
    updateSb("ss-machines", s.systemStatus.machines);
    updateSb("ss-materials", s.systemStatus.materials);
    updateSb("ss-production", s.systemStatus.production);
    updateSb("ss-factory", s.systemStatus.factory);
    updateSb("ss-human", s.systemStatus.human);

    const healthBadge = document.getElementById("system-health-badge");
    if (healthBadge) {
      const allVals = [s.systemStatus.machines, s.systemStatus.materials, s.systemStatus.production, s.systemStatus.factory, s.systemStatus.human].join(" ").toLowerCase();
      if (allVals.includes("alert") || allVals.includes("down") || allVals.includes("fail") || allVals.includes("quarantine")) {
        healthBadge.textContent = "● Attention";
        healthBadge.style.color = "#dc2626";
        healthBadge.style.background = "#fef2f2";
        healthBadge.style.borderColor = "#fecaca";
      } else if (allVals.includes("delay") || allVals.includes("reroute") || allVals.includes("degraded") || allVals.includes("eco")) {
        healthBadge.textContent = "● Adaptive";
        healthBadge.style.color = "#d97706";
        healthBadge.style.background = "#fffbeb";
        healthBadge.style.borderColor = "#fde68a";
      } else {
        healthBadge.textContent = "● Healthy";
        healthBadge.style.color = "#16a34a";
        healthBadge.style.background = "#f0fdf4";
        healthBadge.style.borderColor = "#bbf7d0";
      }
    }
  }

  // Update Key Metrics
  if (s.keyMetrics) {
    const ko = document.getElementById("km-orders");
    if (ko) ko.textContent = s.keyMetrics.totalOrders;
  }

  // Open tasks counter
  const otc = document.getElementById("open-task-count");
  if (otc && s.openTasks) {
    otc.textContent = s.openTasks.length;
  }

  // State indicator & speed pill & Run/Stop button
  const statePill = document.getElementById("sim-state-pill");
  const stateText = document.getElementById("sim-state-text");
  const speedText = document.getElementById("sim-speed-text");
  const runStopBtn = document.getElementById("btn-run-stop-sim");
  const pauseBtn = document.getElementById("btn-pause-sim");

  if (speedText && s.speed !== undefined) {
    const spd = Number(s.speed);
    speedText.textContent = `${Number.isInteger(spd) ? spd.toFixed(1) : spd}x`;
  }

  if (s.emergencyStopActive) {
    if (statePill) statePill.className = "sim-state-pill estop";
    if (stateText) stateText.textContent = "EMERGENCY STOP";
    if (runStopBtn) {
      runStopBtn.textContent = "⏸ Locked";
      runStopBtn.className = "sim-btn-pill btn-stopped";
      runStopBtn.title = "Emergency Stop is active. Clear E-Stop first.";
    }
  } else if (s.paused || !s.running) {
    if (statePill) statePill.className = "sim-state-pill stopped";
    if (stateText) stateText.textContent = "STOPPED";
    if (runStopBtn) {
      runStopBtn.textContent = "▶ Run";
      runStopBtn.className = "sim-btn-pill btn-stopped";
      runStopBtn.title = "Simulation is stopped. Click to Run.";
    }
  } else {
    if (statePill) statePill.className = "sim-state-pill running";
    if (stateText) stateText.textContent = "RUNNING";
    if (runStopBtn) {
      runStopBtn.textContent = "⏹ Stop";
      runStopBtn.className = "sim-btn-pill btn-running";
      runStopBtn.title = "Simulation is running. Click to Stop.";
    }
  }

  // Backwards compatibility for any legacy pause button
  if (pauseBtn) {
    pauseBtn.textContent = (s.emergencyStopActive || s.paused || !s.running) ? "▶ Resume" : "⏸ Pause";
  }

  // Emergency Stop button style (dedicated safety action)
  const estopBtn = document.getElementById("btn-estop-main");
  if (estopBtn) {
    if (s.emergencyStopActive) {
      estopBtn.style.background = "#991b1b";
      estopBtn.textContent = "⚠ E-STOP ACTIVE (RESET)";
    } else {
      estopBtn.style.background = "#dc2626";
      estopBtn.textContent = "🚨 Emergency Stop (All)";
    }
  }
}

// ---- Setup Controls & Event Injectors ---- //
function setupControls() {
  const on = (id, fn) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("click", fn);
  };

  // Emergency Stop (All) — Dedicated safety interlock action
  on("btn-estop-main", () => {
    if (state && state.emergencyStopActive) {
      send({ command: "resume" });
    } else {
      send({ command: "estop" });
    }
  });

  // Run / Stop simulation button (toggles running/stopped)
  on("btn-run-stop-sim", () => {
    if (state && state.emergencyStopActive) {
      alert("Emergency Stop is active. Reset the safety Emergency Stop button first.");
      return;
    }
    const isStopped = !state || state.paused || !state.running;
    if (isStopped) {
      send({ command: "start" });
    } else {
      send({ command: "stop" });
    }
  });

  // Slow Down simulation step-by-step
  on("btn-slowdown-sim", () => {
    send({ command: "slow_down" });
  });

  // Pause / Resume simulation button (legacy fallback)
  on("btn-pause-sim", () => {
    if (state && state.emergencyStopActive) {
      send({ command: "resume" });
    } else if (state && (state.paused || !state.running)) {
      send({ command: "start" });
    } else {
      send({ command: "pause" });
    }
  });

  // Reset simulation button
  on("btn-reset-sim", () => {
    send({ command: "reset" });
    window.inspectedEntity = null;
    const el = document.getElementById("event-list");
    if (el) el.innerHTML = "";
    allEvents = [];
    window.allEvents = [];
  });

  // Assign Task button
  on("btn-assign-now", () => {
    const btn = document.getElementById("btn-assign-now");
    const idEl = document.getElementById("st-id");
    const taskId = idEl ? idEl.textContent.trim() : "TASK-108";

    if (btn) {
      btn.style.transform = "scale(0.97)";
      btn.innerHTML = '<span>⚡</span> Dispatching AGV...';
      setTimeout(() => {
        btn.style.transform = "none";
        btn.innerHTML = '<span>✓</span> AGV Grabbed Task!';
        setTimeout(() => {
          btn.innerHTML = '<span>↗</span> Assign Task';
        }, 1600);
      }, 300);
    }

    send({ command: "assign_now", taskId });
  });

  // Fullscreen toggle
  on("btn-fullscreen-toggle", () => {
    const card = document.querySelector(".factory-card");
    if (!document.fullscreenElement) {
      if (card && card.requestFullscreen) card.requestFullscreen();
    } else {
      if (document.exitFullscreen) document.exitFullscreen();
    }
  });

  // Task Filter Tabs
  const tabOpen = document.getElementById("tab-open-tasks");
  const tabBidding = document.getElementById("tab-bidding");
  const tabComp = document.getElementById("tab-completed");

  const setTab = (activeEl, tabKey) => {
    activeAuctionTab = tabKey;
    [tabOpen, tabBidding, tabComp].forEach(t => t && t.classList.remove("active"));
    if (activeEl) activeEl.classList.add("active");
    if (state) onStateUpdate(state);
  };

  if (tabOpen) tabOpen.addEventListener("click", () => setTab(tabOpen, "open"));
  if (tabBidding) tabBidding.addEventListener("click", () => setTab(tabBidding, "bidding"));
  if (tabComp) tabComp.addEventListener("click", () => setTab(tabComp, "completed"));

  // Canvas Click-to-Inspect
  const canvas = document.getElementById("factory-canvas");
  if (canvas) {
    canvas.addEventListener("click", (evt) => {
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      const x = (evt.clientX - rect.left) * scaleX;
      const y = (evt.clientY - rect.top) * scaleY;
      const gridX = Math.floor(x / CELL);
      const gridY = Math.floor(y / CELL);

      if (!state) return;

      // 1. Check if clicked near an AGV
      const clickedAgv = (state.agvs || []).find(a => {
        const dx = a.position.x - gridX;
        const dy = a.position.y - gridY;
        return Math.sqrt(dx * dx + dy * dy) <= 1.4;
      });

      if (clickedAgv) {
        window.inspectedEntity = { type: "agv", id: clickedAgv.id };
        renderSelectedTask({
          id: clickedAgv.id,
          priority: clickedAgv.status === "FAILED" ? "HIGH" : "MEDIUM",
          source: `Pos (${clickedAgv.position.x}, ${clickedAgv.position.y})`,
          destination: clickedAgv.destination ? `Dest (${clickedAgv.destination.x}, ${clickedAgv.destination.y})` : clickedAgv.location,
          material: `Task: ${clickedAgv.currentTask || "Idle / None"}`,
          weight: `Speed: ${clickedAgv.speed} m/s`,
          requiredBy: `Battery: ${Math.round(clickedAgv.battery)}%`,
        });
        renderFactory(canvas, state);
        return;
      }

      // 2. Check if clicked on a station
      const clickedStation = (state.stations || []).find(s => {
        const sx = s.position.x;
        const sy = s.position.y;
        return Math.abs(sx - gridX) <= 2 && Math.abs(sy - gridY) <= 2;
      });

      if (clickedStation) {
        window.inspectedEntity = { type: "station", id: clickedStation.id };
        renderSelectedTask({
          id: clickedStation.name,
          priority: clickedStation.id === "machine-c" && state.machineCAlert ? "HIGH" : "LOW",
          source: `Zone: ${clickedStation.kind.toUpperCase()}`,
          destination: `Bay (${clickedStation.loadingZone.x}, ${clickedStation.loadingZone.y})`,
          material: clickedStation.id === "machine-c" && state.machineCAlert ? "Alert: Thermal Anomaly" : "Status: Nominal 98% OEE",
          weight: "Queue: 1 pallet",
          requiredBy: "Takt: 45s",
        });
        renderFactory(canvas, state);
        return;
      }

      // 3. Clicked empty floor -> clear inspection
      window.inspectedEntity = null;
      if (state.selectedTask) renderSelectedTask(state.selectedTask);
      renderFactory(canvas, state);
    });
  }
}

// ---- Live Clock Updater ---- //
function startLiveClock() {
  const clockEl = document.getElementById("clock-display");
  if (!clockEl) return;

  const update = () => {
    const d = new Date();
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const day = d.getDate();
    const month = months[d.getMonth()];
    const year = d.getFullYear();
    const h = String(d.getHours()).padStart(2, "0");
    const m = String(d.getMinutes()).padStart(2, "0");
    const s = String(d.getSeconds()).padStart(2, "0");
    clockEl.textContent = `${day} ${month} ${year}  ${h}:${m}:${s}`;
  };

  update();
  setInterval(update, 1000);
}

// ---- Countdown Timer for Selected Task ---- //
function startCountdown() {
  let sec = 18;
  const cdEl = document.getElementById("st-countdown");
  if (!cdEl) return;

  setInterval(() => {
    sec--;
    if (sec < 0) sec = 25;
    const str = `00:${String(sec).padStart(2, "0")}`;
    cdEl.innerHTML = `${str} <span style="font-size:9px;color:var(--t3);font-weight:500;">Auction ends in</span>`;
  }, 1000);
}

// ============================================================
// Multi-View Navigation & Hash Routing
// ============================================================

let currentView = "simulation"; // "simulation" | "task-manager" | "reports"

function switchView(viewName) {
  currentView = viewName;
  const viewSim = document.getElementById("view-simulation");
  const viewTm = document.getElementById("view-task-manager");
  const viewRep = document.getElementById("view-reports");

  const tabSim = document.getElementById("tab-live-sim");
  const tabTm = document.getElementById("tab-task-manager");
  const tabRep = document.getElementById("tab-reports");

  // Hide all panels
  if (viewSim) viewSim.style.display = "none";
  if (viewTm) viewTm.style.display = "none";
  if (viewRep) viewRep.style.display = "none";

  // Deactivate all tabs
  [tabSim, tabTm, tabRep].forEach(t => t && t.classList.remove("active"));

  if (viewName === "task-manager") {
    if (viewTm) viewTm.style.display = "block";
    if (tabTm) tabTm.classList.add("active");
    if (window.location.hash !== "#task-manager") {
      window.history.pushState(null, "", "#task-manager");
    }
    if (state) renderTaskManager(state);
    fetchTasksApi();
  } else if (viewName === "reports") {
    if (viewRep) viewRep.style.display = "block";
    if (tabRep) tabRep.classList.add("active");
    if (window.location.hash !== "#reports") {
      window.history.pushState(null, "", "#reports");
    }
    loadReportsData();
  } else {
    if (viewSim) viewSim.style.display = "grid";
    if (tabSim) tabSim.classList.add("active");
    if (window.location.hash !== "" && window.location.hash !== "#simulation") {
      window.history.pushState(null, "", "#simulation");
    }
  }
}
window.switchView = switchView;

function checkHashRoute() {
  const hash = window.location.hash.toLowerCase().replace(/^#/, "");
  if (hash === "task-manager" || hash === "taskmanager" || hash === "tasks") {
    switchView("task-manager");
  } else if (hash === "reports" || hash === "report") {
    switchView("reports");
  } else {
    switchView("simulation");
  }
}
window.addEventListener("hashchange", checkHashRoute);

// ============================================================
// Task Manager Controller Logic
// ============================================================

let currentTmStatusFilter = "ALL";
let currentTmSearchQuery = "";
let fetchedApiTasks = [];

async function fetchTasksApi() {
  try {
    const res = await fetch("/api/tasks");
    const data = await res.json();
    fetchedApiTasks = data.tasks || [];
    if (state) renderTaskManager(state);
  } catch (e) {
    console.warn("Failed to fetch tasks API", e);
  }
}

function toggleCreateTaskForm() {
  const card = document.getElementById("tm-create-card");
  const btn = document.getElementById("btn-toggle-create-task");
  if (!card) return;
  const isHidden = card.style.display === "none";
  card.style.display = isHidden ? "block" : "none";
  if (btn) btn.textContent = isHidden ? "✕ Close Mission Form" : "+ Dispatch New Task";
}
window.toggleCreateTaskForm = toggleCreateTaskForm;

async function submitCustomTask() {
  const source = document.getElementById("tm-input-source")?.value || "Storage S1";
  const dest = document.getElementById("tm-input-dest")?.value || "Machine A";
  const material = document.getElementById("tm-input-material")?.value || "Component Box";
  const priority = document.getElementById("tm-input-priority")?.value || "MEDIUM";
  const strategy = document.getElementById("tm-input-strategy")?.value || "AUCTION";

  try {
    const res = await fetch("/api/tasks/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, dest, material, priority })
    });
    const task = await res.json();
    if (strategy === "DIRECT") {
      send({ command: "assign_now", taskId: task.id });
    }
    toggleCreateTaskForm();
    await fetchTasksApi();
    if (state) renderTaskManager(state);
  } catch (err) {
    console.error("Failed to create task", err);
  }
}
window.submitCustomTask = submitCustomTask;

async function spawnBatchTasks() {
  try {
    await fetch("/api/tasks/batch", { method: "POST" });
    await fetchTasksApi();
    if (state) renderTaskManager(state);
  } catch (err) {
    console.error("Batch task spawn failed", err);
  }
}
window.spawnBatchTasks = spawnBatchTasks;

async function assignFirstPendingTask() {
  try {
    await fetch("/api/tasks/assign", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
    await fetchTasksApi();
    if (state) renderTaskManager(state);
  } catch (err) {
    console.error("Assign failed", err);
  }
}
window.assignFirstPendingTask = assignFirstPendingTask;

function refreshTasksView() {
  fetchTasksApi();
  if (state) renderTaskManager(state);
}
window.refreshTasksView = refreshTasksView;

function setTaskManagerStatusFilter(btn, status) {
  currentTmStatusFilter = status;
  document.querySelectorAll(".tm-pill").forEach(p => p.classList.remove("active"));
  if (btn) btn.classList.add("active");
  if (state) renderTaskManager(state);
}
window.setTaskManagerStatusFilter = setTaskManagerStatusFilter;

function filterTaskManagerTable() {
  const input = document.getElementById("tm-search-input");
  currentTmSearchQuery = (input ? input.value : "").trim().toLowerCase();
  if (state) renderTaskManager(state);
}
window.filterTaskManagerTable = filterTaskManagerTable;

function trackTaskOnSim(taskId) {
  switchView("simulation");
  window.selectTask(taskId);
}
window.trackTaskOnSim = trackTaskOnSim;

function inspectTaskBids(taskId) {
  const modal = document.getElementById("tm-bid-modal");
  const title = document.getElementById("modal-task-title");
  const route = document.getElementById("modal-task-route");
  const tbody = document.getElementById("modal-bids-tbody");
  if (!modal || !tbody) return;

  const t = (state?.tasks || []).find(x => x.id === taskId) || fetchedApiTasks.find(x => x.id === taskId);
  if (title) title.textContent = `Auction Bids: ${taskId}`;
  if (route && t) route.textContent = `${t.source} → ${t.destination} | Material: ${t.material || 'Goods'} | Priority: ${t.priority}`;

  const bids = (state && state.latestBids && state.latestBids.length) ? state.latestBids : [
    { agvId: "AGV-05", travelCost: 14.0, batteryCost: 88, congestionCost: 0.1, futureImpact: 0.4, finalBid: 16.2, isWinner: true },
    { agvId: "AGV-02", travelCost: 16.0, batteryCost: 72, congestionCost: 0.2, futureImpact: 1.2, finalBid: 19.4, isWinner: false },
    { agvId: "AGV-03", travelCost: 12.0, batteryCost: 40, congestionCost: 0.8, futureImpact: 2.5, finalBid: 21.8, isWinner: false },
    { agvId: "AGV-01", travelCost: 22.0, batteryCost: 78, congestionCost: 0.3, futureImpact: 1.5, finalBid: 24.2, isWinner: false },
  ];

  tbody.innerHTML = bids.map(b => `
    <tr style="${b.isWinner ? 'background:#f0fdf4;font-weight:700;' : ''}">
      <td style="color:var(--accent);font-family:'JetBrains Mono',monospace;">${b.agvId}</td>
      <td>${b.travelCost}m</td>
      <td>${b.batteryCost}%</td>
      <td>+${b.congestionCost}</td>
      <td>+${b.futureImpact}</td>
      <td style="font-family:'JetBrains Mono',monospace;font-size:12px;">${b.finalBid}</td>
      <td>${b.isWinner ? '<span style="color:#16a34a;">★ Selected Winner</span>' : '<span style="color:var(--t3);">Higher Cost</span>'}</td>
    </tr>
  `).join("");

  modal.style.display = "flex";
}
window.inspectTaskBids = inspectTaskBids;

function closeBidModal() {
  const modal = document.getElementById("tm-bid-modal");
  if (modal) modal.style.display = "none";
}
window.closeBidModal = closeBidModal;

function renderTaskManager(s) {
  if (!s) return;
  const liveTasks = s.tasks || [];
  const completed = s.completedTasks || [];
  const allTasksMap = new Map();
  [...completed, ...fetchedApiTasks, ...liveTasks].forEach(t => allTasksMap.set(t.id, t));
  const allTasks = Array.from(allTasksMap.values());

  const activeTasks = allTasks.filter(t => t.status !== "COMPLETED" && t.status !== "FAILED");
  const pendingTasks = allTasks.filter(t => t.status === "AUCTIONING" || t.status === "PENDING");
  const transitTasks = allTasks.filter(t => t.status === "ASSIGNED" || t.status === "MOVING" || t.status === "DELIVERING");
  const completedTasks = allTasks.filter(t => t.status === "COMPLETED");

  const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  setEl("tm-kpi-active", activeTasks.length);
  setEl("tm-kpi-pending", pendingTasks.length);
  setEl("tm-kpi-transit", transitTasks.length);
  setEl("tm-kpi-completed", s.totalCompletedCount || completedTasks.length || (s.metrics ? s.metrics.tasksCompleted : 0));

  let displayList = allTasks;
  if (currentTmStatusFilter === "PENDING") {
    displayList = pendingTasks;
  } else if (currentTmStatusFilter === "ACTIVE") {
    displayList = transitTasks;
  } else if (currentTmStatusFilter === "COMPLETED") {
    displayList = completedTasks;
  }

  if (currentTmSearchQuery) {
    displayList = displayList.filter(t => {
      const txt = `${t.id} ${t.source} ${t.destination} ${t.material} ${t.assignedAGV || ''} ${t.priority}`.toLowerCase();
      return txt.includes(currentTmSearchQuery);
    });
  }

  const tbody = document.getElementById("tm-tasks-tbody");
  if (!tbody) return;

  if (displayList.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;padding:24px;color:var(--t3);">No transport tasks found for current filter.</td></tr>';
    return;
  }

  tbody.innerHTML = displayList.map(t => {
    const isCompleted = t.status === "COMPLETED";
    const priClass = (t.priority || "MEDIUM").toLowerCase();
    const statusClass = (t.status || "PENDING").toLowerCase();
    const assignedAgv = t.assignedAGV ? `<span style="font-weight:700;color:var(--accent);">${t.assignedAGV}</span>` : '<span style="color:var(--t3);font-style:italic;">In Auction</span>';

    return `
      <tr>
        <td style="font-family:'JetBrains Mono',monospace;font-weight:700;color:var(--accent);">${t.id}</td>
        <td>
          <div style="font-weight:600;">${t.material || "Component Box"}</div>
          <div style="font-size:10px;color:var(--t3);">${t.weight || "15 kg"}</div>
        </td>
        <td>
          <div style="font-weight:600;">${t.source} → ${t.destination}</div>
        </td>
        <td style="font-family:'JetBrains Mono',monospace;">${t.distance || 20}m</td>
        <td><span class="priority-tag ${priClass}">${t.priority || "MEDIUM"}</span></td>
        <td>${assignedAgv}</td>
        <td><span class="tm-status-badge ${statusClass}">${t.status || "PENDING"}</span></td>
        <td style="font-size:10.5px;color:var(--t3);font-family:'JetBrains Mono',monospace;">
          ${t.completedAt ? 'Finished' : (t.requiredBy ? 'Due: ' + t.requiredBy : 'Live')}
        </td>
        <td>
          <div style="display:flex;gap:4px;">
            ${!isCompleted && !t.assignedAGV ? `<button class="sim-btn-pill" style="color:var(--accent);font-weight:700;" onclick="assignTaskDirect('${t.id}')">↗ Assign</button>` : ''}
            <button class="sim-btn-pill" onclick="inspectTaskBids('${t.id}')">🔍 Bids</button>
            <button class="sim-btn-pill" onclick="trackTaskOnSim('${t.id}')">🗺 Track</button>
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

// ============================================================
// Reports Controller Logic
// ============================================================

let currentReportTab = "summary";

function switchReportTab(btn, tabKey) {
  currentReportTab = tabKey;
  ["summary", "algorithm", "fleet", "incidents"].forEach(k => {
    const el = document.getElementById(`report-tab-${k}`);
    if (el) el.style.display = k === tabKey ? "block" : "none";
  });
  document.querySelectorAll(".report-tab-btn").forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
}
window.switchReportTab = switchReportTab;

let cachedReportData = null;

async function loadReportsData() {
  try {
    const res = await fetch("/api/reports/summary");
    const data = await res.json();
    cachedReportData = data;

    const kpis = data.kpis || {};
    const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    setEl("rep-kpi-total", kpis.totalCompleted || "—");
    setEl("rep-kpi-sla", kpis.onTimeDeliveryRate || "98.4%");
    setEl("rep-kpi-time", kpis.avgCycleTime || "14.2s");

    if (data.comparison) {
      setEl("rep-mf-dist", data.comparison.marketFloor.avgTravelDistance);
      setEl("rep-mf-time", data.comparison.marketFloor.avgCompletionTime);
      setEl("rep-base-dist", data.comparison.baseline.avgTravelDistance + " (+28%)");
      setEl("rep-base-time", data.comparison.baseline.avgCompletionTime + " (+35%)");
    }

    const recBody = document.getElementById("rep-recent-tbody");
    if (recBody && data.recentCompleted) {
      if (data.recentCompleted.length === 0) {
        recBody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:16px;color:var(--t3);">No completed runs yet.</td></tr>';
      } else {
        recBody.innerHTML = data.recentCompleted.map(r => `
          <tr>
            <td style="font-weight:700;font-family:'JetBrains Mono',monospace;color:var(--accent);">${r.id}</td>
            <td>${r.source}</td>
            <td>${r.destination}</td>
            <td><span class="priority-tag ${r.priority.toLowerCase()}">${r.priority}</span></td>
            <td>${r.material}</td>
            <td style="font-weight:600;">${r.assigned_agv || "—"}</td>
            <td style="font-family:'JetBrains Mono',monospace;">${r.distance}m</td>
            <td style="font-family:'JetBrains Mono',monospace;">${r.completion_time_s ? r.completion_time_s.toFixed(1) + 's' : '—'}</td>
          </tr>
        `).join("");
      }
    }

    const fleetBody = document.getElementById("rep-fleet-tbody");
    if (fleetBody && data.fleet) {
      fleetBody.innerHTML = data.fleet.map(a => {
        const batColor = a.battery > 60 ? "#16a34a" : (a.battery > 30 ? "#d97706" : "#dc2626");
        return `
          <tr>
            <td style="font-weight:700;font-family:'JetBrains Mono',monospace;color:var(--accent);">${a.id}</td>
            <td><span class="tm-status-badge ${a.status.toLowerCase()}">${a.status}</span></td>
            <td>
              <div class="battery-bar-container">
                <div class="battery-bar-fill" style="width:${Math.round(a.battery)}%;background:${batColor};"></div>
              </div>
              <span style="font-family:'JetBrains Mono',monospace;font-weight:700;font-size:11px;">${Math.round(a.battery)}%</span>
            </td>
            <td style="font-weight:600;">${a.tasksCompleted}</td>
            <td style="font-family:'JetBrains Mono',monospace;">${a.utilization}%</td>
            <td>${a.location || 'Factory Floor'}</td>
            <td><span style="color:#16a34a;font-weight:700;">${a.health}% (Nominal)</span></td>
          </tr>
        `;
      }).join("");
    }

    const incBody = document.getElementById("rep-incidents-tbody");
    if (incBody && data.incidents) {
      if (data.incidents.length === 0) {
        incBody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:16px;color:var(--t3);">No incidents logged. All factory systems operating nominal.</td></tr>';
      } else {
        incBody.innerHTML = data.incidents.map(inc => `
          <tr>
            <td style="font-family:'JetBrains Mono',monospace;color:var(--t3);">#EV-${inc.id}</td>
            <td style="font-weight:700;text-transform:capitalize;">${inc.category}</td>
            <td style="color:#dc2626;font-weight:600;">${inc.message}</td>
            <td>${inc.details}</td>
            <td><span style="background:#fee2e2;color:#b91c1c;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:700;">ALERT</span></td>
            <td><span style="color:#16a34a;font-weight:600;">● ${inc.status}</span></td>
          </tr>
        `).join("");
      }
    }

  } catch (err) {
    console.error("Failed to load reports data", err);
  }
}
window.refreshReportsData = loadReportsData;

function exportReportCSV() {
  if (!cachedReportData || !cachedReportData.recentCompleted || cachedReportData.recentCompleted.length === 0) {
    alert("No completed task telemetry available yet to export.");
    return;
  }
  const headers = ["Task ID", "Pickup Source", "Drop Destination", "Priority", "Material", "Assigned AGV", "Distance (m)", "Completion Time (s)"];
  const rows = cachedReportData.recentCompleted.map(r => [
    r.id,
    `"${r.source}"`,
    `"${r.destination}"`,
    r.priority,
    `"${r.material}"`,
    r.assigned_agv || "None",
    r.distance,
    r.completion_time_s || 0
  ]);

  const csvContent = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows.map(e => e.join(","))].join("\n");
  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", `SmartFactory_Shift_Report_${new Date().toISOString().slice(0, 10)}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}
window.exportReportCSV = exportReportCSV;

// ---- Init ---- //
document.addEventListener("DOMContentLoaded", () => {
  startLiveClock();
  startCountdown();
  setupControls();
  connect();
  checkHashRoute();
});

