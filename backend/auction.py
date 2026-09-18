# ============================================================
# MarketFloor — Auction Engine
# ============================================================
# Bid calculation for NEAREST (baseline) and MARKETFLOOR modes.

from __future__ import annotations
from models import AGV, AGVStatus, Bid, Auction, Pos, GridCell, DispatchMode
from astar import find_path
import time

_auction_counter = 0


def _reset_counter():
    global _auction_counter
    _auction_counter = 0


# ---- Future-Impact Heuristic ---- #

def _count_nearby(pos: Pos, agvs: list[AGV], exclude: str, radius: int = 6) -> int:
    return sum(1 for a in agvs if a.id != exclude and a.position.manhattan(pos) <= radius)


def _corridor_util(pos: Pos, grid: list[list[GridCell]], radius: int = 4) -> float:
    rows, cols = len(grid), len(grid[0])
    total, count = 0.0, 0
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            nx, ny = pos.x + dx, pos.y + dy
            if 0 <= nx < cols and 0 <= ny < rows:
                total += grid[ny][nx].congestion
                count += 1
    return total / count if count else 0


def _predicted_traffic(dest: Pos, agvs: list[AGV], exclude: str) -> int:
    return sum(1 for a in agvs if a.id != exclude and a.destination and a.destination.manhattan(dest) < 8)


# Hard-coded narrow-corridor cell positions (same as grid.py)
_NARROW_CELLS = {
    (12, 13), (12, 14), (12, 15),
    (27, 13), (27, 14), (27, 15),
    (19, 10), (20, 10), (21, 10),
    (19, 18), (20, 18), (21, 18),
}


def _near_narrow(pos: Pos) -> bool:
    return any(abs(pos.x - cx) + abs(pos.y - cy) <= 3 for cx, cy in _NARROW_CELLS)


def _future_impact(agv: AGV, src: Pos, dst: Pos, agvs: list[AGV],
                   grid: list[list[GridCell]], queue_len: int) -> tuple[float, float, str, int]:
    """Returns (score 0-10, predicted_delay_s, risk LOW|MED|HIGH, confidence%)."""
    nearby = _count_nearby(src, agvs, agv.id)
    cu = _corridor_util(src, grid)
    traffic = _predicted_traffic(dst, agvs, agv.id)
    dist = agv.position.manhattan(src)

    impact = nearby * 1.2 + cu * 8 + traffic * 1.5 + queue_len * 0.3 + (dist / 40) * 2
    if _near_narrow(src) or _near_narrow(dst):
        impact += nearby * 2.0
    if agv.battery < 30:
        impact += 2.0

    score = min(10.0, max(0.0, round(impact, 1)))
    delay = round(impact * 1.3, 1)
    risk = "HIGH" if score > 6 else ("MEDIUM" if score > 3 else "LOW")
    conf = max(65, min(95, int(95 - nearby * 3 - traffic * 2 - (5 if dist > 20 else 0))))
    return score, delay, risk, conf


# ---- Public API ---- #

def run_auction(
    task_id: str,
    task_src: Pos,
    task_dst: Pos,
    agvs: list[AGV],
    grid: list[list[GridCell]],
    mode: DispatchMode,
    queue_len: int,
    is_re_auction: bool = False,
) -> Auction:
    global _auction_counter
    _auction_counter += 1
    aid = f"AUC-{_auction_counter:04d}"

    available = [a for a in agvs if a.status in (AGVStatus.IDLE, AGVStatus.WAITING)]
    if not available:
        return Auction(id=aid, task_id=task_id, is_re_auction=is_re_auction)

    # Find closest
    closest_id = min(available, key=lambda a: a.position.manhattan(task_src)).id

    bids: list[Bid] = []
    for agv in available:
        if mode == DispatchMode.NEAREST:
            d = agv.position.manhattan(task_src)
            bids.append(Bid(agv_id=agv.id, travel_cost=d, congestion_cost=0,
                            future_impact=0, battery_cost=0, fairness_adjustment=0,
                            final_bid=d, is_closest=(agv.id == closest_id)))
        else:
            pr = find_path(grid, agv.position, task_src)
            travel = pr.distance if pr.found else agv.position.manhattan(task_src) * 1.5
            cong = round(pr.congestion_cost * 3, 1)
            fi_score, _, _, _ = _future_impact(agv, task_src, task_dst, agvs, grid, queue_len)
            fi = round(fi_score, 1)

            bat = 5 if agv.battery < 20 else (2 if agv.battery < 40 else (1 if agv.battery < 60 else 0))
            avg_util = sum(a.utilization for a in agvs) / len(agvs) if agvs else 0
            fair = 3 if agv.utilization < avg_util - 10 else (2 if agv.utilization < avg_util - 5 else (1 if agv.utilization < avg_util else 0))

            final = round(travel + cong + fi + bat - fair, 1)
            bids.append(Bid(agv_id=agv.id, travel_cost=round(travel, 1),
                            congestion_cost=cong, future_impact=fi,
                            battery_cost=bat, fairness_adjustment=fair,
                            final_bid=max(0, final), is_closest=(agv.id == closest_id)))

    winner = min(bids, key=lambda b: b.final_bid)
    winner.is_winner = True

    return Auction(id=aid, task_id=task_id, bids=bids, winner_id=winner.agv_id,
                   is_re_auction=is_re_auction, timestamp=time.time())


def explain_winner(bids: list[Bid]) -> list[str]:
    wb = next((b for b in bids if b.is_winner), None)
    if not wb:
        return []
    others = [b for b in bids if not b.is_winner]
    reasons: list[str] = []
    if any(wb.future_impact < o.future_impact for o in others):
        reasons.append("Lower future congestion impact")
    if any(wb.congestion_cost < o.congestion_cost for o in others):
        reasons.append("Better corridor availability")
    if wb.battery_cost <= 1:
        reasons.append("Sufficient battery level")
    if wb.fairness_adjustment > 0:
        reasons.append("Balanced workload utilization")
    if not wb.is_closest:
        reasons.append("Not closest, but least total impact")
    else:
        reasons.append("Closest with acceptable impact")
    reasons.append("Lowest combined bid score")
    return reasons


def get_future_impact_details(agv: AGV, src: Pos, dst: Pos, agvs: list[AGV],
                               grid: list[list[GridCell]], queue_len: int) -> dict:
    """Full prediction details for display in the AI panel."""
    score, delay, risk, conf = _future_impact(agv, src, dst, agvs, grid, queue_len)
    return {
        "agvId": agv.id,
        "futureImpactScore": score,
        "predictedDelay": delay,
        "congestionRisk": risk,
        "confidence": conf,
        "inputFeatures": {
            "currentPosition": agv.position.to_dict(),
            "distanceToTask": agv.position.manhattan(src),
            "nearbyAGVs": _count_nearby(src, agvs, agv.id),
            "corridorUtilization": round(_corridor_util(src, grid) * 100, 1),
            "queueLength": queue_len,
            "predictedTraffic": _predicted_traffic(dst, agvs, agv.id),
            "chargingDistance": agv.position.manhattan(Pos(4, 14)),
            "idleTime": round(agv.idle_time, 1),
        },
    }
