# ============================================================
# SmartFactory — Simulation Engine
# ============================================================
# Tick loop: AGV movement, task queue, auctions, congestion,
# battery drain, disruptions, machine health alerts, and factory events.

from __future__ import annotations
import asyncio
import random
import time
from typing import Optional

try:
    from .models import (
        AGV, AGVStatus, Task, TaskStatus, TaskPriority, Auction,
        Pos, GridCell, CellType, StationInfo, CorridorInfo,
        DispatchMode, Metrics, SimEvent,
    )
    from .astar import find_path
    from .auction import run_auction, explain_winner, get_future_impact_details
except (ImportError, ValueError):
    from models import (
        AGV, AGVStatus, Task, TaskStatus, TaskPriority, Auction,
        Pos, GridCell, CellType, StationInfo, CorridorInfo,
        DispatchMode, Metrics, SimEvent,
    )
    from astar import find_path
    from auction import run_auction, explain_winner, get_future_impact_details

# ---- Grid / Factory layout ----
GRID_W, GRID_H = 40, 30

# Exact factory stations from SmartFactory interface
STATIONS: list[StationInfo] = [
    StationInfo("raw-material", "Raw Material", "warehouse", Pos(5, 3), Pos(5, 6)),
    StationInfo("machine-a", "Machine A", "production", Pos(14, 3), Pos(14, 6)),
    StationInfo("machine-b", "Machine B", "production", Pos(22, 3), Pos(22, 6)),
    StationInfo("machine-c", "Machine C", "production", Pos(30, 3), Pos(30, 6)),
    StationInfo("finished-goods", "Finished Goods", "warehouse", Pos(36, 3), Pos(36, 6)),
    StationInfo("storage-s1", "Storage S1", "storage", Pos(4, 15), Pos(7, 15)),
    StationInfo("storage-s2", "Storage S2", "storage", Pos(36, 15), Pos(33, 15)),
    StationInfo("charging-c1", "Charging C1", "charging", Pos(11, 25), Pos(11, 23)),
    StationInfo("quality-q1", "Quality Check Q1", "production", Pos(19, 25), Pos(19, 23)),
    StationInfo("charging-c2", "Charging C2", "charging", Pos(27, 25), Pos(27, 23)),
    StationInfo("dispatch-d1", "Dispatch D1", "production", Pos(36, 25), Pos(33, 25)),
]

BLOCKED_AREA = {"x1": 15, "y1": 10, "x2": 21, "y2": 16}

CORRIDORS: list[CorridorInfo] = [
    CorridorInfo("C-01", [Pos(11, 10), Pos(11, 11), Pos(11, 12), Pos(11, 13)], is_narrow=True),
    CorridorInfo("C-02", [Pos(25, 10), Pos(25, 11), Pos(25, 12), Pos(25, 13)], is_narrow=True),
    CorridorInfo("C-03", [Pos(17, 8), Pos(18, 8), Pos(19, 8)], is_narrow=True),
    CorridorInfo("C-04", [Pos(17, 18), Pos(18, 18), Pos(19, 18)], is_narrow=True),
]

MATERIALS = [
    "Component Box", "Raw Material", "Steel Plate", "Circuit Board",
    "Assembly Part", "Motor Unit", "Inspected Unit",
]


def _is_wall(x: int, y: int) -> bool:
    if x == 0 or y == 0 or x == GRID_W - 1 or y == GRID_H - 1:
        return True
    # Center Blocked Area
    if 15 <= x <= 21 and 10 <= y <= 16:
        return True
    # Machine footprints (walls)
    if 3 <= x <= 7 and 1 <= y <= 4: return True    # Raw Material
    if 12 <= x <= 16 and 1 <= y <= 4: return True  # Machine A
    if 20 <= x <= 24 and 1 <= y <= 4: return True  # Machine B
    if 28 <= x <= 32 and 1 <= y <= 4: return True  # Machine C
    if 34 <= x <= 38 and 1 <= y <= 4: return True  # Finished Goods
    if 2 <= x <= 5 and 13 <= y <= 17: return True  # Storage S1
    if 35 <= x <= 38 and 13 <= y <= 17: return True # Storage S2
    if 17 <= x <= 21 and 24 <= y <= 27: return True # Quality Check Q1
    if 34 <= x <= 38 and 24 <= y <= 27: return True # Dispatch D1
    return False


def _cell_type(x: int, y: int) -> CellType:
    if _is_wall(x, y):
        return CellType.WALL
    for s in STATIONS:
        lz = s.loading_zone
        if x == lz.x and y == lz.y:
            return CellType.LOADING_ZONE
        sp = s.position
        if s.kind == "charging" and sp.x - 1 <= x <= sp.x + 1 and sp.y - 1 <= y <= sp.y + 1:
            return CellType.CHARGING
    for c in CORRIDORS:
        if any(p.x == x and p.y == y for p in c.cells):
            return CellType.CORRIDOR
    return CellType.FLOOR


def build_grid() -> list[list[GridCell]]:
    grid: list[list[GridCell]] = []
    for y in range(GRID_H):
        row: list[GridCell] = []
        for x in range(GRID_W):
            ct = _cell_type(x, y)
            cell = GridCell(type=ct, walkable=ct != CellType.WALL)
            for s in STATIONS:
                if x == s.position.x and y == s.position.y:
                    cell.label = s.name
                    cell.station_id = s.id
            row.append(cell)
        grid.append(row)
    return grid


def build_agvs() -> list[AGV]:
    # 7 AGVs matching the exact SmartFactory specification
    configs = [
        {"id": "AGV-01", "pos": Pos(14, 6), "color": "#0284c7", "battery": 78.0, "speed": 1.2, "status": AGVStatus.MOVING, "loc": "Machine B", "task": "TASK-108"},
        {"id": "AGV-02", "pos": Pos(7, 15), "color": "#16a34a", "battery": 45.0, "speed": 1.0, "status": AGVStatus.MOVING, "loc": "Storage S1", "task": "TASK-107"},
        {"id": "AGV-03", "pos": Pos(22, 6), "color": "#e06b3a", "battery": 92.0, "speed": 1.1, "status": AGVStatus.MOVING, "loc": "Machine A", "task": "TASK-105"},
        {"id": "AGV-04", "pos": Pos(11, 23), "color": "#0284c7", "battery": 22.0, "speed": 0.0, "status": AGVStatus.IDLE, "loc": "Charging C1", "task": None},
        {"id": "AGV-05", "pos": Pos(11, 25), "color": "#e06b3a", "battery": 88.0, "speed": 0.0, "status": AGVStatus.CHARGING, "loc": "Charging C1", "task": None},
        {"id": "AGV-06", "pos": Pos(33, 15), "color": "#0284c7", "battery": 70.0, "speed": 1.3, "status": AGVStatus.MOVING, "loc": "Storage S2", "task": "TASK-106"},
        {"id": "AGV-07", "pos": Pos(33, 25), "color": "#16a34a", "battery": 86.0, "speed": 1.2, "status": AGVStatus.MOVING, "loc": "Dispatch D1", "task": "TASK-109"},
    ]
    agvs = []
    for c in configs:
        agv = AGV(
            id=c["id"],
            position=c["pos"],
            battery=c["battery"],
            status=c["status"],
            current_task=c["task"],
            speed=c["speed"],
            location=c["loc"],
            color=c["color"],
            utilization=float(random.randint(45, 85)),
            idle_time=float(random.randint(1, 10)),
            tasks_completed=random.randint(5, 18),
        )
        agvs.append(agv)
    return agvs


# ---- Simulation State ---- #

