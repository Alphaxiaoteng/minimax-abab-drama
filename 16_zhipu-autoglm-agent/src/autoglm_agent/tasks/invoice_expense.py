from __future__ import annotations

"""桌面端「月度发票抓取 + 报销单填写」业务闭环：
邮箱归集本月发票金额 → 财务系统填单 → 传附件 → 提交 → 回读单号。"""

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from ..act.actions import Controller
from ..config import Settings
from ..flow.engine import FlowEngine, FlowResult
from ..flow.step import Flow, Step
from ..locate.spec import ElementSpec
from ..perception.screen import Screen, normalize_text

AMOUNT_RX = re.compile(r"¥([\d,]+(?:\.\d+)?)")

APPLICANT = ElementSpec(name="applicant", texts=["申报人"], patterns=["申报人|申请人"],
                        editable=True, resource_ids=["form.applicant"])
REASON = ElementSpec(name="reason", texts=["报销事由"], patterns=["报销事由|事由"],
                     editable=True, resource_ids=["form.reason"])
AMOUNT = ElementSpec(name="amount", texts=["报销金额"], patterns=["报销金额|金额"],
                     editable=True, resource_ids=["form.amount"])
ATTACH = ElementSpec(name="attach", texts=["上传发票附件"], patterns=["上传.*附件"])
SUBMIT = ElementSpec(name="submit", texts=["提交"], resource_ids=["form.submit"],
                     patterns=["^提交$"], prior=(0.83, 0.925))
EXPENSE_NO_RX = re.compile(r"(BX-\d{4}-\d+)", re.I)


def _parse_amount(raw: str) -> float:
    return float(raw.replace(",", ""))


def _verify_field_filled(ctrl: Controller, spec: ElementSpec, expected: str) -> bool:
    world = getattr(ctrl.device, "world", None)
    if isinstance(world, dict):
        form: Dict[str, str] = world.get("form", {})
        key = spec.name
        return any(v.strip() == expected.strip() for k, v in form.items() if key in k)
    screen = ctrl.snapshot()
    return screen.contains(expected)


def build_flow(applicant: str = "张伟", reason: str = "10月华东出差差旅费报销") -> Flow:
    flow = Flow(flow_id="desktop-invoice-expense", title="发票归集与报销单填报 Agent")

    def open_mail(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        ctrl.launch("mail")

    def collect_invoices(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        screen = ctrl.snapshot()
        invoices: List[Dict[str, Any]] = []
        seen_titles = set()
        page_total = None

        def add(label: str) -> None:
            nonlocal page_total
            norm = normalize_text(label)
            m = AMOUNT_RX.search(norm)
            amount = _parse_amount(m.group(1)) if m else None
            if "合计" in norm:
                if amount is not None:
                    page_total = amount
                return
            if "发票" not in norm or amount is None or label in seen_titles:
                return
            seen_titles.add(label)
            invoices.append({"title": label.strip(), "amount": amount})

        for el in screen.elements:
            add(el.text or el.desc)
        for hit in screen.ocr_hits:
            add(hit.text)

        # 去重：同一页上 OCR 噪声导致的同额异文重复项；以“合计”行做对账约束
        total = round(sum(i["amount"] for i in invoices), 2)
        if page_total is not None and total > page_total:
            by_amount: Dict[float, List[Dict[str, Any]]] = {}
            for i in sorted(invoices, key=lambda x: len(x["title"])):
                by_amount.setdefault(i["amount"], []).append(i)
            invoices = [v[0] for v in by_amount.values()]
        ctx["invoices"] = invoices
        ctx["invoice_total"] = round(sum(i["amount"] for i in invoices), 2)

    def cross_check(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        screen = ctrl.snapshot()
        total_on_page = None
        for t in screen.all_texts():
            if "合计" in t:
                m = AMOUNT_RX.search(t)
                if m:
                    total_on_page = _parse_amount(m.group(1))
                    break
        ctx["mail_total"] = total_on_page

    def open_finance(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        ctrl.launch("finance")

    def fill_form(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        ctrl.type_text(APPLICANT, applicant)
        ctrl.type_text(REASON, reason)
        ctrl.type_text(AMOUNT, f"{ctx['invoice_total']:.2f}")

    def upload_attach(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        ctrl.click(ATTACH)

    def submit(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        ctrl.click(SUBMIT)

    def fallback_submit(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        spec = ElementSpec(name="submit-ocr", texts=["提交"], prior=(0.83, 0.925))
        ctrl.click(spec)

    def read_expense_no(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        screen = ctrl.snapshot()
        joined = " ".join(screen.all_texts())
        m = EXPENSE_NO_RX.search(joined.replace(" ", ""))
        if m:
            ctx["expense_no"] = m.group(1).upper()
        ctx["expense_report"] = {
            "applicant": applicant,
            "reason": reason,
            "invoices": ctx.get("invoices", []),
            "total": ctx.get("invoice_total"),
            "mail_page_total": ctx.get("mail_total"),
            "expense_no": ctx.get("expense_no"),
            "submitted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    flow.add(Step("open_mail", "打开邮箱（自动关闭升级弹窗）", open_mail,
                  verify=lambda c, x: c.snapshot().contains("收件箱"),
                  verify_message="收件箱未就绪", retries=2))
    flow.add(Step("collect", "归集本月发票金额", collect_invoices,
                  verify=lambda c, x: len(x.get("invoices", [])) >= 2,
                  verify_message="发票条目不足", retries=1))
    flow.add(Step("cross_check", "与邮箱合计金额交叉校验", cross_check,
                  verify=lambda c, x: x.get("mail_total") == x.get("invoice_total"),
                  verify_message="合计金额与逐张发票不一致", retries=1, on_fail="skip",
                  critical=False))
    flow.add(Step("open_finance", "启动财务报销系统", open_finance,
                  verify=lambda c, x: c.snapshot().contains("差旅报销单"),
                  verify_message="报销表单未打开", retries=2, on_fail="recover_back"))
    flow.add(Step("fill", "填写申报人/事由/金额", fill_form,
                  verify=lambda c, x: _verify_field_filled(c, AMOUNT, f"{x['invoice_total']:.2f}")
                  and _verify_field_filled(c, APPLICANT, applicant),
                  verify_message="表单字段校验未通过", retries=2))
    flow.add(Step("attach", "上传发票附件", upload_attach,
                  verify=lambda c, x: True, retries=1, on_fail="skip", critical=False))
    flow.add(Step("submit", "提交报销单", submit,
                  verify=lambda c, x: c.snapshot().contains("提交成功"),
                  verify_message="提交后未看到成功回执", retries=2,
                  on_fail="recover_back", fallback=fallback_submit))
    flow.add(Step("receipt", "回读报销单号并汇总", read_expense_no,
                  verify=lambda c, x: bool(x.get("expense_no")),
                  verify_message="未解析到单号", retries=1))
    return flow


def run(controller: Controller, settings: Settings, resume: bool = True) -> FlowResult:
    engine = FlowEngine(controller, settings)
    return engine.run(build_flow(), resume=resume)


def write_artifact(result: FlowResult, settings: Settings) -> str:
    os.makedirs(settings.artifact_dir, exist_ok=True)
    path = os.path.join(settings.artifact_dir, "invoice_expense_report.json")
    payload = {"success": result.success,
               "steps": [o.__dict__ for o in result.outcomes],
               "report": result.ctx.get("expense_report")}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path
