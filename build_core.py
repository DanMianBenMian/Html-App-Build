# -*- coding: utf-8 -*-
"""
build_core.py —— TWNativePack 构建编排核心（平台无关）。
流程：建临时仓库 -> 推 config.json/app.html/icon.png/工作流+生成脚本 -> 触发 -> 轮询 -> 下产物。
"""
import json
import os
import re
import io
import ssl
import time
import socket
import zipfile
import datetime
import http.client
import urllib.error

import gh_api
import templates

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "twpack")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# ---- 网络抖动容忍参数 ----
NET_AUTO_RETRY = 3      # 连续网络异常 <=3 次：自动重试，不打扰用户
NET_RETRY_SLEEP = 10    # 自动重试前的等待秒数
POLL_INTERVAL = 30      # 正常轮询间隔
POLL_ROUNDS = 40        # 每轮轮询次数（40 × 30s ≈ 20 分钟）

_NET_HTTP_RE = re.compile(r"HTTP\s+(5\d{2}|429)\b")
_NET_TEXT_HINTS = (
    "an error occurred while sending the request",
    "timed out",
    "connection reset",
    "connection aborted",
    "temporary failure in name resolution",
    "bad gateway",
)


def is_network_error(e) -> bool:
    """判断是否为「网络/服务端临时故障」——这类错误不代表构建失败，可以重试。

    gh_api 会把 HTTPError 统一包装成 RuntimeError("HTTP 502 url -> ...")，
    所以要连消息文本一起判断；URLError / timeout 等则直接按类型识别。
    """
    if isinstance(e, (urllib.error.URLError, socket.timeout, TimeoutError,
                      ConnectionError, ssl.SSLError, http.client.HTTPException)):
        return True
    msg = str(e)
    if _NET_HTTP_RE.search(msg):
        return True
    low = msg.lower()
    return any(h in low for h in _NET_TEXT_HINTS)


