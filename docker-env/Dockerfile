# Autoware dev environment — ROS 2 Humble (Ubuntu 22.04 Jammy).
# Same DDS env for all processes so ros2 topic echo/hz work from docker exec.

FROM ros:humble-ros-base-jammy

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# Desktop (RViz etc.), Cyclone DDS RMW, Autoware Core, and gdown (official ros image has no desktop tag)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-humble-desktop \
    ros-humble-rmw-cyclonedds-cpp \
    ros-humble-cyclonedds \
    ros-humble-autoware-core \
    python3-pip unzip \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir gdown

# DDS/ROS env — same for all processes so exec sees topics
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ENV ROS_DOMAIN_ID=0
ENV CYCLONEDDS_URI='<CycloneDDS><Domain><SharedMemory><Enable>false</Enable></SharedMemory></Domain></CycloneDDS>'

# Source ROS 2 (and Autoware if present) in every shell
RUN echo 'source /opt/ros/humble/setup.bash' >> /etc/bash.bashrc \
    && echo '[ -f /opt/autoware/setup.bash ] && source /opt/autoware/setup.bash || true' >> /etc/bash.bashrc

WORKDIR /workspace

CMD ["bash"]
