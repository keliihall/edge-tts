# Edge TTS Web

一个基于 Edge TTS 的在线文本转语音工具，支持多种中文语音角色。

## 功能特点

- 支持多种中文语音角色：
  - 普通话：晓晓、晓伊、云健等
  - 方言：东北话（晓北）、陕西话（晓妮）
  - 粤语：晓佳、晓曼、云龙
  - 台湾腔：晓辰、晓语、云哲
- 支持自定义文件名
- 美观的用户界面
- 实时显示语音角色信息
- 支持长文本转换（上限5000字符）
- 自动重试机制

## 快速开始

### 使用打包版本（推荐）

1. 从 [Releases](https://github.com/keliihall/edge-tts/releases) 页面下载对应系统的安装包：
   - Windows: `Edge-TTS-Web-Windows.zip`
   - macOS: `Edge-TTS-Web-macOS.zip`
   - Linux: `Edge-TTS-Web-Linux.tar.gz`

2. 解压下载的文件：
   - Windows: 解压后双击 `Edge TTS Web.exe`
   - macOS: 解压后双击 `Edge TTS Web.app`
   - Linux: 解压后运行 `Edge TTS Web` 可执行文件

应用会自动打开默认浏览器访问界面。

### 从源码运行

1. 克隆仓库：
```bash
git clone https://github.com/keliihall/edge-tts.git
cd edge-tts
```

2. 创建虚拟环境：
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
.\venv\Scripts\activate  # Windows
```

3. 安装依赖：
```bash
pip install -r requirements.txt
```

4. 运行应用：
```bash
python run.py
```

应用会自动打开默认浏览器访问界面。如果没有自动打开，请访问 http://127.0.0.1:5013

## 使用说明

1. 在文本框中输入要转换的文本
2. 从下拉菜单中选择语音角色
3. 点击"转换为语音"按钮
4. 等待转换完成
5. 可选：修改下载文件名
6. 点击"下载音频"按钮保存文件

## 开发者说明

### 项目结构
```
edge-tts/
├── app.py              # Flask 应用主文件
├── run.py              # 启动脚本
├── requirements.txt    # 项目依赖
├── static/            
│   └── css/
│       └── style.css   # 样式文件
├── templates/
│   └── index.html      # 主页面模板
└── build_*.sh/bat      # 打包脚本
```

### 打包说明

项目使用 PyInstaller 进行打包，支持生成各平台的独立可执行文件：

- Windows:
```bash
.\build_windows.bat
```

- macOS:
```bash
./build_macos.sh
```

- Linux:
```bash
./build_linux.sh
```

打包后的文件位于 `dist` 目录。

## 技术栈

- 后端：Flask
- 语音转换：Edge TTS
- 前端：HTML5, CSS3, JavaScript
- 打包工具：PyInstaller

## 注意事项

- 文本长度限制为5000字符
- 音频文件格式为 MP3
- 转换后的临时文件会自动清理
- 支持的语音角色可能会随 Edge TTS 服务更新而变化
- 需要联网使用

## License

[MIT License](LICENSE) 