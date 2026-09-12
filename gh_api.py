# -*- coding: utf-8 -*-
"""
gh_api.py —— 用 GitHub REST API 编排临时仓库 + 触发构建 + 拉日志/产物。
纯标准库（urllib），不依赖 requests。
注意：本机 git push 被 WattToolkit 代理拦截，故一律走 REST Contents API 推文件。
"""
import base64
import json
import os
import urllib.request
import urllib.error
import urllib.parse
import zipfile
import io

API = "https://api.github.com"
UA = {"User-Agent": "TWNativePack", "Accept": "application/vnd.github+json"}


class _StripAuthRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub 产物下载会把 api.github.com 302 跳到 Azure blob 存储；
    Azure 不接受 GitHub token，故跨域重定向时剥离 Authorization 头。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newreq = super().redirect_request(req, fp, code, msg, headers, newurl)
        if newreq is not None:
            old_host = urllib.parse.urlparse(req.get_full_url()).netloc
            new_host = urllib.parse.urlparse(newurl).netloc
            if old_host != new_host and "Authorization" in newreq.headers:
                del newreq.headers["Authorization"]
        return newreq


_artifact_opener = urllib.request.build_opener(_StripAuthRedirect())


def _req(method, url, token, data=None, binary=False, raw=False):
    headers = dict(UA)
    if token:
        headers["Authorization"] = "Bearer %s" % token
    if data is not None and not binary:
        data = data.encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            if raw:
                return body, r.headers
            return json.loads(body.decode("utf-8", "replace")) if body else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError("HTTP %s %s -> %s" % (e.code, url, detail[:500]))


# ---------------- 仓库 ----------------
def create_repo(token, name, private=True):
    body = json.dumps({
        "name": name, "private": private, "auto_init": False,
        "description": "TWNativePack temp build repo (auto-deleted)",
    })
    return _req("POST", API + "/user/repos", token, body)


def delete_repo(token, owner, repo):
    _req("DELETE", "%s/repos/%s/%s" % (API, owner, repo), token)
    return True


def get_default_branch(token, owner, repo):
    d = _req("GET", "%s/repos/%s/%s" % (API, owner, repo), token)
    return d.get("default_branch", "main")


# ---------------- 推文件（Contents API）----------------
def _get_sha(token, owner, repo, path):
    try:
        d = _req("GET", "%s/repos/%s/%s/contents/%s" % (API, owner, repo, path), token)
        return d.get("sha")
    except RuntimeError:
        return None


def push_file(token, owner, repo, path, content_bytes, msg="add %s" % ""):
    sha = _get_sha(token, owner, repo, path)
    payload = {
        "message": msg or ("add %s" % path),
        "content": base64.b64encode(content_bytes).decode("ascii"),
        "branch": get_default_branch(token, owner, repo),
    }
    if sha:
        payload["sha"] = sha
    body = json.dumps(payload)
    return _req("PUT", "%s/repos/%s/%s/contents/%s" % (API, owner, repo, path), token, body)


# ---------------- 触发工作流 ----------------
def dispatch_workflow(token, owner, repo, workflow_file, ref="main"):
    body = json.dumps({"ref": ref})
    return _req("POST",
                "%s/repos/%s/%s/actions/workflows/%s/dispatches"
                % (API, owner, repo, workflow_file), token, body)


def list_runs(token, owner, repo):
    d = _req("GET", "%s/repos/%s/%s/actions/runs?per_page=5" % (API, owner, repo), token)
    return d.get("workflow_runs", [])


def get_run(token, owner, repo, run_id):
    return _req("GET", "%s/repos/%s/%s/actions/runs/%s" % (API, owner, repo, run_id), token)


def download_run_logs(token, owner, repo, run_id):
    """返回合并后的日志文本（Actions 日志接口给的是 zip）。"""
    url = "%s/repos/%s/%s/actions/runs/%s/logs" % (API, owner, repo, run_id)
    body, _ = _req("GET", url, token, raw=True, binary=True)
    try:
        z = zipfile.ZipFile(io.BytesIO(body))
        parts = []
        for n in sorted(z.namelist()):
            parts.append("==== %s ====" % n)
            parts.append(z.read(n).decode("utf-8", "replace"))
        return "\n".join(parts)
    except zipfile.BadZipFile:
        return body.decode("utf-8", "replace")


# ---------------- 产物 ----------------
def list_artifacts(token, owner, repo, run_id):
    d = _req("GET",
             "%s/repos/%s/%s/actions/runs/%s/artifacts" % (API, owner, repo, run_id),
             token)
    return d.get("artifacts", [])


def download_artifact(token, url):
    """下载产物 zip。首请求带 Authorization 拿 GitHub 签名跳转；
    重定向到 Azure blob 时由 _StripAuthRedirect 自动剥离 token。"""
    headers = {"Authorization": "Bearer %s" % token,
               "User-Agent": UA["User-Agent"],
               "Accept": "application/vnd.github+json"}
    req = urllib.request.Request(url, headers=headers)
    with _artifact_opener.open(req, timeout=120) as r:
        return r.read()  # zip bytes


def save_artifact_zip(path, data):
    with open(path, "wb") as f:
        f.write(data)
