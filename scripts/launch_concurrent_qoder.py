#!/usr/bin/env python3
"""Launch concurrent Qoder agents in Orca worktrees:
4 CN (qoder-cn) + 6 International (qoder).
"""
import subprocess
import json
import time
import sys

CONFIGS = [
    # 4 CN Projects
    {
        "id": "07-na-zhou-aidc",
        "type": "cn",
        "bin": "/Users/albert/.qoder-cn/entry/qoder-cn",
        "worktree": "/Users/albert/orca/workspaces/bisai/07-na-zhou-aidc",
        "title": "Qoder-CN 07·钠电AIDC",
        "prompt": "/goal 研读 docs/SUBMISSION.md 与 scripts/demo.sh，运行 uv run --python 3.12 --with-requirements requirements.txt pytest tests/ 验证全部 110 项单测通过，深入检查 PUE 模型与极端尖峰削峰算法并确保 exit code 0"
    },
    {
        "id": "09-watcha-wechat",
        "type": "cn",
        "bin": "/Users/albert/.qoder-cn/entry/qoder-cn",
        "worktree": "/Users/albert/orca/workspaces/bisai/09-watcha-wechat",
        "title": "Qoder-CN 09·观猹小程序",
        "prompt": "/goal 研读 docs/SUBMISSION.md 与 scripts/demo.sh，运行 npm run verify 验证 56 文件静态审计与 41 项单测通过，运行 ./scripts/demo.sh 验证秒开与离线确定性降级"
    },
    {
        "id": "16-zhipu-autoglm",
        "type": "cn",
        "bin": "/Users/albert/.qoder-cn/entry/qoder-cn",
        "worktree": "/Users/albert/orca/workspaces/bisai/16-zhipu-autoglm",
        "title": "Qoder-CN 16·智谱AutoGLM",
        "prompt": "/goal 研读 docs/SUBMISSION.md 与 scripts/demo.sh，运行 uv run --with pytest pytest src/tests/ -q 验证全部 30 项单测，运行 python src/run_demo.py --chaos 验证故障注入自愈闭环"
    },

    # 6 International Projects
    {
        "id": "08-anker-hackathon",
        "type": "intl",
        "bin": "/Users/albert/.qoder/entry/qoder",
        "worktree": "/Users/albert/orca/workspaces/bisai/08-anker-hackathon",
        "title": "Qoder 08·Anker光储",
        "prompt": "/goal Review docs/SUBMISSION.md and scripts/demo.sh, run uv run --with pytest --with pulp --with highspy --with fastapi --with httpx --with pydantic pytest to ensure all 102 tests pass, verify 24h MPC optimization and battery degradation guard"
    },
    {
        "id": "11-genai-open-agent",
        "type": "intl",
        "bin": "/Users/albert/.qoder/entry/qoder",
        "worktree": "/Users/albert/orca/workspaces/bisai/11-genai-open-agent",
        "title": "Qoder 11·OpenAgent",
        "prompt": "/goal Review docs/SUBMISSION.md and scripts/demo.sh, run uv run --with pytest pytest to verify all 66 tests pass, run python examples/demo.py to ensure 4-agent wave execution with blackboard collaboration scores >= 0.85"
    },
    {
        "id": "12-suks-suzhou-ai",
        "type": "intl",
        "bin": "/Users/albert/.qoder/entry/qoder",
        "worktree": "/Users/albert/orca/workspaces/bisai/12-suks-suzhou-ai",
        "title": "Qoder 12·苏客松工业质检",
        "prompt": "/goal Review docs/SUBMISSION.md and scripts/demo.sh, run uv run --python 3.12 --with-requirements src/requirements.txt pytest src/tests to verify 56 tests pass, inspect pure CPU multi-channel defect detection performance"
    },
    {
        "id": "15-minimax-abab-7",
        "type": "intl",
        "bin": "/Users/albert/.qoder/entry/qoder",
        "worktree": "/Users/albert/orca/workspaces/bisai/15-minimax-abab-7",
        "title": "Qoder 15·MiniMax推理剧",
        "prompt": "/goal Review docs/SUBMISSION.md and scripts/demo.sh, cd src && npm test to verify all 116 tests pass, run npm run eval to verify 6-dimension commercial evaluation scores >= 90%"
    },
    {
        "id": "17-dorahacks-anna-mcp",
        "type": "intl",
        "bin": "/Users/albert/.qoder/entry/qoder",
        "worktree": "/Users/albert/orca/workspaces/bisai/17-dorahacks-anna-mcp",
        "title": "Qoder 17·AnnaMCP",
        "prompt": "/goal Review docs/SUBMISSION.md and scripts/demo.sh, run npm run verify (typecheck, lint, test, smoke), ensure 100% MCP 2025-06-18 protocol compliance with 0 dependencies"
    },
    {
        "id": "18-wakeathon-chongqing",
        "type": "intl",
        "bin": "/Users/albert/.qoder/entry/qoder",
        "worktree": "/Users/albert/orca/workspaces/bisai/18-wakeathon-chongqing",
        "title": "Qoder 18·雾客松重庆",
        "prompt": "/goal Review docs/SUBMISSION.md and scripts/demo.sh, cd src && npm run build && npm run eval, verify 24 scenarios 60 FPS evaluation pass with average score >= 81.5"
    }
]

def run_cmd(cmd):
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return res.stdout.strip()

def main():
    print("=" * 70)
    print("并发启动 9 个 Qoder 智能体 (3 CN + 6 国际版，结合已运行的 01·扣子共 10 个)")
    print("=" * 70)

    for item in CONFIGS:
        wt_path = item["worktree"]
        cmd = f'{item["bin"]} --dangerously-skip-permissions'
        print(f"\n[启动] {item['title']} in {wt_path}")
        
        create_cmd = f'orca terminal create --worktree "path:{wt_path}" --title "{item["title"]}" --command "{cmd}" --json'
        out = run_cmd(create_cmd)
        try:
            data = json.loads(out)
            handle = data["result"]["terminal"]["handle"]
            print(f"  ✓ 终端创建成功: {handle}")
        except Exception as e:
            print(f"  ✗ 创建失败: {e}\n  原始输出: {out}")
            continue

        # 等待 TUI 启动就绪
        time.sleep(3.5)

        # 发送目标 Prompt
        send_cmd = f'orca terminal send --terminal "{handle}" --text "{item["prompt"]}" --enter --json'
        send_out = run_cmd(send_cmd)
        try:
            send_data = json.loads(send_out)
            if send_data.get("ok"):
                print(f"  ✓ /goal 任务指令已发送")
            else:
                print(f"  ⚠ 发送提示: {send_out}")
        except Exception as e:
            print(f"  ✗ 发送失败: {e}")

        # 短暂休眠平滑并发负载
        time.sleep(2.0)

    print("\n" + "=" * 70)
    print("全量 10 个 Qoder 智能体并发调度完毕！")
    print("=" * 70)

if __name__ == "__main__":
    main()