# ---------------- 本地 PAT / 偏好 ----------------
def load_local_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_local_config(data: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    old = load_local_config()
    old.update(data)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(old, f, indent=2, ensure_ascii=False)


def load_saved_pat():
    return load_local_config().get("pat", "")


def save_pat(pat: str):
    save_local_config({"pat": pat})


# ---------------- 构建 ----------------
TOTAL_STEPS = 6


def _ascii_slug(s: str) -> str:
    """只保留 ASCII 字母数字（小写），用于拼包名片段。"""
    return "".join(c for c in (s or "").lower() if c.isascii() and c.isalnum())


def sanitize_bundle_id(bundle_id: str, app_name: str) -> str:
    """
    包名必须是 ASCII（字母数字 . -）且至少两段。
    ★ 中文应用名会被 Python 的 isalnum() 判定为真，从而生成
      "com.twpack.示例项目" 这种**非法包名**（iOS / Android 都不接受非 ASCII 包名）。
    ★ 只要原始值被清洗过（含非法字符），就整体重新生成：否则 "com.twpack.示例项目"
      会被截成 "com.twpack" 这种"结构合法但没意义"的包名，导致此类 App 互相撞包名。
    """
    raw = (bundle_id or "").strip()
    cleaned = "".join(c for c in raw if c.isascii() and (c.isalnum() or c in ".-"))
    cleaned = ".".join(p for p in cleaned.split(".") if p)
    segs = [p for p in cleaned.split(".") if p]
    if raw and cleaned == raw and len(segs) >= 2 and all(p[0].isalpha() for p in segs):
        return cleaned
    return "com.twpack.%s" % (_ascii_slug(app_name) or "app")


def _zip_folder(folder: str) -> bytes:
    """把整个文件夹打成 zip（内存中），相对路径用正斜杠，保持目录结构。"""
    import zipfile
    import io
    buf = io.BytesIO()
    n = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(folder):
            for fn in files:
                fp = os.path.join(root, fn)
                rel = os.path.relpath(fp, folder).replace(os.sep, "/")
                # 跳过可能混进来的隐藏/缓存文件（不做硬过滤，保留用户资源）
                z.write(fp, rel)
                n += 1
    return buf.getvalue(), n


def build(platform, html_path, icon_path, name, bundle_id, perms,
          token, log, delete_after=True, out_dir=".", progress=None, orientation="auto",
          folder_path=None, entry_html="index.html", ask=None):
    """
    platform: 'ios' | 'android'
    log: 回调函数(str) 用于回显日志（每行建议带时间戳，已由本函数统一加）
    progress: 可选回调(current:int, total:int, name:str) 用于 UI 进度显示
    ask: 可选回调(title:str, message:str) -> bool
         网络异常/等待超时时询问用户「是否继续等待」；返回 True 继续轮询，False 放弃。
         不传（None）时保持旧行为：网络异常直接失败、轮询到上限直接失败。
    返回产物本地路径或 None
    """
    def _t():
        return datetime.datetime.now().strftime("%H:%M:%S")

    def _log(msg):
        log("[%s] %s" % (_t(), msg))

    def _step(n, name_):
        if progress:
            try:
                progress(n, TOTAL_STEPS, name_)
            except Exception:
                pass
        _log("【步骤 %d/%d】%s" % (n, TOTAL_STEPS, name_))

    def _ask(title, message):
        """询问用户是否继续等待。没有 ask 回调时按「放弃」处理（保持旧行为）。"""
        if not ask:
            return False
        try:
            return bool(ask(title, message))
        except Exception as e:
            _log("(询问回调异常，按放弃处理: %s)" % e)
            return False

    def _net_call(fn, *a, **kw):
        """网络调用 + 自动重试：连续 NET_AUTO_RETRY 次内自动重试，仍失败才抛出。"""
        err = None
        for attempt in range(NET_AUTO_RETRY + 1):
            try:
                return fn(*a, **kw)
            except Exception as e:
                if not is_network_error(e):
                    raise
                err = e
                _log("  ⚠ 网络/服务端异常（%d/%d）：%s"
                     % (attempt + 1, NET_AUTO_RETRY + 1, e))
                if attempt < NET_AUTO_RETRY:
                    _log("    %d 秒后自动重试…（云端构建不受影响）" % NET_RETRY_SLEEP)
                    time.sleep(NET_RETRY_SLEEP)
        raise err

    if not token:
        raise RuntimeError("缺少 GitHub PAT")
    # ---- 来源：单 HTML 文件 或 网页文件夹（二选一）----
    if folder_path:
        if not os.path.isdir(folder_path):
            raise RuntimeError("网页文件夹不存在: %s" % folder_path)
        entry_html = entry_html or "index.html"
        entry_full = os.path.join(folder_path, entry_html)
        if not os.path.isfile(entry_full):
            raise RuntimeError("入口文件不存在: %s（文件夹内找不到 %s）"
                               % (folder_path, entry_html))
        source_mode = "folder"
        _log("来源模式: 文件夹 -> %s （入口 %s）" % (folder_path, entry_html))
    else:
        if not os.path.isfile(html_path):
            raise RuntimeError("HTML 文件不存在: %s" % html_path)
        source_mode = "file"
        _log("来源模式: 单 HTML 文件 -> %s" % html_path)
    _orig_bid = (bundle_id or "").strip()
    bundle_id = sanitize_bundle_id(bundle_id, name)
    if _orig_bid != bundle_id:
        _log("包名规范化: %s -> %s" % (_orig_bid or "(留空)", bundle_id))
    _ORIENT_LABEL = {"portrait": "竖屏", "landscape": "横屏", "auto": "自适应"}
    if orientation not in _ORIENT_LABEL:
        _log("未知旋转方向 %r，按自适应处理" % orientation)
        orientation = "auto"

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    repo = "twpack-%s" % stamp
    owner = None
    _log("TWNativePack 构建会话开始 · 平台=%s · 应用=%s · 包名=%s"
         % (platform.upper(), name, bundle_id))
    _log("旋转方向: %s (%s)" % (_ORIENT_LABEL[orientation], orientation))
    if perms:
        _log("声明的权限: %s" % ", ".join(perms))
    else:
        _log("声明的权限: (无)")
    try:
        _step(1, "建立临时仓库")
        _log("正在创建私有仓库 %s ..." % repo)
        r = gh_api.create_repo(token, repo, private=True)
        owner = r.get("owner", {}).get("login") or r.get("full_name", "").split("/")[0]
        if not owner:
            owner = gh_api._req("GET", gh_api.API + "/user", token)["login"]
        _log("✓ 鉴权通过，所有者: %s" % owner)
        _log("✓ 仓库已建立: %s/%s  (https://github.com/%s/%s)" % (owner, repo, owner, repo))

        _step(2, "推送工程文件")
        # config.json
        cfg = {"name": name, "bundle_id": bundle_id, "permissions": perms,
               "platform": platform, "orientation": orientation,
               "source_mode": source_mode, "entry_html": entry_html if source_mode == "folder" else None}
        _log("推送配置: %s" % json.dumps(cfg, ensure_ascii=False))
        gh_api.push_file(token, owner, repo, "config.json",
                         json.dumps(cfg, indent=2, ensure_ascii=False).encode("utf-8"),
                         "add config")
        _log("  · config.json 已推送")
        # app.html（单文件模式）或 app.zip（文件夹模式）
        if source_mode == "folder":
            zip_bytes, zip_count = _zip_folder(folder_path)
            gh_api.push_file(token, owner, repo, "app.zip", zip_bytes, "add app.zip")
            _log("  · app.zip 已推送 (%.1f KB, %d 个文件)" % (len(zip_bytes) / 1024.0, zip_count))
        else:
            with open(html_path, "rb") as f:
                html_bytes = f.read()
            gh_api.push_file(token, owner, repo, "app.html", html_bytes, "add app.html")
            _log("  · app.html 已推送 (%.1f KB)" % (len(html_bytes) / 1024.0))
        # icon.png
        if icon_path and os.path.isfile(icon_path):
            with open(icon_path, "rb") as f:
                icon_bytes = f.read()
            gh_api.push_file(token, owner, repo, "icon.png", icon_bytes, "add icon")
            _log("  · icon.png 已推送 (%.1f KB)" % (len(icon_bytes) / 1024.0))
        else:
            _log("  · 未提供图标，将使用默认图标")
        # 工作流 + 生成脚本
        wf_name = "ios-build.yml" if platform == "ios" else "android-build.yml"
        gh_api.push_file(token, owner, repo, ".github/workflows/%s" % wf_name,
                         templates.get_workflow(platform).encode("utf-8"), "add workflow")
        makers = templates.get_maker_files(platform)
        for fn, content in makers.items():
            gh_api.push_file(token, owner, repo, fn, content.encode("utf-8"), "add %s" % fn)
        _log("  · 工作流 %s 已推送" % wf_name)
        _log("  · 生成脚本已推送: %s" % ", ".join(makers.keys()))
        _log("✓ 全部工程文件已提交至仓库")

        _step(3, "触发 %s 云端构建" % platform.upper())
        ref = gh_api.get_default_branch(token, owner, repo)
        _log("默认分支: %s" % ref)
        gh_api.dispatch_workflow(token, owner, repo, wf_name, ref)
        _log("✓ 已触发 workflow: %s" % wf_name)
        _log("  实时查看: https://github.com/%s/%s/actions" % (owner, repo))
        time.sleep(3)

        _step(4, "轮询构建状态")
        run_id = None
        net_err_streak = 0
        poll_count = 0
        deadline = POLL_ROUNDS
        while True:
            # 到了本轮上限：问用户要不要继续等（构建本身没失败，只是慢）
            if poll_count >= deadline:
                waited_min = max(1, poll_count * POLL_INTERVAL // 60)
                if not _ask("仍在构建中",
                            "已等待约 %d 分钟，云端构建仍在进行"
                            "（GitHub 托管 runner 偶有排队，属正常现象）。\n\n"
                            "构建并未失败，继续等待通常就能出包。\n\n"
                            "是否继续等待？" % waited_min):
                    _log("已放弃等待。该次构建仍在 GitHub 上继续，可到 Actions 页面查看结果。")
                    raise RuntimeError("等待超时，已放弃（构建可能仍在云端进行）")
                deadline += POLL_ROUNDS
                _log("继续等待：再轮询 %d 次（约 %d 分钟）"
                     % (POLL_ROUNDS, POLL_ROUNDS * POLL_INTERVAL // 60))
                continue
            try:
                # 这里不用 _net_call：重试节奏由下面的 net_err_streak 统一控制，
                # 否则会变成「内层重试 × 外层重试」的双重等待。
                runs = gh_api.list_runs(token, owner, repo)
                net_err_streak = 0
            except Exception as e:
                if not is_network_error(e):
                    raise
                net_err_streak += 1
                _log("  ⚠ 查询构建状态失败（连续第 %d 次）：%s" % (net_err_streak, e))
                if net_err_streak <= NET_AUTO_RETRY:
                    _log("    %d 秒后自动重试…（云端构建不受影响）" % NET_RETRY_SLEEP)
                    time.sleep(NET_RETRY_SLEEP)
                    continue
                # 抖动次数多了就交给用户决定，不再自作主张放弃
                if not _ask("网络异常",
                            "连续 %d 次查询不到构建状态：\n%s\n\n"
                            "这通常是网络波动或 GitHub 临时故障（例如 502），"
                            "云端构建很可能仍在进行。\n\n"
                            "是否继续等待并继续轮询？" % (net_err_streak, e)):
                    raise RuntimeError("已放弃等待（网络异常：%s）" % e)
                net_err_streak = 0
                _log("    %d 秒后继续轮询…" % NET_RETRY_SLEEP)
                time.sleep(NET_RETRY_SLEEP)
                continue
            poll_count += 1
            if runs:
                run_id = runs[0]["id"]
                st = runs[0]["status"]
                con = runs[0].get("conclusion")
                _log("  轮询 %d · run #%s · status=%s conclusion=%s"
                     % (poll_count, run_id, st, con))
                if progress:
                    try:
                        progress(4, TOTAL_STEPS,
                                 "轮询构建状态（已等待约 %d 分钟）"
                                 % max(1, poll_count * POLL_INTERVAL // 60))
                    except Exception:
                        pass
                if st == "completed":
                    break
            time.sleep(POLL_INTERVAL)
        if not run_id:
            raise RuntimeError("未找到工作流运行实例")
        # 抓日志
        _log("----- 云端构建日志（节选）-----")
        try:
            _log(gh_api.download_run_logs(token, owner, repo, run_id)[-6000:])
        except Exception as e:
            _log("(构建日志获取失败: %s)" % e)
        _log("----- 日志结束 -----")

        run = _net_call(gh_api.get_run, token, owner, repo, run_id)
        if run.get("conclusion") != "success":
            raise RuntimeError(
                "构建失败: conclusion=%s（完整日志见 https://github.com/%s/%s/actions/runs/%s）"
                % (run.get("conclusion"), owner, repo, run_id))
        _log("✓ 构建成功 (conclusion=success)")

        _step(5, "下载构建产物")
        arts = _net_call(gh_api.list_artifacts, token, owner, repo, run_id)
        if not arts:
            raise RuntimeError("无可用产物")
        art = arts[0]
        _log("产物: %s (id=%s, size=%s)" % (art.get("name"), art.get("id"), art.get("size_in_bytes")))
        data = gh_api.download_artifact(token, art["archive_download_url"])
        os.makedirs(out_dir, exist_ok=True)
        zip_path = os.path.join(out_dir, "%s-%s.zip" % (repo, platform))
        gh_api.save_artifact_zip(zip_path, data)
        # 解压出 .ipa / .apk
        product = None
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in z.namelist():
                if n.endswith(".ipa") or n.endswith(".apk"):
                    p = os.path.join(out_dir, os.path.basename(n))
                    with open(p, "wb") as f:
                        f.write(z.read(n))
                    product = p
        if not product:
            product = zip_path
        _log("✓ 产物已解包: %s" % product)

        _step(6, "清理与收尾")
        if delete_after:
            _log("正在删除临时仓库 %s/%s ..." % (owner, repo))
            try:
                gh_api.delete_repo(token, owner, repo)
                _log("✓ 临时仓库已删除")
            except Exception as e:
                _log("⚠ 删库失败（可手动删除）: %s" % e)
        else:
            _log("已保留临时仓库: https://github.com/%s/%s" % (owner, repo))
        return product
    finally:
        pass
