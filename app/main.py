from parsers.csv_parser import load_schedule
from optimization.critical_path import build_graph, compute_critical_path
from agent.analyzer import analyze_schedule


def main():
    file_path = "data/sample_schedule.csv"

    df = load_schedule(file_path)

    print("\n📊 Schedule Loaded:")
    print(df)

    # Analyze issues
    issues = analyze_schedule(df)
    if issues:
        print("\n⚠️ Issues Found:")
        for issue in issues:
            print("-", issue)
    else:
        print("\n✅ No dependency issues found")

    # Compute critical path
    G = build_graph(df)
    path, duration = compute_critical_path(G)

    print("\n🚀 Critical Path:")
    print(" → ".join(path))

    print(f"\n⏱️ Total Project Duration: {duration} days")


if __name__ == "__main__":
    main()