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

## 安装说明

1. 克隆仓库：
```bash
git clone https://github.com/你的用户名/edge-tts-web.git
cd edge-tts-web
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
python app.py
```

5. 访问应用：
打开浏览器访问 http://127.0.0.1:5013

## 使用说明

1. 在文本框中输入要转换的文本
2. 从下拉菜单中选择语音角色
3. 点击"转换为语音"按钮
4. 等待转换完成
5. 可选：修改下载文件名
6. 点击"下载音频"按钮保存文件

## 技术栈

- 后端：Flask
- 语音转换：Edge TTS
- 前端：HTML5, CSS3, JavaScript

## 注意事项

- 文本长度限制为5000字符
- 音频文件格式为 MP3
- 转换后的文件会自动清理
- 支持的语音角色可能会随 Edge TTS 服务更新而变化

## License

MIT License 