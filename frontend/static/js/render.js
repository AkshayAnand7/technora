// ============================================================
// SmartFactory — Canvas & DOM Renderer
// ============================================================
// Draws the warm minimalist factory schematic, machinery,
// charging bays, blocked areas, AGV AMRs, routes, and UI tables.

const CELL = 22;

// Colors matching the SmartFactory aesthetic
const PALETTE = {
  floorBg: "#f6f3eb",
  gridLine: "#eae5da",
  roadSurface: "#ded8cc",
  roadBorder: "#cdc5b6",
  roadDashed: "#b5ac9b",

  stationBg: "#ffffff",
  stationBorder: "#d4cdc0",
  stationText: "#232220",

  chargingBg: "rgba(22, 163, 74, 0.08)",
  chargingBorder: "#16a34a",
  chargingText: "#15803d",

  blockedBg: "rgba(220, 38, 38, 0.08)",
  blockedBorder: "#dc2626",
  blockedStripe: "rgba(220, 38, 38, 0.18)",

  machineAlertBg: "rgba(220, 38, 38, 0.12)",
  machineAlertBorder: "#dc2626",
};

// ============================================================
// FACTORY FLOOR CANVAS DRAWING
// ============================================================

function renderFactory(canvas, state) {
  if (!canvas || !state) return;
  const ctx = canvas.getContext("2d");
  const W = state.gridW * CELL;
  const H = state.gridH * CELL;

  if (canvas.width !== W) canvas.width = W;
  if (canvas.height !== H) canvas.height = H;

  // 1. Base floor
  ctx.fillStyle = PALETTE.floorBg;
  ctx.fillRect(0, 0, W, H);

  // 2. Subtle floor grid
  ctx.strokeStyle = PALETTE.gridLine;
  ctx.lineWidth = 0.5;
  for (let x = 0; x <= state.gridW; x++) {
    ctx.beginPath();
    ctx.moveTo(x * CELL, 0);
    ctx.lineTo(x * CELL, H);
    ctx.stroke();
  }
  for (let y = 0; y <= state.gridH; y++) {
    ctx.beginPath();
    ctx.moveTo(0, y * CELL);
    ctx.lineTo(W, y * CELL);
    ctx.stroke();
  }

  // 3. Driveway / Corridor pathways
  drawRoadways(ctx, state);

  // 4. Center Blocked Area
  drawBlockedArea(ctx, state.blockedArea);

  // 5. Stations & Machinery
  drawStations(ctx, state);

  // 6. Planned AGV routes (dashed paths)
  drawRoutes(ctx, state.agvs);

  // 7. Dynamic AMR/AGV Sprites
  drawAGVs(ctx, state.agvs);
}

// ---- Pathway / Roadway Drawing ---- //
function drawRoadways(ctx, state) {
  // Main loop corridors
  const roads = [
    { x1: 5, y1: 6, x2: 36, y2: 6 },   // Top horizontal artery
    { x1: 5, y1: 15, x2: 36, y2: 15 }, // Middle horizontal artery
    { x1: 5, y1: 23, x2: 36, y2: 23 }, // Bottom horizontal artery
    { x1: 7, y1: 6, x2: 7, y2: 23 },   // Left vertical artery
    { x1: 14, y1: 6, x2: 14, y2: 23 }, // Center-left vertical
    { x1: 24, y1: 6, x2: 24, y2: 23 }, // Center-right vertical
    { x1: 33, y1: 6, x2: 33, y2: 23 }, // Right vertical artery
  ];

  ctx.lineCap = "round";

  // Road surfaces
  ctx.strokeStyle = PALETTE.roadSurface;
  ctx.lineWidth = CELL * 1.5;
  for (const r of roads) {
    ctx.beginPath();
    ctx.moveTo(r.x1 * CELL, r.y1 * CELL);
    ctx.lineTo(r.x2 * CELL, r.y2 * CELL);
    ctx.stroke();
  }

  // Road center dashed line
  ctx.strokeStyle = PALETTE.roadDashed;
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  for (const r of roads) {
    ctx.beginPath();
    ctx.moveTo(r.x1 * CELL, r.y1 * CELL);
    ctx.lineTo(r.x2 * CELL, r.y2 * CELL);
    ctx.stroke();
  }
  ctx.setLineDash([]);
}

