# LocalHub

> Turn any folder into a private local media site.

LocalHub 是一个完全本地运行的媒体浏览器和整理工具。把 `LocalHub.exe` 放进你的媒体总目录，双击后即可像浏览网站一样查看视频与图包，并在观看过程中直接完成 Tag、评分、收藏、改名和移动分类。

**不需要安装 Python，不需要 Docker，不需要导入媒体库，也不会把媒体上传到互联网。**

[![Build Windows EXE](https://github.com/dudulu2/local-web/actions/workflows/build-windows.yml/badge.svg)](https://github.com/dudulu2/local-web/actions/workflows/build-windows.yml)

## 为什么是 LocalHub

很多媒体管理器很强，但使用起来更像数据库或文件管理器。LocalHub 的目标不同：

- **先浏览，后整理**：观看体验优先，整理动作嵌在卡片和播放器里。
- **零配置启动**：一个 EXE 放进媒体目录即可运行。
- **网站式体验**：首页、分类、搜索、收藏、继续观看、播放器都围绕浏览体验设计。
- **拖动分类**：进入“移动位置”模式后，可直接把视频拖到左侧文件夹完成归类。
- **图片自动折叠成图包**：同一文件夹中的多张图片只显示一个封面，点开后再阅读整套图片。
- **完全本地**：默认只绑定 `127.0.0.1`，媒体不会上传到远程服务器。

## 30 秒开始使用

1. 从 GitHub Releases 下载 `LocalHub.exe`。
2. 把它放到你的媒体总目录。
3. 双击运行。
4. 浏览器会自动打开 LocalHub。
5. 退出时可使用 Windows 托盘中的 **退出 LocalHub**。

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

## Windows 第一次运行可能出现警告

当前公开构建的 `LocalHub.exe` **没有商业代码签名证书**。因此在一台尚未建立应用信誉的 Windows 电脑上，Microsoft Defender SmartScreen 可能显示：

> Windows 已保护你的电脑 / 未知发布者

这通常是 **未签名应用的信誉提示**，并不等同于 Windows 已检测到恶意代码。

如果你确认 EXE 来自本仓库的 GitHub Release，可以：

1. 在 SmartScreen 窗口点击 **“更多信息”**。
2. 确认应用名称为 `LocalHub.exe`。
3. 点击 **“仍要运行”**。

每个正式构建同时生成 `SHA256.txt`。如需校验下载文件：

```powershell
Get-FileHash .\LocalHub.exe -Algorithm SHA256
```

把结果与 Release 中的 `SHA256.txt` 对比即可。

> 不建议关闭 Windows Defender，也不需要把整个目录加入杀毒软件白名单。

更多说明见 [`docs/windows-smartscreen.md`](docs/windows-smartscreen.md)。

## 核心功能

### 像网站一样浏览本地媒体

- 轻量首页推荐
- 左侧文件夹导航
- 全部视频
- 图包 / 图册
- 搜索
- 收藏
- 继续观看
- 真正分页，不把整个媒体库一次性塞进浏览器

### 边看边整理

- 视频卡片下方固定 Tag 条
- 卡片内快速添加 Tag
- 评分
- 收藏
- 播放进度记录
- 文件改名并保留扩展名
- 移动到已有目录
- 拖动视频到左侧文件夹进行分类
- 改名 / 移动后迁移收藏和播放进度
- 同名目标文件不会被覆盖

### 图包模式

同一文件夹中存在 2 张以上图片时，LocalHub 会把它视为一个图包：

- 首页只展示一个图包封面
- 打开后才逐张读取原图
- 混合目录中的视频仍独立展示

这避免大型图片目录在首页生成几百或几千张卡片。

## 性能设计

LocalHub 2 不再使用“一个视频卡片挂一个 `<video>`”的方式。

### 元数据索引

第一次运行会建立轻量索引：

```text
.localhub/
├─ metadata.json     # Tag 等元数据
├─ catalog-v2.json   # 轻量媒体索引快照
└─ runtime.json      # 当前运行实例信息，退出后删除
```

第二次启动可先读取索引快照快速显示首页和目录，再刷新真实文件系统。

### 缩略图按需获取

缩略图按以下顺序尝试：

1. Windows Shell / Explorer 共享缩略图缓存
2. 图片使用 PIL 轻量缩放
3. 视频缓存未命中时，使用 FFmpeg 快速 seek 抽取单帧

前端只为当前视口和下一排请求缩略图，并限制并发请求数。

### 真正播放时才加载视频

只有打开播放器后才请求媒体文件。视频服务支持 HTTP Range，所以大文件可以拖动进度条，不需要整段读入内存。

## 支持格式

**图片**

`jpg jpeg png webp gif avif bmp svg`

**视频**

`mp4 webm m4v mov mkv avi ogv mpeg mpg ts`

> 文件扩展名受支持，不代表浏览器一定能原生解码其中的视频/音频编码。LocalHub 会尽量提供预览与兼容性回退，但最终直接播放能力仍取决于浏览器和本机解码环境。

## 隐私与本地文件安全

- 默认仅监听 `127.0.0.1`
- 不需要账户
- 不上传媒体文件
- Tag 保存在 `.localhub/metadata.json`
- 不修改媒体文件内部元数据
- 改名和移动会真实修改本地文件路径

请像使用文件管理器一样对待“改名”和“移动”操作。

## Windows EXE 构建

普通用户不需要 Python。开发者可运行：

```powershell
.\build_windows.ps1
```

GitHub Actions 会自动执行：

1. Python 语法校验
2. 前端 JavaScript 语法校验
3. 目录 / 首页 / 图包 smoke test
4. 预览提取测试
5. 媒体兼容性测试
6. 元数据 UX 测试
7. Windows 单文件 GUI EXE 构建
8. SHA256 生成
9. Artifact 上传

推送 `v*` tag 时会自动创建 GitHub Release，并附带 `LocalHub.exe` 与 `SHA256.txt`。

## 项目定位

LocalHub 不追求成为一个重型媒体数据库。它更像是：

> **一个把普通文件夹瞬间变成本地私人视频网站的工具。**

如果你的第一需求是“舒服地看”，第二需求才是“顺手整理”，LocalHub 就是为这个场景设计的。

## Roadmap

目前更关注体验和稳定性，而不是堆功能。优先方向包括：

- 更好的首屏展示与演示素材
- 更稳定的媒体兼容性回退
- 更完整的键盘快捷键
- 更自然的批量整理流程
- 可选的局域网访问模式
- 跨平台可行性评估

## 反馈

如果遇到问题，请在 Issues 中尽量附上：

- Windows 版本
- LocalHub 版本 / Release 名称
- 媒体文件扩展名与编码信息（如知道）
- 复现步骤
- 是否能在浏览器中直接播放同一文件

请不要上传私人媒体文件本体。

---

### English

**LocalHub turns a normal media folder into a private local media site.**

Put `LocalHub.exe` in your media root, double-click it, and browse videos and photo collections in your browser. Tag, rate, favorite, rename, and drag files into folders without leaving the viewing flow. LocalHub runs locally, binds to `127.0.0.1` by default, and does not upload your media.

Windows may show a SmartScreen warning because public builds are currently unsigned. Download only from this repository's Releases page and verify the provided SHA256 if needed.
