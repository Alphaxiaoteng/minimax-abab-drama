from __future__ import annotations

"""演示场景：模拟 3 个购物/领券 App 与 邮箱/财务报销系统，
内置广告弹窗、权限弹窗、OCR 噪声、折叠区元素，用于验证容错链路。"""

from ..device.virtual import Effect, Scenario, ScreenDef, VElem


def _btn(key, x, y, w, h, text="", rid="", desc="", on_tap=None, noisy=False, cls="Button"):
    return VElem(key=key, x=x, y=y, w=w, h=h, text=text, rid=rid, desc=desc,
                 on_tap=on_tap, noisy=noisy, cls=cls)


def _input(key, x, y, w, h, placeholder="", rid=""):
    return VElem(key=key, x=x, y=y, w=w, h=h, text=placeholder, rid=rid,
                 editable=True, clickable=True, cls="EditText")


def mobile_price_coupon_scenario() -> Scenario:
    ad_popup = ScreenDef(modal=True, elements=[
        _btn("ad_title", 0.1, 0.3, 0.8, 0.06, text="限时大促 全场五折"),
        _btn("ad_desc", 0.1, 0.38, 0.8, 0.05, text="推广位：爆款好物等你来"),
        _btn("ad_skip", 0.82, 0.24, 0.12, 0.045, text="跳过3",
             on_tap=Effect(close_modal=True)),
    ])
    perm_popup = ScreenDef(modal=True, elements=[
        _btn("perm_title", 0.1, 0.35, 0.8, 0.06, text="比邻红包想要访问您的剪贴板"),
        _btn("perm_deny", 0.18, 0.5, 0.25, 0.05, text="拒绝",
             on_tap=Effect(close_modal=True)),
        _btn("perm_allow", 0.58, 0.5, 0.25, 0.05, text="允许",
             on_tap=Effect(close_modal=True, record="clipboard_allowed")),
    ])

    def search_screen(app: str, results: str):
        return ScreenDef(elements=[
            _btn(f"{app}_tab_home", 0.05, 0.02, 0.2, 0.05, text="首页"),
            _input(f"{app}_search_input", 0.28, 0.02, 0.5, 0.05,
                   placeholder="搜索商品", rid=f"com.{app}.id/search_box"),
            _btn(f"{app}_search_go", 0.8, 0.02, 0.16, 0.05, text="搜索",
                 on_tap=Effect(goto=results)),
        ])

    results_a = ScreenDef(content_height=1.7, elements=[
        _btn("a_card1", 0.05, 0.12, 0.9, 0.18, text="聚海严选 无线蓝牙耳机 到手价¥249.00", noisy=True),
        _btn("a_card2", 0.05, 0.62, 0.9, 0.18, text="聚海严选 无线蓝牙耳机Pro 到手价¥219.00"),
        _btn("a_card3", 0.05, 1.15, 0.9, 0.18, text="聚海严选 蓝牙耳机降噪款 到手价¥199.00"),
    ])
    results_b = ScreenDef(elements=[
        _btn("b_card1", 0.05, 0.12, 0.9, 0.18, text="淘享岛 无线蓝牙耳机 券后价¥229.00", noisy=True),
    ])
    coupon_home = ScreenDef(elements=[
        _btn("c_logo", 0.3, 0.02, 0.4, 0.06, text="比邻红包中心"),
        _btn("c_item", 0.08, 0.14, 0.84, 0.12, text="耳机品类 20 元无门槛券",
             desc="满100可用"),
        _btn("c_claim", 0.62, 0.2, 0.28, 0.05, text="立即领取",
             on_tap=Effect(goto="c_after_claim")),
    ])
    coupon_after = ScreenDef(elements=[
        _btn("c_done", 0.1, 0.1, 0.8, 0.06, text="券已领取 放入卡包"),
        _btn("c_final", 0.1, 0.2, 0.8, 0.08, text="耳机券后价¥179.00", noisy=True),
        _btn("c_use", 0.62, 0.32, 0.28, 0.05, text="去使用"),
    ])

    return Scenario(
        screens={
            "home": ScreenDef(elements=[_btn("hint", 0.2, 0.4, 0.6, 0.05, text="请从入口启动应用")]),
            "a_search": search_screen("a", "a_results"),
            "a_results": results_a,
            "b_search": search_screen("b", "b_results"),
            "b_results": results_b,
            "c_home": coupon_home,
            "c_after_claim": coupon_after,
            "ad_popup": ad_popup,
            "perm_popup": perm_popup,
        },
        apps={
            "juhai": "a_search",
            "com.juhai.shop": "a_search",
            "taoxiang": "b_search",
            "com.taoxiang.mall": "b_search",
            "bilin": "c_home",
            "com.bilin.coupon": "c_home",
        },
        initial="home",
    )


