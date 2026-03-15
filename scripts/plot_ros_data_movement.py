#!/usr/bin/env python3
"""
Plot data movement and graph stats per run from autoware_ros_info.py CSV output.

Reads PREFIX_summary.csv (and optionally PREFIX_throughput_detail.csv), filters to
numeric runs (excludes 'avg' row), and generates:
  - Data movement per run: total_bytes_s, total_msg_s
  - Optional: graph stats per run (nodes, topics, publishers, subscribers)
  - Optional: top topics by average bytes/s from detail CSV

Usage:
  python3 plot_ros_data_movement.py [--summary PATH] [--detail PATH] [--out DIR]
  python3 plot_ros_data_movement.py --summary report_summary.csv --out ./plots
"""

import argparse
import csv
import sys
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
    elif args.detail:
        print(f"warning: detail file not found, skipping top-topics chart: {args.detail}", file=sys.stderr)

    print("Done.")


if __name__ == "__main__":
    main()
