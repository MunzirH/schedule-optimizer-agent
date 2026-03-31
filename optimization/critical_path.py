import networkx as nx


def build_graph(df):
    G = nx.DiGraph()

    for _, row in df.iterrows():
        task_id = str(row["task_id"])
        duration = row["duration"]

        G.add_node(task_id, duration=duration)

        if row["predecessors"]:
            preds = str(row["predecessors"]).split(",")
            for p in preds:
                G.add_edge(p.strip(), task_id)

    return G


def compute_critical_path(G):
    topo = list(nx.topological_sort(G))
    earliest_start = {}

    for node in topo:
        preds = list(G.predecessors(node))
        if not preds:
            earliest_start[node] = 0
        else:
            earliest_start[node] = max(
                earliest_start[p] + G.nodes[p]["duration"] for p in preds
            )

    end_node = max(
        earliest_start,
        key=lambda n: earliest_start[n] + G.nodes[n]["duration"]
    )

    path = [end_node]
    current = end_node

    while True:
        preds = list(G.predecessors(current))
        if not preds:
            break

        current = max(
            preds,
            key=lambda p: earliest_start[p] + G.nodes[p]["duration"]
        )
        path.insert(0, current)

    total_duration = earliest_start[end_node] + G.nodes[end_node]["duration"]

    return path, total_duration