// ---- Blocked Area with Diagonal Hatch ---- //
function drawBlockedArea(ctx, area) {
  if (!area) return;
  const x = area.x1 * CELL;
  const y = area.y1 * CELL;
  const w = (area.x2 - area.x1 + 1) * CELL;
  const h = (area.y2 - area.y1 + 1) * CELL;

  // Background tint
  ctx.fillStyle = PALETTE.blockedBg;
  ctx.fillRect(x, y, w, h);

  // Diagonal hazard stripes
  ctx.save();
  ctx.beginPath();
  ctx.rect(x, y, w, h);
  ctx.clip();

  ctx.strokeStyle = PALETTE.blockedStripe;
  ctx.lineWidth = 3;
  for (let i = -h; i < w + h; i += 12) {
    ctx.beginPath();
    ctx.moveTo(x + i, y);
    ctx.lineTo(x + i + h, y + h);
    ctx.stroke();
  }
  ctx.restore();

  // Red dashed border
  ctx.strokeStyle = PALETTE.blockedBorder;
  ctx.lineWidth = 1.5;
  ctx.setLineDash([5, 3]);
  ctx.strokeRect(x, y, w, h);
  ctx.setLineDash([]);

  // Warning icon and text
  ctx.fillStyle = "#dc2626";
  ctx.font = "bold 11px Inter, sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("⚠ Blocked Area", x + w / 2, y + h / 2 + 4);
}

// ---- Station & Machinery Drawing ---- //
function drawStations(ctx, state) {
  if (!state.stations) return;

  for (const s of state.stations) {
    const px = s.position.x * CELL;
    const py = s.position.y * CELL;

    // Charging Stations
    if (s.kind === "charging") {
      const cw = 4 * CELL;
      const ch = 3 * CELL;
      const cx = px - cw / 2 + CELL / 2;
      const cy = py - ch / 2 + CELL / 2;

      ctx.fillStyle = PALETTE.chargingBg;
      ctx.fillRect(cx, cy, cw, ch);

      ctx.strokeStyle = PALETTE.chargingBorder;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(cx, cy, cw, ch);

      // Icon & Name
      ctx.fillStyle = PALETTE.chargingText;
      ctx.font = "bold 10px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("⚡ " + s.name, cx + cw / 2, cy + ch / 2 + 4);
      continue;
    }

    // Standard production machines / storage boxes
    const w = s.kind === "production" ? 4.8 * CELL : 3.8 * CELL;
    const h = 2.8 * CELL;
    const bx = px - w / 2 + CELL / 2;
    const by = py - h / 2 + CELL / 2;

    const isMachineCAlert = s.id === "machine-c" && state.machineCAlert;

    // Drop shadow
    ctx.fillStyle = "rgba(0,0,0,0.03)";
    ctx.fillRect(bx + 2, by + 2, w, h);

    // Body
    ctx.fillStyle = isMachineCAlert ? PALETTE.machineAlertBg : PALETTE.stationBg;
    ctx.fillRect(bx, by, w, h);

    ctx.strokeStyle = isMachineCAlert ? PALETTE.machineAlertBorder : PALETTE.stationBorder;
    ctx.lineWidth = isMachineCAlert ? 1.5 : 1;
    ctx.strokeRect(bx, by, w, h);

    // Station Name
    ctx.fillStyle = isMachineCAlert ? "#dc2626" : PALETTE.stationText;
    ctx.font = "600 9.5px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(s.name, bx + w / 2, by + 13);

    // Mini machinery details
    ctx.fillStyle = isMachineCAlert ? "rgba(220,38,38,0.2)" : "#eee8dd";
    ctx.fillRect(bx + 6, by + 18, w - 12, h - 24);

    // Alert Badge on Machine C
    if (isMachineCAlert) {
      ctx.fillStyle = "#dc2626";
      ctx.beginPath();
      ctx.arc(bx + w - 8, by + 8, 7, 0, Math.PI * 2);
      ctx.fillStyle = "#ffffff";
      ctx.font = "bold 9px Inter, sans-serif";
      ctx.fillText("!", bx + w - 8, by + 11);
    }

    // Station inspection ring if selected
    if (window.inspectedEntity && window.inspectedEntity.type === "station" && window.inspectedEntity.id === s.id) {
      ctx.strokeStyle = "#e06b3a";
      ctx.lineWidth = 2.5;
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(bx - 3, by - 3, w + 6, h + 6);
      ctx.setLineDash([]);
    }
  }
}

