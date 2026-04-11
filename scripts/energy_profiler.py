#!/usr/bin/env python3
"""energy_profiler.py – Per-node and per-topic energy profiler for ROS 2 / Autoware.

Measures:
  1. Per-process CPU & GPU energy  (Intel RAPL + NVIDIA pynvml + psutil)
  2. Per-topic data throughput     (rclpy subscriptions)

Communication vs computation split uses the kernel-time / user-time ratio
from psutil.Process.cpu_times():
  - system (kernel) time  ~  I/O, DDS, serialisation  -> communication proxy
  - user time             ~  algorithms, callbacks     -> computation proxy

Outputs (sorted by energy descending):
  <prefix>_node_energy.csv     per-process energy (comm / compute / GPU)
  <prefix>_topic_energy.csv    per-topic throughput & estimated comm energy

CPU energy requires Intel/AMD RAPL (readable /sys/class/powercap/.../energy_uj).
If RAPL is missing or unreadable, CPU joules stay 0; fix permissions or Docker
sysfs (see docker-compose security_opt / RAPL diagnostics printed by this script).

Usage:
  cd /workspace/scripts
  python3 energy_profiler.py --sample-sec 30 --csv energy
"""

import argparse
import csv
import glob
import os
import re
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

import psutil

try:
    import pynvml

    pynvml.nvmlInit()
    _GPU_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
    _HAS_GPU = True
except Exception:
    _HAS_GPU = False
    _GPU_HANDLE = None

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.serialization import serialize_message


def _rapl_energy_paths():
    """Return package-level RAPL energy_uj paths (avoid core subdomains to prevent double-counting)."""
    paths = []
    for p in sorted(glob.glob("/sys/class/powercap/*/energy_uj")):
        # e.g. intel-rapl:0 (package) vs intel-rapl:0:0 (core) — use package/socket only
        if re.match(r".*/intel-rapl:\d+/energy_uj$", p):
            paths.append(p)
        elif re.match(r".*/amd-rapl:\d+/energy_uj$", p):
            paths.append(p)
    if not paths:
        # Fallback: any energy_uj under powercap (may double-count on some CPUs)
        paths = sorted(glob.glob("/sys/class/powercap/*/energy_uj"))
    return paths


def _read_rapl_j():
    """Sum joules from all readable RAPL package counters (microjoules → joules)."""
    total = 0.0
    any_ok = False
    for path in _rapl_energy_paths():
        try:
            with open(path) as f:
                total += int(f.read().strip()) / 1_000_000.0
                any_ok = True
        except (FileNotFoundError, PermissionError, OSError, ValueError):
            continue
    return total if any_ok else None


def _rapl_diagnostic():
    """Print why RAPL may be unavailable (helps Docker / permission issues)."""
    base = "/sys/class/powercap"
    if not os.path.isdir(base):
        print(
            f"  [energy] RAPL: {base} not found (no Intel/AMD powercap on this host).",
            file=sys.stderr,
        )
        return
    paths = _rapl_energy_paths()[:5] or [f"{base}/intel-rapl:0/energy_uj"]
    for path in paths:
        if not os.path.exists(path):
            print(f"  [energy] RAPL: missing {path}", file=sys.stderr)
            continue
        try:
            with open(path) as f:
                f.read()
            print(f"  [energy] RAPL: OK {path}", file=sys.stderr)
            return
        except PermissionError:
            print(
                f"  [energy] RAPL: Permission denied reading {path} (mode is often 0400 root-only).",
                file=sys.stderr,
            )
            print(
                "  [energy] Fix: run the container as root (not rootless), or on the host:",
                file=sys.stderr,
            )
            print(
                "  [energy]   sudo chmod a+r /sys/class/powercap/intel-rapl:*/energy_uj",
                file=sys.stderr,
            )
            return
        except OSError as e:
            print(f"  [energy] RAPL: {path}: {e}", file=sys.stderr)


def _gpu_watts():
    if not _HAS_GPU:
        return 0.0
    try:
        return pynvml.nvmlDeviceGetPowerUsage(_GPU_HANDLE) / 1000.0
    except Exception:
        return 0.0


def _gpu_proc_mem():
    """Return {pid: gpu_memory_bytes} for processes using the GPU."""
    if not _HAS_GPU:
        return {}
    try:
        procs = pynvml.nvmlDeviceGetComputeRunningProcesses(_GPU_HANDLE)
        return {p.pid: (p.usedGpuMemory or 0) for p in procs}
    except Exception:
        return {}


def _import_msg_class(type_str):
    parts = type_str.replace("/", ".").split(".")
    if len(parts) != 3:
        return None
    try:
        mod = __import__(f"{parts[0]}.{parts[1]}", fromlist=[parts[2]])
        return getattr(mod, parts[2])
    except Exception:
        return None


def _fmt(n):
    for p in ("", "K", "M", "G"):
        if abs(n) < 1024:
            return f"{n:.1f} {p}B"
        n /= 1024
    return f"{n:.1f} TB"


# ── process discovery ────────────────────────────────────────────────────


