#!/usr/bin/env bash
# Build the Autoware ROS 2 workspace from inside the autoware-custom container.
#
# Usage:
#   ./build_autoware.sh            # incremental: skips already-built packages
#   ./build_autoware.sh --clean    # wipe build/install/log first, then full rebuild
#   ./build_autoware.sh --no-deps  # skip apt/rosdep (use after first successful run)
#   ./build_autoware.sh <pkg>...   # build only the listed packages (+ deps resolved by colcon)
#
# Idempotent. Safe to re-run from any container state: purges apt-installed
# ros-humble-autoware-* packages that would shadow source headers, installs
# libprotobuf-dev + colcon/rosdep if missing, then does the full colcon build.

set -euo pipefail

WORKSPACE="/workspace/autoware"
ROS_DISTRO="humble"

# Packages to skip at colcon level. Leave empty unless there's a known reason.
SKIP_PACKAGES=()

# Extra apt packages required for source builds that aren't in the base image.
# (libprotobuf-dev fixes sync_tooling_msgs; the python3-* ones are needed for
# colcon/rosdep themselves since the base ros:humble-ros-base image omits them.)
EXTRA_APT_PACKAGES=(
  libprotobuf-dev
  protobuf-compiler
  python3-colcon-common-extensions
  python3-rosdep
  python3-vcstool
)

CLEAN=0
INSTALL_DEPS=1
PACKAGES=()

for arg in "$@"; do
  case "$arg" in
    --clean)    CLEAN=1 ;;
    --no-deps)  INSTALL_DEPS=0 ;;
    -h|--help)  sed -n '2,10p' "$0"; exit 0 ;;
    *)          PACKAGES+=("$arg") ;;
  esac
done

cd "$WORKSPACE"

# ROS env (the script runs in its own subshell; /etc/bash.bashrc is not sourced).
# ROS setup.bash references unset vars, so relax `set -u` while sourcing.
set +u
source "/opt/ros/${ROS_DISTRO}/setup.bash"
set -u

if [[ "$CLEAN" -eq 1 ]]; then
  echo "[build_autoware] wiping build/ install/ log/"
  rm -rf build install log
fi

if [[ "$INSTALL_DEPS" -eq 1 ]]; then
  echo "[build_autoware] refreshing apt index"
  apt-get update -qq

  # ── Purge apt-installed ros-humble-autoware-* packages ─────────────────────
  # These ship older autoware headers into /opt/ros/humble/include that shadow
  # the newer source tree under src/, causing mismatched namespaces (e.g.
  # autoware_lanelet2_extension_python: impl::getClosestSegment missing).
  # Idempotent: the subshell returns empty on a clean container.
  AUTOWARE_APT_PKGS=$(dpkg-query -W -f='${Package}\n' 'ros-humble-autoware-*' 2>/dev/null || true)
  if [[ -n "$AUTOWARE_APT_PKGS" ]]; then
    echo "[build_autoware] purging conflicting apt packages:"
    echo "$AUTOWARE_APT_PKGS" | sed 's/^/    /'
    # shellcheck disable=SC2086
    apt-get purge -y $AUTOWARE_APT_PKGS
    apt-get autoremove -y
  else
    echo "[build_autoware] no ros-humble-autoware-* apt packages present (good)"
  fi

  # ── Install any missing non-autoware apt deps ──────────────────────────────
  MISSING_APT=()
  for pkg in "${EXTRA_APT_PACKAGES[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
      MISSING_APT+=("$pkg")
    fi
  done
  if [[ ${#MISSING_APT[@]} -gt 0 ]]; then
    echo "[build_autoware] installing missing apt packages: ${MISSING_APT[*]}"
    apt-get install -y --no-install-recommends "${MISSING_APT[@]}"
  fi

  # ── rosdep for the rest ────────────────────────────────────────────────────
  echo "[build_autoware] running rosdep"
  [[ -f /etc/ros/rosdep/sources.list.d/20-default.list ]] || rosdep init
  rosdep update --rosdistro "$ROS_DISTRO"
  ROSDEP_ARGS=(--from-paths src --ignore-src -r -y --rosdistro "$ROS_DISTRO")
  if [[ ${#SKIP_PACKAGES[@]} -gt 0 ]]; then
    ROSDEP_ARGS+=(--skip-keys "${SKIP_PACKAGES[*]}")
  fi
  rosdep install "${ROSDEP_ARGS[@]}"
fi

# ── colcon build ─────────────────────────────────────────────────────────────
COLCON_ARGS=(
  --symlink-install
  --cmake-args -DCMAKE_BUILD_TYPE=Release
  --parallel-workers "$(nproc)"
  --event-handlers console_cohesion+ summary+
)

if [[ ${#SKIP_PACKAGES[@]} -gt 0 ]]; then
  COLCON_ARGS+=(--packages-skip "${SKIP_PACKAGES[@]}")
fi

if [[ "$CLEAN" -eq 0 && ${#PACKAGES[@]} -eq 0 ]]; then
  # Incremental: don't redo packages that already succeeded
  COLCON_ARGS+=(--packages-skip-build-finished)
fi

if [[ ${#PACKAGES[@]} -gt 0 ]]; then
  COLCON_ARGS+=(--packages-up-to "${PACKAGES[@]}")
fi

echo "[build_autoware] colcon build ${COLCON_ARGS[*]}"
colcon build "${COLCON_ARGS[@]}"

echo
echo "[build_autoware] done. Source the install with:"
echo "  source $WORKSPACE/install/setup.bash"
