from flask import Flask, render_template, request, send_file, jsonify
import subprocess
import os
import tempfile
from datetime import datetime
import time

app = Flask(__name__)

# 定义可用的语音列表
AVAILABLE_VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓", "gender": "女", "style": "温暖，新闻，小说"},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊", "gender": "女", "style": "可爱，卡通，小说"},
    {"id": "zh-CN-YunjianNeural", "name": "云健", "gender": "男", "style": "热情，运动，小说"},
    {"id": "zh-CN-YunxiNeural", "name": "云希", "gender": "男", "style": "阳光，小说"},
    {"id": "zh-CN-YunxiaNeural", "name": "云夏", "gender": "男", "style": "可爱，卡通，小说"},
    {"id": "zh-CN-YunyangNeural", "name": "云扬", "gender": "男", "style": "专业，新闻"},
    {"id": "zh-CN-liaoning-XiaobeiNeural", "name": "晓北", "gender": "女", "style": "东北方言，幽默"},
    {"id": "zh-CN-shaanxi-XiaoniNeural", "name": "晓妮", "gender": "女", "style": "陕西方言，明快"},
    {"id": "zh-HK-HiuGaaiNeural", "name": "晓佳", "gender": "女", "style": "粤语，亲和"},
    {"id": "zh-HK-HiuMaanNeural", "name": "晓曼", "gender": "女", "style": "粤语，亲和"},
    {"id": "zh-HK-WanLungNeural", "name": "云龙", "gender": "男", "style": "粤语，亲和"},
    {"id": "zh-TW-HsiaoChenNeural", "name": "晓辰", "gender": "女", "style": "台湾腔，亲和"},
    {"id": "zh-TW-HsiaoYuNeural", "name": "晓语", "gender": "女", "style": "台湾腔，亲和"},
    {"id": "zh-TW-YunJheNeural", "name": "云哲", "gender": "男", "style": "台湾腔，亲和"}
]

@app.route('/voices')
def get_voices():
    """获取可用的语音列表"""
    return jsonify(AVAILABLE_VOICES)

def generate_speech(text, voice="zh-CN-XiaoxiaoNeural"):
    """使用命令行方式调用 edge-tts"""
    temp_path = None
    try:
        # 创建临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp_file:
            temp_path = tmp_file.name
        
        # 构建命令
        cmd = [
            'edge-tts',
            '--voice', voice,
            '--text', text,
            '--write-media', temp_path
        ]
        
        # 执行命令
        app.logger.info(f"Executing command: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            env={"PATH": f"{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'venv/bin')}:{os.environ.get('PATH', '')}"})
        
        # 验证文件是否生成成功
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            raise Exception("Failed to generate audio file")
        
        return temp_path
    except subprocess.CalledProcessError as e:
        app.logger.error(f"Command failed with output: {e.stderr}")
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        raise Exception(f"edge-tts command failed: {e.stderr}")
    except Exception as e:
        app.logger.error(f"Error in generate_speech: {str(e)}")
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        raise e

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/convert', methods=['POST'])
def convert():
    text = request.form.get('text', '')
    if not text:
        return jsonify({'error': 'No text provided'}), 400
    
    if len(text) > 5000:  # 添加文本长度限制
        return jsonify({'error': 'Text is too long (maximum 5000 characters)'}), 400
    
    voice = request.form.get('voice', 'zh-CN-XiaoxiaoNeural')  # 允许自定义语音
    max_retries = 3
    last_error = None
    
    for attempt in range(max_retries):
        try:
            # 运行转换任务
            audio_path = generate_speech(text, voice)
            
            # 验证生成的文件
            if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
                raise Exception("Generated audio file is invalid")
            
            # 生成一个临时的下载链接
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            download_name = f'speech_{timestamp}.mp3'
            
            return jsonify({
                'audio_path': audio_path,
                'download_name': download_name,
                'voice': voice,
                'text_length': len(text)
            })
        except Exception as e:
            last_error = str(e)
            app.logger.error(f"Attempt {attempt + 1} failed: {last_error}")
            if attempt < max_retries - 1:
                time.sleep(1 * (attempt + 1))  # 增加重试延迟
                continue
    
    return jsonify({
        'error': f'Failed after {max_retries} attempts. Last error: {last_error}'
    }), 500

@app.route('/download')
def download():
    audio_path = request.args.get('path')
    download_name = request.args.get('name', 'speech.mp3')
    
    if not audio_path or not os.path.exists(audio_path):
        return jsonify({'error': 'Audio file not found'}), 404
    
    try:
        return send_file(
            audio_path,
            as_attachment=True,
            download_name=download_name,
            mimetype='audio/mpeg'
        )
    finally:
        # 在发送文件后清理
        try:
            os.unlink(audio_path)
        except:
            pass

if __name__ == '__main__':
    app.run(debug=True, port=5013) 