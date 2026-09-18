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

try:
    from .simulation import Simulation
    from .database import init_db, save_auction, save_completed_task, get_analytics
    from .models import DispatchMode, AGVStatus, TaskPriority, TaskStatus
except (ImportError, ValueError):
    from simulation import Simulation
    from database import init_db, save_auction, save_completed_task, get_analytics
    from models import DispatchMode, AGVStatus, TaskPriority, TaskStatus

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


# ---- Broadcast Helper ---- #

async def broadcast_state(force_reset: bool = False):
    global last_broadcast_event_id
    if not clients:
        return
    snapshot = sim.snapshot()
    state_msg = json.dumps(snapshot)
    dead: list[WebSocket] = []
    for ws in list(clients):
        try:
            if force_reset:
                await ws.send_text(json.dumps({
                    "type": "RESET",
                    "state": snapshot,
                    "events": [e.to_dict() for e in sim.events[-30:]]
                }))
            else:
                await ws.send_text(state_msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in clients:
            clients.remove(ws)

    if not force_reset and sim.events and clients:
        new_events = [e for e in sim.events if e.id > last_broadcast_event_id]
        if new_events:
            last_broadcast_event_id = new_events[-1].id
            ev_msg = json.dumps({
                "type": "EVENTS",
                "events": [e.to_dict() for e in new_events],
            })
            for ws in list(clients):
                try:
                    await ws.send_text(ev_msg)
                except Exception:
                    pass


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

            # Broadcast state to all connected clients
            await broadcast_state()

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
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except Exception:
                await websocket.send_json({"type": "ERROR", "success": False, "error": "Invalid JSON format"})
                continue

            cmd = msg.get("command")
            if not cmd:
                await websocket.send_json({"type": "ERROR", "success": False, "error": "Missing 'command' attribute"})
                continue

            cmd_lower = str(cmd).lower().strip()

            if cmd_lower in ("domain_action", "domainaction"):
                sim.handle_domain_action(msg.get("domain", ""), msg.get("action", ""))
                await broadcast_state()

            elif cmd_lower in ("run_scenario", "scenario", "demoscenario", "run_demo_scenario"):
                sim.run_demo_scenario(msg.get("scenarioId", msg.get("scenario", "")))
                await broadcast_state()

            elif cmd_lower in ("spawn_task", "spawn"):
                sim.spawn_task(msg.get("source"), msg.get("dest"), msg.get("priority"))
                await broadcast_state()

            elif cmd_lower in ("assign_now", "assign"):
                if sim.emergency_stop_active:
                    await websocket.send_json({"type": "ERROR", "success": False, "error": "Emergency Stop is active. Reset E-Stop first."})
                    continue

                tid = msg.get("taskId")
                success, agv_id, assigned_tid = sim.assign_selected_task(tid)
                await broadcast_state()
                await websocket.send_json({
                    "type": "SUCCESS",
                    "success": True,
                    "command": "assign_now",
                    "agvId": agv_id,
                    "taskId": assigned_tid,
                    "message": f"Task {assigned_tid} assigned to {agv_id}"
                })

            elif cmd_lower in ("fail_agv", "fail"):
                sim.fail_agv(msg.get("agvId"))
                await broadcast_state()

            elif cmd_lower in ("block_corridor", "block"):
                sim.block_corridor()
                await broadcast_state()

            elif cmd_lower in ("force_charge", "charge"):
                sim.force_charge(msg.get("agvId"))
                await broadcast_state()

            elif cmd_lower in ("estop", "emergency_stop"):
                sim.emergency_stop()
                await broadcast_state()
                await websocket.send_json({"type": "SUCCESS", "success": True, "emergencyStopActive": True})

            elif cmd_lower == "resume":
                sim.resume()
                await broadcast_state()
                await websocket.send_json({"type": "SUCCESS", "success": True, "emergencyStopActive": False})

            elif cmd_lower in ("start", "run"):
                if sim.emergency_stop_active:
                    await websocket.send_json({"type": "ERROR", "success": False, "error": "Emergency Stop is active. Clear Emergency Stop first."})
                    continue
                sim.running = True
                sim.paused = False
                await broadcast_state()
                await websocket.send_json({"type": "SUCCESS", "success": True, "running": True})

            elif cmd_lower in ("stop", "pause"):
                if sim.emergency_stop_active:
                    await websocket.send_json({"type": "ERROR", "success": False, "error": "Emergency Stop is active."})
                    continue
                sim.paused = True
                await broadcast_state()
                await websocket.send_json({"type": "SUCCESS", "success": True, "running": False})

            elif cmd_lower in ("toggle_run_stop", "run_stop"):
                if sim.emergency_stop_active:
                    await websocket.send_json({"type": "ERROR", "success": False, "error": "Emergency Stop is active. Clear Emergency Stop first."})
                    continue
                if sim.paused or not sim.running:
                    sim.running = True
                    sim.paused = False
                else:
                    sim.paused = True
                await broadcast_state()
                await websocket.send_json({"type": "SUCCESS", "success": True, "running": sim.running and not sim.paused})

            elif cmd_lower in ("slow_down", "slowdown"):
                speeds = [2.0, 1.5, 1.25, 1.0, 0.75, 0.5, 0.25]
                current = round(sim.speed, 2)
                lower = [s for s in speeds if s < current - 0.05]
                if lower:
                    sim.speed = lower[0]
                else:
                    sim.speed = 2.0
                sim._push_event("SYSTEM", f"Simulation speed adjusted to {sim.speed}x", category="system")
                await broadcast_state()
                await websocket.send_json({"type": "SUCCESS", "success": True, "speed": sim.speed})

            elif cmd_lower == "reset":
                saved_task_ids.clear()
                saved_auction_ids.clear()
                sim.reset()
                last_broadcast_event_id = 0
                await broadcast_state(force_reset=True)
                await websocket.send_json({"type": "SUCCESS", "success": True, "command": "reset"})

            elif cmd_lower == "set_speed":
                try:
                    val = float(msg.get("speed", 1.0))
                    if val <= 0 or val != val:
                        sim.speed = 1.0
                    else:
                        sim.speed = max(0.1, min(5.0, val))
                except (ValueError, TypeError):
                    sim.speed = 1.0
                await broadcast_state()
                await websocket.send_json({"type": "SUCCESS", "success": True, "speed": sim.speed})

            elif cmd_lower in ("set_mode", "set_dispatch_mode"):
                raw_mode = str(msg.get("mode", "")).strip().upper()
                if raw_mode == "AUCTION":
                    raw_mode = "MARKETFLOOR"
                valid_modes = {m.value: m for m in DispatchMode}
                if raw_mode in valid_modes:
                    sim.mode = valid_modes[raw_mode]
                    sim._push_event("SYSTEM", f"Dispatch mode set to {sim.mode.value}", category="system")
                    await broadcast_state()
                    await websocket.send_json({"type": "SUCCESS", "success": True, "mode": sim.mode.value})
                else:
                    await websocket.send_json({
                        "type": "ERROR",
                        "success": False,
                        "error": f"Invalid dispatch mode '{msg.get('mode')}'. Valid options: {list(valid_modes.keys())}"
                    })

            elif cmd_lower in ("inject_machine", "inject_material", "inject_agv", "inject_production", "inject_factory", "inject_human"):
                subtype = msg.get("subtype", "")
                if cmd_lower == "inject_machine":
                    sim.inject_machine_event(subtype or "Temperature high")
                elif cmd_lower == "inject_material":
                    sim.inject_material_event(subtype or "Low stock at S1")
                elif cmd_lower == "inject_agv":
                    sim.inject_agv_event(subtype or "Route updated")
                elif cmd_lower == "inject_production":
                    sim.inject_production_event(subtype or "Order priority increased")
                elif cmd_lower == "inject_factory":
                    sim.inject_factory_event(subtype or "Power stable")
                elif cmd_lower == "inject_human":
                    sim.inject_human_event(subtype or "Worker 2 logged in")
                await broadcast_state()

            else:
                await websocket.send_json({
                    "type": "ERROR",
                    "success": False,
                    "error": f"Unrecognized command: '{cmd}'"
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[ws_factory error] {e}")
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
