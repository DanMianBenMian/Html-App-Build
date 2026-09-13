# -*- coding: utf-8 -*-
"""
TWNativePack —— 云端构建模板（iOS / Android）。
设计原则：工具只需往临时仓库推 4 个文件：
  1) .github/workflows/ios-build.yml 或 android-build.yml  (本文件内容)
  2) config.json   (app 名 / bundle id / 权限)
  3) app.html      (TurboWarp 单文件产物)
  4) icon.png      (用户选的图标，工作流里 resize)
工作流内部用 heredoc + python 生成完整 Xcode / Gradle 工程并出包。
所有占位符用 __APP_NAME__ / __BUNDLE_ID__ 等，由 build_core 做 .replace()。
"""

# ---------------------------------------------------------------------------
# 统一权限定义（iOS Info.plist 键 + Android 权限串）
# 顺序即 GUI 勾选框顺序；单平台独有项在另一平台留空列表（勾选后不产生该平台声明）。
# 取值: key -> (中文标签, [iOS usage keys], [Android permission strings])
# ---------------------------------------------------------------------------
PERMISSION_DEFS = {
    'camera':       ('相机', ['NSCameraUsageDescription'], ['android.permission.CAMERA']),
    'microphone':   ('麦克风', ['NSMicrophoneUsageDescription'], ['android.permission.RECORD_AUDIO']),
    'photolibrary': ('照片 / 媒体库',
                     ['NSPhotoLibraryUsageDescription', 'NSPhotoLibraryAddUsageDescription'],
                     ['android.permission.READ_MEDIA_IMAGES', 'android.permission.READ_MEDIA_VIDEO',
                      'android.permission.READ_EXTERNAL_STORAGE', 'android.permission.WRITE_EXTERNAL_STORAGE']),
    'bluetooth':    ('蓝牙', ['NSBluetoothAlwaysUsageDescription'],
                     ['android.permission.BLUETOOTH', 'android.permission.BLUETOOTH_CONNECT',
                      'android.permission.BLUETOOTH_SCAN', 'android.permission.BLUETOOTH_ADVERTISE']),
    'location':     ('定位',
                     ['NSLocationWhenInUseUsageDescription', 'NSLocationAlwaysAndWhenInUseUsageDescription'],
                     ['android.permission.ACCESS_FINE_LOCATION', 'android.permission.ACCESS_COARSE_LOCATION']),
    'contacts':     ('通讯录', ['NSContactsUsageDescription'],
                     ['android.permission.READ_CONTACTS', 'android.permission.WRITE_CONTACTS', 'android.permission.GET_ACCOUNTS']),
    'calendar':     ('日历', ['NSCalendarsUsageDescription'],
                     ['android.permission.READ_CALENDAR', 'android.permission.WRITE_CALENDAR']),
    'reminders':    ('提醒事项', ['NSRemindersUsageDescription'], []),
    'motion':       ('运动与健身 (计步)', ['NSMotionUsageDescription'], ['android.permission.ACTIVITY_RECOGNITION']),
    'health':       ('健康', ['NSHealthShareUsageDescription', 'NSHealthUpdateUsageDescription'], []),
    'media':        ('音乐 / 媒体库', ['NSAppleMusicUsageDescription'], ['android.permission.READ_MEDIA_AUDIO']),
    'speech':       ('语音识别', ['NSSpeechRecognitionUsageDescription'], []),
    'siri':         ('Siri', ['NSSiriUsageDescription'], []),
    'faceid':       ('面容 ID / 生物识别', ['NSFaceIDUsageDescription'],
                     ['android.permission.USE_BIOMETRIC', 'android.permission.USE_FINGERPRINT']),
    'localnetwork': ('本地网络', ['NSLocalNetworkUsageDescription'],
                     ['android.permission.INTERNET', 'android.permission.ACCESS_NETWORK_STATE', 'android.permission.ACCESS_WIFI_STATE']),
    'homekit':      ('家庭 (HomeKit)', ['NSHomeKitUsageDescription'], []),
    'focus':        ('专注模式', ['NSFocusStatusUsageDescription'], []),
    'tracking':     ('应用跟踪 (ATT)', ['NSUserTrackingUsageDescription'], ['com.google.android.gms.permission.AD_ID']),
    'nearby':       ('近场交互 (U1)', ['NSNearbyInteractionUsageDescription'], ['android.permission.NEARBY_WIFI_DEVICES']),
    'calllog':      ('通话记录', [],
                     ['android.permission.READ_CALL_LOG', 'android.permission.WRITE_CALL_LOG', 'android.permission.READ_PHONE_NUMBERS']),
    'sms':          ('短信', [],
                     ['android.permission.SEND_SMS', 'android.permission.RECEIVE_SMS', 'android.permission.READ_SMS',
                      'android.permission.RECEIVE_WAP_PUSH', 'android.permission.RECEIVE_MMS']),
    'phone':        ('电话 / 通话', [],
                     ['android.permission.READ_PHONE_STATE', 'android.permission.CALL_PHONE',
                      'android.permission.USE_SIP', 'android.permission.PROCESS_OUTGOING_CALLS']),
    'nfc':          ('NFC', [], ['android.permission.NFC']),
    'notification': ('通知', [], ['android.permission.POST_NOTIFICATIONS']),
    'sensors':      ('身体传感器', [], ['android.permission.BODY_SENSORS']),
}


# ---------------------------------------------------------------------------
# iOS 工作流（macos-latest runner，XcodeGen + xcodebuild 出未签名 IPA）
# ---------------------------------------------------------------------------
IOS_WORKFLOW = r"""name: twpack-ios

on:
  workflow_dispatch:

jobs:
  build:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install xcodegen
        run: brew install xcodegen

      - name: Generate Xcode project from config
        run: |
          set -x
          python3 make_project.py

      - name: Generate Xcode project
        run: |
          set -x
          xcodegen generate

      - name: Build archive (unsigned)
        run: |
          set -ex
          APP=$(cat app_name.txt)          # 显示名（可含中文）→ 只用于 .ipa 文件名
          BUNDLE=$(cat bundle_name.txt)    # 包内部名（纯 ASCII）→ 用于 .app 目录名
          echo "ipa filename = ${APP} ; bundle name (ASCII) = ${BUNDLE}"
          xcodebuild -project App.xcodeproj -scheme App -configuration Release \
            archive -archivePath build/App.xcarchive \
            -destination 'generic/platform=iOS' \
            CODE_SIGN_IDENTITY="" CODE_SIGNING_REQUIRED=NO CODE_SIGNING_ALLOWED=NO
          mkdir -p Payload
          cp -r "build/App.xcarchive/Products/Applications/${BUNDLE}.app" Payload/
          rm -rf Payload/*.app/_CodeSignature Payload/*.app/embedded.mobileprovision 2>/dev/null || true
          zip -r -X "${APP}.ipa" Payload
          ls -la *.ipa
          echo "--- zip 内条目（必须全为 ASCII，否则 Windows 侧签名工具会解压失败）---"
          unzip -l "${APP}.ipa"

      - name: Upload IPA
        uses: actions/upload-artifact@v4
        with:
          name: twpack-ios
          path: '*.ipa'
"""

