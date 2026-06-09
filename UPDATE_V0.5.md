# Edge TTS Web v0.5 更新说明

v0.5 聚焦语音创作闭环，在 v0.4 的长文本任务基础上补齐试听、播放、历史记录、音色管理和场景预设。

## 核心更新

### 1. 试听前 300 字

- 新增 `POST /preview`。
- 使用当前文本前 300 字生成试听音频。
- 试听成功后返回 `audio_url`，前端可直接播放。
- 试听会记录最近使用音色，方便后续排序。

### 2. 页面内音频播放

- 新增 `GET /audio/<file_id>` 用于播放试听音频。
- 新增 `GET /jobs/<job_id>/items/<item_id>/audio` 用于播放任务生成的音频片段。
- 单条任务完成后，页面下载区会显示音频播放器。

### 3. 最近生成历史

- 新增 `GET /history`。
- 新增 `DELETE /history/<history_id>`。
- 任务成功完成后自动记录历史。
- 历史记录包含摘要、音色、语速、字数、成功片段数、下载链接和播放链接。
- 前端支持播放、下载和删除历史项。

### 4. 音色搜索、收藏和最近使用

- `/voices` 返回音色时附带 `favorite` 和 `recent` 标记。
- 新增 `GET /preferences`。
- 新增 `POST /preferences/favorites/<voice_id>`。
- 前端支持搜索音色名称、ID、性别和风格。
- 收藏音色和最近使用音色会优先展示。

### 5. 场景预设

- 新增 `GET /presets`。
- 内置短视频口播、新闻播报、小说旁白、儿童故事、粤语口播等预设。
- 预设会自动切换音色和语速。

## 相关接口

```text
POST   /preview
GET    /audio/<file_id>
GET    /jobs/<job_id>/items/<item_id>/audio
GET    /history
DELETE /history/<history_id>
GET    /preferences
POST   /preferences/favorites/<voice_id>
GET    /presets
```

## 相关文件

- `app.py`：试听、播放、历史、偏好和预设接口
- `templates/index.html`：播放器、试听、历史记录、音色搜索收藏、预设交互
- `static/css/style.css`：v0.5 控件样式
- `tests/test_app.py`：v0.5 自动化测试
- `README.md`：v0.5 使用说明

## 验证结果

已通过：

```bash
./.venv/bin/python -m pytest -q
```

结果：

```text
20 passed
```

已通过：

```bash
./.venv/bin/python -m py_compile app.py run.py
```

## 已知取舍

- 历史记录和偏好仍保存在当前进程内存中，重启后会清空。
- 多段音频仍采用 ZIP 下载，尚未合并为单个 MP3。
- 试听接口同步生成前 300 字音频，网络慢时可能需要等待数秒。
