# MarketFloor — Future-Impact AGV Dispatch System

MarketFloor is a full-stack, real-time smart factory simulation demonstrating decentralized market-based dispatching of Automated Guided Vehicles (AGVs).

Instead of traditional proximity-only dispatch ("which AGV is closest?"), MarketFloor evaluates downstream system consequences ("which AGV causes the least future congestion and disruption?").

---

## 1. Project Architecture

```
marketfloor/
├── backend/
│   ├── main.py              # FastAPI app, WebSocket endpoint (/ws/factory), REST API & static serving
│   ├── simulation.py        # Factory simulation engine, tick loop, AGV state machine, disruption handling
│   ├── astar.py             # Congestion-weighted A* pathfinding algorithm
│   ├── auction.py           # Decentralized auction engine (MarketFloor & Nearest modes, AI heuristic)
│   ├── models.py            # Dataclasses for AGVs, Tasks, Auctions, Bids, Grid, and Metrics
│   ├── database.py          # SQLite database layer for auction history & task analytics
│   └── requirements.txt     # Python dependencies (fastapi, uvicorn, websockets)
├── frontend/
│   ├── index.html           # Landing page with problem statement & concept comparison
│   ├── simulation.html      # Real-time factory floor canvas, control panel, bid breakdown, AI panel
│   ├── analytics.html       # Persistent metrics & completed task logs from SQLite
│   └── static/
│       ├── css/style.css    # High-density industrial dark design system
│       ├── js/render.js     # Factory grid, AGVs, routes, and panel renderer
│       ├── js/ws-client.js  # Resilient WebSocket client with auto-reconnect
│       └── favicon.svg      # MarketFloor icon
├── .env.example
├── plan.md
└── README.md
```

---

## 2. Quickstart & Local Setup

### Prerequisites
- Python 3.10+
- pip

### Step 1: Install Dependencies
```bash
pip install -r backend/requirements.txt
```

### Step 2: Run the Server
From the project root:
```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```
Or navigate into `backend/`:
```bash
cd backend
uvicorn main:app --reload --port 8000
```

### Step 3: Open in Browser
- **Landing Page:** [http://localhost:8000/](http://localhost:8000/)
- **Live Simulation:** [http://localhost:8000/simulation](http://localhost:8000/simulation)
- **Analytics:** [http://localhost:8000/analytics](http://localhost:8000/analytics)

---

## 3. Features & Interactive Demonstrations

- **Live Factory Floor Canvas:** 40×30 smart factory floor with production stations (A, B, C, D), warehouse, storage, charging bays, and narrow corridors.
- **Decentralized Auction Dispatch:**
  $$\text{Final Bid} = \text{Travel Cost} + \text{Congestion Cost} + \text{Future Impact} + \text{Battery Cost} - \text{Fairness}$$
- **Proximity vs. Future-Impact Comparison:** Switch between Traditional (Nearest) and MarketFloor dispatch modes live to compare winners and bottleneck prevention.
- **Disruption Simulation:**
  - **Block Corridor:** Spikes traffic in narrow corridors to demonstrate dynamic A* rerouting.
  - **Fail AGV:** Simulates mechanical failure, triggering automatic task re-auction to surviving fleet members.
  - **Emergency Stop (E-Stop):** Instantly halts all active AGVs; resume when cleared.
  - **Force Charging:** Sends low-battery AGVs to designated charging pads.
- **Persistent Analytics:** Completed tasks and auction decisions are automatically saved to SQLite and aggregated in `/analytics`.

---

## 4. REST & WebSocket API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the landing page |
| `GET` | `/simulation` | Serves the live simulation interface |
| `GET` | `/analytics` | Serves the analytics dashboard |
| `WS` | `/ws/factory` | Real-time bidirectional WebSocket stream for state & controls |
| `POST` | `/api/tasks` | Spawns a new transport task |
| `POST` | `/api/disruptions/block` | Blocks a corridor with high congestion |
| `POST` | `/api/disruptions/fail` | Fails an active AGV |
| `POST` | `/api/control/estop` | Halts simulation (Emergency Stop) |
| `POST` | `/api/control/resume` | Resumes simulation |
| `GET` | `/api/analytics` | Returns aggregated completed task and auction statistics |
