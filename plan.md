# MarketFloor — Website Build Plan

Turning the browser prototype into a real, deployed, full-stack website.
Scoped for one student working part-time, not the full 54-section spec.

---

## 1. What we're actually building

**Not** the full "enterprise platform" spec (that's 4-8 months full-time).
**Yes** to: a real backend running the simulation, a live web frontend
showing it, and a simple landing page — deployed at a real URL you can
put on a resume or demo in a viva.

| Layer | What it does |
|---|---|
| Backend | Runs the factory simulation, A*, auction engine — the source of truth |
| Frontend | Connects over WebSocket, renders the live state (canvas, same as prototype) |
| Landing page | One page explaining the idea, with a "Launch simulation" button |
| Database | Stores completed task/auction history for the analytics view |

Cut from scope (add later if you want): auth/RBAC, 3D digital twin,
cinematic scroll animation, trained ML model, Docker/CI, multi-user mode.
The prototype's heuristic future-impact score stays a heuristic — training
a real model needs weeks of simulator-generated data, which is a
phase-2 project on its own.

---

## 2. Tech stack

| Piece | Choice | Why |
|---|---|---|
| Backend | Python, FastAPI | You already have the simulation logic conceptually in JS; FastAPI is the fastest way to get a real API + WebSocket |
| Simulation loop | Plain Python, `asyncio` background task | No need for a task queue at this scale (10-20 AGVs) |
| Database | SQLite → PostgreSQL later | SQLite needs zero setup; swap the connection string when you deploy |
| Frontend | Plain HTML/CSS/JS (reuse prototype's canvas code) | You already have working rendering code — don't rewrite it in React unless you want to |
| Realtime | WebSocket (`fastapi.WebSocket`) | Same event types you already log: TASK_CREATED, AUCTION_STARTED, WINNER_SELECTED, etc. |
| Hosting | Backend: Render.com or Railway (free tier). Frontend: same host, served as static files | No credit card, deploys from GitHub push |

---

## 3. Folder structure

```
marketfloor/
├── backend/
│   ├── main.py              # FastAPI app, WebSocket endpoint
│   ├── simulation.py        # tick loop, moved from JS
│   ├── astar.py             # A* pathfinding (port from prototype)
│   ├── auction.py           # bid engine, both baseline + MarketFloor modes
│   ├── models.py            # AGV, Task, Auction, Bid dataclasses
│   ├── database.py          # SQLite setup + queries
│   └── requirements.txt
├── frontend/
│   ├── index.html           # landing page
│   ├── simulation.html      # the live sim (adapted prototype)
│   ├── analytics.html       # simple charts from stored history
│   └── js/
│       ├── ws-client.js     # connects, receives state, calls render()
│       └── render.js        # canvas drawing, ported from prototype
├── .env.example
└── README.md
```

---

## 4. Phased plan

### Phase 1 — Backend skeleton (3-4 days)
- FastAPI app with one WebSocket endpoint `/ws/factory`
- Port the grid, stations, chargers, and A* function from JS to Python (near-identical logic)
- Port the AGV tick loop: movement, battery drain, status transitions
- Confirm it runs standalone and prints state to console every tick

### Phase 2 — Auction engine (2-3 days)
- Port `runAuction()`: bid calculation (travel, congestion, future-impact heuristic, battery, utilization bonus)
- Both modes (baseline nearest vs MarketFloor) as a toggle in the request
- Unit test: given a fixed AGV layout, the winner is deterministic and explainable

### Phase 3 — WebSocket streaming (2 days)
- Broadcast full state every tick (~150ms) to all connected clients
- Broadcast discrete events (TASK_CREATED, WINNER_SELECTED, AGV_FAILED, etc.) as a separate small message so the frontend event log doesn't need to diff full state
- Handle client disconnect/reconnect gracefully

### Phase 4 — Frontend hookup (2-3 days)
- Reuse the prototype's canvas rendering code almost as-is
- Replace the local JS simulation loop with a WebSocket listener that just renders whatever state arrives
- Buttons (spawn task, block corridor, fail AGV, e-stop) send small POST/WS messages to the backend instead of calling local functions

### Phase 5 — Database + history (2 days)
- On each completed auction, write a row: task, winner, bids, timestamp
- On each completed task, write completion time and distance
- Simple `/api/analytics` endpoint returning aggregates (avg completion time, throughput, baseline vs MarketFloor comparison run over the same seed)

### Phase 6 — Landing page (1-2 days)
- One static page: problem statement, how it works (3-4 static diagrams, no cinematic scroll needed), "Launch simulation" button
- Keep it simple — this is not the bottleneck, don't over-invest here

### Phase 7 — Deploy (1 day)
- Push to GitHub
- Connect repo to Render/Railway, set start command (`uvicorn main:app`)
- Point frontend static files at the deployed WebSocket URL
- Test the public link end-to-end

**Total: roughly 13-18 working days**, i.e. 3-5 weeks at a realistic
part-time pace alongside coursework.

---

## 5. API surface (minimal)

```
GET  /                      → landing page
GET  /simulation            → simulation page
WS   /ws/factory            → streams state + events

POST /api/tasks              → spawn a task
POST /api/disruptions/block  → block a random corridor
POST /api/disruptions/fail   → fail a random AGV
POST /api/control/estop      → emergency stop
POST /api/control/resume     → resume
GET  /api/analytics          → completed-task stats, baseline vs MarketFloor
```

---

## 6. Acceptance checklist

- [ ] Open the public URL, land on the homepage
- [ ] Click through to the live simulation, see AGVs moving
- [ ] Spawn a task, see a real auction with bid breakdown
- [ ] Block a corridor, see rerouting happen
- [ ] Fail an AGV, see re-auction happen
- [ ] Switch to baseline mode, see a different winner for the same layout
- [ ] Visit analytics, see numbers that came from actual runs (never hardcoded)
- [ ] Refresh the page mid-simulation — it reconnects and keeps showing live state

---

## 7. What to add later, if you want to keep going

1. Train a real Gradient Boosting model on logged auction outcomes to replace the future-impact heuristic
2. PostgreSQL + proper migrations once SQLite's limits show up
3. Basic auth if you want multiple named users
4. A polished landing page with scroll animation, once the core product works
