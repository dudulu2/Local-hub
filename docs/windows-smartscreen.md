# Windows SmartScreen 与 `LocalHub.exe`

LocalHub 的公开 Windows 构建目前没有使用商业代码签名证书。对于新发布、下载量较少或尚未建立应用信誉的 EXE，Windows 可能显示 Microsoft Defender SmartScreen 提示，例如：

- “Windows 已保护你的电脑”
- “未知发布者”
- “Microsoft Defender SmartScreen 阻止了无法识别的应用启动”

## 这代表什么

这类提示通常表示 Windows 无法通过受信任代码签名或既有信誉确认发布者身份。

它和“Windows 已确认该文件包含病毒”不是同一件事。

LocalHub 不建议用户关闭 Defender、关闭 SmartScreen，也不建议把整个媒体目录加入杀毒软件排除项。

## 安全地确认下载来源

只从本仓库的 GitHub Releases 获取官方构建。

每次正式构建都会同时提供：

- `LocalHub.exe`
- `SHA256.txt`

下载后可在 PowerShell 中执行：

```powershell
Get-FileHash .\LocalHub.exe -Algorithm SHA256
```

将输出的哈希与同一 Release 中 `SHA256.txt` 的值进行比较。

两者一致，表示你拿到的文件与该 Release 发布的构建一致。

## 确认来源后如何运行

如果 SmartScreen 仍拦截：

1. 点击 **更多信息**。
2. 检查应用名称是否为 `LocalHub.exe`。
3. 确认文件来自本仓库官方 Release。
4. 如有需要，先完成 SHA256 校验。
5. 点击 **仍要运行**。

不同 Windows 版本的文字可能略有差异。

## 为什么现在不签名

Windows Authenticode 代码签名需要受信任证书以及持续的证书管理。LocalHub 当前仍处在早期公开发布阶段，因此暂未加入商业代码签名流程。

未来如果项目进入更稳定的公开分发阶段，可以评估加入正式代码签名，以减少首次运行时的 SmartScreen 摩擦。

## 报告安全问题

如果你发现疑似安全问题，请在提交公开 Issue 时避免附带私人媒体、真实文件路径、个人信息或敏感样本。可先提供最小复现步骤和相关日志片段。
