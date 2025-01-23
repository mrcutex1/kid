for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do sudo apt-get remove $pkg; done
# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin git vim curl  -y

docker build -t jmz .
docker container rm jmz --force &
sleep 3
docker run -d --restart=unless-stopped --name jmz jmz

sleep 2
echo "Error 6783976546789098765"
sleep 5 
echo "Kidding BC , Install ho gya BOT Check kro"
echo "================"
echo "useful commands (Example:xx is docker)"
echo "show active dockers= docker container ls"
echo "show logs on xx: docker logs xx -f"
echo "restart docker: docker restart xx"
echo "DELETE: docker container rm xx -ff"
echo "---------------------"
echo "Ab bi nahi chala to telegram ki maa chood do sale ki bsdkwala" 
