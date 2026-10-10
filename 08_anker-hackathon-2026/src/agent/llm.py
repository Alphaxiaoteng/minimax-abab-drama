"""OpenAI 兼容 LLM 客户端(DashScope compatible-mode)。

仅用标准库 urllib.request;所有失败显式记录在 last_error,
chat_json 永不抛异常、永不返回 None(失败即 {}),供 planner 回退。"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional


class LLMError(RuntimeError):
    """LLM 传输/协议错误(内部使用;chat_json 会吞掉)。"""


@dataclass
class LLMConfig:
    model: str = "qwen3.8-flash"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key_env: str = "DASHSCOPE_API_KEY"
    timeout: float = 30.0
    temperature: float = 0.3


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.match(text)
    return m.group(1) if m else text


@dataclass
class _RawReply:
    content: str
    finish: str = ""


class LLMClient:
    def __init__(self, cfg: Optional[LLMConfig] = None) -> None:
        self.cfg = cfg or LLMConfig()
        self.last_error: str = ""

    @property
    def available(self) -> bool:
        return bool(os.environ.get(self.cfg.api_key_env, "").strip())

    def _api_key(self) -> str:
        return os.environ.get(self.cfg.api_key_env, "").strip()

    def _post(self, body: Dict[str, object]) -> _RawReply:
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self._api_key(),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300] if hasattr(e, "read") else ""
            msg = "HTTP %s: %s" % (e.code, detail)
            self.last_error = msg
            raise LLMError(msg)
        except (urllib.error.URLError, OSError) as e:
            msg = "网络错误: %s" % (e,)
            self.last_error = msg
            raise LLMError(msg)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            msg = "响应非 JSON: %s" % (e,)
            self.last_error = msg
            raise LLMError(msg)
        try:
            choice = payload["choices"][0]
            content = (choice.get("message") or {}).get("content")
        except (KeyError, IndexError, TypeError) as e:
            msg = "响应缺少 choices/message: %s" % (e,)
            self.last_error = msg
            raise LLMError(msg)
        if content is None:
            self.last_error = "message.content 为空"
            raise LLMError("message.content 为空")
        self.last_error = ""
        return _RawReply(content=str(content), finish=str(choice.get("finish_reason") or ""))

    def chat(self, messages: List[Dict[str, str]], json_mode: bool = False,
             max_tokens: int = 800) -> str:
        if not self.available:
            self.last_error = "环境变量 %s 未设置,LLM 不可用" % self.cfg.api_key_env
            raise LLMError(self.last_error)
        body: Dict[str, object] = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        reply = self._post(body)
        return reply.content

    def chat_json(self, messages: List[Dict[str, str]], max_tokens: int = 800) -> dict:
        """解析失败/网络失败/内容空 → {} 且不抛异常,永不返回 None。"""
        try:
            content = self.chat(messages, json_mode=True, max_tokens=max_tokens)
        except LLMError:
            return {}
        except Exception as e:  # 防御:任何意外都不外泄给调用方
            self.last_error = "chat_json 内部异常: %s" % (e,)
            return {}
        text = _strip_fences(content).strip()
        if not text:
            self.last_error = "模型返回空内容"
            return {}
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            self.last_error = "JSON 解析失败: %s" % (e,)
            return {}
        if not isinstance(obj, dict):
            self.last_error = "JSON 顶层不是对象: %r" % (type(obj),)
            return {}
        return obj

    def smoke_test(self) -> Dict[str, object]:
        """一次真实 1-token 调用,返回 {ok, model, latency_ms, error}。"""
        result: Dict[str, object] = {"ok": False, "model": self.cfg.model,
                                     "latency_ms": None, "error": ""}
        if not self.available:
            result["error"] = "环境变量 %s 未设置" % self.cfg.api_key_env
            return result
        t0 = time.time()
        try:
            self.chat([{"role": "user", "content": "回复:ok"}], max_tokens=1)
            result["ok"] = True
        except LLMError:
            result["error"] = self.last_error or "未知错误"
        except Exception as e:
            result["error"] = "未预期异常: %s" % (e,)
        result["latency_ms"] = round((time.time() - t0) * 1000.0, 1)
        return result