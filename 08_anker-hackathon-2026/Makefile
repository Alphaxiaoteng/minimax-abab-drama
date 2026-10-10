.PHONY: help install run demo test sim clean docker

PY := python3
export PYTHONPATH := src

help:
	@echo "make install  安装依赖"
	@echo "make run      启动 Web 控制台  http://127.0.0.1:8000"
	@echo "make demo     终端一页纸 24h 调度演示 (无需浏览器)"
	@echo "make test     运行全部单元测试"
	@echo "make sim      24h 闭环 MPC 仿真 + 套利收益报告"
	@echo "make docker   构建镜像"

install:
	$(PY) -m pip install -r requirements.txt

run:
	$(PY) -m serving.app

demo:
	$(PY) scripts/demo_cli.py

test:
	$(PY) -m pytest src/tests -q

sim:
	$(PY) scripts/simulate.py

docker:
	docker build -t anker-energy-butler:latest .

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .state