def discover_ros2_processes():
    """Return {pid: {name, cmdline, label}} for ROS 2 related OS processes."""
    result = {}
    self_pid = os.getpid()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            pid = proc.info["pid"]
            if pid in (self_pid, 0):
                continue
            name = proc.info.get("name") or ""
            cmdline = proc.info.get("cmdline") or []
            cmd = " ".join(cmdline)
            is_ros = (
                "--ros-args" in cmd
                or "component_container" in name
                or "/opt/ros/" in cmd
                or any(
                    k in name.lower()
                    for k in ("rviz", "robot_state", "autoware", "logging_node")
                )
            )
            if not is_ros:
                continue
            label = name
            m = re.search(r"__node:=(\S+)", cmd) or re.search(
                r"__name:=(\S+)", cmd
            )
            if m:
                label = m.group(1)
            result[pid] = {"name": name, "cmdline": cmd[:300], "label": label}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


# ── background process sampler ───────────────────────────────────────────


class _Sampler:
    """Samples per-process CPU% and GPU power in a background thread."""

    def __init__(self, pids, interval):
        self.interval = interval
        self._stop = threading.Event()
        self.cpu_pct = defaultdict(list)
        self.gpu_w = []
        self._h = {}
        self.t0 = {}
        self.t1 = {}
        for pid in pids:
            try:
                p = psutil.Process(pid)
                p.cpu_percent()
                self._h[pid] = p
                self.t0[pid] = p.cpu_times()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def run(self, dur):
        ncpu = psutil.cpu_count() or 1
        end = time.time() + dur
        while time.time() < end and not self._stop.is_set():
            self.gpu_w.append(_gpu_watts())
            for pid, h in list(self._h.items()):
                try:
                    self.cpu_pct[pid].append(h.cpu_percent() / ncpu)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            time.sleep(self.interval)
        for pid, h in self._h.items():
            try:
                self.t1[pid] = h.cpu_times()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def stop(self):
        self._stop.set()

    def avg_pct(self, pid):
        s = self.cpu_pct.get(pid, [])
        return (sum(s) / len(s)) if s else 0.0

    def cpu_seconds(self, pid):
        """Return (user_seconds, system_seconds) delta."""
        s, e = self.t0.get(pid), self.t1.get(pid)
        if not s or not e:
            return 0.0, 0.0
        return max(0, e.user - s.user), max(0, e.system - s.system)

    def avg_gpu(self):
        return (sum(self.gpu_w) / len(self.gpu_w)) if self.gpu_w else 0.0


# ── topic throughput ─────────────────────────────────────────────────────


def measure_topics(ros_node, dur):
    """Subscribe to all active topics, return per-topic {msgs, bytes}."""
    stats = defaultdict(lambda: {"msgs": 0, "bytes": 0})
    subs = []
    qos = QoSProfile(
        reliability=ReliabilityPolicy.BEST_EFFORT,
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
    )
    for topic, types in ros_node.get_topic_names_and_types():
        if ros_node.count_publishers(topic) == 0 or not types:
            continue
        cls = _import_msg_class(types[0])
        if cls is None:
            continue

        def _cb(msg, t=topic):
            try:
                stats[t]["bytes"] += len(serialize_message(msg))
            except Exception:
                pass
            stats[t]["msgs"] += 1

        try:
            subs.append(ros_node.create_subscription(cls, topic, _cb, qos))
        except Exception:
            continue

    ex = MultiThreadedExecutor()
    ex.add_node(ros_node)
    try:
        end = time.time() + dur
        while time.time() < end:
            ex.spin_once(timeout_sec=0.1)
    finally:
        ex.remove_node(ros_node)
        ex.shutdown()
        for s in subs:
            ros_node.destroy_subscription(s)
    return dict(stats)


