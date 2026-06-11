from __future__ import annotations

import html
from pathlib import Path

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


ROOT = Path(__file__).resolve().parent
ASSET_DIR = ROOT / "assets"
SCORECARD_PATH = ROOT / "scorecard.csv"
REPORT_PATH = ROOT / "report.html"
FONT_PATH = ROOT.parents[1] / "static" / "fonts" / "NotoSansSC-VariableFont_wght.ttf"

WEIGHTS = {
    "quality_zh": 0.25,
    "capability_fit": 0.15,
    "deployment_cost": 0.15,
    "integration_maturity": 0.15,
    "license_clarity": 0.15,
    "ecosystem": 0.10,
    "cross_platform": 0.05,
}

CATEGORY_LABELS = {
    "quality_zh": "中文质量",
    "capability_fit": "能力匹配",
    "deployment_cost": "部署成本",
    "integration_maturity": "集成成熟度",
    "license_clarity": "许可清晰度",
    "ecosystem": "生态维护",
    "cross_platform": "跨平台",
}

SOURCE_URLS = {
    "CosyVoice 3": "https://github.com/FunAudioLLM/CosyVoice",
    "Qwen3-TTS": "https://github.com/QwenLM/Qwen3-TTS",
    "Chatterbox": "https://github.com/resemble-ai/chatterbox",
    "GPT-SoVITS": "https://github.com/RVC-Boss/GPT-SoVITS",
    "Spark-TTS": "https://github.com/SparkAudio/Spark-TTS",
    "Kokoro": "https://github.com/hexgrad/kokoro",
    "OpenVoice": "https://github.com/myshell-ai/OpenVoice",
    "IndexTTS2": "https://github.com/index-tts/index-tts",
    "F5-TTS": "https://github.com/SWivid/F5-TTS",
    "Piper": "https://github.com/OHF-Voice/piper1-gpl",
    "Fish Audio S2": "https://github.com/fishaudio/fish-speech",
    "Edge TTS": "https://github.com/rany2/edge-tts",
}


def load_scores() -> pd.DataFrame:
    scores = pd.read_csv(SCORECARD_PATH)
    scores["product_score"] = sum(
        scores[column] * weight for column, weight in WEIGHTS.items()
    ).round(2)
    scores["quality_capability"] = (
        scores["quality_zh"] * 0.6 + scores["capability_fit"] * 0.4
    ).round(2)
    scores["rank"] = (
        scores.loc[scores["model"] != "Edge TTS", "product_score"]
        .rank(method="min", ascending=False)
        .astype(int)
    )
    return scores


def configure_charts() -> str:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    font_family = "DejaVu Sans"
    if FONT_PATH.exists():
        fm.fontManager.addfont(str(FONT_PATH))
        font_family = fm.FontProperties(fname=str(FONT_PATH)).get_name()
    sns.set_theme(
        style="whitegrid",
        rc={
            "figure.facecolor": "#FCFCFD",
            "axes.facecolor": "#FFFFFF",
            "axes.edgecolor": "#D7DBE7",
            "axes.labelcolor": "#1F2430",
            "text.color": "#1F2430",
            "xtick.color": "#6F768A",
            "ytick.color": "#1F2430",
            "grid.color": "#E6E8F0",
            "grid.linewidth": 0.8,
            "font.family": font_family,
        },
    )
    return font_family


