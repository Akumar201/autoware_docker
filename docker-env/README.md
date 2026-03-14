# Autoware Docker env (outside repo)

Custom image aligned with **Autoware prerequisites**:

| Item   | Requirement        |
|--------|--------------------|
| OS     | Ubuntu 22.04       |
| ROS    | ROS 2 Humble (REP-2000) |

- **Location**: `~/autoware/docker-env` (workspace root, not inside the autoware repo).
- **Why**: Full control over base image and DDS; `ros2 topic echo` / `ros2 topic hz` work from `docker exec`.

## Build

**Default (no autoware_data in the image):**

```bash
cd ~/autoware/docker-env
docker compose build
```

**With autoware_data baked into the image** (build from workspace root; needs the `autoware` repo in context; takes longer, image is larger):

```bash
cd ~/autoware
docker build -f docker-env/Dockerfile --target with-artifacts -t autoware-custom:latest .
```

Then use that image in compose or run as usual; artifacts are in `/opt/autoware_data` inside the container.

## Run

```bash
cd ~/autoware/docker-env
export MAP_PATH=$HOME/autoware_map DATA_PATH=$HOME/autoware_data
docker compose run --rm -v "$HOME/autoware_map:/autoware_map:ro" -v "$HOME/autoware_data:/autoware_data:ro" autoware bash
```

Inside the container:

```bash
source /opt/ros/humble/setup.bash
# source /opt/autoware/setup.bash  # if present
ros2 launch ...   # your launch
```

## Test `ros2 topic` from another terminal

```bash
cd ~/autoware/docker-env
CONTAINER_ID=$(docker ps -q --filter name=autoware-custom)
docker exec -it "$CONTAINER_ID" bash -lc 'source /opt/ros/humble/setup.bash && timeout 5 ros2 topic echo /rosout --once'
```

## Download autoware_data (artifacts)

Planning simulator expects model files in `~/autoware_data` (or inside the workspace, e.g. `~/autoware/autoware_data`). Use the Autoware repo’s Ansible playbook:

**1. Install Ansible** (once, on host):

```bash
sudo apt-get purge -y ansible 2>/dev/null || true
sudo apt-get -y install pipx
python3 -m pipx ensurepath
# re-open shell or: source ~/.bashrc
pipx install --include-deps --force "ansible==10.*"
```

**2. Install the collection and run the download playbook** (from the cloned autoware repo):

```bash
cd ~/autoware/autoware
ansible-galaxy collection install -f -r ansible-galaxy-requirements.yaml
ansible-playbook autoware.dev_env.download_artifacts -e "data_dir=$HOME/autoware/autoware_data" --ask-become-pass
```

This creates `~/autoware/autoware_data/` with folders like `lidar_centerpoint`, `tensorrt_yolo`, `traffic_light_classifier`, `yabloc_pose_initializer`, etc. With the whole workspace mounted, they appear at `/workspace/autoware_data/` in the container.

**Alternative:** use the setup script (may run other playbooks too):

```bash
cd ~/autoware/autoware
./setup-dev-env.sh universe -y --download-artifacts --data-dir $HOME/autoware/autoware_data
```

## What’s in the image

- **Ubuntu 22.04** base
- **ROS 2 Humble** (desktop: RViz, etc.)
- **Autoware Core** (`ros-humble-autoware-core`) from the ROS build farm
- **Cyclone DDS** with shared memory disabled so exec’d shells see the same topics

For the full Universe planning simulator you may need the official image or a source build; this image is for a controllable dev/debug environment with working `ros2 topic` tools.