class Simulation:
    def __init__(self):
        self.grid = build_grid()
        self.agvs = build_agvs()
        self.tasks: list[Task] = []
        self.task_queue: list[Task] = []
        self.completed_tasks: list[Task] = []
        self.current_auction: Optional[Auction] = None
        self.current_prediction: Optional[dict] = None
        self.events: list[SimEvent] = []
        self.metrics = Metrics()
        self.corridors = [CorridorInfo(c.id, list(c.cells), is_narrow=c.is_narrow) for c in CORRIDORS]
        self.mode = DispatchMode.MARKETFLOOR
        self.speed = 1.0
        self.running = True
        self.paused = False
        self.emergency_stop_active = False
        self.tick_count = 0
        self._task_counter = 111
        self._event_counter = 0

        # SmartFactory specific states
        self.machine_c_alert: bool = True
        self.system_status = {
            "status": "Healthy",
            "machines": "8/8 Online",
            "materials": "Normal",
            "production": "On Track",
            "factory": "Stable",
            "human": "3/4 Avail",
        }
        self.key_metrics = {
            "lineUtilization": 92,
            "totalOrders": 3,
            "avgMaterialTime": 12,
            "onTimeDelivery": 96,
        }

        # Seed initial open tasks matching the reference interface
        self._seed_initial_tasks()

        # Seed realistic initial stream events matching the reference UI
        self._seed_initial_events()

        # Decision Trace state (SENSE -> UNDERSTAND -> PREDICT -> DECIDE -> ACT -> UPDATE)
        self.decision_trace = {
            "stage": "UPDATE",
            "stepIndex": 5,
            "title": "UPDATE: Digital Twin Synchronized",
            "description": "Continuous telemetry active. Autonomous closed-loop factory orchestration operational.",
            "traceId": "DT-INIT",
            "timestamp": time.time(),
            "steps": [
                {"stage": "SENSE", "text": "Continuous IoT telemetry monitoring active across 11 stations"},
                {"stage": "UNDERSTAND", "text": "Thermal, stock buffers, and AGV battery levels aggregated"},
                {"stage": "PREDICT", "text": "Corridor traffic & downstream congestion heuristics evaluated"},
                {"stage": "DECIDE", "text": "Multi-attribute auction assigns lowest future-impact AGV"},
                {"stage": "ACT", "text": "A* dynamic routing updates paths avoiding congestion zones"},
                {"stage": "UPDATE", "text": "Digital twin synchronized with physical cell states"}
            ]
        }

        # Multi-attribute auction bids for display in Live Auction "Bidding" tab
        self.latest_bids = [
            {"agvId": "AGV-05", "travelCost": 22.0, "batteryCost": 88, "congestionCost": 0.1, "futureImpact": 0.6, "finalBid": 20.8, "isWinner": True},
            {"agvId": "AGV-02", "travelCost": 18.0, "batteryCost": 72, "congestionCost": 0.2, "futureImpact": 1.1, "finalBid": 21.4, "isWinner": False},
            {"agvId": "AGV-03", "travelCost": 16.0, "batteryCost": 43, "congestionCost": 0.7, "futureImpact": 2.3, "finalBid": 24.6, "isWinner": False},
            {"agvId": "AGV-01", "travelCost": 24.0, "batteryCost": 78, "congestionCost": 0.3, "futureImpact": 1.5, "finalBid": 25.2, "isWinner": False},
        ]

        # Assign routes to moving AGVs
        self._initialize_agv_routes()

    def _seed_initial_tasks(self):
        t1 = Task(id="TASK-108", source="Storage S2", source_position=Pos(33, 15),
                  destination="Packaging P1", destination_position=Pos(33, 25),
                  priority=TaskPriority.HIGH, material="Component Box", distance=24,
                  weight="15 kg", required_by="14:45 (16 min)", bids_count=4, status=TaskStatus.AUCTIONING)
        t2 = Task(id="TASK-109", source="Storage S1", source_position=Pos(7, 15),
                  destination="Machine A", destination_position=Pos(14, 6),
                  priority=TaskPriority.MEDIUM, material="Steel Plate", distance=18,
                  weight="25 kg", required_by="15:00", bids_count=3, status=TaskStatus.AUCTIONING)
        t3 = Task(id="TASK-110", source="Machine A", source_position=Pos(14, 6),
                  destination="Dispatch D1", destination_position=Pos(33, 25),
                  priority=TaskPriority.MEDIUM, material="Assembly Part", distance=32,
                  weight="10 kg", required_by="15:15", bids_count=2, status=TaskStatus.AUCTIONING)
        t4 = Task(id="TASK-111", source="Quality Check Q1", source_position=Pos(19, 23),
                  destination="Storage S2", destination_position=Pos(33, 15),
                  priority=TaskPriority.LOW, material="Inspected Unit", distance=20,
                  weight="8 kg", required_by="15:30", bids_count=1, status=TaskStatus.AUCTIONING)
        self.tasks = [t1, t2, t3, t4]
        self.task_queue = list(self.tasks)

    def _seed_initial_events(self):
        now = time.time()
        self._push_event("Machine M-03", "Temperature high", category="machine", timestamp=now - 50)
        self._push_event("AGV-05", "Picked item at S2", category="agv", agv_id="AGV-05", timestamp=now - 40)
        self._push_event("TASK-108", "Assigned to AGV-06", category="production", task_id="TASK-108", timestamp=now - 30)
        self._push_event("Material", "Low stock at S1", category="material", timestamp=now - 25)
        self._push_event("AGV-01", "Charging completed", category="agv", agv_id="AGV-01", timestamp=now - 20)
        self._push_event("Factory", "Power stable", category="factory", timestamp=now - 16)
        self._push_event("AGV-02", "Route updated", category="agv", agv_id="AGV-02", timestamp=now - 12)
        self._push_event("Human", "Worker 2 logged in", category="human", timestamp=now - 8)
        self._push_event("Production", "Order priority increased", category="production", timestamp=now - 5)
        self._push_event("AGV-07", "Started moving to D1", category="agv", agv_id="AGV-07", timestamp=now - 2)

    def _initialize_agv_routes(self):
        dest_stations = [s for s in STATIONS if s.kind != "charging"]
        for agv in self.agvs:
            if agv.status == AGVStatus.MOVING:
                target_station = random.choice(dest_stations)
                dest = target_station.loading_zone
                pr = find_path(self.grid, agv.position, dest)
                if pr.found and pr.path:
                    agv.route = pr.path
                    agv.destination = dest
                    agv.route_index = 0
                    agv.location = target_station.name

    def _push_event(self, etype: str, msg: str, details: str = "",
                    category: str = "system", agv_id: str | None = None,
                    task_id: str | None = None, timestamp: float | None = None):
        self._event_counter += 1
        ev = SimEvent(
            id=self._event_counter,
            type=etype,
            message=msg,
            details=details,
            agv_id=agv_id,
            task_id=task_id,
            category=category,
            timestamp=timestamp or time.time()
        )
        self.events.append(ev)
        if len(self.events) > 200:
            self.events = self.events[-200:]

    def _station_by_name(self, name: str) -> StationInfo | None:
        for s in STATIONS:
            if s.name.lower() == name.lower() or s.id.lower() == name.lower():
                return s
        return None

    def set_decision_trace(self, stage: str, step_index: int, title: str, desc: str, steps: list[dict] | None = None):
        self.decision_trace["stage"] = stage
        self.decision_trace["stepIndex"] = step_index
        self.decision_trace["title"] = title
        self.decision_trace["description"] = desc
        self.decision_trace["timestamp"] = time.time()
        if steps:
            self.decision_trace["steps"] = steps

    def run_demo_scenario(self, scenario_id: str):
        if scenario_id == "machine_vibration":
            self.machine_c_alert = True
            self.system_status["machines"] = "7/8 Alert"
            self.system_status["production"] = "Rerouted"
            self._push_event("Machine M-03", "Vibration above threshold (4.8 mm/s)", details="Spindle bearing anomaly detected", category="machine")
            steps = [
                {"stage": "SENSE", "text": "Machine-03 vibration telemetry spike (4.8 mm/s) detected by IoT accelerometer"},
                {"stage": "UNDERSTAND", "text": "Thermal & mechanical risk assessed: 82% failure probability within 45 min"},
                {"stage": "PREDICT", "text": "Bottleneck predicted on Machine C; material buffer overflow forecasted"},
                {"stage": "DECIDE", "text": "Reduce Machine C load by 40%, reassign incoming jobs to Machine B"},
                {"stage": "ACT", "text": "Re-auction delivery tasks from Machine C to Machine B loading bay"},
                {"stage": "UPDATE", "text": "Digital twin updated, inventory scheduled for alternative routing"}
            ]
            self.set_decision_trace("ACT", 4, "DECIDE → ACT: Workload Rebalanced", "Machine C jobs shifted to Machine B. Transport tasks rerouted.", steps)
            self.spawn_task(source="Machine B", dest="Finished Goods", priority="HIGH")

        elif scenario_id == "agv_failure":
            self.fail_agv("AGV-02")
            steps = [
                {"stage": "SENSE", "text": "AGV-02 wheel motor stall detected via CAN-bus heartbeat loss"},
                {"stage": "UNDERSTAND", "text": "AGV-02 stranded in storage aisle; active task unfulfilled"},
                {"stage": "PREDICT", "text": "Storage S1 pickup delayed by 18 min if task remains unassigned"},
                {"stage": "DECIDE", "text": "Cancel AGV-02 allocation; trigger urgent re-auction to idle fleet"},
                {"stage": "ACT", "text": "Market-based auction reallocates task to AGV-01; alternate A* route plotted"},
                {"stage": "UPDATE", "text": "Fleet state updated: 1 Fault, 6 Active. Maintenance dispatch queued"}
            ]
            self.set_decision_trace("ACT", 4, "ACT: Automatic Re-auction & Task Transfer", "Task removed from failed vehicle and reassigned via market auction.", steps)

        elif scenario_id == "blocked_corridor":
            self.block_corridor()
            steps = [
                {"stage": "SENSE", "text": "Laser lidar barrier sensor triggered in Corridor C-02"},
                {"stage": "UNDERSTAND", "text": "Central passageway blocked by temporary obstacle"},
                {"stage": "PREDICT", "text": "3 active AGVs would experience >45s delay if continuing planned route"},
                {"stage": "DECIDE", "text": "Invalidate corridor nodes in graph; reroute AGVs via peripheral artery"},
                {"stage": "ACT", "text": "A* recalculates path avoiding blocked area; route lines updated"},
                {"stage": "UPDATE", "text": "Congestion heatmap recalculated; digital twin displays detour"}
            ]
            self.set_decision_trace("ACT", 4, "ACT: A* Dynamic Rerouting Around Obstacle", "Central route closed. AGVs redirected through open peripheral arteries.", steps)

        elif scenario_id == "material_shortage":
            self._push_event("Material", "Low stock warning: Storage S1", details="Component box quantity below reorder threshold (8 units)", category="material")
            self.system_status["materials"] = "Low Stock"
            steps = [
                {"stage": "SENSE", "text": "RFID bin scale registers Storage S1 stock dropped below minimum buffer"},
                {"stage": "UNDERSTAND", "text": "Stockout risk imminent: Machine A will stall in 22 minutes"},
                {"stage": "PREDICT", "text": "Production line starved of Component Boxes within current shift"},
                {"stage": "DECIDE", "text": "Initiate automated replenishment order from Raw Material warehouse"},
                {"stage": "ACT", "text": "Generated replenishment task; auction won by nearest available AGV"},
                {"stage": "UPDATE", "text": "Inventory buffer replenished; production schedule confirmed safe"}
            ]
            self.set_decision_trace("DECIDE", 3, "DECIDE: Automated Replenishment Triggered", "Urgent replenishment task created to prevent machine starvation.", steps)
            self.spawn_task(source="Raw Material", dest="Storage S1", priority="HIGH")

        elif scenario_id == "urgent_order":
            self.key_metrics["totalOrders"] += 1
            steps = [
                {"stage": "SENSE", "text": "ERP injects priority Rush Order #904 into production schedule"},
                {"stage": "UNDERSTAND", "text": "Urgent order requires expedited transport from Machine A to Dispatch D1"},
                {"stage": "PREDICT", "text": "Standard queue wait would breach 15-minute delivery SLA"},
                {"stage": "DECIDE", "text": "Elevate task to HIGH priority with zero-wait preemption weighting"},
                {"stage": "ACT", "text": "Dispatched AGV-07 with direct expressway A* path to Dispatch D1"},
                {"stage": "UPDATE", "text": "Production schedule synchronized; on-time metric protected"}
            ]
            self.set_decision_trace("ACT", 4, "ACT: Priority Preemption Dispatch", "High-priority rush order dispatched with expedited corridor routing.", steps)
            self.spawn_task(source="Machine A", dest="Dispatch D1", priority="HIGH")

    def handle_domain_action(self, domain: str, action: str):
        domain_lower = domain.lower()
        act_lower = action.lower().replace(" ", "_").replace("-", "_")

        if "machine" in domain_lower:
            self.machine_c_alert = True
            if "breakdown" in act_lower or "failure" in act_lower:
                self.system_status["machines"] = "7/8 Down"
                self.system_status["production"] = "Rerouted"
                self._push_event("Machine C", "Breakdown: Emergency Stop", "Spindle motor overload", category="machine")
                
                # Actively reroute any moving AGVs away from Machine C to Machine B
                for agv in self.agvs:
                    if agv.status == AGVStatus.MOVING:
                        pr = find_path(self.grid, agv.position, Pos(22, 6))
                        if pr.found:
                            agv.route = pr.path
                            agv.route_index = 0
                            agv.destination = Pos(22, 6)
                            agv.location = "Rerouted: Machine B"
                            self._push_event(agv.id, "Rerouted away from Machine C", "New target: Machine B bay", category="agv", agv_id=agv.id)
                            break

                # Spawn urgent transfer task from Machine B
                self.spawn_task(source="Machine B", dest="Finished Goods", priority="HIGH")

                steps = [
                    {"stage": "SENSE", "text": "Machine C spindle motor thermal & current spike detected by IoT sensor"},
                    {"stage": "UNDERSTAND", "text": "Machine C shutdown; in-flight materials must be intercepted immediately"},
                    {"stage": "PREDICT", "text": "Assembly line buffer starvation within 12 minutes if unaddressed"},
                    {"stage": "DECIDE", "text": "Reroute approaching transport to Machine B, lock Machine C bay"},
                    {"stage": "ACT", "text": "A* recalculates path to Machine B; delivery vehicles dynamically rerouted"},
                    {"stage": "UPDATE", "text": "Digital twin synchronized; Machine C quarantined in red state"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Dynamic Rerouting & Machine B Load Balancing", "Approaching AGVs redirected to Machine B buffer.", steps)

            elif "temp" in act_lower:
                self.system_status["machines"] = "7/8 Temp"
                self._push_event("Machine C", "Alert: Temperature High (88°C)", "Cooling circulation degraded", category="machine")
                for agv in self.agvs:
                    if agv.status == AGVStatus.MOVING:
                        pr = find_path(self.grid, agv.position, Pos(14, 6))
                        if pr.found:
                            agv.route = pr.path
                            agv.route_index = 0
                            agv.destination = Pos(14, 6)
                            agv.location = "Shifted to Machine A"
                            break
                steps = [
                    {"stage": "SENSE", "text": "Machine C thermal sensor reading 88°C (critical threshold: 80°C)"},
                    {"stage": "UNDERSTAND", "text": "Thermal expansion elevates machining defect probability to 45%"},
                    {"stage": "PREDICT", "text": "Spindle thermal trip in 18 minutes unless workload reduced"},
                    {"stage": "DECIDE", "text": "Throttle Machine C duty cycle by 50%, divert WIP to Machine A"},
                    {"stage": "ACT", "text": "Transport jobs redirected to Machine A loading bay"},
                    {"stage": "UPDATE", "text": "Sensor trending downward; digital twin shows cooling status"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Workload Throttled & Diverted to Machine A", "Incoming material flow redirected to Machine A.", steps)

            elif "vibration" in act_lower:
                self.run_demo_scenario("machine_vibration")

            elif "speed" in act_lower:
                self.system_status["machines"] = "8/8 Degraded"
                self._push_event("Machine A", "Speed Drop: Cycle Time +28%", "Tooling wear detected", category="machine")
                pr = find_path(self.grid, self.agvs[2].position, Pos(14, 6))
                if pr.found:
                    self.agvs[2].route = pr.path
                    self.agvs[2].route_index = 0
                    self.agvs[2].destination = Pos(14, 6)
                    self.agvs[2].status = AGVStatus.MOVING
                    self.agvs[2].speed = 1.4
                steps = [
                    {"stage": "SENSE", "text": "Optical tachometer detects Machine A cycle time slowed from 45s to 58s"},
                    {"stage": "UNDERSTAND", "text": "Tooling wear slowing feed rate; upstream queue increasing"},
                    {"stage": "PREDICT", "text": "Takt deficit will propagate downstream within 20 minutes"},
                    {"stage": "DECIDE", "text": "Dispatch AGV-03 with expedited tool change kit to Machine A"},
                    {"stage": "ACT", "text": "AGV-03 assigned express priority route to Machine A bay"},
                    {"stage": "UPDATE", "text": "Takt pacing compensation active on production dashboard"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Expedited Tooling Dispatch to Machine A", "AGV-03 dispatched at 1.4 m/s to assist Machine A.", steps)

            else:
                self._push_event("Machine B", "Scheduled Maintenance Lock", "Preventive lubrication service", category="machine")
                self.system_status["machines"] = "7/8 Maint"
                steps = [
                    {"stage": "SENSE", "text": "Operating hour counter reached 500h preventive maintenance limit"},
                    {"stage": "UNDERSTAND", "text": "Machine B staging safe shutdown for maintenance window"},
                    {"stage": "PREDICT", "text": "Capacity reduced for 15 minutes"},
                    {"stage": "DECIDE", "text": "Divert transport away from Machine B loading zone"},
                    {"stage": "ACT", "text": "AGV routing updated to bypass Machine B perimeter"},
                    {"stage": "UPDATE", "text": "Lockout verified on factory floor"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Safe Maintenance Lockout Engaged", "Work cells notified; safe maintenance lockout established.", steps)

        elif "material" in domain_lower:
            if "low_stock" in act_lower or "shortage" in act_lower:
                self.run_demo_scenario("material_shortage")
            elif "wrong" in act_lower:
                self._push_event("Material", "Barcode Mismatch: Wrong Material Quarantined", "Lot #B-914 quarantined at S1", category="material")
                self.system_status["materials"] = "Quarantine"
                for a in self.agvs:
                    if a.status == AGVStatus.MOVING:
                        pr = find_path(self.grid, a.position, Pos(7, 15))
                        if pr.found:
                            a.route = pr.path
                            a.route_index = 0
                            a.destination = Pos(7, 15)
                            break
                steps = [
                    {"stage": "SENSE", "text": "Barcode scan at Storage S1 mismatch: expected Component Box, got Steel Ingot"},
                    {"stage": "UNDERSTAND", "text": "Wrong material would jam Machine A tooling if loaded"},
                    {"stage": "PREDICT", "text": "Machine crash risk: 100% containment critical"},
                    {"stage": "DECIDE", "text": "Quarantine container immediately, abort pickup route"},
                    {"stage": "ACT", "text": "AGV route reversed to Storage S1 quarantine zone"},
                    {"stage": "UPDATE", "text": "Inventory discrepancy logged; corrective pick issued"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Wrong Material Containment & Re-route", "Task rejected to prevent machine tooling damage. Correct lot queued.", steps)

            elif "delay" in act_lower:
                self._push_event("Material", "Supplier Delivery Delay: Raw Inflow +30m", "Buffer safety stock engaged", category="material")
                self.system_status["materials"] = "Delayed"
                self.spawn_task(source="Storage S2", dest="Machine A", priority="HIGH")
                steps = [
                    {"stage": "SENSE", "text": "Supplier API reports inbound material shipment delayed by 30 min"},
                    {"stage": "UNDERSTAND", "text": "Raw material buffer sufficient for 45 min; low priority tasks must yield"},
                    {"stage": "PREDICT", "text": "Potential starvation if internal replenishment not accelerated"},
                    {"stage": "DECIDE", "text": "Accelerate internal transfer from Storage S2 secondary buffer"},
                    {"stage": "ACT", "text": "High priority task dispatched from Storage S2 to Machine A"},
                    {"stage": "UPDATE", "text": "Production schedule preserved"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Secondary Buffer Dispatch to Machine A", "Storage S2 internal buffer engaged to bypass supplier delay.", steps)

            else:
                self._push_event("Material", "Warehouse Alert: Storage S1 at 94% Capacity", "Redirecting overflow to S2", category="material")
                self.system_status["materials"] = "S2 Divert"
                for a in self.agvs:
                    if a.status == AGVStatus.MOVING:
                        pr = find_path(self.grid, a.position, Pos(33, 15))
                        if pr.found:
                            a.route = pr.path
                            a.route_index = 0
                            a.destination = Pos(33, 15)
                            a.location = "Diverted to S2"
                            break
                steps = [
                    {"stage": "SENSE", "text": "Storage S1 optical rack volume sensor reports 94% volumetric fill"},
                    {"stage": "UNDERSTAND", "text": "Storage S1 saturated; inbound drop-offs will cause aisle gridlock"},
                    {"stage": "PREDICT", "text": "Aisle congestion imminent within 5 minutes"},
                    {"stage": "DECIDE", "text": "Dynamically redirect drop-offs to Storage S2 loading bay"},
                    {"stage": "ACT", "text": "AGV delivery destinations shifted to Storage S2"},
                    {"stage": "UPDATE", "text": "Warehouse utilization rebalanced"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Storage Overflow Rerouted to S2", "Inbound goods diverted to Storage S2 to prevent aisle blockage.", steps)

        elif "amr" in domain_lower or "agv" in domain_lower:
            if "fail" in act_lower:
                self.run_demo_scenario("agv_failure")
            elif "battery" in act_lower or "low" in act_lower:
                self.force_charge("AGV-02")
                steps = [
                    {"stage": "SENSE", "text": "AGV-02 telemetry reports battery dropped to 15% threshold"},
                    {"stage": "UNDERSTAND", "text": "Vehicle risks mid-transit stalling if assigned next task"},
                    {"stage": "PREDICT", "text": "Stalling risk 95% in next 10 minutes"},
                    {"stage": "DECIDE", "text": "Exclude AGV-02 from auction; assign autonomous docking route to Charging C1"},
                    {"stage": "ACT", "text": "AGV-02 route plotted directly to Charging C1 dock"},
                    {"stage": "UPDATE", "text": "Charging queue updated; replacement vehicle dispatched"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Low Battery Autonomous Docking Transit", "AGV-02 routed to Charging C1 bay.", steps)

            elif "stuck" in act_lower:
                self._push_event("AMR / AGV", "AGV Obstruction: Cooperative Yield Cleared", "Cooperative passing protocol executed", category="agv")
                for a in self.agvs:
                    if a.status == AGVStatus.MOVING:
                        a.speed = 1.4
                steps = [
                    {"stage": "SENSE", "text": "Proximity lidar detects standoff between AGVs in central aisle"},
                    {"stage": "UNDERSTAND", "text": "Two vehicles head-to-head in single-lane corridor"},
                    {"stage": "PREDICT", "text": "Gridlock unless coordinated yield executed"},
                    {"stage": "DECIDE", "text": "Command lower priority vehicle to yield into siding bay"},
                    {"stage": "ACT", "text": "Yield waypoint executed; path cleared at 1.4 m/s"},
                    {"stage": "UPDATE", "text": "Corridor flow restored"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Cooperative Deadlock Resolution", "Cooperative yielding protocol restored flow through corridor.", steps)

            elif "congestion" in act_lower or "blocked" in act_lower:
                self.run_demo_scenario("blocked_corridor")

        elif "production" in domain_lower:
            if "urgent" in act_lower:
                self.run_demo_scenario("urgent_order")
            elif "bottleneck" in act_lower:
                self._push_event("Production", "Bottleneck Managed: Machine B Queue > 3", "Dynamic feed balance triggered", category="production")
                self.system_status["production"] = "Rerouted"
                self.spawn_task(source="Raw Material", dest="Machine A", priority="HIGH")
                steps = [
                    {"stage": "SENSE", "text": "Machine B input queue depth reached 4 pallets; cycle utilization 96%"},
                    {"stage": "UNDERSTAND", "text": "Machine B is critical takt bottleneck for current variant"},
                    {"stage": "PREDICT", "text": "Downstream shift delay of 22 minutes if queue continues growing"},
                    {"stage": "DECIDE", "text": "Reprioritize transport: balance feed between Machine A and Machine B"},
                    {"stage": "ACT", "text": "High priority feed dispatched to Machine A to shed workload"},
                    {"stage": "UPDATE", "text": "Line balance factor restored to 0.92"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Dynamic Bottleneck Workload Shedding", "Feed flow rebalanced across adjacent production machines.", steps)

            elif "delay" in act_lower:
                self._push_event("Production", "Order Delay: Batch #401 Expedited", "Priority elevated in auction", category="production")
                self.system_status["production"] = "Expedited"
                self.spawn_task(priority="HIGH")
                steps = [
                    {"stage": "SENSE", "text": "Job tracker notes Batch #401 running 10 minutes behind schedule"},
                    {"stage": "UNDERSTAND", "text": "Assembly buffer will hit penalty if not expedited at next step"},
                    {"stage": "PREDICT", "text": "SLA breach in 30 minutes without intervention"},
                    {"stage": "DECIDE", "text": "Elevate task priority to HIGH with zero-wait preemption weighting"},
                    {"stage": "ACT", "text": "AGV auction evaluates batch with express corridor priority"},
                    {"stage": "UPDATE", "text": "Schedule slip recovered"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Batch Expediting via Auction Preemption", "Elevated task priority recovers schedule slip.", steps)

            elif "defect" in act_lower or "quality" in act_lower:
                self._push_event("Production", "Quality Defect: Batch Quarantined at Q1", "Vision inspection failed surface check", category="production")
                self.system_status["production"] = "Defect Hold"
                t = self.create_task(source="Quality Check Q1", dest="Storage S1", priority="HIGH")
                self.assign_task(t, self.agvs[6].id)
                steps = [
                    {"stage": "SENSE", "text": "Quality Check Q1 computer vision detects dimensional flaw on component"},
                    {"stage": "UNDERSTAND", "text": "Defect isolated to Machine C tool wear; batch cannot proceed"},
                    {"stage": "PREDICT", "text": "Risk of scrap accumulation downstream"},
                    {"stage": "DECIDE", "text": "Route defective unit to Rework Bay at Storage S1, trigger tool inspection"},
                    {"stage": "ACT", "text": "Dispatched AGV-07 to transfer quarantined part to hold buffer"},
                    {"stage": "UPDATE", "text": "Defect rate logged: 0.7%; SPC control chart updated"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Quality Defect Isolation & Transfer", "Defective part transferred to rework buffer. Tooling check flagged.", steps)

            else:
                self._push_event("Production", "Demand Shift: Product Mix Variant Change", "Capacity reallocation recalculating", category="production")
                self.system_status["production"] = "Mix Shift"
                self.spawn_task(source="Raw Material", dest="Machine C", priority="HIGH")
                steps = [
                    {"stage": "SENSE", "text": "MES system broadcasts product variant shift (Model Alpha → Beta)"},
                    {"stage": "UNDERSTAND", "text": "Material mix changes from Steel Plates to Circuit Boards"},
                    {"stage": "PREDICT", "text": "Retrieval demand will double in next 60 minutes"},
                    {"stage": "DECIDE", "text": "Pre-stage transport to service forecasted demand surge"},
                    {"stage": "ACT", "text": "Repositioning orders sent to active fleet"},
                    {"stage": "UPDATE", "text": "Predictive fleet staging completed"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Predictive Fleet Repositioning", "AGVs prestaged to service forecasted demand surge.", steps)

        elif "factory" in domain_lower:
            if "emergency" in act_lower:
                self.emergency_stop()
                steps = [
                    {"stage": "SENSE", "text": "Emergency Stop control triggered"},
                    {"stage": "UNDERSTAND", "text": "Factory safety system commands immediate physical halt"},
                    {"stage": "PREDICT", "text": "Collision risk eliminated; production paused"},
                    {"stage": "DECIDE", "text": "Zero-torque safe standstill on all 7 AGVs"},
                    {"stage": "ACT", "text": "Immediate deceleration ramp executed; brakes locked"},
                    {"stage": "UPDATE", "text": "Factory status: SAFE STANDSTILL"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Emergency Stop (All) Active", "All AGVs decelerated to 0 m/s. Safe standstill maintained.", steps)

            elif "power" in act_lower:
                self._push_event("Factory", "Peak Demand Shaving: Eco Mode Engaged", "Peak load response active", category="factory")
                self.system_status["factory"] = "Eco-Mode"
                for a in self.agvs:
                    if a.status == AGVStatus.MOVING:
                        a.speed = 0.8
                steps = [
                    {"stage": "SENSE", "text": "Smart meter detects facility power draw nearing peak tariff (480 kW)"},
                    {"stage": "UNDERSTAND", "text": "Peak demand surcharge imminent unless load shed"},
                    {"stage": "PREDICT", "text": "$2,400 peak tariff penalty forecasted"},
                    {"stage": "DECIDE", "text": "Throttle fleet travel speed to 0.8 m/s eco mode; defer charger C2"},
                    {"stage": "ACT", "text": "Fleet speed throttled; factory power draw reduced to 390 kW"},
                    {"stage": "UPDATE", "text": "Power demand stabilized"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Microgrid Demand Shaving & Eco-Throttle", "Fleet throttled to 0.8 m/s to stay under peak tariff.", steps)

            elif "network" in act_lower:
                self._push_event("Factory", "Mesh Network Latency Jitter (120ms)", "Switching to ultra-reliable link", category="factory")
                self.system_status["factory"] = "5G Mesh"
                for a in self.agvs:
                    if a.status == AGVStatus.MOVING:
                        a.speed = 0.9
                steps = [
                    {"stage": "SENSE", "text": "Wi-Fi 6 AP #4 latency jitter increases to 120ms"},
                    {"stage": "UNDERSTAND", "text": "Radio interference near Machine B welding cell"},
                    {"stage": "PREDICT", "text": "Packet loss could delay trajectory updates"},
                    {"stage": "DECIDE", "text": "Engage onboard dead-reckoning safety buffers"},
                    {"stage": "ACT", "text": "Secondary industrial 5G link engaged; AGVs slowed to 0.9 m/s"},
                    {"stage": "UPDATE", "text": "Telemetry link restored"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Network Failover & Safety Buffers Engaged", "Onboard safeguards engaged during Wi-Fi link jitter.", steps)

            elif "environment" in act_lower:
                self._push_event("Factory", "Ambient Humidity Warning (68% RH)", "HVAC dehumidifier active", category="factory")
                self.system_status["factory"] = "HVAC Adj"
                steps = [
                    {"stage": "SENSE", "text": "Environmental sensors report RH 68% in Dispatch D1 (limit: 60%)"},
                    {"stage": "UNDERSTAND", "text": "Exceeds packaging adhesive cure spec"},
                    {"stage": "PREDICT", "text": "Packaging seal time extended by 8 minutes"},
                    {"stage": "DECIDE", "text": "Ramp HVAC dehumidifier unit #3; stage dispatch buffer"},
                    {"stage": "ACT", "text": "HVAC override activated; nominal humidity returning"},
                    {"stage": "UPDATE", "text": "Ambient humidity returning to 52%"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Environmental Control Override", "HVAC dehumidification engaged to protect packaging integrity.", steps)

            else:
                self._push_event("Factory", "Perimeter Zone Authorized Access", "Badge verification successful", category="factory")
                self.system_status["factory"] = "Secure"
                steps = [
                    {"stage": "SENSE", "text": "RFID perimeter gate logged access into automated cell"},
                    {"stage": "UNDERSTAND", "text": "Certified technician credential authenticated"},
                    {"stage": "PREDICT", "text": "Safe authorized entry confirmed"},
                    {"stage": "DECIDE", "text": "Maintain standard safety clearance envelopes"},
                    {"stage": "ACT", "text": "Access granted; audit log recorded"},
                    {"stage": "UPDATE", "text": "Security status: Verified nominal"}
                ]
                self.set_decision_trace("UPDATE", 5, "UPDATE: Security Verification Nominal", "Authorized access confirmed; factory perimeter secure.", steps)

        elif "human" in domain_lower:
            if "safety" in act_lower or "violation" in act_lower:
                self._push_event("Human", "Safety Alert: Worker in Proximity to Corridor C-02", "Speed limit 0.3 m/s enforced", category="human")
                self.system_status["human"] = "Safety Zone"
                for a in self.agvs:
                    if a.status == AGVStatus.MOVING:
                        a.speed = 0.3
                steps = [
                    {"stage": "SENSE", "text": "Optical safety curtain breached near corridor C-02 intersection"},
                    {"stage": "UNDERSTAND", "text": "Human worker stepped into active automated transport zone"},
                    {"stage": "PREDICT", "text": "Proximity collision hazard with approaching AGVs"},
                    {"stage": "DECIDE", "text": "Enforce dynamic safety speed crawl (0.3 m/s) on all vehicles within zone"},
                    {"stage": "ACT", "text": "AGVs instantly slowed to 0.3 m/s with acoustic caution chime"},
                    {"stage": "UPDATE", "text": "Zone cleared; safety confirmed"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Dynamic Safety Speed Crawl (0.3 m/s)", "Nearby vehicles restricted to 0.3 m/s safety crawl until zone clear.", steps)

            elif "worker_unavailable" in act_lower or "unavailable" in act_lower:
                self._push_event("Human", "Worker Unavailable: Station Q1 Shift Swap", "Vision assist automated", category="human")
                self.system_status["human"] = "3/4 Avail"
                steps = [
                    {"stage": "SENSE", "text": "Shift system reports Station Q1 operator on 15-minute break"},
                    {"stage": "UNDERSTAND", "text": "Quality station unmanned during swap window"},
                    {"stage": "PREDICT", "text": "Inspection backlog could build without operator"},
                    {"stage": "DECIDE", "text": "Switch Q1 to autonomous computer vision pre-inspection mode"},
                    {"stage": "ACT", "text": "Camera pre-screens incoming parts; queues flagged units"},
                    {"stage": "UPDATE", "text": "Line flow maintained without interruption"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Automated Vision Inspection Active", "Vision inspection buffers units while operator swaps.", steps)

            elif "error" in act_lower:
                self._push_event("Human", "Task Error: Pallet Barcode Re-scan Completed", "Manifest validated", category="human")
                self.system_status["human"] = "Cleared"
                steps = [
                    {"stage": "SENSE", "text": "Handheld scanner flagged duplicate barcode scan at Dispatch D1"},
                    {"stage": "UNDERSTAND", "text": "Operator scanned outbound label twice; shipping manifest ambiguity"},
                    {"stage": "PREDICT", "text": "Incorrect loading order if unverified"},
                    {"stage": "DECIDE", "text": "Request one-touch re-validation on supervisor tablet"},
                    {"stage": "ACT", "text": "Re-verification reconciled against ERP manifest"},
                    {"stage": "UPDATE", "text": "Manifest cleared for loading; delivery on track"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Manifest Discrepancy Reconciled", "One-touch re-verification reconciled ERP shipment manifest.", steps)

            else:
                self._push_event("Human", "Manual Intervention: Supervisor Task Injected", "Priority dispatch started", category="human")
                self.spawn_task(source="Raw Material", dest="Finished Goods", priority="HIGH")
                steps = [
                    {"stage": "SENSE", "text": "Supervisor tapped manual task injection on interface"},
                    {"stage": "UNDERSTAND", "text": "Authorized supervisory override for custom transport batch"},
                    {"stage": "PREDICT", "text": "Fleet has available capacity to absorb priority batch"},
                    {"stage": "DECIDE", "text": "Accept override and dispatch high-priority job"},
                    {"stage": "ACT", "text": "Market auction initiated for supervisor task"},
                    {"stage": "UPDATE", "text": "Audit log committed to database"}
                ]
                self.set_decision_trace("ACT", 4, "ACT: Supervisor Override Processed", "Manual priority task incorporated into automated schedule.", steps)

    # ---- Injector controls ---- #

    def inject_machine_event(self, subtype: str = "Temperature high"):
        self.handle_domain_action("machine", subtype)

    def inject_material_event(self, subtype: str = "Low stock at S1"):
        self.handle_domain_action("material", subtype)

    def inject_agv_event(self, subtype: str = "Route updated"):
        self.handle_domain_action("amr", subtype)

    def inject_production_event(self, subtype: str = "Order priority increased"):
        self.handle_domain_action("production", subtype)

    def inject_factory_event(self, subtype: str = "Power stable"):
        self.handle_domain_action("factory", subtype)

    def inject_human_event(self, subtype: str = "Worker 2 logged in"):
        self.handle_domain_action("human", subtype)

    # ---- Task creation & auction ---- #

    def create_task(self, source: str | None = None, dest: str | None = None,
                    priority: str | None = None) -> Task:
        self._task_counter += 1
        tid = f"TASK-{self._task_counter}"

        non_charging = [s for s in STATIONS if s.kind != "charging"]
        src_st = self._station_by_name(source) if source else random.choice(non_charging)
        if not src_st: src_st = non_charging[0]

        dst_st = self._station_by_name(dest) if dest else random.choice([s for s in non_charging if s.id != src_st.id])
        if not dst_st: dst_st = non_charging[1]

        pri = TaskPriority(priority) if priority and priority in TaskPriority.__members__ else random.choice(list(TaskPriority))
        mat = random.choice(MATERIALS)
        dist = src_st.loading_zone.manhattan(dst_st.loading_zone)

        task = Task(
            id=tid,
            source=src_st.name,
            source_position=Pos(src_st.loading_zone.x, src_st.loading_zone.y),
            destination=dst_st.name,
            destination_position=Pos(dst_st.loading_zone.x, dst_st.loading_zone.y),
            priority=pri,
            material=mat,
            distance=dist,
            weight=f"{random.randint(5, 30)} kg",
            required_by=f"14:{random.randint(30, 59)}",
            bids_count=random.randint(2, 5),
            status=TaskStatus.AUCTIONING
        )

        self.tasks.append(task)
        self.task_queue.append(task)
        self._push_event(tid, f"Created {src_st.name} → {dst_st.name}",
                         f"{pri.value} | {mat}", category="production", task_id=tid)
        return task

    def run_auction_for(self, task: Task) -> Auction:
        self._push_event(task.id, f"Auction started",
                         f"{task.source} → {task.destination}", category="production", task_id=task.id)
        auction = run_auction(task.id, task.source_position, task.destination_position,
                              self.agvs, self.grid, self.mode, len(self.task_queue))
        for b in auction.bids:
            self._push_event(b.agv_id, f"Bid: {b.final_bid}",
                             f"Travel:{b.travel_cost} Cong:{b.congestion_cost} Future:{b.future_impact}",
                             category="agv", agv_id=b.agv_id, task_id=task.id)
        self.current_auction = auction

        if auction.winner_id:
            if auction.bids:
                self.latest_bids = [
                    {
                        "agvId": b.agv_id,
                        "travelCost": round(b.travel_cost, 1),
                        "batteryCost": round(b.battery_cost, 1),
                        "congestionCost": round(b.congestion_cost, 1),
                        "futureImpact": round(b.future_impact, 1),
                        "finalBid": round(b.final_bid, 1),
                        "isWinner": b.is_winner,
                    }
                    for b in auction.bids
                ]
            reasons = explain_winner(auction.bids)
            self._push_event(auction.winner_id, f"Selected for {task.id}",
                             " | ".join(reasons), category="agv", agv_id=auction.winner_id, task_id=task.id)
            winner_agv = next((a for a in self.agvs if a.id == auction.winner_id), None)
            if winner_agv:
                self.current_prediction = get_future_impact_details(
                    winner_agv, task.source_position, task.destination_position,
                    self.agvs, self.grid, len(self.task_queue))
        return auction

    def assign_task(self, task: Task, agv_id: str) -> bool:
        if self.emergency_stop_active:
            return False
        if not task or task.status in (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS, TaskStatus.DELIVERING, TaskStatus.COMPLETED, TaskStatus.FAILED):
            return False
        agv = next((a for a in self.agvs if a.id == agv_id), None)
        if not agv:
            return False
        if agv.status in (AGVStatus.FAILED, AGVStatus.CHARGING, AGVStatus.MOVING, AGVStatus.DELIVERING):
            return False
        pr = find_path(self.grid, agv.position, task.source_position)
        if pr.found:
            agv.route = pr.path
            agv.route_index = 0
            agv.status = AGVStatus.MOVING
            agv.current_task = task.id
            agv.destination = Pos(task.source_position.x, task.source_position.y)
            agv.speed = 1.2
            agv.location = task.source
            task.status = TaskStatus.ASSIGNED
            task.assigned_agv = agv_id
            task.started_at = time.time()
            if task in self.task_queue:
                self.task_queue.remove(task)
            self._push_event(agv.id, f"Route assigned to {task.source}",
                             f"Path: {pr.distance} cells", category="agv", agv_id=agv.id, task_id=task.id)
            return True
        return False

    def spawn_task(self, source: str | None = None, dest: str | None = None, priority: str | None = None) -> Task:
        task = self.create_task(source, dest, priority)
        auction = self.run_auction_for(task)
        if auction.winner_id:
            self.assign_task(task, auction.winner_id)
        return task

    def fail_agv(self, agv_id: str | None = None):
        target = next((a for a in self.agvs if a.id == agv_id), None) if agv_id else None
        if not target:
            candidates = [a for a in self.agvs if a.status not in (AGVStatus.FAILED, AGVStatus.CHARGING)]
            if candidates: target = random.choice(candidates)
        if not target: return

        target.status = AGVStatus.FAILED
        target.speed = 0.0
        target.route = []
        target.route_index = 0
        self._push_event(target.id, "Fault detected", "Mechanical stop", category="agv", agv_id=target.id)

        if target.current_task:
            affected = next((t for t in self.tasks if t.id == target.current_task), None)
            if affected and affected.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                affected.status = TaskStatus.RE_AUCTIONING
                affected.assigned_agv = None
                target.current_task = None
                self._push_event(affected.id, "Re-auctioning task",
                                 f"Assignee {target.id} failed", category="production", task_id=affected.id)
                auction = self.run_auction_for(affected)
                if auction.winner_id:
                    self.assign_task(affected, auction.winner_id)

    def block_corridor(self):
        c = random.choice(self.corridors)
        for p in c.cells:
            self.grid[p.y][p.x].congestion = min(1.0, self.grid[p.y][p.x].congestion + 0.5)
        self._push_event("AMR / AGV", f"Corridor {c.id} congested",
                         "High traffic volume", category="agv")

    def force_charge(self, agv_id: str | None = None):
        target = next((a for a in self.agvs if a.id == agv_id), None) if agv_id else None
        if not target:
            candidates = [a for a in self.agvs if a.status == AGVStatus.IDLE]
            if candidates: target = random.choice(candidates)
        if not target: return

        charge_pos = Pos(11, 23)
        pr = find_path(self.grid, target.position, charge_pos)
        if pr.found:
            target.route = pr.path
            target.route_index = 0
            target.status = AGVStatus.MOVING
            target.destination = charge_pos
            target.battery = max(10, target.battery - 25)
            self._push_event(target.id, "Heading to Charging C1",
                             "Battery low", category="agv", agv_id=target.id)

    def emergency_stop(self):
        self.emergency_stop_active = True
        self.paused = True
        self.running = False
        for a in self.agvs:
            a.speed = 0.0
        self._push_event("SYSTEM", "EMERGENCY STOP (ALL) Engaged", "All AGVs and factory operations halted", category="machine")

    def resume(self):
        self.emergency_stop_active = False
        self.paused = False
        self.running = True
        for a in self.agvs:
            if a.status in (AGVStatus.MOVING, AGVStatus.DELIVERING):
                a.speed = 1.2
        self._push_event("SYSTEM", "System resumed", "Operations normal", category="system")

    # ---- Tick Loop ---- #

    def _process_queue(self):
        if not self.task_queue or self.emergency_stop_active:
            return
        available = [a for a in self.agvs if a.status in (AGVStatus.IDLE, AGVStatus.WAITING)]
        if not available:
            return
        pending = [t for t in self.task_queue if t.status in (TaskStatus.PENDING, TaskStatus.AUCTIONING)]
        for task in pending:
            available = [a for a in self.agvs if a.status in (AGVStatus.IDLE, AGVStatus.WAITING)]
            if not available:
                break
            auction = self.run_auction_for(task)
            if auction.winner_id:
                self.assign_task(task, auction.winner_id)

    def tick(self):
        if self.emergency_stop_active or not self.running or self.paused:
            return
        self.tick_count += 1

        # Keep simulation lively by periodically generating transport tasks
        active = [t for t in self.tasks if t.status in (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS, TaskStatus.DELIVERING)]
        if len(active) < 4 and self.tick_count % 12 == 0:
            self.spawn_task()

        # Check for idle AGVs that have enough battery and assign them next missions
        for agv in self.agvs:
            if agv.status == AGVStatus.IDLE and agv.battery > 25.0:
                pending = [t for t in self.task_queue if t.status in (TaskStatus.PENDING, TaskStatus.AUCTIONING)]
                if pending:
                    self.assign_task(pending[0], agv.id)
                else:
                    new_t = self.create_task()
                    self.assign_task(new_t, agv.id)

        self._update_congestion()
        self._move_agvs()
        self._process_queue()
        self._update_corridors()
        self._update_metrics()

    def _update_congestion(self):
        for y in range(GRID_H):
            for x in range(GRID_W):
                self.grid[y][x].congestion *= 0.96
                self.grid[y][x].occupied = False
        for agv in self.agvs:
            if agv.status == AGVStatus.FAILED:
                continue
            px, py = agv.position.x, agv.position.y
            if 0 <= px < GRID_W and 0 <= py < GRID_H:
                self.grid[py][px].occupied = True
                self.grid[py][px].congestion = min(1, self.grid[py][px].congestion + 0.12)

    def _move_agvs(self):
        for agv in self.agvs:
            if agv.status == AGVStatus.FAILED:
                agv.speed = 0.0
                continue
            if agv.status == AGVStatus.CHARGING:
                agv.speed = 0.0
                agv.location = "Charging C1"
                agv.battery = min(100.0, agv.battery + 0.5)
                if agv.battery >= 92.0:
                    agv.status = AGVStatus.IDLE
                    self._push_event(agv.id, "Charging complete", "Available for dispatch", category="agv", agv_id=agv.id)
                continue

            if agv.route and agv.route_index < len(agv.route):
                nxt = agv.route[agv.route_index]
                agv.position = Pos(nxt.x, nxt.y)
                agv.route_index += 1
                agv.total_distance += 1
                agv.battery = max(0.0, agv.battery - 0.05)
                if agv.speed == 0.0:
                    agv.speed = round(1.0 + (int(agv.id[-1]) % 4) * 0.1, 1)

                # Determine approximate nearest station for location reporting
                for s in STATIONS:
                    if agv.position.manhattan(s.loading_zone) <= 3:
                        agv.location = s.name
                        break

                if agv.route_index >= len(agv.route):
                    self._on_arrival(agv)
            elif agv.status == AGVStatus.IDLE:
                agv.idle_time += 0.1
                # If idle but has battery, grab a task
                if agv.battery > 25.0:
                    new_t = self.create_task()
                    self.assign_task(new_t, agv.id)

    def _on_arrival(self, agv: AGV):
        task = next((t for t in self.tasks if t.id == agv.current_task), None)
        if not task:
            if agv.destination and (agv.destination == Pos(11, 23) or agv.destination == Pos(27, 23)):
                agv.status = AGVStatus.CHARGING
                agv.speed = 0.0
                agv.route = []
                agv.route_index = 0
                return
            
            # Low battery -> route to charge
            if agv.battery < 30.0:
                charger_pos = Pos(11, 23) if random.random() < 0.5 else Pos(27, 23)
                pr = find_path(self.grid, agv.position, charger_pos)
                if pr.found:
                    agv.route = pr.path
                    agv.route_index = 0
                    agv.destination = charger_pos
                    agv.status = AGVStatus.MOVING
                    agv.location = "Heading to Charging"
                    return

            # Keep moving: assign next task
            pending = [t for t in self.task_queue if t.status in (TaskStatus.PENDING, TaskStatus.AUCTIONING)]
            if pending:
                self.assign_task(pending[0], agv.id)
            else:
                new_t = self.create_task()
                self.assign_task(new_t, agv.id)
            return

        if task.status in (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS):
            self._push_event(agv.id, f"Loaded item at {task.source}",
                             f"Moving to {task.destination}", category="agv", agv_id=agv.id, task_id=task.id)
            pr = find_path(self.grid, agv.position, task.destination_position)
            if pr.found:
                agv.route = pr.path
                agv.route_index = 0
                agv.status = AGVStatus.DELIVERING
                agv.destination = Pos(task.destination_position.x, task.destination_position.y)
                task.status = TaskStatus.DELIVERING
            else:
                agv.status = AGVStatus.IDLE

        elif task.status == TaskStatus.DELIVERING:
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            self.completed_tasks.append(task)

            self._push_event(task.id, f"Delivered to {task.destination}",
                             f"Completed by {agv.id}", category="production", agv_id=agv.id, task_id=task.id)

            agv.current_task = None
            agv.destination = None
            agv.route = []
            agv.route_index = 0
            agv.tasks_completed += 1
            agv.utilization = min(100.0, agv.utilization + 2.5)

            # Continuous motion: check battery or immediately assign next task
            if agv.battery < 30.0:
                charger_pos = Pos(11, 23) if random.random() < 0.5 else Pos(27, 23)
                pr = find_path(self.grid, agv.position, charger_pos)
                if pr.found:
                    agv.route = pr.path
                    agv.route_index = 0
                    agv.destination = charger_pos
                    agv.status = AGVStatus.MOVING
                    agv.location = "Heading to Charging"
                    return

            pending = [t for t in self.task_queue if t.status in (TaskStatus.PENDING, TaskStatus.AUCTIONING)]
            if pending:
                self.assign_task(pending[0], agv.id)
            else:
                new_t = self.create_task()
                self.assign_task(new_t, agv.id)

    def _update_corridors(self):
        for c in self.corridors:
            total_c = sum(self.grid[p.y][p.x].congestion for p in c.cells)
            c.utilization = round(total_c / len(c.cells) * 100, 1) if c.cells else 0
            c.queue_length = sum(1 for a in self.agvs for p in c.cells if a.position == p)

    def _update_metrics(self):
        active = sum(1 for a in self.agvs if a.status != AGVStatus.FAILED)
        comp_times = [(t.completed_at - t.created_at) for t in self.completed_tasks if t.completed_at]
        avg_ct = sum(comp_times) / len(comp_times) if comp_times else 0
        max_cu = max((c.utilization for c in self.corridors), default=0)
        cl = "HIGH" if max_cu > 70 else ("MEDIUM" if max_cu > 40 else "LOW")
        cong_events = sum(1 for e in self.events if "congested" in e.message.lower())
        tp = 14 + len(self.completed_tasks) // 3 if self.mode == DispatchMode.MARKETFLOOR else 0

        self.metrics = Metrics(
            active_agvs=active,
            tasks_in_queue=len(self.task_queue),
            tasks_completed=len(self.completed_tasks),
            congestion_level=cl,
            avg_completion_time=avg_ct,
            throughput_improvement=tp,
            total_congestion_events=cong_events,
        )

    # ---- Full State Snapshot ---- #

    def snapshot(self) -> dict:
        grid_data: list[dict] = []
        for y in range(GRID_H):
            for x in range(GRID_W):
                c = self.grid[y][x]
                if c.type != CellType.FLOOR or c.congestion > 0.08:
                    grid_data.append({
                        "x": x, "y": y,
                        "type": c.type.value,
                        "walkable": c.walkable,
                        "congestion": round(c.congestion, 2),
                        "label": c.label,
                    })

        # Filter open tasks (always maintain 3-5 open/auctioning tasks for table display)
        open_tasks = [
            t.to_dict() for t in self.tasks
            if t.status in (TaskStatus.PENDING, TaskStatus.AUCTIONING, TaskStatus.ASSIGNED, TaskStatus.DELIVERING)
        ]
        while len(open_tasks) < 4:
            new_t = self.create_task()
            open_tasks.append(new_t.to_dict())

        # Selected task details
        selected_task = next((t for t in self.tasks if t.id == "TASK-108"), None)
        if not selected_task and self.tasks:
            selected_task = self.tasks[0]

        fleet_summary = {
            "total": len(self.agvs),
            "active": sum(1 for a in self.agvs if a.status in (AGVStatus.MOVING, AGVStatus.DELIVERING)),
            "idle": sum(1 for a in self.agvs if a.status == AGVStatus.IDLE),
            "charging": sum(1 for a in self.agvs if a.status == AGVStatus.CHARGING),
            "fault": sum(1 for a in self.agvs if a.status == AGVStatus.FAILED),
        }

        return {
            "type": "STATE",
            "grid": grid_data,
            "gridW": GRID_W,
            "gridH": GRID_H,
            "agvs": [a.to_dict() for a in self.agvs],
            "fleetSummary": fleet_summary,
            "tasks": [t.to_dict() for t in self.tasks[-20:]],
            "openTasks": open_tasks[:5],
            "selectedTask": selected_task.to_dict() if selected_task else None,
            "currentAuction": self.current_auction.to_dict() if self.current_auction else None,
            "latestBids": self.latest_bids,
            "decisionTrace": self.decision_trace,
            "currentPrediction": self.current_prediction,
            "metrics": self.metrics.to_dict(),
            "stations": [s.to_dict() for s in STATIONS],
            "corridors": [c.to_dict() for c in self.corridors],
            "blockedArea": BLOCKED_AREA,
            "machineCAlert": self.machine_c_alert,
            "systemStatus": self.system_status,
            "keyMetrics": self.key_metrics,
            "mode": self.mode.value,
            "speed": self.speed,
            "running": self.running,
            "paused": self.paused,
            "emergencyStopActive": self.emergency_stop_active,
            "tickCount": self.tick_count,
        }

    def reset(self):
        self.__init__()
