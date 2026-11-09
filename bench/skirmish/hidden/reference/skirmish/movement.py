import heapq


def reachable(state, unit):
    grid = state.grid
    best = {unit.pos: 0}
    heap = [(0, unit.pos)]
    while heap:
        cost, (x, y) = heapq.heappop(heap)
        if cost > best.get((x, y), 1 << 30):
            continue
        for nx, ny in grid.neighbors(x, y):
            step = grid.move_cost(nx, ny)
            if step is None:
                continue
            other = state.unit_at(nx, ny)
            if other is not None and other.faction != unit.faction:
                continue
            total = cost + step
            if total <= unit.move and total < best.get((nx, ny), 1 << 30):
                best[(nx, ny)] = total
                heapq.heappush(heap, (total, (nx, ny)))
    return {c: v for c, v in best.items() if c == unit.pos or state.unit_at(*c) is None}
