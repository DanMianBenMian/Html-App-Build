# -*- coding: utf-8 -*-
"""
main.py —— TWNativePack 图形界面（PyQt6 科幻光效版 · 上拉遮罩弹窗）。
依赖: pyqt6  (运行: PYTHONPATH=<deps> python main.py)
"""
import os
import sys
import html
import threading

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QFileDialog, QCheckBox, QTextEdit, QGroupBox,
    QMessageBox, QProgressBar, QGraphicsDropShadowEffect, QScrollArea, QGridLayout,
)
from PyQt6.QtCore import (
    pyqtSignal, QObject, Qt, QPropertyAnimation, QEasingCurve, QTimer, QRect,
)
from PyQt6.QtGui import (
    QTextCursor, QPainter, QLinearGradient, QColor, QBrush, QIcon,
)

import build_core
from templates import PERMISSION_DEFS


def resource_path(rel):
    """资源定位：兼容 PyInstaller 单文件模式（资源解包到 sys._MEIPASS）与源码直跑。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


ICON_PNG = resource_path(os.path.join("assets", "icon.png"))


# ---------- 科幻配色 ----------
C_ACCENT = "#22d3ee"      # 霓虹青
C_ACCENT2 = "#a78bfa"     # 霓虹紫
C_OK = "#3fb950"
C_ERR = "#ff6b6b"
C_WARN = "#e3b341"
C_TEXT = "#c9d1d9"
C_PANEL = "rgba(20,28,46,0.72)"


class AskHandle:
    """工作线程 -> 主线程弹窗询问的回复容器（用 Event 同步两个线程）。"""
    def __init__(self):
        self.event = threading.Event()
        self.result = False


class LogEmitter(QObject):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)
    # (标题, 正文, AskHandle)：工作线程请求用户决定是否继续等待
    ask = pyqtSignal(str, str, object)


class Worker(threading.Thread):
    def __init__(self, emitter, **kwargs):
        super().__init__(daemon=True)
        self.emitter = emitter
        self.kwargs = kwargs

    def _ask(self, title, message):
        """构建线程里调用：弹窗阻塞等待用户点按钮，返回 True=继续等待。"""
        handle = AskHandle()
        self.emitter.ask.emit(title, message, handle)
        handle.event.wait()      # 等主线程弹窗完成
        return handle.result

    def run(self):
        try:
            product = build_core.build(
                log=self.emitter.log.emit,
                progress=self.emitter.progress.emit,
                ask=self._ask,
                **self.kwargs)
            if product:
                self.emitter.log.emit("✅ 构建完成，产物: %s" % product)
                self.emitter.progress.emit(6, 6, "已完成")
            else:
                self.emitter.log.emit("⚠️ 未产出文件")
                self.emitter.progress.emit(6, 6, "未产出")
        except Exception as e:
            self.emitter.log.emit("❌ 构建错误: %s" % e)
            self.emitter.progress.emit(6, 6, "失败")


# 权限勾选项：直接来自 templates.PERMISSION_DEFS（与云端 maker 同源，避免漂移）
PERM_LABELS = [(k, v[0]) for k, v in PERMISSION_DEFS.items()]


class GlowProgressBar(QProgressBar):
    """自定义发光进度条：青→紫渐变填充 + 流动高光带。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 6)
        self.setValue(0)
        self.setTextVisible(False)
        self._phase = 0.0
        self._active = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start_glow(self):
        self._active = True
        if not self._timer.isActive():
            self._timer.start(40)

    def stop_glow(self):
        self._active = False
        self._timer.stop()
        self.update()

    def _tick(self):
        self._phase += 5.0
        self.update()

    def paintEvent(self, e):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = h / 2.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(18, 24, 38))
        p.drawRoundedRect(0, 0, w, h, r, r)
        rng = max(1, self.maximum() - self.minimum())
        frac = max(0.0, min(1.0, (self.value() - self.minimum()) / rng))
        if frac > 0:
            pw = max(h, int(w * frac))
            grad = QLinearGradient(0, 0, pw, h)
            grad.setColorAt(0.0, QColor(C_ACCENT))
            grad.setColorAt(1.0, QColor(C_ACCENT2))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(0, 0, pw, h, r, r)
            if self._active:
                gx = int(self._phase) % w
                hl = QLinearGradient(gx - 55, 0, gx + 55, h)
                hl.setColorAt(0.0, QColor(255, 255, 255, 0))
                hl.setColorAt(0.5, QColor(255, 255, 255, 75))
                hl.setColorAt(1.0, QColor(255, 255, 255, 0))
                p.setBrush(QBrush(hl))
                p.setClipRect(0, 0, pw, h)
                p.drawRoundedRect(0, 0, pw, h, r, r)
        p.end()


