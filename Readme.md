## Setup Steps
#### To indatll autoware__data on host
1. **Install pipx**
```sh
sudo apt-get update
sudo apt-get install -y pipx
python3 -m pipx ensurepath
# Run: source ~/.bashrc  (or open a new terminal)
```

2. **Install Ansible**
```sh
pipx install --include-deps --force "ansible==10.*"
```

3. **Install Autoware Ansible collection and download artifacts**
```sh
cd ~/autoware/autoware
ansible-galaxy collection install -f -r ansible-galaxy-requirements.yaml
ansible-playbook autoware.dev_env.download_artifacts \
  -e "data_dir=$HOME/autoware/autoware_data" \
  --ask-become-pass
```


```sh
# Download the sample map files for Autoware
gdown -O ~/autoware_map/ 'https://docs.google.com/uc?export=download&id=1499_nsbUbIeturZaDj7jhUownh5fvXHd'

# Unzip the map file to the autoware_map directory
unzip -d ~/autoware_map ~/autoware_map/sample-map-planning.zip
```