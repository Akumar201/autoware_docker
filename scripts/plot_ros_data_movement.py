#!/usr/bin/env python3
"""
Plot data movement and graph stats per run from autoware_ros_info.py CSV output.

Reads PREFIX_summary.csv (and optionally PREFIX_throughput_detail.csv), filters to
numeric runs (excludes 'avg' row), and generates:
  - Data movement per run: total_bytes_s, total_msg_s
  - Graph stats per run (nodes, topics, publishers, subscribers)
  - With --detail: top topics chart, pipeline-by-category chart, category summary CSV,
    sensor-data chart, and sensor-data summary CSV

Pipeline categories follow Autoware architecture: Sensing, Localization, Perception,
Planning, Control, System, Vehicle Interface, Vehicle, Map, Other
(see node diagram in docs).

Sensor-data categories are derived from topic names:
  - IMU
  - Occupancy Grid Map
  - Laser Scan
  - Point Cloud

Usage:
  python3 plot_ros_data_movement.py [--summary PATH] [--detail PATH] [--out DIR]
  python3 plot_ros_data_movement.py --summary report_summary.csv --detail report_throughput_detail.csv --out ./plots
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
except ImportError:
    print("error: matplotlib and numpy required. pip install matplotlib numpy", file=sys.stderr)
    sys.exit(1)


def load_summary(path: Path):
    """Load summary CSV; return list of run dicts (exclude 'avg' row)."""
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["run_id"] == "avg":
                continue
            rows.append({
                "run_id": int(r["run_id"]),
                "nodes": int(r["nodes"]),
                "topics": int(r["topics"]),
                "publishers": int(r["publishers"]),
                "subscribers": int(r["subscribers"]),
                "elapsed_sec": float(r["elapsed_sec"]),
                "total_msgs": int(r["total_msgs"]),
                "total_bytes": int(r["total_bytes"]),
                "total_msg_s": float(r["total_msg_s"]),
                "total_bytes_s": float(r["total_bytes_s"]),
            })
    return rows


def load_detail(path: Path, top_n: int = 15):
    """Load detail CSV; return top N topics by avg_bytes_s."""
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "topic": r["topic"],
                "avg_bytes_s": float(r["avg_bytes_s"]),
                "avg_msg_s": float(r["avg_msg_s"]),
                "total_bytes": int(r["total_bytes"]),
                "runs_with_data": int(r["runs_with_data"]),
            })
    rows.sort(key=lambda x: -x["avg_bytes_s"])
    return rows[:top_n]


# Pipeline categories per Autoware architecture (node diagram)
# https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/node-diagram/
PIPELINE_ORDER = [
    "Sensing",
    "Localization",
    "Perception",
    "Planning",
    "Control",
    "System",
    "Vehicle Interface",
    "Vehicle",
    "Map",
    "Other",
]

SENSOR_DATA_ORDER = [
    "IMU",
    "Occupancy Grid Map",
    "Laser Scan",
    "Point Cloud",
]


def topic_to_pipeline_category(topic: str) -> str:
    """Map topic path to pipeline stage (first path component)."""
    topic = topic.strip("/")
    if not topic:
        return "Other"
    parts = topic.split("/")
    first = parts[0].lower()
    second = parts[1].lower() if len(parts) > 1 else ""
    # Map first segment to display name
    if first == "sensing":
        return "Sensing"
    if first == "localization":
        return "Localization"
    if first in ("perception", "occupancy_grid_map"):
        return "Perception"
    if first == "planning":
        return "Planning"
    if first == "control":
        return "Control"
    if first == "map":
        return "Map"
    if first == "vehicle":
        return "Vehicle"
    if first == "api":
        if second == "vehicle":
            return "Vehicle Interface"
        return "System"
    if first in (
        "system",
        "diagnostics",
        "diagnostics_graph",
        "logging_diag_graph",
        "tf",
        "autoware",
        "rosout",
        "service_log",
    ):
        return "System"
    if first == "simulation":
        return "System"
    return "Other"


def topic_to_sensor_data_category(topic: str):
    """
    Map topic path to sensor-data type based on topic names.

    More specific payload names take precedence over namespace-only matches so
    `/occupancy_grid_map/virtual_scan/pointcloud` is treated as Point Cloud
    rather than Occupancy Grid Map.
    """
    topic = topic.strip("/")
    if not topic:
        return None

    parts = [p.lower() for p in topic.split("/") if p]
    last = parts[-1] if parts else ""

    if any("imu" in p for p in parts):
        return "IMU"
    if "laserscan" in last:
        return "Laser Scan"
    if "pointcloud" in last or last.startswith("points"):
        return "Point Cloud"
    if "occupancy_grid_map" in parts:
        return "Occupancy Grid Map"
    if any("laserscan" in p for p in parts):
        return "Laser Scan"
    if any("pointcloud" in p or p.startswith("points") for p in parts):
        return "Point Cloud"
    return None


def load_detail_rows(path: Path):
    """Load full detail CSV with all fields needed for plots and grouped summaries."""
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "topic": r["topic"],
                "runs_with_data": int(r["runs_with_data"]),
                "total_msgs": int(r["total_msgs"]),
                "total_bytes": int(r["total_bytes"]),
                "total_elapsed_sec": float(r["total_elapsed_sec"]),
                "avg_msg_s": float(r["avg_msg_s"]),
                "avg_bytes_s": float(r["avg_bytes_s"]),
            })
    return rows


def aggregate_category_metrics(detail_rows, include_empty: bool = False):
    """Aggregate throughput detail rows into pipeline categories."""
    global_elapsed_sec = max((r.get("total_elapsed_sec", 0.0) for r in detail_rows), default=0.0)
    agg = defaultdict(
        lambda: {
            "topic_count": 0,
            "total_msgs": 0,
            "total_bytes": 0,
            "total_elapsed_sec": 0.0,
            "avg_msg_s": 0.0,
            "avg_bytes_s": 0.0,
        }
    )
    for r in detail_rows:
        cat = topic_to_pipeline_category(r["topic"])
        a = agg[cat]
        a["topic_count"] += 1
        a["total_msgs"] += r.get("total_msgs", 0)
        a["total_bytes"] += r.get("total_bytes", 0)
        a["total_elapsed_sec"] = max(a["total_elapsed_sec"], r.get("total_elapsed_sec", 0.0))
        a["avg_msg_s"] += r["avg_msg_s"]
        a["avg_bytes_s"] += r["avg_bytes_s"]

    categories = PIPELINE_ORDER if include_empty else [
        c for c in PIPELINE_ORDER if c in agg and (agg[c]["avg_bytes_s"] > 0 or agg[c]["avg_msg_s"] > 0)
    ]
    rows = []
    for cat in categories:
        a = agg[cat]
        total_msgs = a["total_msgs"]
        avg_bytes_per_msg = (a["total_bytes"] / total_msgs) if total_msgs else 0.0
        total_elapsed_sec = a["total_elapsed_sec"] if a["topic_count"] else global_elapsed_sec
        rows.append({
            "category": cat,
            "topic_count": a["topic_count"],
            "total_msgs": total_msgs,
            "total_bytes": a["total_bytes"],
            "total_elapsed_sec": total_elapsed_sec,
            "avg_msg_s": a["avg_msg_s"],
            "avg_bytes_s": a["avg_bytes_s"],
            "avg_bytes_per_msg": avg_bytes_per_msg,
            "avg_mb_s": a["avg_bytes_s"] / 1e6,
        })
    return rows


def aggregate_sensor_data_metrics(detail_rows, include_empty: bool = False):
    """Aggregate throughput detail rows into sensor-data categories."""
    global_elapsed_sec = max((r.get("total_elapsed_sec", 0.0) for r in detail_rows), default=0.0)
    agg = defaultdict(
        lambda: {
            "topic_count": 0,
            "total_msgs": 0,
            "total_bytes": 0,
            "total_elapsed_sec": 0.0,
            "avg_msg_s": 0.0,
            "avg_bytes_s": 0.0,
        }
    )
    for r in detail_rows:
        cat = topic_to_sensor_data_category(r["topic"])
        if not cat:
            continue
        a = agg[cat]
        a["topic_count"] += 1
        a["total_msgs"] += r.get("total_msgs", 0)
        a["total_bytes"] += r.get("total_bytes", 0)
        a["total_elapsed_sec"] = max(a["total_elapsed_sec"], r.get("total_elapsed_sec", 0.0))
        a["avg_msg_s"] += r["avg_msg_s"]
        a["avg_bytes_s"] += r["avg_bytes_s"]

    categories = SENSOR_DATA_ORDER if include_empty else [
        c for c in SENSOR_DATA_ORDER if c in agg and (agg[c]["avg_bytes_s"] > 0 or agg[c]["avg_msg_s"] > 0)
    ]
    rows = []
    for cat in categories:
        a = agg[cat]
        total_msgs = a["total_msgs"]
        avg_bytes_per_msg = (a["total_bytes"] / total_msgs) if total_msgs else 0.0
        total_elapsed_sec = a["total_elapsed_sec"] if a["topic_count"] else global_elapsed_sec
        rows.append({
            "category": cat,
            "topic_count": a["topic_count"],
            "total_msgs": total_msgs,
            "total_bytes": a["total_bytes"],
            "total_elapsed_sec": total_elapsed_sec,
            "avg_msg_s": a["avg_msg_s"],
            "avg_bytes_s": a["avg_bytes_s"],
            "avg_bytes_per_msg": avg_bytes_per_msg,
            "avg_mb_s": a["avg_bytes_s"] / 1e6,
        })
    return rows


def category_summary_filename(detail_path: Path) -> str:
    """Derive a grouped summary filename from the detail CSV name."""
    name = detail_path.name
    if name.endswith("_throughput_detail.csv"):
        return name.replace("_throughput_detail.csv", "_category_summary.csv")
    if name.endswith(".csv"):
        return name[:-4] + "_category_summary.csv"
    return name + "_category_summary.csv"


def sensor_data_summary_filename(detail_path: Path) -> str:
    """Derive a grouped sensor-data summary filename from the detail CSV name."""
    name = detail_path.name
    if name.endswith("_throughput_detail.csv"):
        return name.replace("_throughput_detail.csv", "_sensor_data_summary.csv")
    if name.endswith(".csv"):
        return name[:-4] + "_sensor_data_summary.csv"
    return name + "_sensor_data_summary.csv"


def write_category_summary_csv(detail_rows, detail_path: Path, out_dir: Path):
    """Write grouped throughput metrics by pipeline category."""
    category_rows = aggregate_category_metrics(detail_rows, include_empty=True)
    out_path = out_dir / category_summary_filename(detail_path)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "category",
                "topic_count",
                "total_msgs",
                "total_bytes",
                "total_elapsed_sec",
                "avg_msg_s",
                "avg_bytes_s",
                "avg_bytes_per_msg",
                "avg_mb_s",
            ],
        )
        writer.writeheader()
        for row in category_rows:
            writer.writerow({
                "category": row["category"],
                "topic_count": row["topic_count"],
                "total_msgs": row["total_msgs"],
                "total_bytes": row["total_bytes"],
                "total_elapsed_sec": f'{row["total_elapsed_sec"]:.2f}',
                "avg_msg_s": f'{row["avg_msg_s"]:.2f}',
                "avg_bytes_s": f'{row["avg_bytes_s"]:.2f}',
                "avg_bytes_per_msg": f'{row["avg_bytes_per_msg"]:.2f}',
                "avg_mb_s": f'{row["avg_mb_s"]:.6f}',
            })
    print(f"Saved {out_path}")
    return out_path


def write_sensor_data_summary_csv(detail_rows, detail_path: Path, out_dir: Path):
    """Write grouped throughput metrics by sensor-data category."""
    category_rows = aggregate_sensor_data_metrics(detail_rows, include_empty=True)
    out_path = out_dir / sensor_data_summary_filename(detail_path)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "category",
                "topic_count",
                "total_msgs",
                "total_bytes",
                "total_elapsed_sec",
                "avg_msg_s",
                "avg_bytes_s",
                "avg_bytes_per_msg",
                "avg_mb_s",
            ],
        )
        writer.writeheader()
        for row in category_rows:
            writer.writerow({
                "category": row["category"],
                "topic_count": row["topic_count"],
                "total_msgs": row["total_msgs"],
                "total_bytes": row["total_bytes"],
                "total_elapsed_sec": f'{row["total_elapsed_sec"]:.2f}',
                "avg_msg_s": f'{row["avg_msg_s"]:.2f}',
                "avg_bytes_s": f'{row["avg_bytes_s"]:.2f}',
                "avg_bytes_per_msg": f'{row["avg_bytes_per_msg"]:.2f}',
                "avg_mb_s": f'{row["avg_mb_s"]:.6f}',
            })
    print(f"Saved {out_path}")
    return out_path


def plot_data_movement_per_run(runs, out_dir: Path):
    """Bar charts: total_bytes_s and total_msg_s per run."""
    run_ids = [r["run_id"] for r in runs]
    bytes_s = [r["total_bytes_s"] / 1e6 for r in runs]  # MB/s
    msg_s = [r["total_msg_s"] for r in runs]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

    x = np.arange(len(run_ids))
    w = 0.6

    ax1.bar(x, bytes_s, width=w, color="steelblue", edgecolor="navy", alpha=0.8)
    ax1.set_ylabel("Throughput (MB/s)")
    ax1.set_title("Data movement per run: bytes/sec")
    ax1.set_xticks(x)
    ax1.set_xticklabels(run_ids)
    ax1.grid(axis="y", linestyle="--", alpha=0.7)

    ax2.bar(x, msg_s, width=w, color="darkgreen", edgecolor="green", alpha=0.8)
    ax2.set_xlabel("Run")
    ax2.set_ylabel("Messages/sec")
    ax2.set_title("Data movement per run: messages/sec")
    ax2.set_xticks(x)
    ax2.set_xticklabels(run_ids)
    ax2.grid(axis="y", linestyle="--", alpha=0.7)

    plt.tight_layout()
    out_path = out_dir / "data_movement_per_run.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


def plot_graph_stats_per_run(runs, out_dir: Path):
    """Line/bar: nodes, topics, publishers, subscribers per run."""
    run_ids = [r["run_id"] for r in runs]
    fig, ax = plt.subplots(figsize=(10, 4))
    x = np.arange(len(run_ids))
    w = 0.2
    ax.bar(x - 1.5 * w, [r["nodes"] for r in runs], width=w, label="Nodes", color="C0")
    ax.bar(x - 0.5 * w, [r["topics"] for r in runs], width=w, label="Topics", color="C1")
    ax.bar(x + 0.5 * w, [r["publishers"] for r in runs], width=w, label="Publishers", color="C2")
    ax.bar(x + 1.5 * w, [r["subscribers"] for r in runs], width=w, label="Subscribers", color="C3")
    ax.set_xlabel("Run")
    ax.set_ylabel("Count")
    ax.set_title("Graph stats per run (nodes, topics, publishers, subscribers)")
    ax.set_xticks(x)
    ax.set_xticklabels(run_ids)
    ax.legend(loc="upper right", ncol=4)
    ax.grid(axis="y", linestyle="--", alpha=0.7)
    plt.tight_layout()
    out_path = out_dir / "graph_stats_per_run.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


def plot_total_bytes_and_msgs_per_run(runs, out_dir: Path):
    """Bar: total_bytes and total_msgs per run (volume in that run)."""
    run_ids = [r["run_id"] for r in runs]
    total_bytes_mb = [r["total_bytes"] / 1e6 for r in runs]
    total_msgs = [r["total_msgs"] for r in runs]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    x = np.arange(len(run_ids))
    w = 0.6

    ax1.bar(x, total_bytes_mb, width=w, color="teal", edgecolor="darkgreen", alpha=0.8)
    ax1.set_ylabel("Total bytes (MB)")
    ax1.set_title("Total data volume per run (bytes)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(run_ids)
    ax1.grid(axis="y", linestyle="--", alpha=0.7)

    ax2.bar(x, total_msgs, width=w, color="coral", edgecolor="darkred", alpha=0.8)
    ax2.set_xlabel("Run")
    ax2.set_ylabel("Total messages")
    ax2.set_title("Total message count per run")
    ax2.set_xticks(x)
    ax2.set_xticklabels(run_ids)
    ax2.grid(axis="y", linestyle="--", alpha=0.7)

    plt.tight_layout()
    out_path = out_dir / "volume_per_run.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


def plot_pipeline_by_category(detail_rows, out_dir: Path, title_suffix: str = ""):
    """Bar charts: averaged MB/s and Messages/s by pipeline stage (Sensing, Localization, etc.)."""
    if not detail_rows:
        return
    category_rows = aggregate_category_metrics(detail_rows, include_empty=False)
    categories = [r["category"] for r in category_rows]
    if not categories:
        return
    bytes_mb_s = [r["avg_mb_s"] for r in category_rows]
    msg_s = [r["avg_msg_s"] for r in category_rows]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    x = np.arange(len(categories))
    w = 0.6

    ax1.bar(x, bytes_mb_s, width=w, color="white", edgecolor="black", linewidth=1.2)
    ax1.set_ylabel("Throughput (MB/s)")
    ax1.set_title("Throughput by pipeline stage (averaged across runs)" + (" — " + title_suffix if title_suffix else ""))
    ax1.set_xticks(x)
    ax1.set_xticklabels(categories)
    ax1.grid(axis="y", linestyle="--", alpha=0.7)
    for spine in ("top", "right"):
        ax1.spines[spine].set_visible(False)

    ax2.bar(x, msg_s, width=w, color="white", edgecolor="black", linewidth=1.2)
    ax2.set_xlabel("Pipeline stage")
    ax2.set_ylabel("Messages/s")
    ax2.set_title("Message rate by pipeline stage (averaged across runs)" + (" — " + title_suffix if title_suffix else ""))
    ax2.set_xticks(x)
    ax2.set_xticklabels(categories)
    ax2.grid(axis="y", linestyle="--", alpha=0.7)
    for spine in ("top", "right"):
        ax2.spines[spine].set_visible(False)

    plt.tight_layout()
    out_path = out_dir / "pipeline_throughput.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


def plot_sensor_data_by_category(detail_rows, out_dir: Path, title_suffix: str = ""):
    """Bar charts: averaged MB/s and Messages/s by sensor-data category."""
    if not detail_rows:
        return
    category_rows = aggregate_sensor_data_metrics(detail_rows, include_empty=False)
    categories = [r["category"] for r in category_rows]
    if not categories:
        return
    bytes_mb_s = [r["avg_mb_s"] for r in category_rows]
    msg_s = [r["avg_msg_s"] for r in category_rows]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    x = np.arange(len(categories))
    w = 0.6

    ax1.bar(x, bytes_mb_s, width=w, color="white", edgecolor="black", linewidth=1.2)
    ax1.set_ylabel("Throughput (MB/s)")
    ax1.set_title("Throughput by sensor data type (averaged across runs)" + (" — " + title_suffix if title_suffix else ""))
    ax1.set_xticks(x)
    ax1.set_xticklabels(categories)
    ax1.grid(axis="y", linestyle="--", alpha=0.7)
    for spine in ("top", "right"):
        ax1.spines[spine].set_visible(False)

    ax2.bar(x, msg_s, width=w, color="white", edgecolor="black", linewidth=1.2)
    ax2.set_xlabel("Sensor data type")
    ax2.set_ylabel("Messages/s")
    ax2.set_title("Message rate by sensor data type (averaged across runs)" + (" — " + title_suffix if title_suffix else ""))
    ax2.set_xticks(x)
    ax2.set_xticklabels(categories)
    ax2.grid(axis="y", linestyle="--", alpha=0.7)
    for spine in ("top", "right"):
        ax2.spines[spine].set_visible(False)

    plt.tight_layout()
    out_path = out_dir / "sensor_data_throughput.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


def plot_top_topics_bar(detail_rows, out_dir: Path):
    """Horizontal bar: top topics by avg_bytes_s (from detail CSV)."""
    if not detail_rows:
        return
    # Use last 55 chars of path so we see topic name and parent
    topics = [(r["topic"][-55:] if len(r["topic"]) > 55 else r["topic"]) for r in detail_rows]
    avg_mb_s = [r["avg_bytes_s"] / 1e6 for r in detail_rows]
    fig, ax = plt.subplots(figsize=(10, max(5, len(detail_rows) * 0.35)))
    y = np.arange(len(detail_rows))
    ax.barh(y, avg_mb_s, height=0.7, color="steelblue", alpha=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels(topics, fontsize=8)
    ax.set_xlabel("Avg throughput (MB/s)")
    ax.set_title("Top topics by average bytes/sec (from detail CSV)")
    ax.grid(axis="x", linestyle="--", alpha=0.7)
    plt.tight_layout()
    out_path = out_dir / "top_topics_throughput.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Plot data movement and graph stats per run from autoware_ros_info CSV output.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("report_summary.csv"),
        metavar="PATH",
        help="Path to summary CSV (default: report_summary.csv)",
    )
    parser.add_argument(
        "--detail",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to throughput detail CSV (optional; for top-topics chart)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("."),
        metavar="DIR",
        help="Output directory for PNGs (default: current dir)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=15,
        metavar="N",
        help="Number of top topics to show when using --detail (default: 15)",
    )
    args = parser.parse_args()

    if not args.summary.exists():
        print(f"error: summary file not found: {args.summary}", file=sys.stderr)
        sys.exit(1)

    args.out.mkdir(parents=True, exist_ok=True)
    runs = load_summary(args.summary)
    if not runs:
        print("error: no run rows found in summary (only 'avg'?)", file=sys.stderr)
        sys.exit(1)

    plot_data_movement_per_run(runs, args.out)
    plot_graph_stats_per_run(runs, args.out)
    plot_total_bytes_and_msgs_per_run(runs, args.out)

    if args.detail and args.detail.exists():
        detail_rows = load_detail(args.detail, top_n=args.top_n)
        plot_top_topics_bar(detail_rows, args.out)
        detail_all = load_detail_rows(args.detail)
        plot_pipeline_by_category(detail_all, args.out)
        write_category_summary_csv(detail_all, args.detail, args.out)
        plot_sensor_data_by_category(detail_all, args.out)
        write_sensor_data_summary_csv(detail_all, args.detail, args.out)
    elif args.detail:
        print(f"warning: detail file not found, skipping top-topics chart: {args.detail}", file=sys.stderr)

    print("Done.")


if __name__ == "__main__":
    main()