class NeonButton(QPushButton):
    """主按钮：青→紫渐变。静止不发光，悬停时增强发光。"""
    _BASE = (
        "QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
        "stop:0 #1b8fb3,stop:1 #6d4fc4);color:#eafcff;border:1px solid #5fe9ff;"
        "border-radius:9px;padding:11px 16px;font-weight:bold;font-size:14px;}"
    )
    _HOVER = (
        "QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
        "stop:0 #25b6e0,stop:1 #8a6cf0);color:#ffffff;border:1px solid #aef6ff;"
        "border-radius:9px;padding:11px 16px;font-weight:bold;font-size:14px;}"
    )
    _DISABLED = (
        "QPushButton{background:rgba(40,48,68,0.6);color:#6b7689;"
        "border:1px solid rgba(120,130,150,0.4);border-radius:9px;"
        "padding:11px 16px;font-weight:bold;font-size:14px;}"
    )

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.setStyleSheet(self._BASE)
        self._glow = QGraphicsDropShadowEffect()
        self._glow.setBlurRadius(0)   # 静止不发光
        self._glow.setColor(QColor(C_ACCENT))
        self._glow.setOffset(0, 0)
        self.setGraphicsEffect(self._glow)

    def enterEvent(self, e):
        if not self.isEnabled():
            return
        self._glow.setBlurRadius(30)
        self.setStyleSheet(self._HOVER)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._glow.setBlurRadius(0)
        self.setStyleSheet(self._BASE)
        super().leaveEvent(e)

    def setEnabled(self, on):
        super().setEnabled(on)
        self.setStyleSheet(self._BASE if on else self._DISABLED)
        self._glow.setBlurRadius(0)


class GhostButton(QPushButton):
    """幽灵按钮：半透明描边，悬停提亮。"""
    _BASE = (
        "QPushButton{background:rgba(34,211,238,0.08);color:#bdecf7;"
        "border:1px solid rgba(34,211,238,0.45);border-radius:8px;"
        "padding:7px 12px;font-size:12px;}"
    )
    _HOVER = (
        "QPushButton{background:rgba(34,211,238,0.18);color:#eafcff;"
        "border:1px solid #5fe9ff;border-radius:8px;padding:7px 12px;font-size:12px;}"
    )

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.setStyleSheet(self._BASE)

    def enterEvent(self, e):
        self.setStyleSheet(self._HOVER)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.setStyleSheet(self._BASE)
        super().leaveEvent(e)


