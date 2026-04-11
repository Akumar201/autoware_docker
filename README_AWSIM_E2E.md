# AWSIM E2E Setup Guide

This guide explains how to recreate the working AWSIM + Autoware setup in this workspace from scratch.

Use this file when you want the exact reproducible AWSIM flow, including the custom `autoware_launch` and `autoware_universe` branches.

For the general workspace guide, planning simulator flow, and ROS throughput scripts, see [README.md](README.md).

This guide is based on the current official AWSIM quick start demo, but adapted for this repository's Docker workflow instead of the stock `setup-dev-env.sh` flow:

- Official AWSIM quick start: [https://tier4.github.io/AWSIM/GettingStarted/QuickStartDemo/](https://tier4.github.io/AWSIM/GettingStarted/QuickStartDemo/)
- `autoware_launch` fork: `https://github.com/Akumar201/autoware_launch` on branch `fix/awsim-e2e-workarounds`
- `autoware_universe` fork: `https://github.com/Akumar201/autoware_universe` on branch `fix/pointcloud-row-step`

## 1. Before You Start

The official AWSIM quick start assumes a supported Ubuntu + NVIDIA setup and localhost-only DDS settings.

Before starting, verify on the host:

- Ubuntu `22.04`
- NVIDIA GPU available to both the host and the Docker container
- current NVIDIA driver installed
- Vulkan working on the host
- DDS localhost settings applied as described in the official AWSIM quick start

If you change the DDS localhost settings, follow the official guidance and reboot before testing.

## 2. Workspace Layout

Assume this repository is your workspace root. The directory should look like this on the host:

```text
<workspace_root>/
├── README.md
├── README_AWSIM_E2E.md
├── docker-env/
├── scripts/
├── autoware/
├── autoware_data/
├── autoware_map/
├── Shinjuku-Map/
└── AWSIM-Demo/
```

Notes:

- `autoware/` is the main Autoware workspace clone.
- `autoware_data/` is required by Autoware runtime.
- `autoware_map/` is optional and is only used for the sample planning simulator described in [README.md](README.md).
- `Shinjuku-Map/` is required for the AWSIM e2e simulator flow.
- `AWSIM-Demo/` runs on the host, not inside the container.

Because `docker-env/docker-compose.yaml` mounts the workspace root to `/workspace`, the important container paths become:

- `/workspace/autoware`
- `/workspace/autoware_data`
- `/workspace/autoware_map`
- `/workspace/Shinjuku-Map`
- `/workspace/docker-env`

## 3. Clone The Main Autoware Workspace

From the host:

```bash
cd <workspace_root>
git clone https://github.com/autowarefoundation/autoware.git autoware
```

The official quick start uses the `main` branch, and that is what this guide assumes as the base workspace.

## 4. Start Docker

From the host:

```bash
cd <workspace_root>/docker-env
./start.sh --build
./start.sh --up
./start.sh --getin
```

All remaining build commands below run inside the container.

## 5. Import Autoware Source Repositories

Inside the container:

```bash
cd /workspace/autoware
mkdir -p src
vcs import src < repositories/autoware.repos
```

## 6. Switch To The Custom Fork Branches

Still inside the container:

### `autoware_launch`

```bash
cd /workspace/autoware/src/launcher/autoware_launch
git remote add akumar https://github.com/Akumar201/autoware_launch.git 2>/dev/null || \
  git remote set-url akumar https://github.com/Akumar201/autoware_launch.git
git fetch akumar
git checkout fix/awsim-e2e-workarounds
```

### `autoware_universe`

```bash
cd /workspace/autoware/src/universe/autoware_universe
git remote add akumar https://github.com/Akumar201/autoware_universe.git 2>/dev/null || \
  git remote set-url akumar https://github.com/Akumar201/autoware_universe.git
git fetch akumar
git checkout fix/pointcloud-row-step
```

These two branches contain the fixes/workarounds needed for this workspace:

- `autoware_launch`
  - lazy lookup of CUDA-only ground segmentation launch resources
  - top-level `use_traffic_light_recognition` launch argument
  - `ignore_traffic_lights_preset.yaml`
- `autoware_universe`
  - fix for `PointCloud2.row_step` in `ring_outlier_filter_node.cpp`

## 7. Install Dependencies And Build Autoware

Inside the container:

```bash
apt-get update && apt-get install -y \
  python3-colcon-common-extensions \
  python3-vcstool \
  python3-rosdep
```

```bash
rosdep init 2>/dev/null || true
rosdep update
source /opt/ros/humble/setup.bash
rosdep install -y --from-paths /workspace/autoware/src --ignore-src --rosdistro humble
```

```bash
cd /workspace/autoware
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release
```

If `autoware_lanelet2_extension_python` fails, use:

```bash
cd /workspace/autoware
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release \
  --packages-skip autoware_lanelet2_extension_python --continue-on-error
```

## 8. Install `autoware_data`

Run this on the host, not inside the container.

```bash
sudo apt-get update
sudo apt-get install -y pipx
python3 -m pipx ensurepath
```

Open a new shell or run `source ~/.bashrc`, then:

```bash
pipx install --include-deps --force "ansible==10.*"
```

```bash
cd <workspace_root>/autoware
ansible-galaxy collection install -f -r ansible-galaxy-requirements.yaml
ansible-playbook autoware.dev_env.download_artifacts \
  -e "data_dir=<workspace_root>/autoware_data" \
  --ask-become-pass
```

Inside the container, this directory appears as `/workspace/autoware_data`.

## 9. Download Maps And AWSIM Demo

### Optional: sample planning map

This is not required for AWSIM, but it is useful for `planning_simulator.launch.xml`. For that flow, see [README.md](README.md).

```bash
mkdir -p <workspace_root>/autoware_map
gdown -O <workspace_root>/autoware_map/sample-map-planning.zip \
  'https://docs.google.com/uc?export=download&id=1499_nsbUbIeturZaDj7jhUownh5fvXHd'
unzip -d <workspace_root>/autoware_map <workspace_root>/autoware_map/sample-map-planning.zip
```

### Required: Shinjuku map for AWSIM e2e

Download `Shinjuku-Map.zip` from the official AWSIM quick start page and extract it so the host path becomes:

```text
<workspace_root>/Shinjuku-Map/map/
```

That is why the Autoware launch command uses `/workspace/Shinjuku-Map/map` inside the container.

### Required: AWSIM Demo

Download `AWSIM-Demo.zip` from the official AWSIM quick start page and extract it on the host. One reasonable location is:

```text
<workspace_root>/AWSIM-Demo/
```

Make the binary executable on the host if needed:

```bash
chmod +x <workspace_root>/AWSIM-Demo/AWSIM-Demo.x86_64
```

If the full demo is too heavy, the official docs also mention `AWSIM-Demo-LightWeight` as an alternative.

## 10. Optional Host Checks

If you need to verify GPU and graphics support inside the container:

```bash
apt update
apt install -y libvulkan1 vulkan-tools mesa-utils
nvidia-smi
vulkaninfo --summary
glxinfo -B
```

## 11. Run AWSIM And Autoware

The working order is:

1. start AWSIM on the host
2. start Autoware inside the container

### Start AWSIM on the host

```bash
<workspace_root>/AWSIM-Demo/AWSIM-Demo.x86_64
```

### Start Autoware in the container

```bash
cd /workspace/autoware
source install/setup.bash

ros2 launch autoware_launch e2e_simulator.launch.xml \
  vehicle_model:=sample_vehicle \
  sensor_model:=awsim_sensor_kit \
  map_path:=/workspace/Shinjuku-Map/map \
  data_path:=/workspace/autoware_data \
  use_obstacle_segmentation_time_series_filter:=false \
  occupancy_grid_map_method:=laserscan_based \
  planning_module_preset:=ignore_traffic_lights \
  use_traffic_light_recognition:=false
```

Why these overrides are needed in this workspace:

- `use_obstacle_segmentation_time_series_filter:=false`
  - avoids the blocked time-series filter path
- `occupancy_grid_map_method:=laserscan_based`
  - uses the occupancy-grid implementation available in this non-CUDA build
- `planning_module_preset:=ignore_traffic_lights`
  - disables planning traffic-light modules
- `use_traffic_light_recognition:=false`
  - avoids the broken traffic-light recognition pipeline in the current build

## 12. Start Driving

After both AWSIM and Autoware are running:

1. wait for localization to settle
2. set the initial pose in RViz if needed
3. set a goal pose
4. wait for the route and trajectory to be generated
5. engage only when the vehicle is stationary

## Notes

- Do not rely on files under `install/`, `build/`, or `log/`. Rebuild the workspace instead.
- `autoware_map/` is optional. `Shinjuku-Map/` is the required map for the AWSIM e2e run.
- The current AWSIM workaround command is specific to this non-CUDA workspace state.
- If you later build a complete CUDA/TensorRT-capable workspace, you should retest whether the stock `e2e_simulator.launch.xml` command works without the current overrides.