def mobile_price_coupon_with_popups() -> Scenario:
    sc = mobile_price_coupon_scenario()
    sc.screens["a_search"].popup_on_enter = "ad_popup"
    sc.screens["c_home"].popup_on_enter = "perm_popup"
    return sc


def desktop_invoice_scenario() -> Scenario:
    update_popup = ScreenDef(modal=True, elements=[
        _btn("up_title", 0.2, 0.3, 0.6, 0.05, text="温馨提示 发现新版本 V8.2.1"),
        _btn("up_later", 0.5, 0.42, 0.2, 0.05, text="以后再说",
             on_tap=Effect(close_modal=True)),
        _btn("up_now", 0.28, 0.42, 0.2, 0.05, text="立即更新"),
    ])
    mail_inbox = ScreenDef(elements=[
        _btn("m_title", 0.05, 0.02, 0.4, 0.05, text="企业邮箱 - 收件箱"),
        _btn("m_mail1", 0.05, 0.1, 0.9, 0.08,
             text="10月网约车发票 金额¥86.50", rid="mail.list.item"),
        _btn("m_mail2", 0.05, 0.2, 0.9, 0.08,
             text="10月餐饮发票 金额¥148.00", rid="mail.list.item", noisy=True),
        _btn("m_mail3", 0.05, 0.3, 0.9, 0.08,
             text="10月差旅酒店发票 金额¥1015.50", rid="mail.list.item"),
        _btn("m_summary", 0.05, 0.42, 0.9, 0.05, text="本月待报销发票合计 ¥1250.00"),
    ])
    expense_form = ScreenDef(elements=[
        _btn("f_title", 0.05, 0.02, 0.5, 0.05, text="差旅报销单"),
        _input("f_applicant", 0.25, 0.12, 0.5, 0.05, placeholder="申报人",
               rid="form.applicant"),
        _input("f_reason", 0.25, 0.2, 0.5, 0.05, placeholder="报销事由",
               rid="form.reason"),
        _input("f_amount", 0.25, 0.28, 0.5, 0.05, placeholder="报销金额",
               rid="form.amount"),
        _btn("f_attach", 0.25, 0.36, 0.5, 0.05, text="上传发票附件",
             on_tap=Effect(record="attach_uploaded")),
        _btn("f_submit", 0.72, 0.9, 0.22, 0.05, text="提交", rid="form.submit",
             on_tap=Effect(goto="expense_done", record="expense_submitted")),
    ])
    expense_done = ScreenDef(elements=[
        _btn("d_ok", 0.2, 0.3, 0.6, 0.06, text="提交成功 单号 BX-2026-1001"),
        _btn("d_back", 0.4, 0.45, 0.2, 0.05, text="返回收件箱",
             on_tap=Effect(goto="mail_inbox")),
    ])
    return Scenario(
        screens={
            "home": ScreenDef(elements=[_btn("hint", 0.2, 0.4, 0.6, 0.05, text="桌面")]),
            "mail_inbox": mail_inbox,
            "expense_form": expense_form,
            "expense_done": expense_done,
            "update_popup": update_popup,
        },
        apps={"mail": "mail_inbox", "finance": "expense_form"},
        initial="home",
    )


def desktop_invoice_with_popup() -> Scenario:
    sc = desktop_invoice_scenario()
    sc.screens["mail_inbox"].popup_on_enter = "update_popup"
    return sc


def _gb(key, x, y, w, h, text="", rid="", desc="", on_tap=None, noisy=False, cls="Button"):
    return VElem(key=key, x=x, y=y, w=w, h=h, text=text, rid=rid, desc=desc,
                 on_tap=on_tap, noisy=noisy, cls=cls)


def _ginput(key, x, y, w, h, placeholder="", rid="", noisy=False):
    return VElem(key=key, x=x, y=y, w=w, h=h, text=placeholder, rid=rid, desc="",
                 editable=True, clickable=True, noisy=noisy, cls="EditText")


