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
        .card { max-width: 560px; margin: 20px auto; background: white; border-radius: 16px; padding: 25px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        h1 { font-size: 20px; color: #333; margin-bottom: 20px; }
        .status-badge { font-size: 26px; font-weight: bold; padding: 15px; border-radius: 12px; margin-bottom: 20px; }
        .NORMAL { background-color: #e8f5e9; color: #2e7d32; }
        .TURTLE_NECK { background-color: #ffebee; color: #c62828; }
        .BENT_BACK { background-color: #fff3e0; color: #ef6c00; }
        .POSE_LOST { background-color: #eceff1; color: #455a64; }
        .metrics { display: flex; justify-content: space-around; background: #fafafa; padding: 15px; border-radius: 10px; }
        .metric-item p { margin: 5px 0; font-size: 14px; color: #666; }
        .metric-item span { font-size: 20px; font-weight: bold; color: #111; }
        .correction-panel { margin-top: 16px; padding: 16px; border: 1px solid #e0e0e0; border-radius: 12px; text-align: left; }
        .correction-title { margin: 0 0 12px; color: #555; font-size: 14px; }
        .correction-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
        .correction-item { padding: 12px; background: #fafafa; border-radius: 10px; }
        .correction-item p { margin: 0 0 6px; color: #777; font-size: 12px; }
        .correction-item span { font-size: 16px; font-weight: bold; }
        .correction-badge { display: inline-block; padding: 6px 10px; border-radius: 999px; }
        .phase-IDLE { background: #eceff1; color: #455a64; }
        .phase-APPLYING { background: #fff3e0; color: #ef6c00; }
        .phase-APPLIED { background: #e3f2fd; color: #1565c0; }
        .phase-RESTORING { background: #ede7f6; color: #5e35b1; }
        .phase-FAULT { background: #ffebee; color: #c62828; }
        .connection-ok { color: #2e7d32; }
        .connection-off { color: #c62828; }
        .safety-ok { color: #2e7d32; }
        .safety-stop { color: #c62828; }
        .response-value { word-break: break-all; font-family: monospace; font-size: 12px !important; }
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
        <div class="correction-panel">
            <p class="correction-title">책상 교정 상태</p>
            <div class="correction-grid">
                <div class="correction-item">
                    <p>현재 단계</p>
                    <span id="correction-phase" class="correction-badge phase-IDLE">IDLE</span>
                </div>
                <div class="correction-item">
                    <p>적용된 교정</p>
                    <span id="active-correction">NONE</span>
                </div>
                <div class="correction-item">
                    <p>원위치 복귀</p>
                    <span id="restore-remaining">-</span>
                </div>
                <div class="correction-item">
                    <p>Arduino 연결</p>
                    <span id="arduino-connection" class="connection-off">연결 안 됨</span>
                </div>
                <div class="correction-item">
                    <p>비상정지</p>
                    <span id="emergency-stop" class="safety-ok">정상</span>
                </div>
                <div class="correction-item">
                    <p>전류 센서 / 기울기</p>
                    <span><span id="current-sensor">-</span> / <span id="tilt-mm">-</span> mm</span>
                </div>
                <div class="correction-item" style="grid-column: 1 / -1;">
                    <p>마지막 Arduino 응답</p>
                    <span id="arduino-response" class="response-value">-</span>
                </div>
                <div class="correction-item" style="grid-column: 1 / -1;">
                    <p>마지막 Arduino 오류</p>
                    <span id="arduino-error" class="response-value safety-stop">-</span>
                </div>
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

                    const phase = data.correction_phase || 'IDLE';
                    const phaseBadge = document.getElementById('correction-phase');
                    phaseBadge.innerText = phase;
                    phaseBadge.className = 'correction-badge phase-' + phase;

                    document.getElementById('active-correction').innerText =
                        data.active_correction || 'NONE';

                    const restoreText = phase === 'APPLIED'
                        ? '정상 자세 대기 중'
                        : (phase === 'RESTORING'
                            ? '복귀 진행 중'
                            : (phase === 'FAULT' ? '오류 확인 필요' : '-'));
                    document.getElementById('restore-remaining').innerText = restoreText;

                    const connection = document.getElementById('arduino-connection');
                    connection.innerText = data.arduino_connected ? '연결됨' : '연결 안 됨';
                    connection.className = data.arduino_connected
                        ? 'connection-ok'
                        : 'connection-off';

                    const emergencyStop = document.getElementById('emergency-stop');
                    emergencyStop.innerText = data.emergency_stop ? '작동' : '정상';
                    emergencyStop.className = data.emergency_stop
                        ? 'safety-stop'
                        : 'safety-ok';

                    document.getElementById('current-sensor').innerText =
                        Number.isFinite(data.current_sensor) ? data.current_sensor : '-';
                    document.getElementById('tilt-mm').innerText =
                        Number.isFinite(data.tilt_mm) ? data.tilt_mm.toFixed(2) : '-';
                    document.getElementById('arduino-response').innerText =
                        data.last_arduino_response || '-';
                    document.getElementById('arduino-error').innerText =
                        data.last_arduino_error || '-';
                })
                .catch(() => {
                    const connection = document.getElementById('arduino-connection');
                    connection.innerText = '서버 응답 오류';
                    connection.className = 'connection-off';
                });
        }
        fetchStatus();
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
    return jsonify({
        "pose": "UNKNOWN",
        "neck_angle": 0,
        "back_angle": 0,
        "correction_phase": "IDLE",
        "active_correction": "NONE",
        "restore_remaining_sec": None,
        "arduino_connected": False,
        "emergency_stop": False,
        "current_sensor": None,
        "tilt_mm": None,
        "last_arduino_response": "",
        "last_arduino_error": "",
        "updated_time": ""
    })

def start_server(ctrl_obj):
    global controller_instance
    controller_instance = ctrl_obj
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
