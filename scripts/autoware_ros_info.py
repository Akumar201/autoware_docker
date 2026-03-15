#!/usr/bin/env python3
"""
Print ROS 2 graph counts: nodes, topics, total publishers, total subscribers.
With --active: subscribe to every topic that has publishers, sample, and report which have traffic.
If any such topic cannot be subscribed to (unknown type, import error, or subscribe failure), the script
raises and prints the list of failed topics and reasons. Run with the same DDS env as the rest of the system.
"""

import argparse
import csv
import importlib
import sys
import time
from collections import defaultdict
from pathlib import Path

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rclpy.serialization import serialize_message


def get_message_class(type_str: str):
    """Resolve a type string like 'std_msgs/msg/String' to (Python class, None) or (None, reason)."""
    if "/msg/" not in type_str:
        return None, f"type not msg (e.g. srv/action): {type_str!r}"
    parts = type_str.split("/")
    if len(parts) != 3:
        return None, f"malformed type: {type_str!r}"
    pkg, module, name = parts[0], parts[1], parts[2]
    try:
        mod = importlib.import_module(f"{pkg}.{module}")
        return getattr(mod, name), None
    except ImportError as e:
        return None, f"import failed: {e}"
    except AttributeError as e:
        return None, f"message class not found: {e}"


def get_counts(node: Node, topic_names_and_types=None):
    """Return dict with nodes, topics, publishers, subscribers, topics_with_pub, topics_no_pub."""
    self_name = node.get_name()
    node_names = [n for n in node.get_node_names() if n != self_name]
    if topic_names_and_types is None:
        topic_names_and_types = node.get_topic_names_and_types()
    pub_total = sum(node.count_publishers(t) for t, _ in topic_names_and_types)
    sub_total = sum(node.count_subscribers(t) for t, _ in topic_names_and_types)
    with_pub = sum(1 for t, _ in topic_names_and_types if node.count_publishers(t) > 0)
    no_pub = len(topic_names_and_types) - with_pub
    return {
        "nodes": len(node_names),
        "topics": len(topic_names_and_types),
        "publishers": pub_total,
        "subscribers": sub_total,
        "topics_with_pub": with_pub,
        "topics_no_pub": no_pub,
    }


def run_counts(node: Node, topic_names_and_types=None):
    """Print node/topic/pub/sub counts. If topic_names_and_types is provided, use it (single snapshot)."""
    c = get_counts(node, topic_names_and_types)
    print("Nodes:      ", c["nodes"])
    print("Topics:     ", c["topics"])
    print("  (with ≥1 publisher:", c["topics_with_pub"], "| no publisher:", c["topics_no_pub"], ")")
    print("Publishers: ", c["publishers"])
    print("Subscribers:", c["subscribers"])