# iOS 工程的生成脚本（被工作流调用，读取 config.json + app.html + icon.png）
IOS_MAKER = r"""import json, os, subprocess, shutil, io, re

cfg = json.load(open('config.json'))
APP_NAME = cfg.get('name', 'TWPackApp')
BUNDLE_ID = cfg.get('bundle_id', 'com.twpack.app')
PERMS = cfg.get('permissions', [])
ORIENT = cfg.get('orientation', 'auto')          # portrait | landscape | auto

# ---- 来源模式：单文件 app.html 或 文件夹 app.zip ----
SOURCE_MODE = cfg.get('source_mode', 'file')      # 'file' | 'folder'
ENTRY_HTML = cfg.get('entry_html') or 'index.html'
import zipfile as _zf
if SOURCE_MODE == 'folder':
    if os.path.exists('app.zip'):
        _zf.ZipFile('app.zip').extractall('app')
        print('已解压 app.zip -> app/')
    _web_entry = 'app/%s' % ENTRY_HTML
    if not os.path.exists(_web_entry):
        raise SystemExit('ERROR: 入口文件缺失 %s' % _web_entry)
    print('文件夹模式：入口 =', _web_entry)
else:
    if not os.path.exists('app.html'):
        raise SystemExit('ERROR: 仓库里找不到 app.html，无法打包')
    _web_entry = 'app.html'
    print('单文件模式：app.html')

# ---- 注入原生桥接 polyfill（让保存/打开/新窗口/插件在 WKWebView 可用）----
# 注入位置很关键：插在 </head> 之前，而不是紧跟 <head>。
# 原因：bridge 有 4KB+，紧跟 <head> 会把 <meta charset> 挤出浏览器 1024 字节
# 预扫描窗口 -> 整页（含 index.js）按错误编码解析 -> 中文乱码/脚本异常。
# 插在 </head> 之前：charset 仍在文件最前，且 bridge 依然早于 <script src="index.js">。
try:
    _bridge_path = 'tw_bridge.js'
    if os.path.exists(_bridge_path) and os.path.exists(_web_entry):
        _bjs = io.open(_bridge_path, encoding='utf-8').read()
        _html = io.open(_web_entry, encoding='utf-8', errors='replace').read()
        if 'tw_bridge_v1' not in _html:
            _wrapped = '\n<!-- tw_bridge native polyfill -->\n<script>\n' + _bjs + '\n</script>\n'
            _m_end = re.search(r'</head\s*>', _html, re.IGNORECASE)
            _pos = None
            if _m_end:
                _pos = _m_end.start()
            else:
                _m_head = re.search(r'<head[^>]*>', _html, re.IGNORECASE)
                if _m_head:
                    _pos = _m_head.end()
            if _pos is not None:
                _html = _html[:_pos] + _wrapped + _html[_pos:]
                # 自检：charset 声明必须仍在浏览器 1024 字节预扫描窗口内
                _probe = _html[:1024].lower()
                if 'charset' not in _probe:
                    print('WARNING: <meta charset> 不在前 1024 字节内，可能出现编码异常')
                io.open(_web_entry, 'w', encoding='utf-8').write(_html)
                print('已注入 tw_bridge 到', _web_entry, '(@', _pos, ')')
            else:
                print('WARNING: 入口 HTML 无 <head>/</head>，未注入 bridge')
        else:
            print('bridge 已存在，跳过注入')
    else:
        print('WARNING: 缺少 tw_bridge.js 或入口 HTML，未注入 bridge')
except Exception as _e:
    print('bridge 注入异常（忽略）:', _e)

# ---- 旋转方向 -> UISupportedInterfaceOrientations ----
ORIENT_MAP = {
    'portrait':  ['UIInterfaceOrientationPortrait'],
    'landscape': ['UIInterfaceOrientationLandscapeLeft', 'UIInterfaceOrientationLandscapeRight'],
    'auto':      ['UIInterfaceOrientationPortrait',
                  'UIInterfaceOrientationLandscapeLeft',
                  'UIInterfaceOrientationLandscapeRight'],
}
_ori = ORIENT_MAP.get(ORIENT) or ORIENT_MAP['auto']
if ORIENT not in ORIENT_MAP:
    print('未知旋转方向 %r，按 auto 处理' % ORIENT)

def _ori_array(key):
    s = '  <key>%s</key>\n  <array>\n' % key
    for o in _ori:
        s += '    <string>%s</string>\n' % o
    return s + '  </array>\n'

# 同时写通用键与 ~ipad 键：iPad 上以 ~ipad 为准，缺了会退回通用键
ORIENTS_XML = (_ori_array('UISupportedInterfaceOrientations')
               + _ori_array('UISupportedInterfaceOrientations~ipad')).rstrip('\n')
print('旋转方向:', ORIENT, '->', _ori)

# ---- 显示名（可含中文；用于 .ipa 文件名 / 图标下显示名）----
import re as _re
def _safe_filename(s):
    s = _re.sub(r'[\\/:*?"<>|\x00-\x1f]', '', s).strip().strip('.')
    return s or 'TWApp'
SAFE_NAME = _safe_filename(APP_NAME)
open('app_name.txt', 'w').write(SAFE_NAME)

# ---- ASCII 片段工具 ----
def _ascii_slug(s, lower=False):
    if lower:
        s = (s or '').lower()
    return ''.join(c for c in (s or '') if c.isascii() and c.isalnum())

# ---- 包名清洗（必须 ASCII 且至少两段）----
# ★ 中文名经 Python isalnum() 判定为真，会生成 com.twpack.示例项目 这种**非法包名**
# ★ 只要原始值被清洗过（含非法字符），就整体重新生成 —— 否则 com.twpack.示例项目 会被
#   截成 com.twpack 这种"结构合法但没意义"的包名，导致所有此类 App 互相撞包名。
_raw_bid = BUNDLE_ID.strip()
_cleaned = ''.join(c for c in _raw_bid if c.isascii() and (c.isalnum() or c in '.-'))
_cleaned = '.'.join(p for p in _cleaned.split('.') if p)
_segs = [p for p in _cleaned.split('.') if p]
if _raw_bid and _cleaned == _raw_bid and len(_segs) >= 2 and all(p[0].isalpha() for p in _segs):
    BUNDLE_ID = _cleaned
else:
    BUNDLE_ID = 'com.twpack.%s' % (_ascii_slug(APP_NAME, lower=True) or 'app')
    print('包名非法，已重新生成:', BUNDLE_ID)

# ---- 包内部名（必须纯 ASCII！）----
# ★ 关键：.app 目录名/可执行文件名含中文时，macOS 的 zip 会写出「不带 UTF-8 标志」的
#   中文条目，Windows 侧签名工具按 GBK 解析 → 文件名乱码 → 解压失败。
#   所以包内部一律用 ASCII 名；桌面显示的中文名由 CFBundleDisplayName 决定，与此无关。
BUNDLE_NAME = (_ascii_slug(APP_NAME)
               or _ascii_slug(BUNDLE_ID.split('.')[-1]).capitalize()
               or 'App')
if not BUNDLE_NAME[0].isalpha():
    BUNDLE_NAME = 'App' + BUNDLE_NAME
open('bundle_name.txt', 'w').write(BUNDLE_NAME)
print('显示名:', SAFE_NAME, '| 包内部名(ASCII):', BUNDLE_NAME)

# XML 转义（应用名可能含 & < > 等，直接写进 plist 会破坏 XML）
APP_NAME_XML = APP_NAME.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

# ---- 无图标时生成默认占位 PNG（避免 xcodegen 报 missing source）----
if not os.path.exists('icon.png'):
    import zlib as _zlib, struct as _struct
    def _make_png(path, size=1024, color=(60, 120, 240)):
        w = h = size
        raw = b''
        for _ in range(h):
            raw += b'\x00' + bytes(color) * w
        def _chunk(typ, data):
            c = typ + data
            return _struct.pack('>I', len(data)) + c + _struct.pack('>I', _zlib.crc32(c) & 0xffffffff)
        sig = b'\x89PNG\r\n\x1a\n'
        ihdr = _struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
        idat = _zlib.compress(raw, 9)
        open(path, 'wb').write(sig + _chunk(b'IHDR', ihdr) + _chunk(b'IDAT', idat) + _chunk(b'IEND', b''))
    _make_png('icon.png')
    print('未提供图标，已生成默认占位图标 (1024x1024)')

# ---- 权限 -> iOS Info.plist 键 ----
PERMISSION_DEFS = {
    'camera':       ('相机', ['NSCameraUsageDescription'], []),
    'microphone':   ('麦克风', ['NSMicrophoneUsageDescription'], []),
    'photolibrary': ('照片 / 媒体库', ['NSPhotoLibraryUsageDescription', 'NSPhotoLibraryAddUsageDescription'], []),
    'bluetooth':    ('蓝牙', ['NSBluetoothAlwaysUsageDescription'], []),
    'location':     ('定位', ['NSLocationWhenInUseUsageDescription', 'NSLocationAlwaysAndWhenInUseUsageDescription'], []),
    'contacts':     ('通讯录', ['NSContactsUsageDescription'], []),
    'calendar':     ('日历', ['NSCalendarsUsageDescription'], []),
    'reminders':    ('提醒事项', ['NSRemindersUsageDescription'], []),
    'motion':       ('运动与健身 (计步)', ['NSMotionUsageDescription'], []),
    'health':       ('健康', ['NSHealthShareUsageDescription', 'NSHealthUpdateUsageDescription'], []),
    'media':        ('音乐 / 媒体库', ['NSAppleMusicUsageDescription'], []),
    'speech':       ('语音识别', ['NSSpeechRecognitionUsageDescription'], []),
    'siri':         ('Siri', ['NSSiriUsageDescription'], []),
    'faceid':       ('面容 ID / 生物识别', ['NSFaceIDUsageDescription'], []),
    'localnetwork': ('本地网络', ['NSLocalNetworkUsageDescription'], []),
    'homekit':      ('家庭 (HomeKit)', ['NSHomeKitUsageDescription'], []),
    'focus':        ('专注模式', ['NSFocusStatusUsageDescription'], []),
    'tracking':     ('应用跟踪 (ATT)', ['NSUserTrackingUsageDescription'], []),
    'nearby':       ('近场交互 (U1)', ['NSNearbyInteractionUsageDescription'], []),
    'calllog':      ('通话记录', [], []),
    'sms':          ('短信', [], []),
    'phone':        ('电话 / 通话', [], []),
    'nfc':          ('NFC', [], []),
    'notification': ('通知', [], []),
    'sensors':      ('身体传感器', [], []),
}

USAGE_KEYS = []
for _key, (_label, _ios_keys, _android_keys) in PERMISSION_DEFS.items():
    if _key in PERMS:
        for _k in _ios_keys:
            USAGE_KEYS.append((_k, '%s 需要访问%s' % (APP_NAME_XML, _label)))

usage_xml = ''
for k, v in USAGE_KEYS:
    usage_xml += '  <key>%s</key>\n  <string>%s</string>\n' % (k, v)

info_plist = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>__APP_NAME__</string>
  <key>CFBundleDisplayName</key>
  <string>__APP_NAME__</string>
  <key>CFBundleExecutable</key>
  <string>__BUNDLE_NAME__</string>
  <key>CFBundleIdentifier</key>
  <string>__BUNDLE_ID__</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>LSRequiresIPhoneOS</key>
  <true/>
__ORIENTS__
  <key>UILaunchScreen</key>
  <dict/>
  <key>UIRequiresFullScreen</key>
  <true/>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsArbitraryLoads</key>
    <true/>
  </dict>
__USAGE__
</dict>
</plist>
'''
# 注意：这里必须用 str.replace（占位符是 __XXX__ 形式，不是 %(key)s，用 % 字典格式化不会生效）
info_plist = (info_plist
              .replace('__APP_NAME__', APP_NAME_XML)
              .replace('__BUNDLE_NAME__', BUNDLE_NAME)
              .replace('__BUNDLE_ID__', BUNDLE_ID)
              .replace('__ORIENTS__', ORIENTS_XML)
              .replace('__USAGE__', usage_xml.rstrip('\n')))
open('Info.plist', 'w').write(info_plist)

# ---- entitlements（仅 get-task-allow，未签名侧载够用）----
open('App.entitlements', 'w').write('''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>get-task-allow</key>
  <true/>
</dict>
</plist>
''')

# ---- project.yml (XcodeGen) ----
# ⚠️ 文件夹模式必须用 folder reference（type: folder）整体拷贝目录。
#    绝不能用默认的 group：group 会把目录里所有文件逐个塞进 Resources 阶段并
#    **扁平铺到 bundle 根目录**，于是：
#      1) 不同子目录下的同名文件（如 blocks-media/default/zoom-in.svg 与
#         high-contrast/zoom-in.svg）会被两条 CpResource 命令抢同一个输出名，
#         直接报 `error: Multiple commands produce '...app/zoom-in.svg'` —— 构建失败；
#      2) 即便不重名，相对目录结构也被抹平，网页里的 static/... 相对路径全部失效。
if SOURCE_MODE == 'folder':
    app_source_block = ('      - path: app\n'
                        '        buildPhase: resources\n'
                        '        type: folder')
else:
    app_source_block = ('      - path: app.html\n'
                        '        buildPhase: resources')
project_yml = '''name: App
options:
  bundleIdPrefix: com.twpack
  deploymentTarget:
    iOS: "15.0"
targets:
  App:
    type: application
    platform: iOS
    sources:
      - path: App.swift
__APP_SOURCE_BLOCK__
      - path: icon.png
        buildPhase: resources
      - path: Assets.xcassets
        buildPhase: resources
    entitlements:
      path: App.entitlements
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: __BUNDLE_ID__
        PRODUCT_NAME: __BUNDLE_NAME__
        ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon
        INFOPLIST_FILE: Info.plist
        GENERATE_INFOPLIST_FILE: NO
        CODE_SIGN_ENTITLEMENTS: App.entitlements
'''.replace('__BUNDLE_ID__', BUNDLE_ID).replace('__BUNDLE_NAME__', BUNDLE_NAME) \
  .replace('__APP_SOURCE_BLOCK__', app_source_block)
open('project.yml', 'w').write(project_yml)

# ---- App.swift (WKWebView 加载 app.html) ----
app_swift = r'''import UIKit
import WebKit
import UniformTypeIdentifiers

@main
class AppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        window = UIWindow(frame: UIScreen.main.bounds)
        window?.rootViewController = ViewController()
        window?.makeKeyAndVisible()
        return true
    }
}

class ViewController: UIViewController, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, WKDownloadDelegate {
    var webView: WKWebView!
    var entryURL: URL!
    var readAccessURL: URL!

    override func loadView() {
        let config = Self.makeConfig(handler: self)
        let resURL = Bundle.main.resourceURL!
        entryURL = resURL.appendingPathComponent("__WEB_ENTRY__")
        readAccessURL = __READ_ACCESS__
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.scrollView.bounces = false
        webView.allowsLinkPreview = false
        view = webView
    }

    static func makeConfig(handler: WKScriptMessageHandler) -> WKWebViewConfiguration {
        let config = WKWebViewConfiguration()
        config.preferences.javaScriptEnabled = true
        config.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        config.setValue(true, forKey: "allowUniversalAccessFromFileURLs")
        if #available(iOS 14.0, *) {
            config.defaultWebpagePreferences.allowsContentJavaScript = true
        }
        let uc = WKUserContentController()
        uc.add(handler, name: "twBridge")
        let errJS = "(function(){function post(m){try{window.webkit.messageHandlers.twBridge.postMessage({type:'err',msg:String(m)});}catch(e){}}window.onerror=function(msg,src,line,col){post('JSERR: '+msg+' @'+(src||'')+':'+line+':'+col);return false;};window.addEventListener('unhandledrejection',function(ev){var r=ev.reason;post('PROMISE: '+(r&&r.message?r.message:(r||'')));});})();"
        uc.addUserScript(WKUserScript(source: errJS, injectionTime: .atDocumentStart, forMainFrameOnly: false))
        config.userContentController = uc
        return config
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        webView.loadFileURL(entryURL, allowingReadAccessTo: readAccessURL)
    }

    deinit {
        webView?.configuration.userContentController.removeScriptMessageHandler(forName: "twBridge")
    }

    // MARK: - bridge: web -> native
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any] else { return }
        let type = body["type"] as? String ?? ""
        let id = body["id"] as? String ?? ""
        let src = message.webView
        if type == "save" {
            if let name = body["name"] as? String, let b64 = body["data"] as? String {
                saveFile(name: name, base64: b64)
                complete(webView: src, id: id, result: true)
            } else {
                complete(webView: src, id: id, error: "save: 参数缺失")
            }
        } else if type == "open" {
            pickFile { (name, data, mime) in
                guard let name = name, let data = data else {
                    self.complete(webView: src, id: id, error: "用户取消或未选择文件")
                    return
                }
                let s = data.base64EncodedString()
                self.complete(webView: src, id: id, result: ["name": name, "data": s, "mime": mime ?? "application/octet-stream"])
            }
        } else if type == "err" {
            if let m = body["msg"] as? String { showError(m) }
        }
    }

    func complete(webView: WKWebView?, id: String, result: Any? = nil, error: String? = nil) {
        guard !id.isEmpty, let wv = webView else { return }
        var payload: [String: Any] = [:]
        if let e = error { payload["error"] = e } else { payload["result"] = result ?? true }
        guard let json = try? JSONSerialization.data(withJSONObject: payload),
              let s = String(data: json, encoding: .utf8) else { return }
        let js = "window.__twComplete('" + id + "', " + s + ")"
        wv.evaluateJavaScript(js, completionHandler: nil)
    }

    // MARK: - present 辅助（兼容 iPad 弹窗锚点）
    func presentVC(_ vc: UIViewController) {
        guard let window = UIApplication.shared.windows.first else { return }
        var presenter = window.rootViewController
        while let p = presenter?.presentedViewController { presenter = p }
        if let pop = vc.popoverPresentationController {
            pop.sourceView = presenter?.view ?? window
            pop.sourceRect = (presenter?.view ?? window).bounds
        }
        presenter?.present(vc, animated: true)
    }

    func showError(_ msg: String) {
        DispatchQueue.main.async {
            if let lb = self.view.viewWithTag(9911) as? UILabel {
                lb.text = msg
                return
            }
            let lb = UILabel()
            lb.tag = 9911
            lb.numberOfLines = 0
            lb.lineBreakMode = .byCharWrapping
            lb.backgroundColor = UIColor.red.withAlphaComponent(0.92)
            lb.textColor = .white
            lb.font = UIFont.systemFont(ofSize: 13)
            lb.text = "加载错误:\n" + msg
            lb.textAlignment = .left
            lb.layer.cornerRadius = 6
            lb.clipsToBounds = true
            let w = self.view.bounds.width - 16
            lb.frame = CGRect(x: 8, y: 30, width: w, height: 140)
            lb.autoresizingMask = [.flexibleWidth]
            self.view.addSubview(lb)
        }
    }

    func saveFile(name: String, base64: String) {
        guard let data = Data(base64Encoded: base64) else { return }
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent(name)
        try? data.write(to: tmp)
        DispatchQueue.main.async { self.presentVC(UIActivityViewController(activityItems: [tmp], applicationActivities: nil)) }
    }

    func pickFile(completion: @escaping (String?, Data?, String?) -> Void) {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [UTType.data, UTType.item])
        picker.allowsMultipleSelection = false
        picker.delegate = DocumentPickerProxy(completion: completion)
        DispatchQueue.main.async { self.presentVC(picker) }
    }

    // MARK: - 新窗口（文件-新窗口 / 外部链接）
    func webView(_ webView: WKWebView, createWebViewWithConfiguration configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        let newConfig = Self.makeConfig(handler: self)
        let newWebView = WKWebView(frame: .zero, configuration: newConfig)
        newWebView.navigationDelegate = self
        newWebView.uiDelegate = self
        newWebView.scrollView.bounces = false
        let vc = UIViewController()
        vc.view = newWebView
        DispatchQueue.main.async { self.presentVC(vc) }
        return newWebView
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        showError("导航失败(provisional): " + error.localizedDescription)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        showError("加载失败: " + error.localizedDescription)
    }

    // MARK: - JS 原生对话框（alert / confirm / prompt）
    // WKWebView 默认不弹这些框；不实现代理方法时 confirm 会直接返回 false，
    // 导致 TurboWarp 加载扩展时的「与 Scratch 不兼容，是否继续」确认框在 iPad 上
    // 既不显示、扩展也永远加载不了。这里用系统弹窗呈现，并正确回调 completionHandler。
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let ac = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        ac.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler() })
        DispatchQueue.main.async { self.presentVC(ac) }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let ac = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        ac.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(false) })
        ac.addAction(UIAlertAction(title: "Continue", style: .default) { _ in completionHandler(true) })
        DispatchQueue.main.async { self.presentVC(ac) }
    }
    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let ac = UIAlertController(title: nil, message: prompt, preferredStyle: .alert)
        ac.addTextField { $0.text = defaultText }
        ac.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(nil) })
        ac.addAction(UIAlertAction(title: "OK", style: .default) { _ in
            completionHandler(ac.textFields?.first?.text ?? defaultText)
        })
        DispatchQueue.main.async { self.presentVC(ac) }
    }

    // MARK: - 下载兜底（<a download>）
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent(suggestedFilename)
        completionHandler(tmp)
    }
    func downloadDidFinish(_ download: WKDownload) {
        if let url = download.originalRequest?.url {
            DispatchQueue.main.async { self.presentVC(UIActivityViewController(activityItems: [url], applicationActivities: nil)) }
        }
    }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {}
}

class DocumentPickerProxy: NSObject, UIDocumentPickerDelegate {
    let completion: (String?, Data?, String?) -> Void
    init(completion: @escaping (String?, Data?, String?) -> Void) { self.completion = completion }
    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        guard let url = urls.first else { completion(nil, nil, nil); return }
        let name = url.lastPathComponent
        let mime = (try? url.resourceValues(forKeys: [.contentTypeKey]))?.contentType?.identifier ?? "application/octet-stream"
        if let data = try? Data(contentsOf: url) { completion(name, data, mime) }
        else { completion(nil, nil, nil) }
    }
    func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) { completion(nil, nil, nil) }
}
'''
if SOURCE_MODE == 'folder':
    read_access = 'resURL.appendingPathComponent("app")'
else:
    read_access = 'entryURL.deletingLastPathComponent()'
open('App.swift', 'w').write(
    app_swift.replace('__WEB_ENTRY__', _web_entry).replace('__READ_ACCESS__', read_access))

# ---- 图标资源目录（sips resize 成各尺寸）----
os.makedirs('Assets.xcassets/AppIcon.appiconset', exist_ok=True)
specs = [
    (20, 'icon-20'), (29, 'icon-29'), (40, 'icon-40'), (58, 'icon-58'),
    (60, 'icon-60'), (76, 'icon-76'), (80, 'icon-80'), (87, 'icon-87'),
    (120, 'icon-120'), (152, 'icon-152'), (167, 'icon-167'), (180, 'icon-180'),
    (1024, 'icon-1024'),
]
contents = {'images': [], 'info': {'author': 'xcode', 'version': 1}}
if os.path.exists('icon.png'):
    for size, name in specs:
        out = 'Assets.xcassets/AppIcon.appiconset/%s.png' % name
        try:
            subprocess.run(['sips', '-z', str(size), str(size), 'icon.png',
                            '--out', out], check=False)
        except (FileNotFoundError, OSError):
            # sips 仅存在于 macOS；非 macOS 开发/测试环境跳过图标缩放，
            # 真实云端（macos runner）仍会正常缩放生成各尺寸图标。
            pass
        contents['images'].append({'idiom': 'universal', 'size': '%dx%d' % (size, size),
                                   'scale': '1x', 'filename': '%s.png' % name})
else:
    contents['images'].append({'idiom': 'universal', 'size': '1024x1024',
                               'scale': '1x', 'filename': ''})
open('Assets.xcassets/AppIcon.appiconset/Contents.json', 'w').write(json.dumps(contents, indent=2))
open('Assets.xcassets/Contents.json', 'w').write(
    json.dumps({'info': {'author': 'xcode', 'version': 1}}, indent=2))

print('iOS project generated for', APP_NAME, BUNDLE_ID, 'perms=', PERMS)
"""