def gov_auth_scenario() -> Scenario:
    """政务/银行类 App：开屏广告 → 权限弹窗 → 会话过期重登 → OTP 挑战 → 余额页。

    OTP 输入框故意带 `noisy=True`：短信码场景下 OCR/UI 文本都会抖动，
    用于验证「输入后必须回读校验」这条容错链路不是摆设。
    """
    ad_popup = ScreenDef(modal=True, elements=[
        _gb("g_ad_title", 0.1, 0.3, 0.8, 0.06, text="政务服务平台 全新升级"),
        _gb("g_ad_skip", 0.82, 0.24, 0.12, 0.045, text="跳过2",
            on_tap=Effect(close_modal=True)),
    ])
    perm_popup = ScreenDef(modal=True, elements=[
        _gb("g_perm_title", 0.1, 0.35, 0.8, 0.06, text="政务通想要获取本机识别码"),
        _gb("g_perm_deny", 0.18, 0.5, 0.25, 0.05, text="拒绝",
            on_tap=Effect(close_modal=True)),
        _gb("g_perm_allow", 0.58, 0.5, 0.25, 0.05, text="允许",
            on_tap=Effect(close_modal=True, record="device_id_allowed")),
    ])
    login_page = ScreenDef(elements=[
        _gb("g_title", 0.05, 0.02, 0.5, 0.05, text="政务通 - 会话已过期，请重新登录"),
        _ginput("gov.phone", 0.1, 0.16, 0.8, 0.06, placeholder="请输入手机号",
                rid="gov.phone"),
        _gb("g_send", 0.1, 0.26, 0.4, 0.055, text="获取验证码",
            on_tap=Effect(goto="otp_page", set_challenge="111111")),
        # 登录态仍有效时，「登录」直接进办事大厅；否则走验证码挑战（goto_if 分流）
        _gb("g_login", 0.1, 0.36, 0.8, 0.06, text="登录",
            on_tap=Effect(goto="home_page", goto_if=("logged_in", "True"))),
        _gb("__back__", 0.05, 0.9, 0.2, 0.05, text="退出"),
    ])
    otp_page = ScreenDef(elements=[
        _gb("g_otp_hint", 0.05, 0.02, 0.9, 0.05, text="验证码已发送至 138****8000"),
        _gb("g_otp_demo", 0.05, 0.1, 0.9, 0.05, text="演示验证码：111111"),
        _ginput("otp_input", 0.1, 0.2, 0.8, 0.06, placeholder="请输入短信验证码",
                rid="gov.otp", noisy=True),
        _gb("g_otp_submit", 0.1, 0.3, 0.8, 0.06, text="提交",
            on_tap=Effect(goto="home_page", goto_if=("otp_input", "111111"),
                          set={"logged_in": True}, record="otp_verified")),
        _gb("__back__", 0.05, 0.9, 0.2, 0.05, text="返回登录",
            on_tap=Effect(goto="login_page")),
    ])
    home_page = ScreenDef(elements=[
        _gb("g_home_title", 0.05, 0.02, 0.6, 0.05, text="我的办事大厅"),
        _gb("g_entry", 0.08, 0.14, 0.84, 0.1, text="公积金查询",
            on_tap=Effect(goto="balance_page")),
    ])
    balance_page = ScreenDef(elements=[
        _gb("g_bal_title", 0.05, 0.02, 0.6, 0.05, text="公积金账户详情"),
        _gb("g_bal_amount", 0.08, 0.14, 0.84, 0.1, text="公积金余额 ¥12345.67"),
        _gb("g_bal_unit", 0.08, 0.26, 0.84, 0.06, text="缴存单位：某某科技有限公司"),
        _gb("__back__", 0.05, 0.9, 0.2, 0.05, text="返回首页",
            on_tap=Effect(goto="home_page")),
    ])
    return Scenario(
        screens={
            "home": ScreenDef(elements=[_gb("g_hint", 0.2, 0.4, 0.6, 0.05, text="桌面")]),
            "login_page": login_page,
            "otp_page": otp_page,
            "home_page": home_page,
            "balance_page": balance_page,
            "ad_popup": ad_popup,
            "perm_popup": perm_popup,
        },
        apps={"govapp": "login_page"},
        initial="home",
    )


def gov_auth_with_popups() -> Scenario:
    """带开屏广告与权限弹窗的变体：`login_page` 进入即弹广告，广告跳权限弹窗。"""
    sc = gov_auth_scenario()
    sc.screens["login_page"].popup_on_enter = "ad_popup"
    sc.screens["ad_popup"].elements[0].on_tap = Effect(popup="perm_popup")
    return sc
