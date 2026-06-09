# Edge TTS Web v0.6 更新说明

v0.6 聚焦桌面使用体验，补齐设置页、网络诊断、动态端口、单实例启动和发布包命名。

## 核心更新

### 1. 设置页

- 新增 `GET /settings` 和 `POST /settings`。
- 支持保存默认音色、默认语速、代理地址、默认保存目录、历史保留天数、临时文件保留小时、长文本分段字数和自动打开浏览器。
- 设置会写入本地 `settings.json`，应用重启后继续生效。
- 单条转换、试听和批量转换都会使用默认音色和默认语速。

### 2. 网络和代理诊断

- 新增 `GET /diagnostics`。
- 展示代理是否配置、代理是否可用、Edge TTS 服务是否可连接、整体网络状态、设置文件路径和临时目录。
- `/health` 增加代理和 Edge TTS 诊断字段。
- 设置页支持一键重新诊断。

### 3. 动态端口和单实例启动

- `run.py` 不再强依赖固定 5013 端口。
- 如果 5013 被占用，会自动寻找后续可用端口。
- 启动时写入 `runtime.json`，包含端口、URL、PID、版本和启动时间。
- 如果检测到已有可用实例，重复启动会直接打开已有实例 URL。
- 可通过设置控制启动后是否自动打开浏览器。

### 4. 发布包质量提升

- Linux/macOS/Windows 打包脚本的发布包名称加入版本号。
- Linux/macOS/Windows 打包脚本统一使用 `edge-tts-web` 产物名。

## 相关接口

```text
GET  /settings
POST /settings
GET  /diagnostics
GET  /health
```

## 相关文件

- `app.py`：设置、诊断、代理读取、清理 TTL、默认音色/语速
- `run.py`：动态端口、单实例复用、运行状态文件
- `templates/index.html`：设置与诊断 UI
- `static/css/style.css`：设置页和诊断面板样式
- `build_linux.sh`、`build_macos.sh`、`build_windows.bat`：版本化发布包名
- `tests/test_app.py`：v0.6 自动化测试
- `README.md`：v0.6 使用说明

## 验证结果

已通过：

```bash
./.venv/bin/python -m pytest -q
```

结果：

```text
24 passed
```

已通过：

```bash
./.venv/bin/python -m py_compile app.py run.py
```

## 已知取舍

- 设置文件保存在应用临时目录下，后续可迁移到更标准的用户配置目录。
- v0.6 仍未引入系统托盘，托盘能力可在后续版本继续开发。
- 发布脚本更新了命名和产物引用，但本次未执行跨平台真实打包。