# ---------------------------------------------------------------------------
# Android 工作流（ubuntu-latest + Android SDK，Gradle 出可装 APK）
# ---------------------------------------------------------------------------
ANDROID_WORKFLOW = r"""name: twpack-android

on:
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '17'

      - name: Setup Android SDK
        uses: android-actions/setup-android@v3

      - name: Install SDK platform & build-tools
        run: |
          set -ex
          yes | sdkmanager --licenses >/dev/null 2>&1 || true
          sdkmanager "platforms;android-34" "build-tools;34.0.0"

      - name: Install Gradle 8.2 (this project has no wrapper on purpose)
        run: |
          set -ex
          curl -sSL -o /tmp/gradle.zip https://services.gradle.org/distributions/gradle-8.2-bin.zip
          unzip -q /tmp/gradle.zip -d /opt
          echo "/opt/gradle-8.2/bin" >> "$GITHUB_PATH"
          /opt/gradle-8.2/bin/gradle --version

      - name: Generate Android project from config
        run: |
          set -ex
          python3 -m pip install --quiet --upgrade pillow
          python3 -c "import PIL; print('pillow', PIL.__version__)"
          python3 make_project.py
          python3 make_icons.py
          echo "--- generated launcher icons ---"
          find app/src/main/res -name 'ic_launcher*' | sort

      - name: Build APK (debug-signed release)
        run: |
          set -ex
          gradle assembleRelease --no-daemon --stacktrace
          ls -la app/build/outputs/apk/release/

      - name: Rename APK to app name
        run: |
          set -ex
          APP=$(cat app_name.txt)
          echo "application name = ${APP}"
          SRC=$(ls app/build/outputs/apk/release/*.apk | grep -v -- '-unsigned' | head -n1)
          mv "$SRC" "app/build/outputs/apk/release/${APP}.apk"
          ls -la app/build/outputs/apk/release/

      - name: Upload APK
        uses: actions/upload-artifact@v4
        with:
          name: twpack-android
          path: app/build/outputs/apk/release/*.apk
"""