# ── main ─────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="ROS 2 energy profiler")
    ap.add_argument("--sample-sec", type=float, default=30)
    ap.add_argument("--csv", default="energy", help="output CSV file prefix")
    ap.add_argument(
        "--interval", type=float, default=0.5, help="CPU sampling interval (s)"
    )
    args = ap.parse_args()

    rclpy.init()
    node = Node("energy_profiler")
    node.get_logger().set_level(40)

    procs = discover_ros2_processes()
    if not procs:
        print("No ROS 2 processes found. Is Autoware running?", file=sys.stderr)
        node.destroy_node()
        rclpy.shutdown()
        sys.exit(1)
    print(f"Discovered {len(procs)} ROS 2 processes")

    sampler = _Sampler(list(procs.keys()), args.interval)
    rapl0 = _read_rapl_j()
    if rapl0 is None:
        _rapl_diagnostic()

    th = threading.Thread(target=sampler.run, args=(args.sample_sec,), daemon=True)
    th.start()

    print(f"Sampling {args.sample_sec:.0f}s ...")
    t0 = time.time()
    topic_stats = measure_topics(node, args.sample_sec)
    elapsed = time.time() - t0

    sampler.stop()
    th.join(timeout=5)
    rapl1 = _read_rapl_j()

    has_rapl = rapl0 is not None and rapl1 is not None
    gpu_avg = sampler.avg_gpu()
    gpu_j = gpu_avg * elapsed

    # ── CPU energy (RAPL only) ──
    if has_rapl:
        cpu_j = max(0.0, rapl1 - rapl0)
        energy_method = "RAPL (powercap)"
    else:
        cpu_j = 0.0
        energy_method = "unavailable (RAPL denied / missing / unreadable)"

    # ── per-process energy attribution ──
    total_pct = sum(sampler.avg_pct(p) for p in procs) or 1.0
    gm = _gpu_proc_mem()
    total_gm = sum(gm.values()) or 1

    node_rows = []
    for pid in sorted(procs, key=lambda p: -sampler.avg_pct(p)):
        avg = sampler.avg_pct(pid)
        u, s = sampler.cpu_seconds(pid)
        total_t = u + s or 1.0
        comm_f = s / total_t

        if has_rapl:
            p_cpu = cpu_j * (avg / total_pct)
        else:
            p_cpu = 0.0

        p_gpu = gpu_j * (gm.get(pid, 0) / total_gm) if gm.get(pid, 0) else 0

        node_rows.append(
            {
                "pid": pid,
                "process_name": procs[pid]["name"],
                "node_label": procs[pid]["label"],
                "avg_cpu_pct": round(avg, 2),
                "user_time_s": round(u, 3),
                "system_time_s": round(s, 3),
                "comm_fraction": round(comm_f, 4),
                "cpu_energy_j": round(p_cpu, 4),
                "est_comm_energy_j": round(p_cpu * comm_f, 4),
                "est_compute_energy_j": round(p_cpu * (1 - comm_f), 4),
                "gpu_energy_j": round(p_gpu, 4),
                "total_energy_j": round(p_cpu + p_gpu, 4),
            }
        )

    # ── per-topic communication energy ──
    comm_budget = sum(r["est_comm_energy_j"] for r in node_rows)
    total_bytes = sum(s["bytes"] for s in topic_stats.values()) or 1

    topic_rows = []
    for t in sorted(topic_stats, key=lambda t: -topic_stats[t]["bytes"]):
        s = topic_stats[t]
        if s["msgs"] == 0:
            continue
        bps = s["bytes"] / elapsed
        mps = s["msgs"] / elapsed
        abm = s["bytes"] / s["msgs"]
        tj = comm_budget * (s["bytes"] / total_bytes)
        topic_rows.append(
            {
                "topic": t,
                "msgs": s["msgs"],
                "total_bytes": s["bytes"],
                "msg_per_sec": round(mps, 2),
                "bytes_per_sec": round(bps, 2),
                "avg_bytes_per_msg": round(abm, 1),
                "est_comm_energy_j": round(tj, 6),
            }
        )

    # ── write CSVs ──
    base = Path(args.csv)
    nf = base.parent / f"{base.name}_node_energy.csv"
    tf = base.parent / f"{base.name}_topic_energy.csv"

    if node_rows:
        with open(nf, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(node_rows[0].keys()))
            w.writeheader()
            w.writerows(node_rows)
    else:
        print("Warning: no process data collected", file=sys.stderr)

    if topic_rows:
        with open(tf, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(topic_rows[0].keys()))
            w.writeheader()
            w.writerows(topic_rows)
    else:
        print("Warning: no topic data collected", file=sys.stderr)

    # ── print summary ──
    tc = sum(r["est_comm_energy_j"] for r in node_rows)
    tp = sum(r["est_compute_energy_j"] for r in node_rows)

    print(f"\n{'=' * 70}")
    print(f"  ENERGY PROFILE  ({elapsed:.1f}s, {energy_method})")
    print(f"{'=' * 70}")
    print(f"  CPU energy:            {cpu_j:>10.2f} J")
    print(f"  GPU energy (avg {gpu_avg:.1f}W): {gpu_j:>10.2f} J")
    print(f"  Combined:              {cpu_j + gpu_j:>10.2f} J")
    print(
        f"  Est. communication:    {tc:>10.2f} J"
        f"  ({tc / (cpu_j or 1) * 100:.1f}% of CPU)"
    )
    print(
        f"  Est. computation:      {tp:>10.2f} J"
        f"  ({tp / (cpu_j or 1) * 100:.1f}% of CPU)"
    )
    print(f"  Active topics:         {len(topic_rows)}")
    print(f"  Throughput:            {_fmt(total_bytes / elapsed)}/s")

    print(f"\n  Top 10 processes by energy:")
    for r in node_rows[:10]:
        print(
            f"    {r['node_label']:<35} {r['total_energy_j']:>8.2f} J"
            f"  cpu:{r['avg_cpu_pct']:>5.1f}%"
            f"  comm:{r['comm_fraction'] * 100:>4.1f}%"
        )

    print(f"\n  Top 10 topics by throughput:")
    for r in topic_rows[:10]:
        print(
            f"    {r['topic']:<55} {_fmt(r['bytes_per_sec'])}/s"
            f"  comm:{r['est_comm_energy_j']:.4f} J"
        )

    print(f"\n  Saved: {nf}")
    print(f"  Saved: {tf}")
    print(f"{'=' * 70}")

    node.destroy_node()
    rclpy.shutdown()
    if _HAS_GPU:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
