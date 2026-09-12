# TWNativePack · TurboWarp 一键转原生 App

把 TurboWarp 导出的**单文件 HTML** 一键打包成 **iOS 可侧载 IPA** 或 **Android 可装 APK**。
无需 Mac、无需 Android SDK——云端 GitHub Actions 出包，本地只需选文件、填名、点构建。

## 功能
- 选平台（iOS / Android）
- 选图标图片 + 应用名称 + TurboWarp 打包后的 `.html`
- 勾选需要的权限（相机 / 麦克风 / 照片库 / 蓝牙 / 定位）→ 自动写进 Info.plist / AndroidManifest，降低桥接复杂度
- iOS 分支：填 GitHub PAT（可勾「记住」存本机）→ 建临时仓库并推送 → 触发 macos runner 构建 → 拉日志 → 下载 IPA → （默认）自动删库
- Android 分支：同样走云端 ubuntu+Android SDK runner 出 APK（代码已留本地 Gradle 接口，装了 SDK 可切真·本地）

## 安装（本机）
```bash
pip install pyqt6
```
（仅 GUI 依赖；编排走标准库 urllib，不装 requests）

## 运行
```bash
python main.py
```

## 流程（iOS 分支示意）
```
选平台 → 选图标/名称/.html → 勾权限 → 填 PAT(可记)
   └─ 工具建临时仓库 twpack-<时间戳>
        └─ 推 config.json + app.html + icon.png + 工作流 + 生成脚本
             └─ 触发 GitHub Actions (macos-latest)
                  └─ 工作流内 python 生成 Xcode 工程 (XcodeGen)
                       └─ xcodebuild 出未签名 IPA
                            └─ 上传 artifact → 工具下载 → 删库
```

## 已知边界（诚实说明）
1. **iOS 未签名 IPA = 侧载**，不能上 App Store。免费用户走侧载；要上架需 $99/年开发者账号 + 真机 archive（工具可改造成一键出 Xcode 工程让你自 archive）。
2. **Android APK 用 debug key 自签**，可直接安装；要上架需自有签名。
3. 复杂 TW 项目在移动端 WebView 性能弱于桌面，超大型游戏可能掉帧。
4. 调原生硬件的 unsandboxed 扩展（摄像头等）已通过权限声明桥接，但个别扩展仍需原生桥适配——这是下一步。

## 文件
- `main.py` —— PyQt6 图形界面
- `build_core.py` —— 构建编排（建库/推文件/触发/轮询/下产物/删库）
- `gh_api.py` —— GitHub REST API 封装（标准库）
- `templates.py` —— iOS/Android 工作流 + 工程生成脚本（全内联）

## 待办 / 下一步
- [ ] 本地 Android Gradle 构建路径（检测到 SDK 时切换）
- [ ] iOS 上架模式：产出 Xcode 工程而非直接 IPA
- [ ] 多扩展原生桥适配模板