def run_active(node: Node, sample_sec: float = 3.0, topic_names_and_types=None):
    """Subscribe to all topics with publishers, sample for sample_sec, report which have traffic.
    Raises if any topic with publishers could not be subscribed to.
    If topic_names_and_types is provided, use it (single snapshot with run_counts).
    """
    if topic_names_and_types is None:
        topic_names_and_types = node.get_topic_names_and_types()
    with_pub = [
        (t, types) for t, types in topic_names_and_types if node.count_publishers(t) > 0
    ]

    msg_count = defaultdict(int)
    subscriptions = []
    failed = []  # (topic_name, type_str, reason)

    for topic_name, type_names in with_pub:
        if not type_names:
            failed.append((topic_name, "(no type)", "no type names"))
            continue
        type_str = type_names[0]
        msg_class, reason = get_message_class(type_str)
        if msg_class is None:
            failed.append((topic_name, type_str, reason))
            continue
        try:
            qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
            sub = node.create_subscription(
                msg_class,
                topic_name,
                lambda msg, t=topic_name: msg_count.__setitem__(t, msg_count[t] + 1),
                qos,
            )
            subscriptions.append(sub)
        except Exception as e:
            failed.append((topic_name, type_str, f"subscribe failed: {e}"))

    if failed:
        lines = [
            "",
            "Cannot subscribe to the following topics (publishers present but subscribe failed):",
        ]
        for topic, type_str, reason in failed:
            lines.append(f"  {topic}")
            lines.append(f"    type={type_str}  reason: {reason}")
        raise RuntimeError("\n".join(lines))

    if not subscriptions:
        print("No subscribable topics with publishers found.")
        return

    total_topics = len(topic_names_and_types)
    skipped_no_pub = total_topics - len(with_pub)
    print(f"Sampling {len(subscriptions)} topics (all with ≥1 publisher) for {sample_sec}s...")
    if skipped_no_pub > 0:
        print(f"Skipped {skipped_no_pub} topics with no publisher (nothing to receive).")
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        end = time.time() + sample_sec
        while time.time() < end:
            executor.spin_once(timeout_sec=0.1)
    finally:
        executor.shutdown()

    active = [(t, msg_count[t]) for t, _ in with_pub if msg_count.get(t, 0) > 0]
    active.sort(key=lambda x: -x[1])
    inactive_count = len(with_pub) - len(active)

    print()
    print("Topics with data (message count in sample):")
    for topic, count in active:
        print(f"  {count:6}  {topic}")
    print()
    print(f"Active topics:   {len(active)}")
    print(f"Inactive (0 msgs): {inactive_count}")


