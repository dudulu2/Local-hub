# LocalHub

LocalHub 是一个完全本地运行的媒体浏览器和整理工具：把普通视频 / 图片文件夹变成类似视频网站的本地媒体库，同时支持 Tag、收藏、继续观看、改名和移动文件。

## 普通用户：只需要 LocalHub.exe

Windows 用户不再需要 BAT、命令行、Python 或安装依赖。

1. 从 GitHub Actions 的 `LocalHub-Windows-x64` 构建产物，或版本 Release 中下载 `LocalHub.exe`。
2. 把 `LocalHub.exe` 放到你要浏览的媒体总目录。
3. 双击 `LocalHub.exe`。
4. LocalHub 会无黑框启动本地服务，并自动打开浏览器。

示例：

```text
媒体库/
├─ LocalHub.exe
├─ 视频/
│  ├─ A.mp4
│  └─ B.webm
└─ 图片/
   ├─ 1.jpg
   └─ 2.png
```

LocalHub 会递归扫描 EXE 所在目录和所有子目录。

## Windows 启动体验

`LocalHub.exe` 是单文件便携程序：

- 双击直接启动，不出现 CMD / PowerShell 黑框。
- 自动打开浏览器中的 LocalHub 页面。
- 启动后在 Windows 托盘区保留 LocalHub 图标。
- 托盘右键可“打开 LocalHub”“打开媒体文件夹”“退出 LocalHub”。
- 同一个媒体目录重复双击 EXE 不会启动第二个服务器，而是直接打开已经运行的 LocalHub。
- 不安装系统服务，不写注册表，不需要管理员权限。
- 默认只监听 `127.0.0.1`，媒体不会上传互联网。

运行时数据保存在媒体目录内：

```text
.localhub/
├─ metadata.json   # Tag 等媒体元数据
└─ runtime.json    # 当前运行实例信息，退出后自动删除
```

`.localhub` 不会出现在媒体扫描结果里。

## 主要功能

- 自动递归扫描本地视频和图片
- 深色高对比视频网站式媒体墙
- 视频 / 图片 / 收藏 / 继续观看分类
- 文件夹导航
- Tag 导航和搜索
- 每个视频卡片下方固定 Tag 条
- 卡片上直接快速增删 Tag
- 播放器旁整理面板
- 批量添加 Tag、批量移动
- 改文件名并保留扩展名
- 移动到已有或新建文件夹
- 改名 / 移动后保持 Tag、收藏和播放进度
- 名称、修改时间、文件大小排序
- 视频拖动进度、全屏、倍速等浏览器原生控制
- HTTP Range 分段读取，大视频无需一次载入内存
- 图片大图查看
- 上一个 / 下一个与方向键切换
- 自动记忆播放位置
- 响应式桌面 / 窄屏布局

## 支持格式

### 图片

`jpg jpeg png webp gif avif bmp svg`

### 视频

`mp4 webm m4v mov mkv avi ogv mpeg mpg ts`

能否直接播放取决于浏览器是否支持文件内部编码。Chrome / Edge 对 MP4（H.264/AAC）、WebM 通常支持最好；部分 MKV、AVI 或特殊编码可能能被扫描但不能直接播放。

## 快捷键

- `/`：聚焦搜索框
- `E`：播放器内展开 / 收起整理面板
- `←`：上一个媒体
- `→`：下一个媒体
- `Esc`：关闭查看器

## 开发者运行

源码模式仍可直接运行：

```bash
python server.py
```

指定媒体目录：

```bash
python server.py --root "D:\Videos"
```

## 本地构建 Windows EXE

开发者可在 Windows PowerShell 中运行：

```powershell
.\build_windows.ps1
```

脚本会安装构建依赖、生成 LocalHub 图标，并输出：

```text
dist/LocalHub.exe
dist/SHA256.txt
```

普通用户不需要执行这个脚本。

## GitHub 自动构建

`.github/workflows/build-windows.yml` 会在相关文件推送到 `main` 后自动：

1. 使用 Windows runner 和 Python 3.12。
2. 通过 PyInstaller 打包单文件、无控制台窗口的 `LocalHub.exe`。
3. 生成 Windows 应用图标和版本信息。
4. 生成 SHA256。
5. 上传 `LocalHub-Windows-x64` Artifact。
6. 当推送 `v*` Tag 时，同时发布 GitHub Release。

## 隐私与文件安全

LocalHub 默认只绑定本机回环地址 `127.0.0.1`。媒体通过本机 HTTP 服务直接提供给自己的浏览器，不上传到互联网。

文件改名和移动会真实作用于本地文件；程序会阻止 Windows 非法文件名和同名覆盖。Tag 只保存在 `.localhub/metadata.json` 中，不修改视频文件本体。

## 设计说明

视觉思路参考大型视频站常见的黑色背景、高密度缩略图和醒目强调色，但 LocalHub 是独立实现，不使用第三方品牌名称、Logo 或素材；重点针对本地媒体场景增加 Tag、文件移动、改名、收藏和继续观看等能力。
