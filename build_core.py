# -*- coding: utf-8 -*-
"""
build_core.py —— TWNativePack 构建编排核心（平台无关）。
流程：建临时仓库 -> 推 config.json/app.html/icon.png/工作流+生成脚本 -> 触发 -> 轮询 -> 下产物。
"""
import json
import os
import time
import datetime
import zipfile
import io

import gh_api
import templates

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "twpack")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


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


def build(platform, html_path, icon_path, name, bundle_id, perms,
          token, log, delete_after=True, out_dir=".", progress=None, orientation="auto"):
    """
    platform: 'ios' | 'android'
    log: 回调函数(str) 用于回显日志（每行建议带时间戳，已由本函数统一加）
    progress: 可选回调(current:int, total:int, name:str) 用于 UI 进度显示
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

    if not token:
        raise RuntimeError("缺少 GitHub PAT")
    if not os.path.isfile(html_path):
        raise RuntimeError("HTML 文件不存在: %s" % html_path)
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
               "platform": platform, "orientation": orientation}
        _log("推送配置: %s" % json.dumps(cfg, ensure_ascii=False))
        gh_api.push_file(token, owner, repo, "config.json",
                         json.dumps(cfg, indent=2, ensure_ascii=False).encode("utf-8"),
                         "add config")
        _log("  · config.json 已推送")
        # app.html
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
        for i in range(40):
            runs = gh_api.list_runs(token, owner, repo)
            if runs:
                run_id = runs[0]["id"]
                st = runs[0]["status"]
                con = runs[0].get("conclusion")
                _log("  轮询 %d/40 · run #%s · status=%s conclusion=%s"
                     % (i + 1, run_id, st, con))
                if progress:
                    try:
                        progress(4, TOTAL_STEPS, "轮询构建状态 (%d/40)" % (i + 1))
                    except Exception:
                        pass
                if st == "completed":
                    break
            time.sleep(30)
        if not run_id:
            raise RuntimeError("未找到工作流运行实例")
        # 抓日志
        _log("----- 云端构建日志（节选）-----")
        try:
            _log(gh_api.download_run_logs(token, owner, repo, run_id)[-6000:])
        except Exception as e:
            _log("(构建日志获取失败: %s)" % e)
        _log("----- 日志结束 -----")

        run = gh_api.get_run(token, owner, repo, run_id)
        if run.get("conclusion") != "success":
            raise RuntimeError("构建失败: conclusion=%s" % run.get("conclusion"))
        _log("✓ 构建成功 (conclusion=success)")

        _step(5, "下载构建产物")
        arts = gh_api.list_artifacts(token, owner, repo, run_id)
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