// Dynamic AGV state color mapping:
// Blue (#0284c7): Default / Idle
// Orange (#ea580c): Performing task (assigned, en route)
// Green (#16a34a): Charging
// Black (#1a1a1a): Quality Check task
// Grey (#6b7280): Delivering
// Red (#dc2626): Failed / Fault
function isQualityCheckTask(agv) {
  if (!agv) return false;
  const src = (agv.taskSource || "").toLowerCase();
  const dst = (agv.taskDest || "").toLowerCase();
  return src.includes("quality") || dst.includes("quality");
}

function getAGVColor(agv) {
  if (!agv) return "#0284c7";
  if (agv.status === "FAILED") return "#dc2626";
  if (agv.status === "CHARGING" || (agv.location && agv.location.toLowerCase().includes("charging") && !agv.currentTask)) {
    return "#16a34a"; // Green when charging
  }
  if (agv.currentTask && isQualityCheckTask(agv)) {
    return "#1a1a1a"; // Black when performing Quality Check
  }
  if (agv.status === "DELIVERING") {
    return "#6b7280"; // Grey when delivering
  }
  if (agv.currentTask || (agv.status === "MOVING" && agv.currentTask)) {
    return "#ea580c"; // Orange when performing task
  }
  return "#0284c7"; // Blue by default / idle
}