# Android 工程生成脚本（写 Gradle / Manifest / MainActivity / res）
ANDROID_MAKER = r"""import json, os

cfg = json.load(open('config.json'))
APP_NAME = cfg.get('name', 'TWPackApp')
BUNDLE_ID = cfg.get('bundle_id', 'com.twpack.app')
PERMS = cfg.get('permissions', [])
ORIENT = cfg.get('orientation', 'auto')          # portrait | landscape | auto

# ---- 来源模式：单文件 app.html 或 文件夹 app.zip ----
SOURCE_MODE = cfg.get('source_mode', 'file')
ENTRY_HTML = cfg.get('entry_html') or 'index.html'
import zipfile as _zf
if SOURCE_MODE == 'folder':
    if os.path.exists('app.zip'):
        _zf.ZipFile('app.zip').extractall('web')
        print('已解压 app.zip -> web/')
    _entry_src = os.path.join('web', ENTRY_HTML)
    if not os.path.exists(_entry_src):
        raise SystemExit('ERROR: 入口文件缺失 web/%s' % ENTRY_HTML)
    print('文件夹模式：入口 =', _entry_src)
else:
    if not os.path.exists('app.html'):
        raise SystemExit('ERROR: 仓库里找不到 app.html，无法打包')
    print('单文件模式：app.html')

# ---- 旋转方向 -> android:screenOrientation ----
# auto 用 fullSensor：跟随重力传感器（忽略系统旋转锁），行为最可预期；
# 若想"尊重系统旋转锁"，把它改成 unspecified。
ORIENT_MAP = {'portrait': 'portrait', 'landscape': 'landscape', 'auto': 'fullSensor'}
ORIENT_ANDROID = ORIENT_MAP.get(ORIENT) or ORIENT_MAP['auto']
if ORIENT not in ORIENT_MAP:
    print('未知旋转方向 %r，按 auto 处理' % ORIENT)
print('旋转方向:', ORIENT, '-> android:screenOrientation=%s' % ORIENT_ANDROID)

# ---- 安全文件名（用于 APK 命名；保留中文与空格，仅剔除文件系统非法字符）----
import re as _re
def _safe_filename(s):
    s = _re.sub(r'[\\/:*?"<>|\x00-\x1f]', '', s).strip().strip('.')
    return s or 'TWApp'
SAFE_NAME = _safe_filename(APP_NAME)
open('app_name.txt', 'w').write(SAFE_NAME)
print('产物命名:', SAFE_NAME)

# ---- 包名清洗（Android applicationId / Java package 必须 ASCII）----
# ★ 中文名会让 Python 的 isalnum() 判定为真 → com.twpack.示例项目 这种非法包名，
#   且会生成中文目录的 MainActivity.java（Java 包名不允许非 ASCII）。
def _ascii_slug(s, lower=False):
    if lower:
        s = (s or '').lower()
    return ''.join(c for c in (s or '') if c.isascii() and c.isalnum())
_raw_bid = BUNDLE_ID.strip()
_cleaned = ''.join(c for c in _raw_bid if c.isascii() and (c.isalnum() or c in '.-'))
_cleaned = '.'.join(p for p in _cleaned.split('.') if p)
_segs = [p for p in _cleaned.split('.') if p]
if _raw_bid and _cleaned == _raw_bid and len(_segs) >= 2 and all(p[0].isalpha() for p in _segs):
    BUNDLE_ID = _cleaned
else:
    BUNDLE_ID = 'com.twpack.%s' % (_ascii_slug(APP_NAME, lower=True) or 'app')
    print('包名非法，已重新生成:', BUNDLE_ID)

# XML 转义（应用名可能含 & < > 等，直接写进 Manifest / strings.xml 会破坏 XML）
APP_NAME_XML = APP_NAME.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

# ---- 无图标时生成默认占位 PNG（供 make_icons.py 使用）----
if not os.path.exists('icon.png'):
    import zlib as _zlib, struct as _struct
    def _make_png(path, size=1024, color=(60, 120, 240)):
        w = h = size
        raw = b''
        for _ in range(h):
            raw += b'\x00' + bytes(color) * w
        def _chunk(typ, data):
            c = typ + data
            return _struct.pack('>I', len(data)) + c + _struct.pack('>I', _zlib.crc32(c) & 0xffffffff)
        sig = b'\x89PNG\r\n\x1a\n'
        ihdr = _struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
        idat = _zlib.compress(raw, 9)
        open(path, 'wb').write(sig + _chunk(b'IHDR', ihdr) + _chunk(b'IDAT', idat) + _chunk(b'IEND', b''))
    _make_png('icon.png')
    print('未提供图标，已生成默认占位图标 (1024x1024)')

PKG = BUNDLE_ID
PKG_PATH = '/'.join(PKG.split('.'))
os.makedirs('app/src/main/java/%s' % PKG_PATH, exist_ok=True)
os.makedirs('app/src/main/res/values', exist_ok=True)
os.makedirs('app/src/main/res/layout', exist_ok=True)
os.makedirs('app/src/main/assets', exist_ok=True)

# ---- 把 TurboWarp 产物放进 assets ----
# ★ 必须复制：MainActivity 加载的是 file:///android_asset/...，
#   少了这一步 APK 里就没有对应文件 → 打开即白屏（且构建不会报任何错）。
import shutil as _shutil
if SOURCE_MODE == 'folder':
    # 整个 app/ 目录拷贝进 assets/www/，入口为 www/<ENTRY_HTML>
    WWW = 'app/src/main/assets/www'
    os.makedirs(WWW, exist_ok=True)
    for _item in os.listdir('web'):
        _s = os.path.join('web', _item)
        _d = os.path.join(WWW, _item)
        if os.path.isdir(_s):
            _shutil.copytree(_s, _d, dirs_exist_ok=True)
        else:
            _shutil.copy(_s, _d)
    _web_url = 'file:///android_asset/www/%s' % ENTRY_HTML
    print('assets/www/%s (文件夹模式)' % ENTRY_HTML)
else:
    if not os.path.exists('app.html'):
        raise SystemExit('ERROR: 仓库里找不到 app.html，无法打包')
    _shutil.copy('app.html', 'app/src/main/assets/app.html')
    _web_url = 'file:///android_asset/app.html'
    print('assets/app.html =', os.path.getsize('app/src/main/assets/app.html'), 'bytes')

# ---- 权限映射 ----
PERMISSION_DEFS = {
    'camera':       ('相机', [], ['android.permission.CAMERA']),
    'microphone':   ('麦克风', [], ['android.permission.RECORD_AUDIO']),
    'photolibrary': ('照片 / 媒体库', [],
                     ['android.permission.READ_MEDIA_IMAGES', 'android.permission.READ_MEDIA_VIDEO',
                      'android.permission.READ_EXTERNAL_STORAGE', 'android.permission.WRITE_EXTERNAL_STORAGE']),
    'bluetooth':    ('蓝牙', [],
                     ['android.permission.BLUETOOTH', 'android.permission.BLUETOOTH_CONNECT',
                      'android.permission.BLUETOOTH_SCAN', 'android.permission.BLUETOOTH_ADVERTISE']),
    'location':     ('定位', [], ['android.permission.ACCESS_FINE_LOCATION', 'android.permission.ACCESS_COARSE_LOCATION']),
    'contacts':     ('通讯录', [], ['android.permission.READ_CONTACTS', 'android.permission.WRITE_CONTACTS', 'android.permission.GET_ACCOUNTS']),
    'calendar':     ('日历', [], ['android.permission.READ_CALENDAR', 'android.permission.WRITE_CALENDAR']),
    'reminders':    ('提醒事项', [], []),
    'motion':       ('运动与健身 (计步)', [], ['android.permission.ACTIVITY_RECOGNITION']),
    'health':       ('健康', [], []),
    'media':        ('音乐 / 媒体库', [], ['android.permission.READ_MEDIA_AUDIO']),
    'speech':       ('语音识别', [], []),
    'siri':         ('Siri', [], []),
    'faceid':       ('面容 ID / 生物识别', [], ['android.permission.USE_BIOMETRIC', 'android.permission.USE_FINGERPRINT']),
    'localnetwork': ('本地网络', [], ['android.permission.INTERNET', 'android.permission.ACCESS_NETWORK_STATE', 'android.permission.ACCESS_WIFI_STATE']),
    'homekit':      ('家庭 (HomeKit)', [], []),
    'focus':        ('专注模式', [], []),
    'tracking':     ('应用跟踪 (ATT)', [], ['com.google.android.gms.permission.AD_ID']),
    'nearby':       ('近场交互 (U1)', [], ['android.permission.NEARBY_WIFI_DEVICES']),
    'calllog':      ('通话记录', [],
                     ['android.permission.READ_CALL_LOG', 'android.permission.WRITE_CALL_LOG', 'android.permission.READ_PHONE_NUMBERS']),
    'sms':          ('短信', [],
                     ['android.permission.SEND_SMS', 'android.permission.RECEIVE_SMS', 'android.permission.READ_SMS',
                      'android.permission.RECEIVE_WAP_PUSH', 'android.permission.RECEIVE_MMS']),
    'phone':        ('电话 / 通话', [],
                     ['android.permission.READ_PHONE_STATE', 'android.permission.CALL_PHONE',
                      'android.permission.USE_SIP', 'android.permission.PROCESS_OUTGOING_CALLS']),
    'nfc':          ('NFC', [], ['android.permission.NFC']),
    'notification': ('通知', [], ['android.permission.POST_NOTIFICATIONS']),
    'sensors':      ('身体传感器', [], ['android.permission.BODY_SENSORS']),
}

ANDROID_PERMS = []
for _key, (_label, _ios_keys, _android_keys) in PERMISSION_DEFS.items():
    if _key in PERMS:
        for _p in _android_keys:
            ANDROID_PERMS.append(_p)

perm_xml = ''.join('  <uses-permission android:name="%s"/>\n' % p for p in ANDROID_PERMS)

manifest = '''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:tools="http://schemas.android.com/tools">
__PERMS__
  <application
      android:allowBackup="true"
      android:icon="@mipmap/ic_launcher"
      android:label="__APP_NAME__"
      android:theme="@style/AppTheme"
      android:usesCleartextTraffic="true"
      tools:targetApi="31">
    <activity
        android:name=".MainActivity"
        android:exported="true"
        android:configChanges="orientation|screenSize|keyboardHidden|screenLayout|smallestScreenSize|uiMode"
        android:screenOrientation="__ORIENT__">
      <intent-filter>
        <action android:name="android.intent.action.MAIN"/>
        <category android:name="android.intent.category.LAUNCHER"/>
      </intent-filter>
    </activity>
  </application>
</manifest>
'''.replace('__PERMS__', perm_xml).replace('__APP_NAME__', APP_NAME_XML).replace('__ORIENT__', ORIENT_ANDROID)
open('app/src/main/AndroidManifest.xml', 'w').write(manifest)

main_activity = '''package __PKG__;

import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebSettings;

public class MainActivity extends Activity {
    private WebView webView;
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        webView = new WebView(this);
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setAllowFileAccess(true);
        s.setAllowUniversalAccessFromFileURLs(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        webView.setWebViewClient(new WebViewClient());
        setContentView(webView);
        webView.loadUrl("__WEB_URL__");
    }
    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }
}
'''.replace('__PKG__', PKG).replace('__WEB_URL__', _web_url)
open('app/src/main/java/%s/MainActivity.java' % PKG_PATH, 'w').write(main_activity)

# res
open('app/src/main/res/values/strings.xml', 'w').write(
    '<resources><string name="app_name">%s</string></resources>' % APP_NAME_XML)
open('app/src/main/res/values/styles.xml', 'w').write(
    '<resources><style name="AppTheme" parent="android:Theme.Material.Light.NoActionBar"/></resources>')
open('app/src/main/res/layout/activity_main.xml', 'w').write(
    '<FrameLayout xmlns:android="http://schemas.android.com/apk/res/android" '
    'android:layout_width="match_parent" android:layout_height="match_parent"/>')

# build.gradle (app)
open('app/build.gradle', 'w').write('''apply plugin: 'com.android.application'

android {
    namespace '__PKG__'
    compileSdk 34
    defaultConfig {
        applicationId '__PKG__'
        minSdk 21
        targetSdk 34
        versionCode 1
        versionName "1.0"
    }
    buildTypes {
        release {
            signingConfig signingConfigs.debug
            minifyEnabled false
        }
    }
    compileOptions {
        sourceCompatibility JavaVersion.VERSION_17
        targetCompatibility JavaVersion.VERSION_17
    }
}

dependencies {}
'''.replace('__PKG__', PKG))

# root build.gradle + settings
open('build.gradle', 'w').write('''buildscript {
    repositories { google(); mavenCentral() }
    dependencies { classpath 'com.android.tools.build:gradle:8.2.2' }
}
allprojects { repositories { google(); mavenCentral() } }
''')
open('settings.gradle', 'w').write("rootProject.name = 'TWPack'\ninclude ':app'\n")
open('gradle.properties', 'w').write('org.gradle.jvmargs=-Xmx2048m\nandroid.useAndroidX=false\n')

print('Android project generated for', APP_NAME, PKG, 'perms=', PERMS)
"""

