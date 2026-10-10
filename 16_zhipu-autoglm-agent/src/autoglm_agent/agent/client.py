from __future__ import annotations

"""AutoGLM 智能体接入层：
- 在线：调用智谱开放平台（AutoGLM / GLM-4V-Air）做“看屏→决策”闭环；
- 离线：无 API Key 时抛出 AgentUnavailable，由调用方回落到确定性脚本流程，
  保证演示与打榜环境永远可跑。"""

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..act.actions import Controller
from ..config import Settings
from ..locate.locator import LocateError
from ..locate.spec import ElementSpec
from ..perception.screen import Screen
from .prompts import AGENT_SYSTEM_PROMPT, SCREEN_TEMPLATE


class AgentUnavailable(RuntimeError):
    pass


class GLMClient:
    def __init__(self, settings: Settings):
        self.s = settings

    def chat(self, messages: List[Dict[str, str]], model: Optional[str] = None) -> str:
        if not self.s.api_enabled:
            raise AgentUnavailable("未配置 ZHIPU_API_KEY，无法使用在线 AutoGLM 规划")
        body = json.dumps({
            "model": model or self.s.model,
            "messages": messages,
            "temperature": 0.1,
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.s.base_url.rstrip("/") + "/chat/completions",
            data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.s.api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.s.request_timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            raise AgentUnavailable(f"智谱接口调用失败: {e}") from e
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise AgentUnavailable(f"接口返回结构异常: {payload}") from e


class AutoGLMPlanner:
    def __init__(self, client: GLMClient, vision_model: Optional[str] = None):
        self.client = client
        self.model = vision_model

    def next_action(self, goal: str, screen: Screen, history: List[str]) -> Dict[str, Any]:
        elements = self._render(screen)
        prompt = SCREEN_TEMPLATE.format(goal=goal, history=history[-8:], elements=elements)
        raw = self.client.chat(
            [{"role": "system", "content": AGENT_SYSTEM_PROMPT},
             {"role": "user", "content": prompt}],
            model=self.model,
        )
        return self._parse_action(raw)

    @staticmethod
    def _render(screen: Screen) -> str:
        lines = []
        seen = set()
        for el in screen.elements:
            label = el.label()
            if not label:
                continue
            cx = round(el.bounds.center[0] / max(screen.width, 1), 3)
            cy = round(el.bounds.center[1] / max(screen.height, 1), 3)
            key = (label, cx, cy)
            if key in seen:
                continue
            seen.add(key)
            tag = "input" if el.editable else ("btn" if el.clickable else "txt")
            lines.append(f"[{tag}] {label} @ {cx},{cy}")
        for hit in screen.ocr_hits:
            cx = round(hit.center[0] / max(screen.width, 1), 3)
            cy = round(hit.center[1] / max(screen.height, 1), 3)
            if (hit.text, cx, cy) not in seen:
                lines.append(f"[ocr] {hit.text} @ {cx},{cy}")
        return "\n".join(lines[:60]) or "(空屏)"

    @staticmethod
    def _parse_action(raw: str) -> Dict[str, Any]:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise AgentUnavailable(f"模型未返回 JSON 动作: {raw[:120]}")
        try:
            action = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise AgentUnavailable(f"动作 JSON 解析失败: {e}") from e
        if "type" not in action:
            raise AgentUnavailable("动作缺少 type 字段")
        return action


class AutonomousRunner:
    """把规划器的 JSON 动作翻译成高容错定位/操作，形成端侧闭环。"""

    def __init__(self, controller: Controller, planner: AutoGLMPlanner,
                 settings: Optional[Settings] = None):
        self.ctrl = controller
        self.planner = planner
        self.s = settings or controller.settings

    def run(self, goal: str, max_steps: int = 30) -> Dict[str, Any]:
        history: List[str] = []
        stuck = 0
        last_sig: Optional[str] = None
        for i in range(max_steps):
            screen = self.ctrl.snapshot()
            try:
                action = self.planner.next_action(goal, screen, history)
            except AgentUnavailable:
                raise
            sig = "|".join(screen.all_texts()[:30])
            history.append(f"step{i}:{json.dumps(action, ensure_ascii=False)}")
            atype = action.get("type")
            if atype == "done":
                return {"status": "done", "summary": action.get("summary", ""),
                        "steps": i + 1, "history": history}
            if atype == "fail":
                return {"status": "fail", "reason": action.get("reason", ""),
                        "steps": i + 1, "history": history}
            try:
                self._execute(action, screen)
            except LocateError as e:
                history.append(f"step{i}:定位失败 {e}")
            same = sig == last_sig
            stuck = stuck + 1 if same else 0
            last_sig = sig
            if stuck >= 3:
                self.ctrl.device.back()
                stuck = 0
        return {"status": "timeout", "steps": max_steps, "history": history}

    def _execute(self, action: Dict[str, Any], screen: Screen) -> None:
        atype = action.get("type")
        if atype == "tap":
            text = action.get("text", "")
            spec = ElementSpec(name=f"agent-tap:{text}", texts=[text],
                               patterns=[re.escape(text)])
            cand = self.ctrl.locator.locate(spec, timeout=8)
            self.ctrl.device.tap(*cand.center)
            time.sleep(0.3)
            self.ctrl.popups.handle(self.ctrl.device, self.ctrl.ocr)
        elif atype == "type":
            clue = action.get("text", "")
            spec = ElementSpec(name=f"agent-input:{clue}", texts=[clue],
                               patterns=[re.escape(clue)], editable=True)
            self.ctrl.type_text(spec, action.get("value", ""))
        elif atype == "swipe":
            if action.get("direction", "up") == "down":
                self.ctrl.device.scroll_down(0.6)
            else:
                self.ctrl.device.scroll_up(0.6)
        elif atype == "launch":
            self.ctrl.launch(action.get("app", ""))
        elif atype == "back":
            self.ctrl.back()
        elif atype == "wait":
            time.sleep(min(float(action.get("seconds", 1)), 5.0))


def make_planner(settings: Settings) -> Optional[AutoGLMPlanner]:
    if not settings.api_enabled:
        return None
    return AutoGLMPlanner(GLMClient(settings))
