# ============================================================
# MarketFloor — Data Models
# ============================================================
# Dataclasses for AGV, Task, Bid, Auction, and simulation state.

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class CellType(str, Enum):
    FLOOR = "FLOOR"
    WALL = "WALL"
    STATION = "STATION"
    CORRIDOR = "CORRIDOR"
    CHARGING = "CHARGING"
    WAREHOUSE = "WAREHOUSE"
    STORAGE = "STORAGE"
    LOADING_ZONE = "LOADING_ZONE"


class AGVStatus(str, Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    LOADING = "LOADING"
    DELIVERING = "DELIVERING"
    CHARGING = "CHARGING"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class TaskPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    AUCTIONING = "AUCTIONING"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    LOADING = "LOADING"
    DELIVERING = "DELIVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RE_AUCTIONING = "RE_AUCTIONING"


class DispatchMode(str, Enum):
    NEAREST = "NEAREST"
    MARKETFLOOR = "MARKETFLOOR"


@dataclass
class Pos:
    x: int
    y: int

    def __eq__(self, other):
        if not isinstance(other, Pos):
            return False
        return self.x == other.x and self.y == other.y

    def __hash__(self):
        return hash((self.x, self.y))

    def manhattan(self, other: Pos) -> int:
        return abs(self.x - other.x) + abs(self.y - other.y)

    def to_dict(self):
        return {"x": self.x, "y": self.y}


@dataclass
class GridCell:
    type: CellType
    walkable: bool
    congestion: float = 0.0
    occupied: bool = False
    label: Optional[str] = None
    station_id: Optional[str] = None


@dataclass
class StationInfo:
    id: str
    name: str
    kind: str  # production, warehouse, storage, charging
    position: Pos
    loading_zone: Pos

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "position": self.position.to_dict(),
            "loadingZone": self.loading_zone.to_dict(),
        }


@dataclass
class CorridorInfo:
    id: str
    cells: list[Pos]
    utilization: float = 0.0
    queue_length: int = 0
    is_narrow: bool = False

    def to_dict(self):
        return {
            "id": self.id,
            "cells": [c.to_dict() for c in self.cells],
            "utilization": self.utilization,
            "queueLength": self.queue_length,
            "isNarrow": self.is_narrow,
        }


@dataclass
class AGV:
    id: str
    position: Pos
    battery: float = 100.0
    status: AGVStatus = AGVStatus.IDLE
    current_task: Optional[str] = None
    destination: Optional[Pos] = None
    route: list[Pos] = field(default_factory=list)
    route_index: int = 0
    utilization: float = 0.0
    idle_time: float = 0.0
    tasks_completed: int = 0
    total_distance: float = 0.0
    color: str = "#0284c7"
    speed: float = 1.2
    location: str = "Floor"

    @property
    def dynamic_color(self) -> str:
        """
        Dynamically determine AGV visual indicator color:
        - Blue (#0284c7): Default base color / Idle
        - Orange (#ea580c): Performing a task (assigned, en route)
        - Grey (#6b7280): Delivering
        - Green (#16a34a): When charging or routing to charge
        - Red (#dc2626): When failed / fault
        Note: Quality Check (Black #1a1a1a) is resolved at snapshot level
        since AGV doesn't have direct task source info.
        """
        if self.status == AGVStatus.FAILED:
            return "#dc2626"
        if self.status == AGVStatus.CHARGING or (self.location and "charging" in self.location.lower() and not self.current_task):
            return "#16a34a"
        if self.status == AGVStatus.DELIVERING:
            return "#6b7280"
        if self.current_task or self.status == AGVStatus.MOVING:
            return "#ea580c"
        return "#0284c7"

    def to_dict(self):
        return {
            "id": self.id,
            "position": self.position.to_dict(),
            "battery": round(self.battery, 1),
            "status": self.status.value,
            "currentTask": self.current_task,
            "destination": self.destination.to_dict() if self.destination else None,
            "route": [p.to_dict() for p in self.route],
            "routeIndex": self.route_index,
            "utilization": round(self.utilization, 1),
            "idleTime": round(self.idle_time, 1),
            "tasksCompleted": self.tasks_completed,
            "totalDistance": round(self.total_distance, 1),
            "color": self.dynamic_color,
            "speed": round(self.speed, 1),
            "location": self.location,
        }


@dataclass
class Task:
    id: str
    source: str
    source_position: Pos
    destination: str
    destination_position: Pos
    priority: TaskPriority
    material: str
    distance: int
    weight: str = "15 kg"
    required_by: str = "14:45"
    bids_count: int = 4
    status: TaskStatus = TaskStatus.PENDING
    assigned_agv: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    def to_dict(self):
        return {
            "id": self.id,
            "source": self.source,
            "sourcePosition": self.source_position.to_dict(),
            "destination": self.destination,
            "destinationPosition": self.destination_position.to_dict(),
            "priority": self.priority.value,
            "material": self.material,
            "distance": self.distance,
            "weight": self.weight,
            "requiredBy": self.required_by,
            "bidsCount": self.bids_count,
            "status": self.status.value,
            "assignedAGV": self.assigned_agv,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "completedAt": self.completed_at,
        }


@dataclass
class Bid:
    agv_id: str
    travel_cost: float
    congestion_cost: float
    future_impact: float
    battery_cost: float
    fairness_adjustment: float
    final_bid: float
    is_winner: bool = False
    is_closest: bool = False

    def to_dict(self):
        return {
            "agvId": self.agv_id,
            "travelCost": self.travel_cost,
            "congestionCost": self.congestion_cost,
            "futureImpact": self.future_impact,
            "batteryCost": self.battery_cost,
            "fairnessAdjustment": self.fairness_adjustment,
            "finalBid": self.final_bid,
            "isWinner": self.is_winner,
            "isClosest": self.is_closest,
        }


@dataclass
class Auction:
    id: str
    task_id: str
    bids: list[Bid] = field(default_factory=list)
    winner_id: Optional[str] = None
    is_re_auction: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self):
        return {
            "id": self.id,
            "taskId": self.task_id,
            "bids": [b.to_dict() for b in self.bids],
            "winnerId": self.winner_id,
            "isReAuction": self.is_re_auction,
            "timestamp": self.timestamp,
        }


@dataclass
class SimEvent:
    id: int = 0
    type: str = ""
    message: str = ""
    details: str = ""
    agv_id: Optional[str] = None
    task_id: Optional[str] = None
    category: str = "system"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "message": self.message,
            "details": self.details,
            "agvId": self.agv_id,
            "taskId": self.task_id,
            "category": self.category,
            "timestamp": self.timestamp,
        }


@dataclass
class Metrics:
    active_agvs: int = 0
    tasks_in_queue: int = 0
    tasks_completed: int = 0
    congestion_level: str = "LOW"
    avg_completion_time: float = 0.0
    throughput_improvement: float = 0.0
    total_congestion_events: int = 0

    def to_dict(self):
        return {
            "activeAGVs": self.active_agvs,
            "tasksInQueue": self.tasks_in_queue,
            "tasksCompleted": self.tasks_completed,
            "congestionLevel": self.congestion_level,
            "avgCompletionTime": round(self.avg_completion_time, 1),
            "throughputImprovement": round(self.throughput_improvement, 1),
            "totalCongestionEvents": self.total_congestion_events,
        }