# Android 图标生成（Pillow，本地 resize 各密度）
# ⚠️ 不要生成 mipmap-anydpi-v26/ic_launcher.xml：空的 <adaptive-icon/> 缺 background/foreground
#    子节点，AAPT2 会报资源错误（即便不报也是无效资源）。直接给各密度 PNG 最稳。
ANDROID_ICONS = r"""import os, sys
from PIL import Image
sizes = {'mdpi': 48, 'hdpi': 72, 'xhdpi': 96, 'xxhdpi': 144, 'xxxhdpi': 192}
src = 'icon.png'
if not os.path.exists(src):
    sys.exit('ERROR: icon.png 不存在（make_project.py 应先生成占位图）')
im = Image.open(src).convert('RGBA')
for d, s in sizes.items():
    d2 = 'app/src/main/res/mipmap-%s' % d
    os.makedirs(d2, exist_ok=True)
    im.resize((s, s), Image.LANCZOS).save('%s/ic_launcher.png' % d2)
    print('  mipmap-%-8s %dx%d' % (d, s, s))
print('android icons done')
"""


# ---------------------------------------------------------------------------
# Web 层原生桥接 polyfill（注入到入口 HTML 的 <head>，在 index.js 之前执行）。
# 让 WKWebView 里缺失的 File System Access API / 文件选择 / 插件加载 转到原生。
# 注入逻辑见 IOS_MAKER；本常量作为 tw_bridge.js 推到云端仓库，运行时被读取。
# ---------------------------------------------------------------------------
TW_BRIDGE_JS = r'''(function(){
  if (window.__tw_bridge_v1) return;
  window.__tw_bridge_v1 = true;
  var _pending = {};
  var _seq = 1;
  function _post(type, extra) {
    return new Promise(function(resolve, reject){
      var id = 'r' + (_seq++);
      _pending[id] = {resolve: resolve, reject: reject};
      try {
        window.webkit.messageHandlers.twBridge.postMessage(Object.assign({id:id, type:type}, extra||{}));
      } catch(e){ delete _pending[id]; reject(e); }
    });
  }
  window.__twComplete = function(id, payload){
    var p = _pending[id]; if(!p) return; delete _pending[id];
    if(payload && payload.error) p.reject(new Error(payload.error)); else p.resolve(payload?payload.result:true);
  };
  function blobToB64(blob){
    return new Promise(function(res,rej){
      var fr=new FileReader();
      fr.onload=function(){ res(fr.result.split(',')[1]); };
      fr.onerror=rej; fr.readAsDataURL(blob);
    });
  }
  // ---- showSaveFilePicker：骗过 TurboWarp 的禁用判断 ----
  if (typeof window.showSaveFilePicker !== 'function') {
    window.showSaveFilePicker = function(opts){
      var suggestedName = (opts && opts.suggestedName) || 'untitled';
      var fakeHandle = {
        name: suggestedName,
        createWritable: function(){
          return {
            write: function(data){
              var blob = (data instanceof Blob) ? data : new Blob([data]);
              return blobToB64(blob).then(function(b64){
                return _post('save', {name: suggestedName, data: b64, mime: blob.type||'application/octet-stream'});
              });
            },
            close: function(){ return Promise.resolve(); }
          };
        }
      };
      return Promise.resolve(fakeHandle);
    };
  }
  // ---- showOpenFilePicker ----
  if (typeof window.showOpenFilePicker !== 'function') {
    window.showOpenFilePicker = function(opts){
      return _post('open', {}).then(function(res){
        var bytes = atob(res.data);
        var arr = new Uint8Array(bytes.length);
        for (var i=0;i<bytes.length;i++) arr[i]=bytes.charCodeAt(i);
        var blob = new Blob([arr], {type: res.mime||'application/octet-stream'});
        var fakeFile = {
          name: res.name, size: arr.length, type: res.mime||'application/octet-stream',
          arrayBuffer: function(){ return Promise.resolve(arr.buffer.slice(0)); },
          text: function(){ return Promise.resolve(bytes); },
          getFile: function(){ return Promise.resolve(this); }
        };
        return [ { getFile: function(){ return Promise.resolve(fakeFile); }, name: res.name } ];
      });
    };
  }
  // ---- 插件加载：JS 或 JSON（兼容）----
  window.twLoadPlugin = function(text){
    return new Promise(function(resolve, reject){
      try {
        var code = text;
        try {
          var j = JSON.parse(text);
          if (j && typeof j === 'object') {
            if (typeof j.code === 'string') code = j.code;
            else if (typeof j.extension === 'string') code = j.extension;
            else if (typeof j.source === 'string') code = j.source;
          }
        } catch(e){}
        var vm = findVM();
        if (!vm || !vm.extensionManager) { reject(new Error('找不到 TurboWarp 运行时(vm.extensionManager)')); return; }
        var blobUrl = URL.createObjectURL(new Blob([code], {type:'text/javascript'}));
        Promise.resolve(vm.extensionManager.loadExtensionURL(blobUrl)).then(function(){ resolve(true); }).catch(reject);
      } catch(e){ reject(e); }
    });
  };
  function findVM(){
    var roots = [document.getElementById('app'), document.querySelector('#root')];
    for (var ri=0; ri<roots.length; ri++){
      var r = roots[ri]; if(!r) continue;
      for (var k in r){
        if (k.indexOf('__reactContainer$')===0 || k.indexOf('__reactInternalInstance$')===0){
          var fiber = r[k]; if (fiber && fiber.current) fiber = fiber.current;
          var found = walkFiber(fiber); if (found) return found;
        }
      }
    }
    return null;
  }
  function walkFiber(fiber){
    if (!fiber) return null;
    var sn = fiber.stateNode;
    if (sn && sn.props && sn.props.vm && sn.props.vm.extensionManager) return sn.props.vm;
    if (fiber.memoizedProps && fiber.memoizedProps.vm && fiber.memoizedProps.vm.extensionManager) return fiber.memoizedProps.vm;
    var c = walkFiber(fiber.child); if (c) return c;
    return walkFiber(fiber.sibling);
  }
  console.log('[tw_bridge] injected v1 (save/open/plugin)');
})();
'''

