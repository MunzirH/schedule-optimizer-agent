def analyze_schedule(df):
    issues = []

    task_ids = set(df["task_id"].astype(str))

    for _, row in df.iterrows():
        preds = str(row["predecessors"]).split(",") if row["predecessors"] else []
        for p in preds:
            if p.strip() and p.strip() not in task_ids:
                issues.append(f"Task {row['task_id']} has invalid predecessor {p}")

    return issues