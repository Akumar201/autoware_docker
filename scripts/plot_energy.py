#!/usr/bin/env python3
"""plot_energy.py – Visualise output from energy_profiler.py.

Reads <prefix>_node_energy.csv and <prefix>_topic_energy.csv and generates:
  1. Top processes by CPU utilisation (bar)
  2. Per-process user vs system (kernel) time — computation vs communication (stacked bar)
  3. Per-process communication fraction (bar)
  4. Top topics by throughput in bytes/sec (horizontal bar)
  5. Top topics by message rate (horizontal bar)
  6. Autoware pipeline category breakdown by throughput (pie + bar)
  7. Per-process energy breakdown if energy data is available (bar)

Usage:
  python3 plot_energy.py --nodes energy_node_energy.csv --topics energy_topic_energy.csv --out ./energy_plots
  python3 plot_energy.py --nodes energy_node_energy.csv --topics energy_topic_energy.csv --out ./energy_plots --top-n 20
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
    print(
        "error: matplotlib and numpy required. pip install matplotlib numpy",
        file=sys.stderr,
    )
    sys.exit(1)

PIPELINE_CATEGORIES = {
    "Sensing": "/sensing/",
    "Localization": "/localization/",
    "Perception": "/perception/",
    "Planning": "/planning/",
    "Control": "/control/",
    "System": "/system/",
    "Vehicle": "/vehicle/",
    "Map": "/map/",
    "Diagnostics": "/diagnostics",
}


def categorize_topic(topic_name):
    for cat, prefix in PIPELINE_CATEGORIES.items():
        if prefix in topic_name:
            return cat
    return "Other"


def _fmt(n):
    for p in ("", "K", "M", "G"):
        if abs(n) < 1024:
            return f"{n:.1f} {p}B"
        n /= 1024
    return f"{n:.1f} TB"


def load_nodes(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append(
                {
                    "pid": int(r["pid"]),
                    "process_name": r["process_name"],
                    "node_label": r["node_label"],
                    "avg_cpu_pct": float(r["avg_cpu_pct"]),
                    "user_time_s": float(r["user_time_s"]),
                    "system_time_s": float(r["system_time_s"]),
                    "comm_fraction": float(r["comm_fraction"]),
                    "cpu_energy_j": float(r["cpu_energy_j"]),
                    "est_comm_energy_j": float(r["est_comm_energy_j"]),
                    "est_compute_energy_j": float(r["est_compute_energy_j"]),
                    "gpu_energy_j": float(r["gpu_energy_j"]),
                    "total_energy_j": float(r["total_energy_j"]),
                }
            )
    return rows


def load_topics(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append(
                {
                    "topic": r["topic"],
                    "msgs": int(r["msgs"]),
                    "total_bytes": int(r["total_bytes"]),
                    "msg_per_sec": float(r["msg_per_sec"]),
                    "bytes_per_sec": float(r["bytes_per_sec"]),
                    "avg_bytes_per_msg": float(r["avg_bytes_per_msg"]),
                    "est_comm_energy_j": float(r["est_comm_energy_j"]),
                }
            )
    return rows


def _short_label(label, maxlen=35):
    if len(label) <= maxlen:
        return label
    return "..." + label[-(maxlen - 3) :]


# ── plot functions ───────────────────────────────────────────────────────


def plot_node_cpu_bar(nodes, out_dir, top_n):
    top = sorted(nodes, key=lambda r: -r["avg_cpu_pct"])[:top_n]
    labels = [r["node_label"] for r in top]
    vals = [r["avg_cpu_pct"] for r in top]

    fig, ax = plt.subplots(figsize=(10, max(4, len(labels) * 0.38)))
    y = np.arange(len(labels))
    ax.barh(y, vals, color="#4A90D9")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Avg CPU %  (normalised to package)")
    ax.set_title(f"Top {len(labels)} ROS 2 Processes by CPU Utilisation")
    ax.grid(axis="x", linestyle="--", alpha=0.5)
    plt.tight_layout()
    p = out_dir / "node_cpu_utilisation.png"
    plt.savefig(p, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved {p}")


def plot_node_user_system(nodes, out_dir, top_n):
    top = sorted(nodes, key=lambda r: -(r["user_time_s"] + r["system_time_s"]))[
        :top_n
    ]
    labels = [r["node_label"] for r in top]
    user = [r["user_time_s"] for r in top]
    system = [r["system_time_s"] for r in top]

    fig, ax = plt.subplots(figsize=(10, max(4, len(labels) * 0.38)))
    y = np.arange(len(labels))
    ax.barh(y, user, label="User (computation)", color="#5CB85C")
    ax.barh(y, system, left=user, label="System/kernel (communication)", color="#D9534F")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("CPU Time (seconds)")
    ax.set_title("Per-Process CPU Time: Computation vs Communication")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(axis="x", linestyle="--", alpha=0.5)
    plt.tight_layout()
    p = out_dir / "node_user_vs_system_time.png"
    plt.savefig(p, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved {p}")


def plot_node_comm_fraction(nodes, out_dir, top_n):
    top = sorted(nodes, key=lambda r: -r["comm_fraction"])[:top_n]
    labels = [r["node_label"] for r in top]
    vals = [r["comm_fraction"] * 100 for r in top]

    fig, ax = plt.subplots(figsize=(10, max(4, len(labels) * 0.38)))
    y = np.arange(len(labels))
    colors = ["#D9534F" if v > 20 else "#F0AD4E" if v > 10 else "#5CB85C" for v in vals]
    ax.barh(y, vals, color=colors)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Communication Fraction (%)")
    ax.set_title(
        "Per-Process Communication Overhead\n"
        "(system/kernel time as % of total CPU time)"
    )
    ax.grid(axis="x", linestyle="--", alpha=0.5)
    plt.tight_layout()
    p = out_dir / "node_comm_fraction.png"
    plt.savefig(p, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved {p}")


def plot_topic_throughput(topics, out_dir, top_n):
    top = sorted(topics, key=lambda r: -r["bytes_per_sec"])[:top_n]
    labels = [_short_label(r["topic"]) for r in top]
    vals = [r["bytes_per_sec"] for r in top]

    fig, ax = plt.subplots(figsize=(12, max(4, len(labels) * 0.38)))
    y = np.arange(len(labels))
    ax.barh(y, vals, color="#4A90D9")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("Bytes / sec")
    ax.set_title(f"Top {len(labels)} Topics by Throughput (bytes/sec)")
    ax.grid(axis="x", linestyle="--", alpha=0.5)

    for i, v in enumerate(vals):
        ax.text(v + max(vals) * 0.01, i, _fmt(v) + "/s", va="center", fontsize=7)

    plt.tight_layout()
    p = out_dir / "topic_throughput_bytes.png"
    plt.savefig(p, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved {p}")


def plot_topic_msg_rate(topics, out_dir, top_n):
    top = sorted(topics, key=lambda r: -r["msg_per_sec"])[:top_n]
    labels = [_short_label(r["topic"]) for r in top]
    vals = [r["msg_per_sec"] for r in top]

    fig, ax = plt.subplots(figsize=(12, max(4, len(labels) * 0.38)))
    y = np.arange(len(labels))
    ax.barh(y, vals, color="#F0AD4E")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("Messages / sec")
    ax.set_title(f"Top {len(labels)} Topics by Message Rate (msg/sec)")
    ax.grid(axis="x", linestyle="--", alpha=0.5)
    plt.tight_layout()
    p = out_dir / "topic_msg_rate.png"
    plt.savefig(p, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved {p}")


def plot_pipeline_throughput(topics, out_dir):
    cat_bytes = {}
    cat_msgs = {}
    for r in topics:
        cat = categorize_topic(r["topic"])
        cat_bytes[cat] = cat_bytes.get(cat, 0) + r["bytes_per_sec"]
        cat_msgs[cat] = cat_msgs.get(cat, 0) + r["msg_per_sec"]

    cats = sorted(cat_bytes.keys(), key=lambda c: -cat_bytes[c])
    bvals = [cat_bytes[c] for c in cats]
    mvals = [cat_msgs[c] for c in cats]

    palette = {
        "Sensing": "#2196F3",
        "Localization": "#4CAF50",
        "Perception": "#FF9800",
        "Planning": "#9C27B0",
        "Control": "#F44336",
        "System": "#607D8B",
        "Vehicle": "#795548",
        "Map": "#009688",
        "Diagnostics": "#CDDC39",
        "Other": "#9E9E9E",
    }
    colors = [palette.get(c, "#9E9E9E") for c in cats]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    wedges, texts, autotexts = ax1.pie(
        bvals,
        labels=cats,
        autopct="%1.1f%%",
        colors=colors,
        startangle=140,
        textprops={"fontsize": 8},
    )
    ax1.set_title("Throughput by Pipeline Category\n(bytes/sec)")

    y = np.arange(len(cats))
    ax2.barh(y, [b / 1024 for b in bvals], color=colors)
    ax2.set_yticks(y)
    ax2.set_yticklabels(cats, fontsize=9)
    ax2.invert_yaxis()
    ax2.set_xlabel("KB/sec")
    ax2.set_title("Pipeline Category Throughput")
    ax2.grid(axis="x", linestyle="--", alpha=0.5)

    plt.tight_layout()
    p = out_dir / "pipeline_category_throughput.png"
    plt.savefig(p, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved {p}")

    with open(out_dir / "pipeline_category_summary.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category", "bytes_per_sec", "msg_per_sec", "topic_count"])
        cat_count = {}
        for r in topics:
            c = categorize_topic(r["topic"])
            cat_count[c] = cat_count.get(c, 0) + 1
        for c in cats:
            w.writerow([c, round(cat_bytes[c], 2), round(cat_msgs[c], 2), cat_count.get(c, 0)])
    print(f"  Saved {out_dir / 'pipeline_category_summary.csv'}")


def plot_node_energy(nodes, out_dir, top_n):
    has_energy = any(r["total_energy_j"] > 0 for r in nodes)
    if not has_energy:
        return

    top = sorted(nodes, key=lambda r: -r["total_energy_j"])[:top_n]
    labels = [r["node_label"] for r in top]
    comm = [r["est_comm_energy_j"] for r in top]
    comp = [r["est_compute_energy_j"] for r in top]
    gpu = [r["gpu_energy_j"] for r in top]

    fig, ax = plt.subplots(figsize=(10, max(4, len(labels) * 0.38)))
    y = np.arange(len(labels))
    ax.barh(y, comp, label="Computation (CPU user)", color="#5CB85C")
    ax.barh(y, comm, left=comp, label="Communication (CPU kernel)", color="#D9534F")
    ax.barh(
        y,
        gpu,
        left=[c + k for c, k in zip(comp, comm)],
        label="GPU",
        color="#4A90D9",
    )
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Energy (Joules)")
    ax.set_title("Per-Process Energy: Computation vs Communication vs GPU")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(axis="x", linestyle="--", alpha=0.5)
    plt.tight_layout()
    p = out_dir / "node_energy_breakdown.png"
    plt.savefig(p, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved {p}")


def plot_topic_avg_msg_size(topics, out_dir, top_n):
    top = sorted(topics, key=lambda r: -r["avg_bytes_per_msg"])[:top_n]
    labels = [_short_label(r["topic"]) for r in top]
    vals = [r["avg_bytes_per_msg"] for r in top]

    fig, ax = plt.subplots(figsize=(12, max(4, len(labels) * 0.38)))
    y = np.arange(len(labels))
    ax.barh(y, vals, color="#9C27B0")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("Average Bytes per Message")
    ax.set_title(f"Top {len(labels)} Topics by Average Message Size")
    ax.grid(axis="x", linestyle="--", alpha=0.5)

    for i, v in enumerate(vals):
        ax.text(v + max(vals) * 0.01, i, _fmt(v), va="center", fontsize=7)

    plt.tight_layout()
    p = out_dir / "topic_avg_msg_size.png"
    plt.savefig(p, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved {p}")


# ── main ─────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="Plot energy profiler results")
    ap.add_argument(
        "--nodes",
        type=Path,
        default=Path("energy_node_energy.csv"),
        help="Path to node energy CSV",
    )
    ap.add_argument(
        "--topics",
        type=Path,
        default=Path("energy_topic_energy.csv"),
        help="Path to topic energy CSV",
    )
    ap.add_argument(
        "--out", type=Path, default=Path("energy_plots"), help="Output directory"
    )
    ap.add_argument(
        "--top-n", type=int, default=15, help="Number of items in bar charts"
    )
    args = ap.parse_args()

    if not args.nodes.exists():
        print(f"error: {args.nodes} not found", file=sys.stderr)
        sys.exit(1)
    if not args.topics.exists():
        print(f"error: {args.topics} not found", file=sys.stderr)
        sys.exit(1)

    args.out.mkdir(parents=True, exist_ok=True)
    nodes = load_nodes(args.nodes)
    topics = load_topics(args.topics)

    print(f"Loaded {len(nodes)} processes, {len(topics)} topics")
    print(f"Generating plots in {args.out}/\n")

    plot_node_cpu_bar(nodes, args.out, args.top_n)
    plot_node_user_system(nodes, args.out, args.top_n)
    plot_node_comm_fraction(nodes, args.out, args.top_n)
    plot_topic_throughput(topics, args.out, args.top_n)
    plot_topic_msg_rate(topics, args.out, args.top_n)
    plot_topic_avg_msg_size(topics, args.out, args.top_n)
    plot_pipeline_throughput(topics, args.out)
    plot_node_energy(nodes, args.out, args.top_n)

    print("\nDone.")


if __name__ == "__main__":
    main()
