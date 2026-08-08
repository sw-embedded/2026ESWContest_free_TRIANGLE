from flask import Flask, render_template_string, jsonify

app = Flask(__name__)
controller_instance = None

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>스마트 책상 모니터링</title>
    <style>
        body { font-family: sans-serif; background-color: #f0f2f5; margin: 0; padding: 20px; text-align: center; }
        .card { max-width: 450px; margin: 20px auto; background: white; border-radius: 16px; padding: 25px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        h1 { font-size: 20px; color: #333; margin-bottom: 20px; }
        .status-badge { font-size: 26px; font-weight: bold; padding: 15px; border-radius: 12px; margin-bottom: 20px; }
        .NORMAL { background-color: #e8f5e9; color: #2e7d32; }
        .TURTLE_NECK { background-color: #ffebee; color: #c62828; }
        .BENT_BACK { background-color: #fff3e0; color: #ef6c00; }
        .metrics { display: flex; justify-content: space-around; background: #fafafa; padding: 15px; border-radius: 10px; }
        .metric-item p { margin: 5px 0; font-size: 14px; color: #666; }
        .metric-item span { font-size: 20px; font-weight: bold; color: #111; }
        .time { margin-top: 15px; font-size: 12px; color: #aaa; }
    </style>
</head>
<body>
    <div class="card">
        <h1>스마트 책상 실시간 자세 모니터링</h1>
        <div id="badge" class="status-badge NORMAL">
            <span id="pose-text">NORMAL</span>
        </div>
        <div class="metrics">
            <div class="metric-item">
                <p>목 각도 (귀-어깨)</p>
                <span id="neck-angle">0</span>°
            </div>
            <div class="metric-item">
                <p>허리 각도 (어깨-골반)</p>
                <span id="back-angle">0</span>°
            </div>
        </div>
        <div class="time">최종 갱신 시간: <span id="update-time">-</span></div>
    </div>

    <script>
        function fetchStatus() {
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('pose-text').innerText = data.pose;
                    document.getElementById('neck-angle').innerText = data.neck_angle;
                    document.getElementById('back-angle').innerText = data.back_angle;
                    document.getElementById('update-time').innerText = data.updated_time;
                    
                    const badge = document.getElementById('badge');
                    badge.className = 'status-badge ' + data.pose;
                });
        }
        setInterval(fetchStatus, 1000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/status')
def get_status():
    if controller_instance:
        return jsonify(controller_instance.current_status)
    return jsonify({"pose": "UNKNOWN", "neck_angle": 0, "back_angle": 0, "updated_time": ""})

def start_server(ctrl_obj):
    global controller_instance
    controller_instance = ctrl_obj
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