class ConsoleSheet(QWidget):
    """上拉式遮罩弹窗：盖住整个主窗口，从底部滑入，构建完提示可关闭。"""

    def __init__(self, parent):
        super().__init__(parent)
        self._parent = parent
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("ConsoleSheet{background:transparent;}")
        self.hide()

        # 遮罩层（挡住后面、捕获点击）
        self.backdrop = QWidget(self)
        self.backdrop.setStyleSheet("background:rgba(2,4,10,0.74);")

        # 底部面板
        self.panel = QWidget(self)
        self.panel.setObjectName("sheetPanel")
        self.panel.setStyleSheet(
            "QWidget#sheetPanel{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #0e1626,stop:1 #070b14);"
            "border-top:1px solid rgba(34,211,238,0.45);"
            "border-top-left-radius:14px;border-top-right-radius:14px;}")

        cc = QVBoxLayout(self.panel)
        cc.setContentsMargins(16, 14, 16, 14)
        cc.setSpacing(10)

        # 顶部：标题 + 完成提示
        top = QHBoxLayout()
        self.sheet_title = QLabel("构建控制台")
        self.sheet_title.setStyleSheet(
            "QLabel{color:%s;font-size:14px;font-weight:bold;}" % C_ACCENT)
        self.banner = QLabel("")
        self.banner.setStyleSheet(
            "QLabel{color:%s;font-size:13px;font-weight:bold;}" % C_OK)
        top.addWidget(self.sheet_title)
        top.addStretch(1)
        top.addWidget(self.banner)
        cc.addLayout(top)

        # 进度标签
        self.progress_label = QLabel("当前任务：空闲（0/6）")
        self.progress_label.setStyleSheet(self._progress_style(C_TEXT))
        pglow = QGraphicsDropShadowEffect()
        pglow.setBlurRadius(12)
        pglow.setColor(QColor(C_ACCENT))
        pglow.setOffset(0, 0)
        self.progress_label.setGraphicsEffect(pglow)
        cc.addWidget(self.progress_label)

        # 进度条
        self.progress_bar = GlowProgressBar()
        cc.addWidget(self.progress_bar)

        # 日志标题
        log_title = QLabel("构建日志")
        log_title.setStyleSheet("QLabel{color:%s;font-size:12px;}" % C_ACCENT)
        cc.addWidget(log_title)

        # 日志框
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(220)
        self.log.setStyleSheet(
            "QTextEdit{background:#080b14;color:%s;border:1px solid rgba(34,211,238,0.35);"
            "border-radius:8px;font-family:'Consolas','Courier New',monospace;"
            "font-size:12px;padding:8px;}" % C_TEXT)
        lglow = QGraphicsDropShadowEffect()
        lglow.setBlurRadius(10)
        lglow.setColor(QColor(C_ACCENT))
        lglow.setOffset(0, 0)
        self.log.setGraphicsEffect(lglow)
        cc.addWidget(self.log, 1)

        # 底部：关闭按钮（构建完成后才可点）
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.close_btn = GhostButton("关闭")
        self.close_btn.setVisible(False)
        self.close_btn.clicked.connect(self._on_close)
        bottom.addWidget(self.close_btn)
        cc.addLayout(bottom)

    def _progress_style(self, color):
        return ("QLabel{color:%s;background:rgba(34,211,238,0.10);"
                "border:1px solid rgba(34,211,238,0.4);border-radius:8px;"
                "padding:8px 12px;font-weight:bold;font-size:13px;}" % color)

    def _layout(self):
        W = self._parent.width()
        H = self._parent.height()
        self.setGeometry(0, 0, W, H)
        self.backdrop.setGeometry(0, 0, W, H)
        self._panelH = int(H * 0.74)
        self.panel.setGeometry(0, H - self._panelH, W, self._panelH)

    def open_sheet(self):
        self._layout()
        self.log.clear()
        self.banner.setText("")
        self.close_btn.setVisible(False)
        self.progress_label.setText("当前任务：准备中（0/6）")
        self.progress_label.setStyleSheet(self._progress_style(C_TEXT))
        self.show()
        self.raise_()
        # 从底部滑入
        H = self._parent.height()
        anim = QPropertyAnimation(self.panel, b"geometry")
        anim.setDuration(480)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(QRect(0, H, self._parent.width(), self._panelH))
        anim.setEndValue(QRect(0, H - self._panelH, self._parent.width(), self._panelH))
        self._anim = anim
        anim.start()

    def show_result(self, ok, label):
        color = C_OK if ok else C_ERR
        self.banner.setText(label)
        self.banner.setStyleSheet("QLabel{color:%s;font-size:13px;font-weight:bold;}" % color)
        self.close_btn.setVisible(True)
        self.close_btn.setEnabled(True)

    def _on_close(self):
        self.hide()

    def append_log(self, text):
        color = self._classify(text)
        safe = html.escape(text, quote=False)
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml('<span style="color:%s;">%s</span><br>' % (color, safe))
        self.log.setTextCursor(cursor)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_progress(self, current, total, name):
        self.progress_label.setText("当前任务：%s（%d/%d）" % (name, current, total))
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
        if name == "已完成":
            self.progress_bar.stop_glow()
            self.progress_label.setStyleSheet(self._progress_style(C_OK))
        elif name in ("失败", "未产出"):
            self.progress_bar.stop_glow()
            self.progress_label.setStyleSheet(self._progress_style(C_ERR))
        else:
            self.progress_bar.start_glow()
            self.progress_label.setStyleSheet(self._progress_style(C_TEXT))

    def _classify(self, text):
        t = text
        if "❌" in t or "错误" in t or "失败" in t or "未产出" in t or "未找到" in t:
            return C_ERR
        if "✅" in t or "✓" in t or "已完成" in t or "成功" in t:
            return C_OK
        if "⚠" in t or "警告" in t:
            return C_WARN
        if "【步骤" in t or t.startswith("-----") or "会话开始" in t:
            return C_ACCENT
        return C_TEXT


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Html App Build")
        self.setMinimumWidth(660)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if os.path.exists(ICON_PNG):
            self.setWindowIcon(QIcon(ICON_PNG))
        self.emitter = LogEmitter()
        self.emitter.log.connect(self._on_log)
        self.emitter.progress.connect(self._on_progress)
        self.emitter.ask.connect(self._on_ask)
        self._init_ui()
        self._load_saved()
        # 上拉弹窗（构建时才显示）
        self.sheet = ConsoleSheet(self)

    def _init_ui(self):
        self.setStyleSheet(
            "MainWindow{background:qradialgradient(cx:50%,cy:-10%,radius:130%,"
            "stop:0 #1a2540,stop:0.55 #0c1120,stop:1 #05070f);}"
        )
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(18, 18, 18, 18)

        # 顶部标题
        hdr = QHBoxLayout()
        title = QLabel("TWNativePack")
        title.setStyleSheet(
            "QLabel{color:%s;font-size:26px;font-weight:bold;"
            "letter-spacing:1px;}" % C_ACCENT)
        # 新增一行：产品名
        brand = QLabel("Html App Build")
        brand.setStyleSheet(
            "QLabel{color:#e8f4ff;font-size:15px;font-weight:bold;"
            "letter-spacing:3px;}")
        bglow = QGraphicsDropShadowEffect()
        bglow.setBlurRadius(16)
        bglow.setColor(QColor(C_ACCENT2))
        bglow.setOffset(0, 0)
        brand.setGraphicsEffect(bglow)
        sub = QLabel("TurboWarp → 原生 iOS / Android App · 一站式打包")
        sub.setStyleSheet("QLabel{color:#7d8ba5;font-size:12px;}")
        hv = QVBoxLayout()
        hv.setSpacing(3)
        hv.addWidget(title)
        hv.addWidget(brand)
        hv.addWidget(sub)
        hdr.addLayout(hv)
        hdr.addStretch(1)
        glow = QGraphicsDropShadowEffect()
        glow.setBlurRadius(22)
        glow.setColor(QColor(C_ACCENT))
        glow.setOffset(0, 0)
        title.setGraphicsEffect(glow)
        root.addLayout(hdr)

        # 平台 + 旋转方向
        h = QHBoxLayout()
        h.addWidget(self._field_label("平台:"))
        self.platform = QComboBox()
        self.platform.addItems(["iOS", "Android"])
        self.platform.setStyleSheet(self._combo_style())
        h.addWidget(self.platform, 2)
        h.addWidget(self._field_label("旋转方向:"))
        self.orientation = QComboBox()
        for _lbl, _key in (("竖屏", "portrait"), ("横屏", "landscape"), ("自适应", "auto")):
            self.orientation.addItem(_lbl, _key)
        self.orientation.setCurrentIndex(2)          # 默认：自适应
        self.orientation.setStyleSheet(self._combo_style())
        self.orientation.setToolTip("竖屏=只允许竖屏\n横屏=只允许横屏\n自适应=跟随设备旋转")
        h.addWidget(self.orientation, 2)
        root.addLayout(h)

        # 应用名 + 包名
        h = QHBoxLayout()
        h.addWidget(self._field_label("应用名称:"))
        self.name = QLineEdit()
        self.name.textChanged.connect(self._auto_bundle)
        self.name.setStyleSheet(self._edit_style())
        h.addWidget(self.name, 3)
        h.addWidget(self._field_label("包名:"))
        self.bundle = QLineEdit()
        self.bundle.setPlaceholderText("留空自动生成 com.twpack.xxx")
        self.bundle.setStyleSheet(self._edit_style())
        h.addWidget(self.bundle, 3)
        root.addLayout(h)

        # 图标 + 来源（单 HTML 或 文件夹）
        h = QHBoxLayout()
        self.icon_btn = GhostButton("选择图标图片")
        self.icon_btn.clicked.connect(self._pick_icon)
        self.icon_label = QLabel("未选择")
        self.icon_label.setStyleSheet("QLabel{color:#7d8ba5;}")
        self.html_btn = GhostButton("选择 .html (单文件)")
        self.html_btn.clicked.connect(self._pick_html)
        self.html_label = QLabel("未选择")
        self.html_label.setStyleSheet("QLabel{color:#7d8ba5;}")
        self.folder_btn = GhostButton("选择文件夹")
        self.folder_btn.clicked.connect(self._pick_folder)
        self.folder_label = QLabel("未选择")
        self.folder_label.setStyleSheet("QLabel{color:#7d8ba5;}")
        h.addWidget(self.icon_btn)
        h.addWidget(self.icon_label)
        h.addWidget(self.html_btn)
        h.addWidget(self.html_label)
        h.addWidget(self.folder_btn)
        h.addWidget(self.folder_label)
        root.addLayout(h)

        # 入口文件（仅文件夹模式需要）
        h = QHBoxLayout()
        h.addWidget(self._field_label("入口文件:"))
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("文件夹模式加载的首页，留空默认 index.html（如 gui/gui.html）")
        self.entry.setStyleSheet(self._edit_style())
        h.addWidget(self.entry, 1)
        root.addLayout(h)

        # 权限（按平台动态展示：仅列出该平台可申请项）
        self.perm_group = QGroupBox("需要声明的权限")
        self.perm_group.setStyleSheet(
            "QGroupBox{color:%s;background:%s;border:1px solid rgba(34,211,238,0.25);"
            "border-radius:10px;padding:10px 8px 8px;font-size:13px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}"
            % (C_ACCENT, C_PANEL))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(188)
        # 注意：QScrollArea{background} 只管自身，viewport 与内层 widget 会露出浅色调板 → 必须一并置透明
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea > QWidget > QWidget{background:transparent;}"
            "QWidget#permInner{background:transparent;}"
            "QScrollBar:vertical{background:transparent;width:8px;margin:0;}"
            "QScrollBar::handle:vertical{background:rgba(34,211,238,0.35);"
            "border-radius:4px;min-height:24px;}"
            "QScrollBar::handle:vertical:hover{background:rgba(34,211,238,0.6);}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        self.perm_inner = QWidget()
        self.perm_inner.setObjectName("permInner")
        self.perm_inner.setAutoFillBackground(False)
        self.perm_grid = QGridLayout(self.perm_inner)
        self.perm_grid.setContentsMargins(4, 4, 4, 4)
        self.perm_grid.setSpacing(8)
        for c in range(3):
            self.perm_grid.setColumnStretch(c, 1)
        self.perm_inner.setLayout(self.perm_grid)
        scroll.setWidget(self.perm_inner)
        gv = QVBoxLayout(self.perm_group)
        gv.setContentsMargins(10, 16, 10, 10)
        gv.setSpacing(6)
        tool = QHBoxLayout()
        self.perm_count = QLabel("")
        self.perm_count.setStyleSheet("QLabel{color:#7d8ba5;font-size:12px;}")
        tool.addWidget(self.perm_count)
        tool.addStretch(1)
        sel_all = GhostButton("全选")
        sel_all.clicked.connect(lambda: self._set_all_perms(True))
        sel_none = GhostButton("清空")
        sel_none.clicked.connect(lambda: self._set_all_perms(False))
        tool.addWidget(sel_all)
        tool.addWidget(sel_none)
        gv.addLayout(tool)
        gv.addWidget(scroll)
        self.perm_group.setLayout(gv)
        root.addWidget(self.perm_group, 1)   # 吸走多余竖直空间，列表随窗口自适应，不浮空

        self.perm_boxes = {}
        self._checked_perms = set()
        self.platform.currentIndexChanged.connect(self._on_platform_changed)
        self._refresh_perms()

        # PAT
        h = QHBoxLayout()
        h.addWidget(self._field_label("GitHub PAT:"))
        self.pat = QLineEdit()
        self.pat.setEchoMode(QLineEdit.EchoMode.Password)
        self.pat.setStyleSheet(self._edit_style())
        self.remember = QCheckBox("记住到本机")
        self.remember.setStyleSheet(self._check_style())
        self.remember.stateChanged.connect(self._on_remember)
        h.addWidget(self.pat, 3)
        h.addWidget(self.remember)
        root.addLayout(h)

        # 输出目录
        h = QHBoxLayout()
        self.out_btn = GhostButton("产物保存目录")
        self.out_btn.clicked.connect(self._pick_out)
        self.out_label = QLabel(os.path.join(os.path.expanduser("~"), "Downloads"))
        self.out_label.setStyleSheet("QLabel{color:#7d8ba5;}")
        self.out_dir = self.out_label.text()
        h.addWidget(self.out_btn)
        h.addWidget(self.out_label)
        root.addLayout(h)

        # 删除临时仓库
        self.del_repo = QCheckBox("构建完成后删除临时仓库")
        self.del_repo.setChecked(True)
        self.del_repo.setStyleSheet(self._check_style())
        root.addWidget(self.del_repo)

        # 构建按钮
        self.build_btn = NeonButton("🚀 开始构建")
        self.build_btn.clicked.connect(self._build)
        root.addWidget(self.build_btn)

    # ---------- 样式辅助 ----------
    def _field_label(self, t):
        l = QLabel(t)
        l.setStyleSheet("QLabel{color:#9fb0c8;}")
        return l

    def _edit_style(self):
        return ("QLineEdit{background:rgba(8,12,22,0.85);color:#e6f1ff;"
                "border:1px solid rgba(34,211,238,0.35);border-radius:7px;"
                "padding:7px 9px;font-size:13px;}"
                "QLineEdit:focus{border:1px solid #5fe9ff;}")

    def _combo_style(self):
        return ("QComboBox{background:rgba(8,12,22,0.85);color:#e6f1ff;"
                "border:1px solid rgba(34,211,238,0.35);border-radius:7px;"
                "padding:6px 9px;font-size:13px;}"
                "QComboBox::drop-down{border:none;width:18px;}"
                "QComboBox QAbstractItemView{background:#0c1120;color:#e6f1ff;"
                "selection-background-color:#1b8fb3;}")

    def _check_style(self):
        return ("QCheckBox{color:#bcd0e6;font-size:13px;spacing:6px;}"
                "QCheckBox::indicator{width:16px;height:16px;border-radius:4px;"
                "border:1px solid rgba(34,211,238,0.5);background:rgba(8,12,22,0.8);}"
                "QCheckBox::indicator:checked{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                "stop:0 #22d3ee,stop:1 #a78bfa);border:1px solid #5fe9ff;}")

    # ---------- 权限（按平台动态展示） ----------
    def _on_platform_changed(self, _idx):
        self._refresh_perms()

    def _perm_items_for(self, platform):
        """返回该平台可申请的 [(key, 中文标签)]，顺序同 PERMISSION_DEFS。"""
        idx = 1 if platform.lower().startswith("ios") else 2
        return [(k, v[0]) for k, v in PERMISSION_DEFS.items() if v[idx]]

    def _refresh_perms(self):
        # 先记住已勾选（跨平台切换保留，切回来不丢）
        for k, cb in self.perm_boxes.items():
            if cb.isChecked():
                self._checked_perms.add(k)
            else:
                self._checked_perms.discard(k)
        # 清空旧勾选框
        while self.perm_grid.count():
            item = self.perm_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.perm_boxes = {}
        plat = self.platform.currentText()
        items = self._perm_items_for(plat)
        cols = 3
        for r in range(16):                      # 复位历史行拉伸，避免残留
            self.perm_grid.setRowStretch(r, 0)
        for i, (key, label) in enumerate(items):
            cb = QCheckBox(label)
            cb.setStyleSheet(self._check_style())
            cb.setToolTip(key)
            cb.setChecked(key in self._checked_perms)
            cb.stateChanged.connect(lambda _s: self._update_perm_count())
            self.perm_boxes[key] = cb
            self.perm_grid.addWidget(cb, i // cols, i % cols)
        # 多余竖直空间收到表格末尾，保证各行紧凑贴顶、不被拉散
        self.perm_grid.setRowStretch((len(items) + cols - 1) // cols, 1)
        self.perm_group.setTitle("需要声明的权限（%s 可申请 %d 项）" % (plat, len(items)))
        self._update_perm_count()

    def _update_perm_count(self):
        sel = sum(1 for cb in self.perm_boxes.values() if cb.isChecked())
        self.perm_count.setText("已选 %d / %d 项 · 切换平台会保留选择"
                                % (sel, len(self.perm_boxes)))

    def _set_all_perms(self, flag):
        for cb in self.perm_boxes.values():
            cb.setChecked(flag)
        self._update_perm_count()

    # ---------- 交互 ----------
    def _auto_bundle(self, text):
        if not self.bundle.text().strip():
            # 包名必须 ASCII：中文经 Python isalnum() 判定为真会生成非法包名 com.twpack.示例项目
            safe = "".join(c for c in text.lower() if c.isascii() and c.isalnum())
            self.bundle.setPlaceholderText("com.twpack.%s" % (safe or "app"))

    def _pick_icon(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择图标", "", "图片 (*.png *.jpg *.jpeg)")
        if p:
            self.icon_path = p
            self.icon_label.setText(os.path.basename(p))

    def _pick_html(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择 HTML", "", "HTML (*.html)")
        if p:
            self.html_path = p
            self.html_label.setText(os.path.basename(p))
            # 单文件模式：清空文件夹选择
            self.folder_path = ""
            self.folder_label.setText("未选择")

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "产物目录")
        if d:
            self.out_dir = d
            self.out_label.setText(d)

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "选择网页文件夹")
        if d:
            self.folder_path = d
            self.folder_label.setText(d)
            # 文件夹模式：清空单文件选择
            self.html_path = ""
            self.html_label.setText("未选择")
            # 自动探测入口：优先 index.html，否则第一个 .html
            cand = os.path.join(d, "index.html")
            if os.path.isfile(cand):
                self.entry.setText("index.html")
            else:
                found = None
                for r, _, fs in os.walk(d):
                    for f in fs:
                        if f.endswith(".html"):
                            found = os.path.relpath(os.path.join(r, f), d).replace(os.sep, "/")
                            break
                    if found:
                        break
                self.entry.setText(found or "index.html")

    def _on_remember(self, state):
        if state:
            build_core.save_pat(self.pat.text().strip())

    def _load_saved(self):
        saved = build_core.load_local_config()
        if saved.get("pat"):
            self.pat.setText(saved["pat"])
            self.remember.setChecked(True)

    def _on_log(self, text):
        self.sheet.append_log(text)

    def _on_progress(self, current, total, name):
        self.sheet.set_progress(current, total, name)
        if name == "已完成":
            self.sheet.show_result(True, "✅ 构建完成 · 可关闭")
        elif name in ("失败", "未产出"):
            self.sheet.show_result(False, "❌ 构建失败 · 可关闭")

    def _on_ask(self, title, message, handle):
        """构建线程遇到网络异常/等待超时时的询问弹窗（在主线程执行）。"""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(message)
        box.setStyleSheet(
            "QMessageBox{background:#0d1117;}"
            "QLabel{color:#c9d1d9;font-size:13px;}"
            "QPushButton{background:#161b22;color:#c9d1d9;border:1px solid #30363d;"
            "border-radius:6px;padding:7px 18px;min-width:110px;}"
            "QPushButton:hover{background:#1f2634;border-color:#58a6ff;}"
            "QPushButton:default{border-color:#58a6ff;color:#58a6ff;}")
        btn_continue = box.addButton("继续等待", QMessageBox.ButtonRole.AcceptRole)
        btn_stop = box.addButton("放弃这次构建", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_continue)
        box.exec()
        handle.result = (box.clickedButton() is btn_continue)
        handle.event.set()

    def _build(self):
        platform = self.platform.currentText().lower()
        name = self.name.text().strip()
        html_path = getattr(self, "html_path", "")
        folder_path = getattr(self, "folder_path", "")
        icon_path = getattr(self, "icon_path", "")
        perms = [k for k, cb in self.perm_boxes.items() if cb.isChecked()]
        token = self.pat.text().strip()
        if not name:
            QMessageBox.warning(self, "缺信息", "请填写应用名称")
            return
        if folder_path:
            if not os.path.isdir(folder_path):
                QMessageBox.warning(self, "缺信息", "请选择网页文件夹")
                return
            entry_html = self.entry.text().strip() or "index.html"
            if not os.path.isfile(os.path.join(folder_path, entry_html)):
                QMessageBox.warning(self, "缺信息",
                                    "文件夹内找不到入口文件：%s" % entry_html)
                return
        else:
            if not html_path or not os.path.isfile(html_path):
                QMessageBox.warning(self, "缺信息",
                                    "请选择 .html 文件 或 一个网页文件夹")
                return
            entry_html = None
        if not token:
            QMessageBox.warning(self, "缺信息", "请填写 GitHub PAT（可勾记住）")
            return
        if self.remember.isChecked():
            build_core.save_pat(token)
        self.build_btn.setEnabled(False)
        self.sheet.open_sheet()
        self._on_log("=== 开始构建 %s: %s ===" % (platform.upper(), name))
        w = Worker(self.emitter, platform=platform, html_path=html_path,
                   folder_path=folder_path, entry_html=entry_html,
                   icon_path=icon_path, name=name,
                   bundle_id=self.bundle.text().strip(),
                   perms=perms, token=token,
                   orientation=self.orientation.currentData(),
                   delete_after=self.del_repo.isChecked(), out_dir=self.out_dir)
        w.start()

        def _watch():
            w.join()
            self.build_btn.setEnabled(True)
        threading.Thread(target=_watch, daemon=True).start()

    def resizeEvent(self, e):
        if getattr(self, "sheet", None) and self.sheet.isVisible():
            self.sheet._layout()
        super().resizeEvent(e)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    if os.path.exists(ICON_PNG):
        app.setWindowIcon(QIcon(ICON_PNG))   # 应用级图标：任务栏/任务切换器也生效
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