def render_score_chart(scores: pd.DataFrame) -> None:
    ranked = (
        scores[scores["model"] != "Edge TTS"]
        .sort_values("product_score", ascending=True)
        .copy()
    )
    colors = [
        "#5477C4" if score >= 8.5 else "#A3BEFA" if score >= 8.0 else "#E2E5EA"
        for score in ranked["product_score"]
    ]
    fig, ax = plt.subplots(figsize=(10.5, 6.8))
    bars = ax.barh(
        ranked["model"],
        ranked["product_score"],
        color=colors,
        edgecolor="#2E4780",
        linewidth=0.8,
    )
    ax.set_xlim(0, 10)
    ax.set_xlabel("加权产品落地评分（10 分制）")
    ax.set_ylabel("")
    ax.xaxis.grid(True)
    ax.yaxis.grid(False)
    for bar, value in zip(bars, ranked["product_score"]):
        ax.text(
            value + 0.08,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.1f}",
            va="center",
            fontsize=10,
            color="#1F2430",
        )
    fig.subplots_adjust(top=0.84, left=0.22, right=0.94, bottom=0.12)
    fig.text(
        0.22,
        0.965,
        "本地 TTS 候选综合评分",
        ha="left",
        va="top",
        fontsize=17,
        fontweight="semibold",
    )
    fig.text(
        0.22,
        0.92,
        "中文质量 25%，能力/部署/集成/许可各 15%，生态 10%，跨平台 5%；桌面调研评分，待实测校准",
        ha="left",
        va="top",
        fontsize=9.5,
        color="#6F768A",
    )
    sns.despine(ax=ax, left=False, bottom=False)
    fig.savefig(ASSET_DIR / "product-score.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def render_heatmap(scores: pd.DataFrame) -> None:
    selected = (
        scores[scores["model"] != "Edge TTS"]
        .sort_values("product_score", ascending=False)
        .head(8)
        .set_index("model")
    )
    matrix = selected[list(WEIGHTS)].rename(columns=CATEGORY_LABELS)
    fig, ax = plt.subplots(figsize=(10.8, 6.0))
    sns.heatmap(
        matrix,
        annot=True,
        fmt=".1f",
        cmap=sns.light_palette("#5477C4", as_cmap=True),
        vmin=0,
        vmax=10,
        linewidths=1,
        linecolor="#FFFFFF",
        cbar_kws={"label": "评分"},
        ax=ax,
    )
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.tick_params(axis="x", rotation=0)
    ax.tick_params(axis="y", rotation=0)
    fig.subplots_adjust(top=0.82, left=0.19, right=0.95, bottom=0.13)
    fig.text(
        0.19,
        0.965,
        "高分模型的优势结构不同",
        ha="left",
        va="top",
        fontsize=17,
        fontweight="semibold",
    )
    fig.text(
        0.19,
        0.92,
        "CosyVoice/Qwen 偏质量与控制，Chatterbox/GPT-SoVITS 偏创作工作流，Kokoro 偏轻量离线",
        ha="left",
        va="top",
        fontsize=9.5,
        color="#6F768A",
    )
    fig.savefig(
        ASSET_DIR / "capability-heatmap.png",
        dpi=180,
        bbox_inches="tight",
    )
    plt.close(fig)


def score_table(scores: pd.DataFrame) -> str:
    candidates = (
        scores[scores["model"] != "Edge TTS"]
        .sort_values("product_score", ascending=False)
        .copy()
    )
    rows = []
    for _, row in candidates.iterrows():
        source_url = SOURCE_URLS[row["model"]]
        rows.append(
            "<tr>"
            f"<td class='rank'>{int(row['rank'])}</td>"
            f"<td><a href='{html.escape(source_url)}'>{html.escape(row['model'])}</a>"
            f"<span>{html.escape(row['variant'])}</span></td>"
            f"<td class='score'>{row['product_score']:.1f}</td>"
            f"<td class='score'>{row['quality_capability']:.1f}</td>"
            f"<td>{html.escape(row['hardware_band'])}</td>"
            f"<td>{html.escape(row['license_summary'])}</td>"
            f"<td>{html.escape(row['recommendation'])}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_report(scores: pd.DataFrame) -> None:
    table_rows = score_table(scores)
    report = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>声笺本地 TTS 选型评估</title>
  <style>
    @font-face {{
      font-family: "Noto Sans SC";
      src: url("../../static/fonts/NotoSansSC-VariableFont_wght.ttf") format("truetype");
      font-weight: 100 900;
    }}
    :root {{
      --ink: #1f2430;
      --muted: #687086;
      --line: #e1e5ed;
      --panel: #ffffff;
      --surface: #f7f8fb;
      --blue: #5477c4;
      --blue-soft: #eaf1fe;
      --gold-soft: #fff4c2;
      --orange-soft: #ffedde;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: var(--surface);
      font-family: "Noto Sans SC", ui-sans-serif, system-ui, sans-serif;
    }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 46px 24px 80px; }}
    header, section {{
      margin-bottom: 28px;
      padding: 30px 34px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--panel);
      box-shadow: 0 10px 28px rgba(31, 36, 48, 0.05);
    }}
    header {{ background: linear-gradient(135deg, #ffffff 30%, var(--blue-soft)); }}
    h1 {{ margin: 0 0 10px; font-size: clamp(30px, 5vw, 48px); line-height: 1.15; }}
    h2 {{ margin: 0 0 16px; font-size: 25px; line-height: 1.25; }}
    h3 {{ margin: 24px 0 8px; font-size: 18px; }}
    p, li {{ line-height: 1.72; }}
    .meta {{ color: var(--muted); }}
    .executive-summary-box {{
      background: linear-gradient(180deg, #f4f7ff, #eef3ff);
      border-color: #cedffe;
    }}
    .executive-summary-box ul {{ margin: 0; padding-left: 22px; }}
    .executive-summary-box li + li {{ margin-top: 10px; }}
    .callout {{
      padding: 16px 18px;
      border-left: 4px solid var(--blue);
      border-radius: 10px;
      background: var(--blue-soft);
    }}
    .warning {{ border-left-color: #cc6f47; background: var(--orange-soft); }}
    .decision-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .decision-card {{
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fcfcfd;
    }}
    .decision-card strong {{ display: block; margin-bottom: 6px; color: #2e4780; }}
    figure {{ margin: 22px 0 8px; }}
    figure img {{ display: block; width: 100%; height: auto; border-radius: 12px; }}
    figcaption {{ margin-top: 10px; color: var(--muted); font-size: 14px; line-height: 1.6; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 12px; }}
    table {{ width: 100%; min-width: 1000px; border-collapse: collapse; font-size: 14px; }}
    th, td {{ padding: 12px 13px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--line); }}
    th {{ background: #f2f4f8; position: sticky; top: 0; }}
    td span {{ display: block; margin-top: 3px; color: var(--muted); font-size: 12px; }}
    td a {{ color: #2e4780; font-weight: 700; text-decoration: none; }}
    .rank, .score {{ text-align: center; font-variant-numeric: tabular-nums; font-weight: 700; }}
    code {{ padding: 2px 6px; border-radius: 5px; background: #f0f2f6; font-size: 0.92em; }}
    ol, ul {{ padding-left: 24px; }}
    .weights {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
    }}
    .weight {{ padding: 12px; border-radius: 10px; background: #f3f5f9; }}
    .weight b {{ display: block; color: #2e4780; }}
    .source-inline a {{ color: #2e4780; }}
    @media (max-width: 760px) {{
      main {{ padding: 24px 12px 54px; }}
      header, section {{ padding: 22px 18px; border-radius: 14px; }}
      .decision-grid, .weights {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<main data-report-audience="product stakeholders">
  <header data-contract-section="title">
    <h1>声笺本地 TTS 选型评估</h1>
    <p class="meta">截至 2026 年 6 月 11 日 · 面向中文桌面产品、离线能力和后续多引擎扩展</p>
  </header>

  <section class="executive-summary-box" data-contract-section="executive-summary">
    <h2>Executive Summary</h2>
    <ul>
      <li><strong>首选质量引擎：CosyVoice 3 0.5B。</strong>它在中文、方言、零样本克隆、发音修正和双向流式方面最贴合声笺，官方模型与代码采用 Apache-2.0，适合作为第一条 NVIDIA GPU 本地链路。</li>
      <li><strong>第二质量引擎：Qwen3-TTS。</strong>0.6B 适合较低资源部署，1.7B 提供更强的语音设计、指令控制和克隆能力；它应作为与 CosyVoice 并行验证的第二候选，而不是一开始同时产品化全部变体。</li>
      <li><strong>轻量离线引擎：Kokoro 82M；宽松许可克隆备选：Chatterbox 中文 V3。</strong>Kokoro 适合无独显设备和固定音色，Chatterbox 则兼顾 MIT、中文专模、CUDA/CPU/MPS 与零样本克隆。</li>
      <li><strong>不要把大模型直接塞进当前 PyInstaller 单文件。</strong>现有代码把网络检查、Edge 音色、MP3 临时文件和生成函数绑在一起；本地模型应作为独立常驻 sidecar，通过统一 Provider 协议接入，Edge TTS 保留为在线回退。</li>
    </ul>
  </section>

  <section data-contract-section="key-findings">
    <h2>优先做“双档本地模式”，而不是押注单一模型</h2>
    <p><strong>质量档</strong>建议先验证 CosyVoice 3，并用 Qwen3-TTS 做对照；<strong>轻量档</strong>建议用 Kokoro 验证真正离线、无独显、低安装成本的用户路径。Chatterbox 中文 V3 和 GPT-SoVITS 更适合后续“自定义音色/创作者工作流”。</p>
    <figure>
      <img src="assets/product-score.png" alt="本地 TTS 候选综合评分横向条形图">
      <figcaption>这是面向声笺的产品落地评分，不是单纯音质榜。Fish Audio S2 的质量上限很高，但商业许可和资源成本使其综合排名下降。</figcaption>
    </figure>
    <div class="decision-grid">
      <div class="decision-card"><strong>P0 · CosyVoice 3</strong>中文和方言覆盖强、0.5B、支持发音修正与约 150 ms 官方流式延迟主张；适合本产品的第一条高质量本地链路。</div>
      <div class="decision-card"><strong>P0 · Kokoro 82M</strong>Apache-2.0、CPU 友好、支持普通话管线；能力较窄，但最适合先打通离线安装、模型下载和 Provider 抽象。</div>
      <div class="decision-card"><strong>P1 · Qwen3-TTS</strong>Apache-2.0，0.6B/1.7B 梯度清晰，支持十种语言、克隆、语音设计和流式；新项目，需重点测稳定性与实际 RTF。</div>
      <div class="decision-card"><strong>P1 · Chatterbox 中文 V3</strong>MIT、0.5B、中文单语专模和克隆，设备选择更宽；适合作为跨平台、商业许可清晰的高级音色后端。</div>
    </div>
    <p class="source-inline">关键官方资料：
      <a href="https://github.com/FunAudioLLM/CosyVoice">CosyVoice 3</a>、
      <a href="https://github.com/QwenLM/Qwen3-TTS">Qwen3-TTS</a>、
      <a href="https://huggingface.co/ResembleAI/Chatterbox-Multilingual-zh-cmn">Chatterbox 中文 V3</a>、
      <a href="https://github.com/hexgrad/kokoro">Kokoro</a>。
    </p>
  </section>

  <section>
    <h2>评分结构解释了“试听最好”不等于“最适合首发”</h2>
    <p>CosyVoice 3 和 Qwen3-TTS 在中文质量与控制能力上领先；GPT-SoVITS 和 Chatterbox 更适合用户自定义音色；Kokoro 的优势集中在部署、集成、许可和跨平台。IndexTTS2 的时长控制很适合配音，但自定义许可和更高资源档位需要单独评审。</p>
    <figure>
      <img src="assets/capability-heatmap.png" alt="主要候选模型分项评分热力图">
      <figcaption>硬件档位为规划估计，不是厂商统一口径。0.5B/0.6B 一般按 8-12 GB 显存舒适档规划，1.5B/1.7B 按 12-24 GB 规划，最终以本产品实测为准。</figcaption>
    </figure>
  </section>

  <section>
    <h2>完整评分表</h2>
    <div class="weights">
      <div class="weight"><b>25%</b>中文质量与稳定性</div>
      <div class="weight"><b>15%</b>能力匹配</div>
      <div class="weight"><b>15%</b>本地部署成本</div>
      <div class="weight"><b>15%</b>集成与服务成熟度</div>
      <div class="weight"><b>15%</b>许可与商业清晰度</div>
      <div class="weight"><b>10%</b>生态与维护</div>
      <div class="weight"><b>5%</b>跨平台与离线打包</div>
    </div>
    <p>“能力/音质”是中文质量 60% 与能力匹配 40% 的辅助读数；“综合分”才用于本产品排序。</p>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>排名</th><th>模型/变体</th><th>综合分</th><th>能力/音质</th><th>规划硬件档</th><th>许可判断</th><th>建议角色</th></tr>
        </thead>
        <tbody>
          {table_rows}
        </tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>现有代码的四个接入阻点</h2>
    <ol>
      <li><strong>生成逻辑没有 Provider 边界。</strong><code>process_text_job</code> 直接调用 <code>generate_speech_with_retries</code>，后者再直接调用 Edge TTS。新增模型前应先抽象 <code>list_voices</code>、<code>synthesize</code>、<code>health</code> 和 <code>capabilities</code>。</li>
      <li><strong>本地模式会被网络检查挡住。</strong>试听和转换入口都在建任务前检查 Edge 网络；检查必须下沉到具体 Provider。</li>
      <li><strong>参数与音色命名空间属于 Edge。</strong>当前任务只存 <code>voice/speech_rate/volume/pitch</code>，需要增加 <code>provider/model/version/language/instruction/reference_audio</code>，并按 capability 决定哪些控件可用。</li>
      <li><strong>音频管线固定为 MP3 字节拼接。</strong>多数本地模型输出 WAV。应先统一成 PCM/WAV 分段，做真正的音频拼接，再一次性编码 MP3；否则跨模型长文本会出现容器或时间戳问题。</li>
    </ol>
    <div class="callout"><strong>部署建议：</strong>保留当前 Flask 主程序和任务系统；每个本地引擎运行在独立常驻进程或容器，通过 localhost HTTP/Unix socket 通信。模型权重按需下载，不进入主 PyInstaller 包。</div>
  </section>

  <section data-contract-section="recommended-next-steps">
    <h2>推荐实施顺序</h2>
    <ol>
      <li><strong>先做 Provider 协议和音频标准化。</strong>实现 Edge 适配器保持现有行为，再加一个 mock/local adapter，确保任务、重试、历史和批量接口不感知具体引擎。</li>
      <li><strong>两周内完成两个 POC。</strong>质量 POC 用 CosyVoice 3 0.5B；轻量 POC 用 Kokoro 82M。两者均以 sidecar 形式实现 <code>/health</code>、<code>/voices</code>、<code>/synthesize</code>。</li>
      <li><strong>用同一套中文语料横评 Qwen3-TTS 与 Chatterbox。</strong>只有在相对 Cosy/Kokoro 明显改善某一用户场景时，才进入正式 Provider 列表。</li>
      <li><strong>把克隆音色作为受控高级功能。</strong>上传参考音频前增加授权确认、来源记录、保留期、删除能力和滥用提示；不要在第一版本默认开放。</li>
    </ol>
  </section>

  <section data-contract-section="further-questions">
    <h2>实测需要回答的关键问题</h2>
    <ul>
      <li>目标用户中，无独显、Apple Silicon、8 GB/12 GB NVIDIA、24 GB NVIDIA 的占比分别是多少？</li>
      <li>普通话、粤语、方言、小说长文本、短视频口播和克隆音色，哪一类是下一阶段主场景？</li>
      <li>是否允许单独下载 1-10 GB 模型包，以及是否接受首次启动数分钟的安装和编译准备？</li>
      <li>商业发行是否需要完全宽松许可，还是可以接受 GPL 独立进程或商业模型授权？</li>
    </ul>
  </section>

  <section data-contract-section="caveats-and-assumptions">
    <h2>限制与假设</h2>
    <div class="callout warning">
      <p><strong>本报告是桌面调研，不是最终听感结论。</strong>各项目公开基准的数据集、参考音频和推理配置不同，不能直接横向等价。下一步必须在目标硬件上测首音延迟、RTF、峰值显存/内存、长文本失败率、中文 CER、主观 MOS 和克隆相似度。</p>
      <p><strong>许可评分不是法律意见。</strong>Fish Audio S2 明确要求商业用途另行授权；F5 官方预训练权重为非商业许可；Piper 引擎为 GPL-3.0 且音色另有许可证；IndexTTS2 使用自定义模型协议。正式发行前需要逐项法务确认。</p>
    </div>
  </section>
</main>
</body>
</html>
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


def main() -> None:
    scores = load_scores()
    configure_charts()
    render_score_chart(scores)
    render_heatmap(scores)
    render_report(scores)
    print(f"Wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
