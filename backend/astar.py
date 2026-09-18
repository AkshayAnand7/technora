# ============================================================
# MarketFloor — A* Pathfinding
# ============================================================
# Real A* on the factory grid. Cost = distance + congestion.
# Prefers lower-congestion routes when distances are similar.

from __future__ import annotations
import heapq
from dataclasses import dataclass, field
from typing import Optional
from models import Pos, GridCell

CONGESTION_WEIGHT = 5.0


@dataclass(order=True)
class _Node:
    f: float
    g: float = field(compare=False)
    pos: Pos = field(compare=False)
    parent: Optional["_Node"] = field(default=None, compare=False)


@dataclass
class PathResult:
    path: list[Pos]
    distance: int
    estimated_time: float
    congestion_cost: float
    found: bool

    def to_dict(self):
        return {
            "path": [p.to_dict() for p in self.path],
            "distance": self.distance,
            "estimatedTime": round(self.estimated_time, 1),
            "congestionCost": round(self.congestion_cost, 2),
            "found": self.found,
        }


_DIRS = [(0, -1), (0, 1), (-1, 0), (1, 0)]


def find_path(
    grid: list[list[GridCell]],
    start: Pos,
    goal: Pos,
    blocked: set[tuple[int, int]] | None = None,
) -> PathResult:
    """A* search from *start* to *goal* on *grid*."""

    rows = len(grid)
    cols = len(grid[0]) if rows else 0

    if blocked is None:
        blocked = set()

    open_heap: list[_Node] = []
    closed: set[tuple[int, int]] = set()
    g_scores: dict[tuple[int, int], float] = {}

    h = start.manhattan(goal)
    start_node = _Node(f=h, g=0.0, pos=start)
    heapq.heappush(open_heap, start_node)
    g_scores[(start.x, start.y)] = 0.0

    max_iter = rows * cols * 2

    for _ in range(max_iter):
        if not open_heap:
            break

        current = heapq.heappop(open_heap)
        cx, cy = current.pos.x, current.pos.y
        key = (cx, cy)

        if key in closed:
            continue

        # Goal reached — reconstruct path
        if cx == goal.x and cy == goal.y:
            path: list[Pos] = []
            total_cong = 0.0
            node: Optional[_Node] = current
            while node is not None:
                path.append(node.pos)
                cell = grid[node.pos.y][node.pos.x]
                total_cong += cell.congestion
                node = node.parent
            path.reverse()
            return PathResult(
                path=path,
                distance=len(path) - 1,
                estimated_time=(len(path) - 1) * 1.5,
                congestion_cost=total_cong,
                found=True,
            )

        closed.add(key)

        for dx, dy in _DIRS:
            nx, ny = cx + dx, cy + dy
            nkey = (nx, ny)
            if nx < 0 or ny < 0 or nx >= cols or ny >= rows:
                continue
            if nkey in closed or nkey in blocked:
                continue
            cell = grid[ny][nx]
            if not cell.walkable:
                continue

            cong_pen = cell.congestion * CONGESTION_WEIGHT
            tentative_g = current.g + 1.0 + cong_pen

            prev_g = g_scores.get(nkey)
            if prev_g is not None and tentative_g >= prev_g:
                continue
            g_scores[nkey] = tentative_g

            h = Pos(nx, ny).manhattan(goal)
            neighbor = _Node(f=tentative_g + h, g=tentative_g, pos=Pos(nx, ny), parent=current)
            heapq.heappush(open_heap, neighbor)

    # No path
    return PathResult(path=[], distance=0, estimated_time=0, congestion_cost=0, found=False)
