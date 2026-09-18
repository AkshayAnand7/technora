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

// ---- Init ---- //
document.addEventListener("DOMContentLoaded", () => {
  startLiveClock();
  startCountdown();
  setupControls();
  connect();
});
