#!/usr/bin/env bash
# EC2 (Ubuntu 22.04) 최초 셋업 스크립트.
# 사용법: 코드가 서버의 ~/matcause 에 올라와 있고, .env 파일도 그 안에 있다고 가정.
#   ssh -i key.pem ubuntu@<Elastic-IP>
#   cd ~/matcause && chmod +x deploy/ec2_setup.sh && ./deploy/ec2_setup.sh
set -euo pipefail

APP_DIR="$HOME/matcause"
cd "$APP_DIR"

echo "==> apt 업데이트 및 Python 3.11 설치"
sudo apt-get update -y
sudo apt-get install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update -y
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev build-essential

echo "==> 가상환경 생성"
python3.11 -m venv .venv
source .venv/bin/activate

echo "==> 의존성 설치 (dev 도구 제외, 실행에 필요한 것만)"
pip install --upgrade pip
pip install -e ".[all]"

if [ ! -f .env ]; then
  echo "!! .env 파일이 없습니다. GATEWAY_BASE_URL / API_KEY / MP_API_KEY 등을 채운 .env 를 ${APP_DIR}/.env 에 올려주세요."
fi

echo "==> systemd 서비스 등록"
sudo cp deploy/matcause-streamlit.service /etc/systemd/system/matcause-streamlit.service
sudo sed -i "s#__APP_DIR__#${APP_DIR}#g" /etc/systemd/system/matcause-streamlit.service
sudo sed -i "s#__USER__#$(whoami)#g" /etc/systemd/system/matcause-streamlit.service
sudo systemctl daemon-reload
sudo systemctl enable --now matcause-streamlit

echo "==> 완료. 상태 확인: sudo systemctl status matcause-streamlit"
echo "==> 로그 확인:      journalctl -u matcause-streamlit -f"
echo "==> 브라우저에서 http://<이 인스턴스의 Elastic IP>:8501 접속 확인"
