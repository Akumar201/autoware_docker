# Autoware dev environment — ROS 2 Humble (Ubuntu 22.04 Jammy).
# Same DDS env for all processes so ros2 topic echo/hz work from docker exec.

FROM ros:humble-ros-base-jammy

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# Desktop (RViz etc.), Cyclone DDS RMW, and gdown (official ros image has no desktop tag).
#
# NOTE: we intentionally do NOT install ros-humble-autoware-core here. That package
# pulls ~14 ros-humble-autoware-* libraries into /opt/ros/humble/include, which
# shadow the (newer) source tree under /workspace/autoware/src and cause header /
# namespace mismatches — e.g. autoware_lanelet2_extension_python failing because
# impl::getClosestSegment is in the source header but not the apt one.
# Build everything from source; rosdep pulls the remaining non-autoware deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-humble-desktop \
    ros-humble-rmw-cyclonedds-cpp \
    ros-humble-cyclonedds \
    ros-humble-topic-tools \
    ros-humble-behaviortree-cpp-v3 \
    ros-humble-grid-map-msgs \
    ros-humble-grid-map-ros \
    ros-humble-xacro \
    libgflags-dev \
    libprotobuf-dev protobuf-compiler \
    python3-pip python3-colcon-common-extensions python3-rosdep python3-vcstool \
    unzip \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir gdown

# DDS/ROS env — same for all processes so exec sees topics
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ENV ROS_DOMAIN_ID=0
ENV CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface address="127.0.0.1"/></Interfaces><AllowMulticast>false</AllowMulticast></General><SharedMemory><Enable>false</Enable></SharedMemory><Discovery><ParticipantIndex>auto</ParticipantIndex><MaxAutoParticipantIndex>120</MaxAutoParticipantIndex></Discovery></Domain></CycloneDDS>'

# Source ROS 2 and the Autoware workspace (if built) in every shell.
# The install tree is created by /workspace/autoware/build_autoware.sh; the
# guard makes this a no-op until the first successful build.
RUN echo 'source /opt/ros/humble/setup.bash' >> /etc/bash.bashrc \
    && echo '[ -f /workspace/autoware/install/setup.bash ] && source /workspace/autoware/install/setup.bash || true' >> /etc/bash.bashrc

WORKDIR /workspace

CMD ["bash"]
