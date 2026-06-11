# 声笺 v1.1

v1.1 将声笺从单一 Edge TTS 客户端扩展为多 Provider 语音工作台。

## 新增

- CosyVoice 3 与 Kokoro 本地 sidecar 接入
- Provider 健康检查、能力声明和动态音色目录
- 工作台语音引擎选择与能力适配
- 管理后台本地引擎地址、启用状态、超时和默认音色设置
- 任务、历史和配置收藏记录 Provider
- 回环地址校验，阻止本地 TTS 配置指向远程主机

## 兼容

- 旧任务、历史和收藏自动按 `edge` Provider 读取
- 现有 Edge TTS API 调用与五参数生成函数保持兼容
- 本地模型权重与推理依赖不进入 PyInstaller 主安装包

本地部署与 sidecar HTTP 契约见 `docs/LOCAL_TTS.md`。