def _fmt_bytes(b):
    """Human-readable byte size."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(b) < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def run_throughput(
    node: Node,
    sample_sec: float = 5.0,
    topic_names_and_types=None,
    quiet: bool = False,
):
    """Subscribe to all topics with publishers, measure per-topic and total bytes/sec.
    Returns (topic_rows, elapsed, total_msgs, total_bytes) or None if no subscriptions.
    topic_rows: list of (topic_name, msgs, bytes, msg_s, bytes_s).
    """
    if topic_names_and_types is None:
        topic_names_and_types = node.get_topic_names_and_types()
    with_pub = [
        (t, types) for t, types in topic_names_and_types if node.count_publishers(t) > 0
    ]

    stats = defaultdict(lambda: {"msgs": 0, "bytes": 0})
    subscriptions = []
    failed = []

    def _cb(msg, topic_name):
        try:
            raw = serialize_message(msg)
            stats[topic_name]["msgs"] += 1
            stats[topic_name]["bytes"] += len(raw)
        except Exception:
            stats[topic_name]["msgs"] += 1

    for topic_name, type_names in with_pub:
        if not type_names:
            failed.append((topic_name, "(no type)", "no type names"))
            continue
        msg_class, reason = get_message_class(type_names[0])
        if msg_class is None:
            failed.append((topic_name, type_names[0], reason))
            continue
        try:
            qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
            sub = node.create_subscription(
                msg_class,
                topic_name,
                lambda msg, t=topic_name: _cb(msg, t),
                qos,
            )
            subscriptions.append(sub)
        except Exception as e:
            failed.append((topic_name, type_names[0], f"subscribe failed: {e}"))

    if failed and not quiet:
        print(f"\nCould not subscribe to {len(failed)} topic(s):", file=sys.stderr)
        for topic, type_str, reason in failed:
            print(f"  {topic}  type={type_str}  reason: {reason}", file=sys.stderr)
        print()

    if not subscriptions:
        if not quiet:
            print("No subscribable topics with publishers found.")
        return None

    if not quiet:
        print(f"Measuring throughput on {len(subscriptions)} topics for {sample_sec}s...\n")
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        t0 = time.time()
        end = t0 + sample_sec
        while time.time() < end:
            executor.spin_once(timeout_sec=0.1)
        elapsed = time.time() - t0
    finally:
        executor.shutdown()

    rows = []
    total_bytes = 0
    total_msgs = 0
    for topic_name, _ in with_pub:
        s = stats.get(topic_name)
        if not s or s["msgs"] == 0:
            continue
        bps = s["bytes"] / elapsed
        mps = s["msgs"] / elapsed
        rows.append((topic_name, s["msgs"], s["bytes"], mps, bps))
        total_bytes += s["bytes"]
        total_msgs += s["msgs"]

    rows.sort(key=lambda r: -r[4])  # sort by bytes/sec descending

    if not quiet:
        print(f"{'TOPIC':<90} {'msgs':>7} {'msg/s':>8} {'bytes':>12} {'rate':>12}")
        print("-" * 135)
        for topic, msgs, nbytes, mps, bps in rows:
            print(f"{topic:<90} {msgs:>7} {mps:>8.1f} {_fmt_bytes(nbytes):>12} {_fmt_bytes(bps):>10}/s")
        print("-" * 135)
        total_bps = total_bytes / elapsed
        total_mps = total_msgs / elapsed
        print(f"{'TOTAL':<90} {total_msgs:>7} {total_mps:>8.1f} {_fmt_bytes(total_bytes):>12} {_fmt_bytes(total_bps):>10}/s")
        print(f"\nSampled {elapsed:.1f}s | {len(rows)} active topics | {_fmt_bytes(total_bps)}/s aggregate throughput")

    return (rows, elapsed, total_msgs, total_bytes)


def run_analysis_to_csv(
    sample_sec: float,
    num_runs: int,
    csv_prefix: str,
):
    """Run throughput analysis num_runs times (each for sample_sec) and write summary + detail CSVs.
    Uses a fresh node per run so subscriptions do not accumulate and throughput stays consistent.
    """
    summary_rows = []
    all_topic_data = defaultdict(lambda: {"msgs": 0, "bytes": 0, "runs_with_data": 0})
    total_elapsed_all_runs = 0.0

    for run_id in range(1, num_runs + 1):
        if num_runs > 1:
            print(f"Run {run_id}/{num_runs} ({sample_sec}s)...")
        node = Node(f"autoware_ros_info_run_{run_id}")
        node.get_logger().set_level(40)
        try:
            topic_names_and_types = node.get_topic_names_and_types()
            counts = get_counts(node, topic_names_and_types)
            result = run_throughput(node, sample_sec, topic_names_and_types, quiet=True)
        finally:
            node.destroy_node()

        if result is None:
            summary_rows.append({
                "run_id": run_id,
                "nodes": counts["nodes"],
                "topics": counts["topics"],
                "publishers": counts["publishers"],
                "subscribers": counts["subscribers"],
                "elapsed_sec": 0,
                "total_msgs": 0,
                "total_bytes": 0,
                "total_msg_s": 0.0,
                "total_bytes_s": 0.0,
            })
            continue
        rows, elapsed, total_msgs, total_bytes = result
        total_elapsed_all_runs += elapsed
        total_msg_s = total_msgs / elapsed if elapsed > 0 else 0
        total_bytes_s = total_bytes / elapsed if elapsed > 0 else 0
        summary_rows.append({
            "run_id": run_id,
            "nodes": counts["nodes"],
            "topics": counts["topics"],
            "publishers": counts["publishers"],
            "subscribers": counts["subscribers"],
            "elapsed_sec": round(elapsed, 2),
            "total_msgs": total_msgs,
            "total_bytes": total_bytes,
            "total_msg_s": round(total_msg_s, 2),
            "total_bytes_s": round(total_bytes_s, 2),
        })
        for topic_name, msgs, nbytes, _mps, _bps in rows:
            all_topic_data[topic_name]["msgs"] += msgs
            all_topic_data[topic_name]["bytes"] += nbytes
            all_topic_data[topic_name]["runs_with_data"] += 1

    prefix = Path(csv_prefix).resolve()
    summary_path = prefix.parent / f"{prefix.name}_summary.csv"
    detail_path = prefix.parent / f"{prefix.name}_throughput_detail.csv"

    with open(summary_path, "w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "run_id", "nodes", "topics", "publishers", "subscribers",
                "elapsed_sec", "total_msgs", "total_bytes", "total_msg_s", "total_bytes_s",
            ],
        )
        w.writeheader()
        w.writerows(summary_rows)
        if summary_rows:
            avg_elapsed = total_elapsed_all_runs / num_runs
            last = summary_rows[-1]
            w.writerow({
                "run_id": "avg",
                "nodes": round(sum(r["nodes"] for r in summary_rows) / len(summary_rows), 1),
                "topics": round(sum(r["topics"] for r in summary_rows) / len(summary_rows), 1),
                "publishers": round(sum(r["publishers"] for r in summary_rows) / len(summary_rows), 1),
                "subscribers": round(sum(r["subscribers"] for r in summary_rows) / len(summary_rows), 1),
                "elapsed_sec": round(avg_elapsed, 2),
                "total_msgs": round(sum(r["total_msgs"] for r in summary_rows) / len(summary_rows), 0),
                "total_bytes": round(sum(r["total_bytes"] for r in summary_rows) / len(summary_rows), 0),
                "total_msg_s": round(sum(r["total_msg_s"] for r in summary_rows) / len(summary_rows), 2),
                "total_bytes_s": round(sum(r["total_bytes_s"] for r in summary_rows) / len(summary_rows), 2),
            })

    with open(detail_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "topic", "runs_with_data", "total_msgs", "total_bytes", "total_elapsed_sec",
            "avg_msg_s", "avg_bytes_s",
        ])
        total_elapsed_sec = total_elapsed_all_runs  # same for all topics in this run set
        for topic_name in sorted(all_topic_data.keys(), key=lambda t: -all_topic_data[t]["bytes"]):
            d = all_topic_data[topic_name]
            # total_elapsed for this topic: only count runs where we had data (use num_runs * sample_sec as denominator for avg)
            # Actually we ran num_runs times, each ~sample_sec. So total_elapsed = num_runs * avg_elapsed_per_run.
            # We don't have per-run elapsed stored per topic; each run had same elapsed. So total_elapsed_sec = total_elapsed_all_runs.
            elapsed = total_elapsed_all_runs if total_elapsed_all_runs > 0 else 1
            avg_msg_s = d["msgs"] / elapsed
            avg_bytes_s = d["bytes"] / elapsed
            w.writerow([
                topic_name,
                d["runs_with_data"],
                d["msgs"],
                d["bytes"],
                round(total_elapsed_all_runs, 2),
                round(avg_msg_s, 2),
                round(avg_bytes_s, 2),
            ])

    print(f"Wrote {summary_path}")
    print(f"Wrote {detail_path}")


def main():
    parser = argparse.ArgumentParser(description="ROS 2 graph and topic activity info")
    parser.add_argument(
        "--active",
        action="store_true",
        help="Sample topics and list which ones have data transmitting",
    )
    parser.add_argument(
        "--throughput",
        action="store_true",
        help="Measure per-topic and total bytes/sec throughput",
    )
    parser.add_argument(
        "--sample-sec",
        type=float,
        default=5.0,
        metavar="SEC",
        help="Seconds to sample per run for --active / --throughput (default: 5)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        metavar="N",
        help="Number of sampling runs (each of --sample-sec). Used with --csv for averaging (default: 1)",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default="",
        metavar="PREFIX",
        help="Write summary and throughput detail CSVs (PREFIX_summary.csv, PREFIX_throughput_detail.csv). Implies --throughput, runs --runs times.",
    )
    args = parser.parse_args()

    if args.csv and args.runs < 1:
        print("error: --runs must be >= 1 when using --csv", file=sys.stderr)
        sys.exit(1)

    rclpy.init()
    node = Node("autoware_ros_info_node")
    node.get_logger().set_level(40)  # ERROR only (suppress QoS incompatibility warnings)

    try:
        topic_names_and_types = node.get_topic_names_and_types()
        run_counts(node, topic_names_and_types)

        if args.active:
            print()
            run_active(node, args.sample_sec, topic_names_and_types)

        if args.csv:
            print()
            run_analysis_to_csv(args.sample_sec, args.runs, args.csv.strip())
        elif args.throughput:
            print()
            run_throughput(node, args.sample_sec, topic_names_and_types)
    except KeyboardInterrupt:
        sys.exit(130)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
