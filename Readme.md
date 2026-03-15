## Setup Steps

### 0. Clone Autoware

Clone the [Autoware](https://github.com/autowarefoundation/autoware) meta-repository and use it as the workspace root (e.g. `~/autoware`):

```sh
mkdir -p ~/autoware && cd ~/autoware
git clone https://github.com/autowarefoundation/autoware.git autoware
```

Put `docker-env` (and later `autoware_map`, `autoware_data`) in this same folder so the layout is: `~/autoware/autoware/`, `~/autoware/docker-env/`, etc.

### 1. Docker (from workspace root)

```sh
cd ~/autoware/docker-env   # or <workspace_root>/docker-env
docker compose build
docker compose up -d
./start.sh --getin
```

All steps below run **inside the container** (after `./start.sh --getin`).

### 2. Autoware Workspace Setup (inside container)

#### Install build tools

```sh
apt-get update && apt-get install -y \
    python3-colcon-common-extensions \
    python3-vcstool \
    python3-rosdep
```

#### Pull source

```sh
cd /workspace/autoware
mkdir -p src
vcs import src < repositories/autoware.repos
```

#### Install dependencies

```sh
rosdep init 2>/dev/null || true
rosdep update
source /opt/ros/humble/setup.bash
rosdep install -y --from-paths src --ignore-src --rosdistro humble
```

#### Build (30 min to 1+ hour)

```sh
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release
```

If `autoware_lanelet2_extension_python` fails, use:

```sh
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release \
  --packages-skip autoware_lanelet2_extension_python --continue-on-error
```

### 3. Run planning simulator (inside container)

```sh
source /workspace/autoware/install/setup.bash 2>/dev/null

ros2 launch autoware_launch planning_simulator.launch.xml \
  map_path:=/workspace/autoware_map/sample-map-planning \
  vehicle_model:=sample_vehicle \
  sensor_model:=sample_sensor_kit \
  data_path:=/workspace/autoware_data
```

Set initial pose in RViz to finish initialization. A second terminal can use `./start.sh --getin` and run `ros2 topic list` / `ros2 topic echo` (DDS is configured for discovery).

---

### To Install `autoware_data` on Host

#### 1. Install pipx

```sh
sudo apt-get update
sudo apt-get install -y pipx
python3 -m pipx ensurepath
# Then: source ~/.bashrc   # Or open a new terminal
```

#### 2. Install Ansible

```sh
pipx install --include-deps --force "ansible==10.*"
```

#### 3. Install Autoware Ansible Collection & Download Artifacts

```sh
cd ~/autoware/autoware
ansible-galaxy collection install -f -r ansible-galaxy-requirements.yaml
ansible-playbook autoware.dev_env.download_artifacts \
    -e "data_dir=$HOME/autoware/autoware_data" \
    --ask-become-pass
```

#### 4. Download and Unzip Sample Map Files

```sh
# Download the sample map files for Autoware
gdown -O ~/autoware_map/ 'https://docs.google.com/uc?export=download&id=1499_nsbUbIeturZaDj7jhUownh5fvXHd'

# Unzip the map file to the autoware_map directory
unzip -d ~/autoware_map ~/autoware_map/sample-map-planning.zip
```