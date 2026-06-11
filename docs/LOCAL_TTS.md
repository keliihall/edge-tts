# CosyVoice 3 与 Kokoro 本地接入

声笺 v1.1 将本地模型作为独立 sidecar 进程运行。主程序只负责用户、任务、
音色和文件管理，不直接加载 PyTorch、CUDA、MLX 或模型权重。

## 默认端口

| Provider | 默认地址 | 定位 |
| --- | --- | --- |
| CosyVoice 3 | `http://127.0.0.1:50000` | 中文质量、零样本音色克隆 |
| Kokoro | `http://127.0.0.1:50001` | 轻量、低资源、高并发 |

地址只能使用 `localhost`、`127.0.0.1` 或 `::1`。也可通过
`COSYVOICE_TTS_URL`、`KOKORO_TTS_URL` 环境变量覆盖后台设置。

## Sidecar 契约

### `GET /health`

返回模型是否已加载：

```json
{
  "status": "ready",
  "message": "model loaded",
  "model": "CosyVoice 3"
}
```

`status` 必须为 `ok`、`ready` 或 `healthy` 才会被视为可用。

### `GET /voices`

返回当前服务实际可用的预置或克隆音色：

```json
{
  "voices": [
    {
      "id": "narrator-zh",
      "name": "中文旁白",
      "gender": "女",
      "style": "自然、沉稳"
    }
  ]
}
```

也可以直接返回数组。`id` 和 `name` 为必需信息，克隆音色建议使用稳定 ID。

### `POST /synthesize`

请求：

```json
{
  "text": "欢迎使用声笺。",
  "voice": "narrator-zh",
  "speech_rate": 1.0,
  "volume": 1.0,
  "pitch": 0,
  "format": "mp3"
}
```

成功响应优先直接返回 `Content-Type: audio/mpeg` 的 MP3 字节。也支持 JSON：

```json
{
  "format": "mp3",
  "audio_base64": "<base64>"
}
```

v1.1 要求 sidecar 输出 MP3，采样率与声道可自行选择，但同一任务的所有分段应保持
一致编码参数。CosyVoice/Kokoro 原始输出若为 PCM/WAV，可在 sidecar 内用 ffmpeg
编码为 MP3 后返回。

## 部署步骤

1. 分别创建 CosyVoice 3、Kokoro 的独立虚拟环境。
2. 按 [CosyVoice 官方仓库](https://github.com/FunAudioLLM/CosyVoice) 或
   [Kokoro 官方仓库](https://github.com/hexgrad/kokoro) 安装推理依赖和模型权重。
3. 用适配层实现上述三个 HTTP 端点，并只监听回环地址。
4. 启动服务后先验证健康与音色接口：

```bash
curl http://127.0.0.1:50000/health
curl http://127.0.0.1:50000/voices
curl http://127.0.0.1:50001/health
curl http://127.0.0.1:50001/voices
```

5. 在声笺后台启用对应引擎，保存地址并进入诊断页复查。

还可以运行完整协议验收，它会生成一段真实 MP3：

```bash
python scripts/check_local_tts.py http://127.0.0.1:50000
python scripts/check_local_tts.py http://127.0.0.1:50001
```

## 产品建议

- CosyVoice 3 用于高质量中文、品牌音色和音色克隆。
- Kokoro 用于预置音色、CPU/Apple Silicon 和高并发快速生成。
- 两个服务应独立设置并发上限；声笺默认单工作线程，可避免显存争抢。
- 不要让 sidecar 监听 `0.0.0.0`，也不要接受任意文件路径或远程 URL。
- 克隆参考音频的上传、授权和生命周期应由 sidecar 单独管理；v1.1 主程序只消费
  sidecar 已发布的音色 ID。
