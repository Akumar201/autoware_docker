#!/usr/bin/env python3
"""
Print ROS 2 graph counts: nodes, topics, total publishers, total subscribers.
With --active: report which topics have data transmitting (sample ~3s).
Run with the same DDS env as the rest of the system (e.g. inside the container after sourcing).
"""

import argparse
import importlib
import sys
import time
from collections import defaultdict

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy


def get_message_class(type_str: str):
    """Resolve a type string like 'std_msgs/msg/String' to the Python class."""
    if "/msg/" not in type_str:
        return None
    parts = type_str.split("/")
    if len(parts) != 3:
        return None
    pkg, module, name = parts[0], parts[1], parts[2]
    try:
        mod = importlib.import_module(f"{pkg}.{module}")
        return getattr(mod, name)
    except (ImportError, AttributeError):
        return None


def run_counts(node: Node):
    """Print node/topic/pub/sub counts."""
    node_names = [n for n in node.get_node_names() if n != "autoware_ros_info_node"]
    topic_names_and_types = node.get_topic_names_and_types()

    pub_total = sum(node.count_publishers(t) for t, _ in topic_names_and_types)
    sub_total = sum(node.count_subscribers(t) for t, _ in topic_names_and_types)

    print("Nodes:      ", len(node_names))
    print("Topics:     ", len(topic_names_and_types))
    print("Publishers: ", pub_total)
    print("Subscribers:", sub_total)


def run_active(node: Node, sample_sec: float = 3.0):
    """Subscribe to all topics with publishers, sample for sample_sec, report which have traffic."""
    topic_names_and_types = node.get_topic_names_and_types()
    # Only topics that have at least one publisher can have data
    with_pub = [
        (t, types) for t, types in topic_names_and_types if node.count_publishers(t) > 0
    ]

    msg_count = defaultdict(int)
    subscriptions = []

    for topic_name, type_names in with_pub:
        if not type_names:
            continue
        type_str = type_names[0]
        msg_class = get_message_class(type_str)
        if msg_class is None:
            continue
        try:
            # BEST_EFFORT so we receive from both RELIABLE and BEST_EFFORT publishers (no QoS warnings)
            qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
            sub = node.create_subscription(
                msg_class,
                topic_name,
                lambda msg, t=topic_name: msg_count.__setitem__(t, msg_count[t] + 1),
                qos,
            )
            subscriptions.append(sub)
        except Exception:
            continue

    if not subscriptions:
        print("No subscribable topics with publishers found.")
        return

    print(f"Sampling {len(subscriptions)} topics for {sample_sec}s...")
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


def main():
    parser = argparse.ArgumentParser(description="ROS 2 graph and topic activity info")
    parser.add_argument(
        "--active",
        action="store_true",
        help="Sample topics and list which ones have data transmitting",
    )
    parser.add_argument(
        "--sample-sec",
        type=float,
        default=3.0,
        metavar="SEC",
        help="Seconds to sample for --active (default: 3)",
    )
    args = parser.parse_args()

    rclpy.init()
    node = Node("autoware_ros_info_node")
    node.get_logger().set_level(40)  # ERROR only (suppress QoS incompatibility warnings)

    try:
        run_counts(node)
        if args.active:
            print()
            run_active(node, args.sample_sec)
    except KeyboardInterrupt:
        sys.exit(130)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
