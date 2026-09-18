# ============================================================
# MarketFloor — FastAPI Application
# ============================================================
# WebSocket endpoint streams live state.
# REST endpoints for task spawn, disruptions, control, analytics.
# Serves the frontend as static files.

from __future__ import annotations
import asyncio
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from simulation import Simulation
from database import init_db, save_auction, save_completed_task, get_analytics
from models import DispatchMode

# ---- Globals ---- #
sim = Simulation()
clients: list[WebSocket] = []

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


# ---- Lifespan ---- #

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Start the simulation tick loop as a background task
    task = asyncio.create_task(tick_loop())
    yield
    task.cancel()


app = FastAPI(title="MarketFloor", lifespan=lifespan)


saved_task_ids: set[str] = set()
saved_auction_ids: set[str] = set()

last_broadcast_event_id = 0

# ---- Tick Loop ---- #

async def tick_loop():
    global last_broadcast_event_id
    """Runs forever, ticking the simulation and broadcasting state."""
    while True:
        try:
            sim.tick()

            # Persist completed tasks once per task
            for t in list(sim.completed_tasks):
                if t.id not in saved_task_ids and t.completed_at:
                    try:
                        save_completed_task(t.to_dict())
                        saved_task_ids.add(t.id)
                    except Exception:
                        pass

            # Persist auctions once per auction
            if sim.current_auction and sim.current_auction.winner_id:
                a = sim.current_auction
                if a.id not in saved_auction_ids:
                    try:
                        save_auction(a.id, a.task_id, a.winner_id, sim.mode.value,
                                    [b.to_dict() for b in a.bids], a.is_re_auction)
                        saved_auction_ids.add(a.id)
                    except Exception:
                        pass

            # Broadcast state to all WebSocket clients
            if clients:
                state_msg = json.dumps(sim.snapshot())
                dead: list[WebSocket] = []
                for ws in clients:
                    try:
                        await ws.send_text(state_msg)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    clients.remove(ws)

            # Broadcast ONLY genuinely new events (prevent repeated spam/flicker)
            if clients and sim.events:
                new_events = [e for e in sim.events if e.id > last_broadcast_event_id]
                if new_events:
                    last_broadcast_event_id = new_events[-1].id
                    ev_msg = json.dumps({
                        "type": "EVENTS",
                        "events": [e.to_dict() for e in new_events],
                    })
                    for ws in clients:
                        try:
                            await ws.send_text(ev_msg)
                        except Exception:
                            pass

            interval = max(0.05, 0.15 / sim.speed)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[tick_loop error] {e}")
            await asyncio.sleep(0.5)


# ---- WebSocket ---- #

@app.websocket("/ws/factory")
async def ws_factory(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    # Send initial state and recent events immediately
    try:
        await websocket.send_text(json.dumps(sim.snapshot()))
        if sim.events:
            await websocket.send_text(json.dumps({
                "type": "EVENTS",
                "events": [e.to_dict() for e in sim.events[-30:]],
            }))
    except Exception:
        pass
    try:
        while True:
            # Listen for client messages (commands)
            data = await websocket.receive_text()
            msg = json.loads(data)
            cmd = msg.get("command")
            if cmd == "domain_action":
                sim.handle_domain_action(msg.get("domain", ""), msg.get("action", ""))
            elif cmd == "run_scenario":
                sim.run_demo_scenario(msg.get("scenarioId", ""))
            elif cmd == "spawn_task":
                sim.spawn_task(msg.get("source"), msg.get("dest"))
            elif cmd == "inject_machine":
                sim.inject_machine_event(msg.get("subtype", "Temperature high"))
            elif cmd == "inject_material":
                sim.inject_material_event(msg.get("subtype", "Low stock at S1"))
            elif cmd == "inject_agv":
                sim.inject_agv_event(msg.get("subtype", "Route updated"))
            elif cmd == "inject_production":
                sim.inject_production_event(msg.get("subtype", "Order priority increased"))
            elif cmd == "inject_factory":
                sim.inject_factory_event(msg.get("subtype", "Power stable"))
            elif cmd == "inject_human":
                sim.inject_human_event(msg.get("subtype", "Worker 2 logged in"))
            elif cmd == "assign_now":
                tid = msg.get("taskId", "TASK-108")
                target_task = next((t for t in sim.tasks if t.id == tid), None)
                if not target_task and sim.tasks: target_task = sim.tasks[0]
                if target_task:
                    avail = [a for a in sim.agvs if a.status in (AGVStatus.IDLE, AGVStatus.WAITING)]
                    if avail:
                        sim.assign_task(target_task, avail[0].id)
                    else:
                        sim.run_auction_for(target_task)
            elif cmd == "fail_agv":
                sim.fail_agv(msg.get("agvId"))
            elif cmd == "block_corridor":
                sim.block_corridor()
            elif cmd == "force_charge":
                sim.force_charge(msg.get("agvId"))
            elif cmd == "estop":
                sim.emergency_stop()
            elif cmd == "resume":
                sim.resume()
            elif cmd == "start":
                sim.running = True
                sim.paused = False
            elif cmd == "pause":
                sim.paused = not sim.paused
            elif cmd == "reset":
                saved_task_ids.clear()
                saved_auction_ids.clear()
                sim.reset()
                last_broadcast_event_id = 0
            elif cmd == "set_speed":
                sim.speed = float(msg.get("speed", 1))
            elif cmd == "set_mode":
                mode = msg.get("mode", "MARKETFLOOR")
                sim.mode = DispatchMode(mode)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if websocket in clients:
            clients.remove(websocket)


# ---- REST API ---- #

@app.post("/api/tasks")
async def api_spawn_task():
    task = sim.spawn_task()
    return JSONResponse(task.to_dict())


@app.post("/api/disruptions/block")
async def api_block():
    sim.block_corridor()
    return {"ok": True}


@app.post("/api/disruptions/fail")
async def api_fail():
    sim.fail_agv()
    return {"ok": True}


@app.post("/api/control/estop")
async def api_estop():
    sim.emergency_stop()
    return {"ok": True}


@app.post("/api/control/resume")
async def api_resume():
    sim.resume()
    return {"ok": True}


@app.get("/api/state")
async def api_state():
    return JSONResponse(sim.snapshot())


@app.get("/api/analytics")
async def api_analytics():
    return JSONResponse(get_analytics())


# ---- Frontend Serving ---- #
# Serve specific HTML pages, then mount static for everything else.

@app.get("/")
async def landing():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/simulation")
async def simulation_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "simulation.html"))


@app.get("/analytics")
async def analytics_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "analytics.html"))


# Mount static files last (CSS, JS, images)
app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_DIR, "static")), name="static")