// ---- Dashed Route Visualization ---- //
function drawRoutes(ctx, agvs) {
  if (!agvs) return;

  for (const agv of agvs) {
    if (!agv.route || agv.routeIndex >= agv.route.length) continue;
    const remaining = agv.route.slice(agv.routeIndex);
    if (remaining.length < 2) continue;

    const color = getAGVColor(agv);
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.5;
    ctx.globalAlpha = 0.75;
    ctx.setLineDash([5, 4]);

    ctx.beginPath();
    ctx.moveTo(remaining[0].x * CELL + CELL / 2, remaining[0].y * CELL + CELL / 2);
    for (let i = 1; i < remaining.length; i++) {
      ctx.lineTo(remaining[i].x * CELL + CELL / 2, remaining[i].y * CELL + CELL / 2);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;

    // Destination target dot
    const target = remaining[remaining.length - 1];
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(target.x * CELL + CELL / 2, target.y * CELL + CELL / 2, 4.5, 0, Math.PI * 2);
    ctx.fill();
  }
}

// ---- AMR / AGV Sprite Drawing ---- //
function drawAGVs(ctx, agvs) {
  if (!agvs) return;

  for (const agv of agvs) {
    const cx = agv.position.x * CELL + CELL / 2;
    const cy = agv.position.y * CELL + CELL / 2;
    const radius = CELL * 0.44;
    const color = getAGVColor(agv);
    const isCharging = agv.status === "CHARGING" || (agv.location && agv.location.toLowerCase().includes("charging") && !agv.currentTask);
    const isFault = agv.status === "FAILED";
    const isQC = agv.currentTask && isQualityCheckTask(agv);
    const isDelivering = agv.status === "DELIVERING";
    const isPerformingTask = !isQC && !isDelivering && (agv.currentTask || (agv.status === "MOVING" && agv.currentTask));

    // Shadow
    ctx.fillStyle = "rgba(0,0,0,0.12)";
    ctx.beginPath();
    ctx.arc(cx, cy + 2, radius, 0, Math.PI * 2);
    ctx.fill();

    // Outer aura ring based on state
    if (isQC) {
      ctx.fillStyle = "rgba(26, 26, 26, 0.25)";
      ctx.beginPath();
      ctx.arc(cx, cy, radius + 3.5, 0, Math.PI * 2);
      ctx.fill();
    } else if (isDelivering) {
      ctx.fillStyle = "rgba(107, 114, 128, 0.25)";
      ctx.beginPath();
      ctx.arc(cx, cy, radius + 3.5, 0, Math.PI * 2);
      ctx.fill();
    } else if (isPerformingTask) {
      ctx.fillStyle = "rgba(234, 88, 12, 0.25)";
      ctx.beginPath();
      ctx.arc(cx, cy, radius + 3.5, 0, Math.PI * 2);
      ctx.fill();
    } else if (isCharging) {
      ctx.fillStyle = "rgba(22, 163, 74, 0.25)";
      ctx.beginPath();
      ctx.arc(cx, cy, radius + 3.5, 0, Math.PI * 2);
      ctx.fill();
    }

    // Outer White Ring
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fill();

    // Body (Blue for idle, Orange for performing task, Green for charging, Red for fault)
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(cx, cy, radius - 2, 0, Math.PI * 2);
    ctx.fill();

    // Directional headlight / notch
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.arc(cx, cy - radius + 4, 2, 0, Math.PI * 2);
    ctx.fill();

    // ID Badge
    ctx.font = "bold 8.5px 'JetBrains Mono', monospace";
    ctx.fillStyle = "#232220";
    ctx.textAlign = "center";
    ctx.fillText(agv.id, cx, cy - radius - 3);

    // Center icon
    if (isCharging) {
      ctx.fillStyle = "#ffffff";
      ctx.font = "bold 8px sans-serif";
      ctx.fillText("⚡", cx, cy + 3);
    } else if (isPerformingTask) {
      // Small cargo box dot
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(cx, cy, 2.5, 0, Math.PI * 2);
      ctx.fill();
    }

    // Inspection ring if selected
    if (window.inspectedEntity && window.inspectedEntity.type === "agv" && window.inspectedEntity.id === agv.id) {
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.5;
      ctx.setLineDash([3, 2]);
      ctx.beginPath();
      ctx.arc(cx, cy, radius + 5, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }
}

// ============================================================
// DOM PANEL RENDERERS
// ============================================================

// ---- Render Open Tasks Table ---- //
function renderOpenTasks(tbody, tasks) {
  if (!tbody || !tasks) return;
  if (tasks.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--t3);padding:14px;">No open tasks</td></tr>';
    return;
  }

  tbody.innerHTML = tasks.map(t => {
    const pc = t.priority === "HIGH" ? "high" : t.priority === "MEDIUM" ? "medium" : "low";
    const priLabel = t.priority === "HIGH" ? "High" : t.priority === "MEDIUM" ? "Medium" : "Low";
    const shortRoute = `${t.source.split(" ")[0]} → ${t.destination.split(" ")[0]}`;

    return `
      <tr>
        <td style="font-family:'JetBrains Mono', monospace;font-weight:700;color:var(--t1)">${t.id}</td>
        <td style="color:var(--t2)">${shortRoute}</td>
        <td><span class="priority-tag ${pc}">${priLabel}</span></td>
        <td style="font-family:'JetBrains Mono', monospace;font-weight:600;text-align:center;">${t.bidsCount || 3}</td>
        <td><span class="btn-auction-tag" onclick="assignTaskDirect('${t.id}')" title="Assign to AGV immediately" style="cursor:pointer;">↻ Auction</span></td>
        <td><button class="tab-pill" style="padding:2px 8px;font-size:9.5px;" onclick="selectTask('${t.id}')">View</button></td>
      </tr>
    `;
  }).join("");
}

// ---- Render Multi-Attribute Bidding Table ---- //
function renderBiddingTable(tbody, bids) {
  if (!tbody) return;
  if (!bids || bids.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--t3);padding:14px;">No active bids</td></tr>';
    return;
  }

  tbody.innerHTML = bids.map(b => {
    const isWin = b.isWinner;
    const rowClass = isWin ? 'winner-row' : '';
    const badge = isWin ? '<span class="winner-badge">WINNER</span>' : '';
    return `
      <tr class="${rowClass}">
        <td style="font-family:'JetBrains Mono',monospace;font-weight:700;">${b.agvId}${badge}</td>
        <td>${b.travelCost}s</td>
        <td>${b.batteryCost}%</td>
        <td>${b.congestionCost}</td>
        <td style="color:${b.futureImpact > 1.5 ? '#dc2626' : 'inherit'};font-weight:600;">${b.futureImpact}</td>
        <td style="font-family:'JetBrains Mono',monospace;font-weight:700;color:${isWin ? '#16a34a' : 'var(--t1)'}">${b.finalBid}</td>
      </tr>
    `;
  }).join("");
}

// ---- Render Autonomous Decision Trace ---- //
function renderDecisionTrace(trace) {
  if (!trace) return;
  const stepper = document.getElementById("dt-stepper");
  const titleEl = document.getElementById("dt-stage-title");
  const descEl = document.getElementById("dt-stage-desc");

  if (titleEl && trace.title) titleEl.textContent = trace.title;
  if (descEl && trace.description) descEl.textContent = trace.description;

  if (stepper) {
    const steps = stepper.querySelectorAll(".dt-step");
    const activeIdx = trace.stepIndex !== undefined ? trace.stepIndex : 0;
    steps.forEach((st, idx) => {
      st.classList.remove("active", "done");
      if (idx === activeIdx) {
        st.classList.add("active");
      } else if (idx < activeIdx) {
        st.classList.add("done");
      }
    });
  }
}

// ---- Render Selected Task Panel ---- //
function renderSelectedTask(task) {
  if (!task) return;
  const idEl = document.getElementById("st-id");
  const priEl = document.getElementById("st-priority");
  const pickEl = document.getElementById("st-pickup");
  const dropEl = document.getElementById("st-drop");
  const matEl = document.getElementById("st-mat");
  const wtEl = document.getElementById("st-weight");
  const reqEl = document.getElementById("st-required");

  if (idEl) idEl.textContent = task.id;
  if (priEl) {
    priEl.textContent = task.priority === "HIGH" ? "High Priority" : task.priority === "MEDIUM" ? "Medium Priority" : "Low Priority";
    priEl.className = `priority-tag ${task.priority.toLowerCase()}`;
  }
  if (pickEl) pickEl.textContent = task.source;
  if (dropEl) dropEl.textContent = task.destination;
  if (matEl) matEl.textContent = task.material;
  if (wtEl) wtEl.textContent = task.weight || "15 kg";
  if (reqEl) reqEl.textContent = task.requiredBy || "14:45 (16 min)";
}

// ---- Render Fleet Table ---- //
function renderFleetTable(tbody, agvs) {
  if (!tbody || !agvs) return;

  tbody.innerHTML = agvs.map(a => {
    const col = getAGVColor(a);
    const isCharging = a.status === "CHARGING" || (a.location && a.location.toLowerCase().includes("charging") && !a.currentTask);
    const isQC = a.currentTask && isQualityCheckTask(a);
    const isDelivering = a.status === "DELIVERING";
    const isPerformingTask = !isQC && !isDelivering && (a.currentTask || (a.status === "MOVING" && a.currentTask));
    
    // Status dot/label color matches AGV state color
    const sc =
      a.status === "FAILED" ? "#dc2626" :
      isCharging ? "#16a34a" :
      isQC ? "#1a1a1a" :
      isDelivering ? "#6b7280" :
      isPerformingTask ? "#ea580c" : "#0284c7";

    const statusLabel =
      a.status === "FAILED" ? "Fault" :
      isCharging ? "Charging" :
      isQC ? "Quality Check" :
      isDelivering ? "Delivering" :
      isPerformingTask ? "Task Transit" :
      a.status === "MOVING" ? "Moving" : "Idle";

    // Battery bar color based on operational state:
    // Charging → Green, Delivering → Grey, Task → Orange, Quality Check → Black
    const batColor =
      isCharging ? "#16a34a" :
      isQC ? "#1a1a1a" :
      isDelivering ? "#6b7280" :
      isPerformingTask ? "#ea580c" :
      (a.battery > 50 ? "#16a34a" : a.battery > 25 ? "#d97706" : "#dc2626");

    // Task cell color
    const taskColor = isQC ? "#1a1a1a" : isDelivering ? "#6b7280" : isPerformingTask ? "#ea580c" : "var(--t2)";
    const taskWeight = (isPerformingTask || isQC || isDelivering) ? '700' : 'normal';

    return `
      <tr>
        <td class="agv-id-cell">
          <span style="width:8px;height:8px;border-radius:50%;background:${col};box-shadow:0 0 5px ${col}88;display:inline-block;"></span>
          <span style="font-weight:700;">${a.id}</span>
        </td>
        <td>
          <span style="display:inline-flex;align-items:center;gap:5px;color:${sc};font-weight:600;">
            <span style="width:6px;height:6px;border-radius:50%;background:${sc};display:inline-block;"></span>
            ${statusLabel}
          </span>
        </td>
        <td style="font-family:'JetBrains Mono', monospace;font-weight:${taskWeight};color:${taskColor}">
          ${a.currentTask || "—"}
        </td>
        <td style="color:var(--t2)">${a.location || "Floor"}</td>
        <td>
          <div class="battery-bar-container">
            <div class="battery-bar-outer">
              <div class="battery-bar-inner" style="width:${a.battery}%;background:${batColor}"></div>
            </div>
            <span class="battery-text">${Math.round(a.battery)}%</span>
          </div>
        </td>
        <td style="font-family:'JetBrains Mono', monospace;font-weight:600;color:var(--t1)">${a.speed || 0} m/s</td>
      </tr>
    `;
  }).join("");
}

// ---- Render Fleet Summary Bar ---- //
function renderFleetSummary(summary) {
  if (!summary) return;
  const set = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };
  set("fs-total", summary.total);
  set("fs-active", summary.active);
  set("fs-idle", summary.idle);
  set("fs-charging", summary.charging);
  set("fs-fault", summary.fault);
}