def get_workflow(platform: str) -> str:
    return IOS_WORKFLOW if platform == 'ios' else ANDROID_WORKFLOW


def inject_bridge_into_html(html_text: str, bridge_js: str) -> str:
    """把 tw_bridge polyfill 以 <script> 形式插到 </head> 之前（原样返回表示未改动）。

    两个踩过的坑（务必保持）：
      1) 必须用 <script> 包裹：桥接 JS 里有 `<`（如 i<len），裸插会被 HTML 解析器
         当成标签起始，吞掉 <meta charset> 并破坏 head 结构。
      2) 必须插在 </head> 之前，而不是紧跟 <head>：桥接有 4KB+，紧跟 <head> 会把
         <meta charset> 挤出浏览器 1024 字节预扫描窗口，导致整页（含 index.js）
         按错误编码解析。
    """
    import re as _re
    if not bridge_js or 'tw_bridge_v1' in html_text:
        return html_text
    _wrapped = '\n<!-- tw_bridge native polyfill -->\n<script>\n' + bridge_js + '\n</script>\n'
    _m = _re.search(r'</head\s*>', html_text, _re.IGNORECASE)
    if _m:
        _pos = _m.start()
    else:
        _m2 = _re.search(r'<head[^>]*>', html_text, _re.IGNORECASE)
        if not _m2:
            return html_text
        _pos = _m2.end()
    return html_text[:_pos] + _wrapped + html_text[_pos:]


def get_maker_files(platform: str) -> dict:
    """返回需要随仓库推送的「生成脚本」文件名 -> 内容（文本）。"""
    if platform == 'ios':
        return {'make_project.py': IOS_MAKER, 'tw_bridge.js': TW_BRIDGE_JS}
    return {'make_project.py': ANDROID_MAKER, 'make_icons.py': ANDROID_ICONS}
