# LocalHub

**把本地视频和图片文件夹，一键变成在你电脑上运行的 Pornhub 风格私人媒体网站。**

把 `LocalHub.exe` 放进媒体总目录，双击即可。LocalHub 会自动扫描本地视频和图片，在浏览器中打开一个本地网站，并让你直接完成浏览、播放、Tag、评分、收藏、改名和移动分类。

**一个 EXE。无需导入。无需部署服务器。无需账号。无需上传。**

[English](README.md) · [简体中文](README.zh-CN.md)

[![Build Windows EXE](https://github.com/dudulu2/Local-hub/actions/workflows/build-windows.yml/badge.svg)](https://github.com/dudulu2/Local-hub/actions/workflows/build-windows.yml)

## 它是什么感觉

LocalHub 不是把你的媒体库做成一个数据库后台，也不是换皮文件管理器。

它更像是：**直接依托你现有的本地文件夹，自动运行起来的私人媒体网站。**

- **网站式浏览**：首页、文件夹、搜索、收藏、继续观看和完整播放器。
- **边看边整理**：不用离开播放流程，就能加 Tag、评分、收藏、改名和移动。
- **拖动分类**：直接把视频拖到左侧文件夹，就能移动到对应目录。
- **图片自动变图包**：多张图片自动折叠成一个图包卡片，不让首页被几百张图塞满。
- **零配置启动**：一个 EXE 放进媒体根目录，双击就能用。
- **完全本地**：默认仅绑定 `127.0.0.1`，媒体不会上传到互联网。

## 快速开始

1. 从 [GitHub Releases](https://github.com/dudulu2/Local-hub/releases) 下载 `LocalHub.exe`。
2. 把它放进包含视频和图片的媒体总目录。
3. 双击 `LocalHub.exe`。
4. 浏览器会自动打开 LocalHub。
5. Windows 托盘图标可以重新打开网站、打开媒体文件夹或退出 LocalHub。

```text
媒体库/
├─ LocalHub.exe
├─ video-a.mp4
├─ 视频合集/
│  ├─ episode-01.mp4
│  └─ episode-02.mp4
└─ 图包/
   ├─ 001.jpg
   ├─ 002.jpg
   └─ 003.jpg
```

## Windows 首次运行警告

目前公开发布的 `LocalHub.exe` **还没有商业代码签名证书**。因此部分 Windows 电脑第一次运行时，Microsoft Defender SmartScreen 可能会显示：

> Windows 已保护你的电脑 / 未知发布者

这是未签名应用常见的信誉 / 发布者提示，**它本身不等于 Windows 已检测到病毒或恶意代码**。

如果 EXE 来自本仓库官方 Release：

1. 点击 SmartScreen 窗口中的 **“更多信息”**。
2. 确认应用名称为 `LocalHub.exe`。
3. 如有需要，先校验 SHA256。
4. 确认后点击 **“仍要运行”**。

每个正式构建都会同时提供 `SHA256.txt`：

```powershell
Get-FileHash .\LocalHub.exe -Algorithm SHA256
```

把结果和同一 Release 中的 `SHA256.txt` 对比即可。

你**不需要关闭 Windows Defender**，也不需要把整个媒体目录加入杀毒软件白名单。

详细说明：[`docs/windows-smartscreen.md`](docs/windows-smartscreen.md)

## 核心功能

### 像网站一样浏览本地媒体

- 轻量首页推荐
- 左侧文件夹导航
- 全部视频
- 图包 / 图册
- 搜索
- 收藏
- 继续观看
- 真正分页，不一次性把整个媒体库塞进浏览器

### 边看边整理

- 卡片直接添加 Tag
- 评分
- 收藏
- 播放进度记录
- 改文件名并保留扩展名
- 移动到已有目录
- 拖动视频到左侧文件夹完成分类
- 改名 / 移动后自动迁移收藏和播放进度
- 同名目标文件不会被覆盖

### 自动图包模式

同一个文件夹里存在 2 张以上图片时，LocalHub 可以把它视为一个图包：

- 首页只显示一个封面；
- 打开图包后才读取整套原图；
- 混合文件夹里的视频仍然独立展示。

这可以避免大型图片目录在首页生成几百甚至几千张卡片。

## 面向大型本地媒体库的性能设计

LocalHub 不会给每个视频卡片都挂一个真实 `<video>`。

### 轻量索引

第一次运行会生成一个很小的媒体索引：

```text
.localhub/
├─ metadata.json     # Tag 等元数据
├─ catalog-v2.json   # 轻量媒体索引快照
└─ runtime.json      # 当前运行实例信息，退出后删除
```

后续启动时可以先读取索引快速显示页面，再在后台刷新真实目录。

### 缩略图按需加载

缩略图优先按下面的顺序获取：

1. Windows Shell / Explorer 共享缩略图缓存
2. 图片使用 PIL 轻量缩放
3. 视频缓存未命中时，用 FFmpeg 快速抽取单帧

前端只请求当前视口附近的缩略图，不会一次打开整个媒体库。

### 真正播放时才读取视频

只有进入播放器后，LocalHub 才会请求真实媒体文件。视频服务支持 HTTP Range，因此大文件可以直接拖动进度条，不需要先把整个视频读进内存。

## 支持格式

**图片**

`jpg jpeg png webp gif avif bmp svg`

**视频**

`mp4 webm m4v mov mkv avi ogv mpeg mpg ts`

> 扩展名受支持，不代表浏览器一定能原生解码所有内部视频 / 音频编码。最终直接播放能力仍取决于浏览器和本机解码环境。

## 隐私与本地文件安全

- 默认仅监听 `127.0.0.1`
- 不需要账号
- 不上传媒体
- Tag 保存在 `.localhub/metadata.json`
- 不会重写媒体文件内部元数据
- 改名和移动会真实改变本地文件路径

请像使用文件管理器一样对待“改名”和“移动”操作。

## 构建 Windows EXE

普通用户不需要 Python。开发者可以运行：

```powershell
.\build_windows.ps1
```

GitHub Actions 会执行 Python / JavaScript 校验、目录与预览 smoke test、媒体兼容性测试、元数据 UX 测试，然后构建单文件 Windows GUI EXE、生成 SHA256 并上传构建产物。

推送 `v*` tag 时会自动创建 GitHub Release，并附带 `LocalHub.exe` 与 `SHA256.txt`。

## 项目方向

LocalHub 不打算变成一个沉重的媒体数据库。

它的目标很简单：

> **文件还是普通文件，但浏览和整理体验像一个真正的私人媒体网站。**

目前优先方向包括更好的播放兼容性、更顺手的键盘操作、更自然的批量整理、可选局域网访问，以及大型媒体库性能优化。

## 反馈

提交问题时建议附上：

- Windows 版本
- LocalHub 版本 / Release 名称
- 媒体扩展名与编码信息（如果知道）
- 复现步骤
- 同一个文件是否能直接在浏览器播放

请不要在 Issue 中上传私人媒体文件本体。

---

*文中“Pornhub 风格”仅用于说明大家熟悉的卡片 / 网格式浏览和交互形态。LocalHub 是独立项目，与 Pornhub 无隶属或合作关系。*
