/home/akumar/autoware/AWSIM-Demo/AWSIM-Demo.x86_64


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


  cd /workspace/scripts
python3 autoware_ros_info.py --throughput --sample-sec 30


cd /workspace/scripts
python3 autoware_ros_info.py --csv cam_bw --sample-sec 30 --runs 1


cd /workspace/scripts
python3 plot_ros_data_movement.py \
  --summary report_summary.csv \
  --detail report_throughput_detail.csv \
  --out ./plots


python3 plot_energy.py \
  --nodes energy_node_energy.csv \
  --topics energy_topic_energy.csv \
  --out ./energy_plots


  cd /workspace/autoware
source /opt/ros/humble/setup.bash
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release \
  --packages-skip autoware_lanelet2_extension_python --continue-on-error



python3 energy_profiler.py --sample-sec 90 --interval 0.2 --csv energy_run
