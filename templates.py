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
IOS_MAKER = r"""import json, os, subprocess, shutil

cfg = json.load(open('config.json'))
APP_NAME = cfg.get('name', 'TWPackApp')
BUNDLE_ID = cfg.get('bundle_id', 'com.twpack.app')
PERMS = cfg.get('permissions', [])
ORIENT = cfg.get('orientation', 'auto')          # portrait | landscape | auto

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
      - path: app.html
        buildPhase: resources
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
'''.replace('__BUNDLE_ID__', BUNDLE_ID).replace('__BUNDLE_NAME__', BUNDLE_NAME)
open('project.yml', 'w').write(project_yml)

# ---- App.swift (WKWebView 加载 app.html) ----
app_swift = '''import UIKit
import WebKit

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

class ViewController: UIViewController, WKNavigationDelegate {
    var webView: WKWebView!
    override func loadView() {
        let config = WKWebViewConfiguration()
        config.preferences.javaScriptEnabled = true
        config.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        config.setValue(true, forKey: "allowUniversalAccessFromFileURLs")
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.scrollView.bounces = false
        view = webView
    }
    override func viewDidLoad() {
        super.viewDidLoad()
        if let url = Bundle.main.url(forResource: "app", withExtension: "html") {
            webView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
        }
    }
}
'''
open('App.swift', 'w').write(app_swift)

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
        subprocess.run(['sips', '-z', str(size), str(size), 'icon.png',
                        '--out', out], check=False)
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
# ★ 必须复制：MainActivity 加载的是 file:///android_asset/app.html，
#   少了这一步 APK 里就没有 app.html → 打开即白屏（且构建不会报任何错）。
import shutil as _shutil
if not os.path.exists('app.html'):
    raise SystemExit('ERROR: 仓库里找不到 app.html，无法打包')
_shutil.copy('app.html', 'app/src/main/assets/app.html')
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
        webView.loadUrl("file:///android_asset/app.html");
    }
    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }
}
'''.replace('__PKG__', PKG)
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


def get_workflow(platform: str) -> str:
    return IOS_WORKFLOW if platform == 'ios' else ANDROID_WORKFLOW


def get_maker_files(platform: str) -> dict:
    """返回需要随仓库推送的「生成脚本」文件名 -> 内容（文本）。"""
    if platform == 'ios':
        return {'make_project.py': IOS_MAKER}
    return {'make_project.py': ANDROID_MAKER, 'make_icons.py': ANDROID_ICONS}
