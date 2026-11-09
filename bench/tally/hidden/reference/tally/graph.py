"""Cycles and recalculation order (SPEC section 5.2)."""
from __future__ import annotations

import heapq


def components(nodes, preds) -> list[list]:
    """Strongly connected components (Tarjan, iterative). preds: node -> set of nodes it depends on."""
    index, low, on, stack, out = {}, {}, set(), [], []
    counter = 0
    nodes_list, nodes = list(nodes), set(nodes)
    for root in nodes_list:
        if root in index:
            continue
        work = [(root, iter(preds.get(root, ())))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in nodes:
                    continue
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(preds.get(w, ()))))
                    advanced = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                out.append(comp)
    return out


def order(nodes, preds, key) -> list[tuple[list, bool]]:
    """Groups of `nodes` in recalculation order: (members in key order, is_cycle).

    Only dependencies inside `nodes` count. A group comes after the groups it depends on; among the groups that could
    come next, the one whose smallest member has the smallest key comes first."""
    nodes = set(nodes)
    comps = components(sorted(nodes, key=key), preds)
    comp_of = {n: i for i, c in enumerate(comps) for n in c}
    after = [set() for _ in comps]        # comp -> comps that depend on it
    waiting = [0] * len(comps)
    for i, c in enumerate(comps):
        deps = {comp_of[p] for n in c for p in preds.get(n, ()) if p in nodes} - {i}
        waiting[i] = len(deps)
        for d in deps:
            after[d].add(i)
    keys = [min(key(n) for n in c) for c in comps]
    heap = [(keys[i], i) for i in range(len(comps)) if waiting[i] == 0]
    heapq.heapify(heap)
    out = []
    while heap:
        _, i = heapq.heappop(heap)
        members = sorted(comps[i], key=key)
        cyclic = len(members) > 1 or members[0] in preds.get(members[0], ())
        out.append((members, cyclic))
        for j in after[i]:
            waiting[j] -= 1
            if waiting[j] == 0:
                heapq.heappush(heap, (keys[j], j))
    return out
