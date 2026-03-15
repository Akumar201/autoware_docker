#!/usr/bin/env bash
set -euo pipefail

# =======================
# Paths (script lives in docker-env)
# =======================
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yaml"
SERVICE="autoware"
CONTAINER="autoware-custom"
IMAGE="autoware-custom:latest"
COMPOSE=(docker compose -f "$COMPOSE_FILE")

usage() {
  cat <<EOF
Usage: $(basename "$0") --<command>

Commands:
  --build         Build image (uses cache)
  --rebuild       Rebuild image (no cache)
  --up            Start service in background (runs xhost if available)
  --down          Stop and remove the stack
  --restart       Restart the service
  --getin         Exec interactive shell (ROS 2 + Autoware sourced)
  --logs          Tail logs
  --status        Show container state and GPU (if available)
  --clean         down + remove built image and dangling data
  --help          Show this help

Examples:
  $(basename "$0") --build
  $(basename "$0") --up
  $(basename "$0") --getin
  $(basename "$0") --down
EOF
}

require_compose() { [[ -f "$COMPOSE_FILE" ]] || { echo "[start.sh] not found: $COMPOSE_FILE"; exit 1; }; }
need_running() {
  if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "[start.sh] '$CONTAINER' is not running. Start it with: $0 --up"
    exit 1
  fi
}
xhost_allow() { command -v xhost >/dev/null && xhost +local:root >/dev/null 2>&1 || true; }

[[ $# -eq 0 ]] && { usage; exit 1; }
require_compose

case "$1" in
  --build)   "${COMPOSE[@]}" build ;;
  --rebuild) "${COMPOSE[@]}" build --no-cache ;;
  --up)      xhost_allow; "${COMPOSE[@]}" up -d "$SERVICE" ;;
  --restart) "${COMPOSE[@]}" restart "$SERVICE" ;;
  --down)    "${COMPOSE[@]}" down ;;
  --getin)
    need_running
    # Pass DDS env explicitly so exec shell sees same topics as main container process
    docker exec -it "$CONTAINER" env \
      ROS_DOMAIN_ID=0 \
      RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
      CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface address="127.0.0.1"/></Interfaces><AllowMulticast>false</AllowMulticast></General><SharedMemory><Enable>false</Enable></SharedMemory><Discovery><ParticipantIndex>auto</ParticipantIndex><MaxAutoParticipantIndex>120</MaxAutoParticipantIndex></Discovery></Domain></CycloneDDS>' \
      bash -lc '
      source /opt/ros/humble/setup.bash
      [ -f /opt/autoware/setup.bash ] && source /opt/autoware/setup.bash
      # Suppress "not found" for optional/skipped packages (CUDA, TensorRT, etc.)
      [ -f /workspace/autoware/install/setup.bash ] && source /workspace/autoware/install/setup.bash 2>/dev/null || true
      exec bash -i
    '
    ;;
  --logs)    "${COMPOSE[@]}" logs -f "$SERVICE" ;;
  --status)
    echo "== container =="
    docker ps --filter "name=$CONTAINER" --format 'table {{.Names}}\t{{.Status}}' || true
    echo
    echo "== GPU in container =="
    if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
      docker exec "$CONTAINER" nvidia-smi 2>/dev/null || echo "nvidia-smi unavailable (or no GPU)."
    else
      echo "container not running."
    fi
    ;;
  --clean)
    echo "[start.sh] bringing stack down…"; "${COMPOSE[@]}" down --remove-orphans --volumes 2>/dev/null || true
    echo "[start.sh] removing image $IMAGE (if present)…"; docker rmi "$IMAGE" 2>/dev/null || true
    echo "[start.sh] pruning dangling images…"; docker image prune -f >/dev/null || true
    echo "[start.sh] pruning dangling volumes…"; docker volume prune -f >/dev/null 2>&1 || true
    echo "[start.sh] clean complete."
    ;;
  --help|-h) usage ;;
  *) echo "unknown command: $1"; usage; exit 1 ;;
esac