// ---- Incremental Event Stream with Category Filtering ---- //
let currentEventFilter = "all";

function setEventFilter(cat) {
  currentEventFilter = (cat || "all").toLowerCase();
  const el = document.getElementById("event-list");
  if (el) {
    el.innerHTML = "";
    if (window.allEvents) {
      renderEvents(el, window.allEvents, true);
    }
  }
}

function renderEvents(el, events, forceReset = false) {
  if (!el || !events) return;

  if (forceReset) {
    el.innerHTML = "";
  }

  const filtered = currentEventFilter === "all"
    ? events
    : events.filter(e => (e.category || "system").toLowerCase() === currentEventFilter);

  const slice = filtered.slice(-30);
  let appended = false;

  for (const e of slice) {
    const key = String(e.id !== undefined ? e.id : (e.timestamp + "_" + e.message));
    if (!el.querySelector(`[data-ev-key="${key}"]`)) {
      const d = new Date(e.timestamp * 1000);
      const t = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;

      const cat = (e.category || "system").toLowerCase();

      const itemEl = document.createElement("div");
      itemEl.className = "stream-item";
      itemEl.setAttribute("data-ev-key", key);
      itemEl.innerHTML = `
        <span class="stream-time">${t}</span>
        <span class="stream-badge"><span class="stream-dot ${cat}"></span>${e.type}</span>
        <span class="stream-desc">${e.message}</span>
      `;
      el.appendChild(itemEl);
      appended = true;
    }
  }

  while (el.children.length > 35) {
    el.removeChild(el.firstChild);
  }

  if (appended) {
    el.scrollTop = el.scrollHeight;
  }
}
