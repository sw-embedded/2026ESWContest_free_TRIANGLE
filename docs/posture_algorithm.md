# MoveNet 자세 평가 알고리즘

## 모델 입출력

- 기술: MoveNet SinglePose TFLite
- 기본 설정: `thunder`
- 모델 파일: `models/movenet_singlepose_thunder.tflite`
- 입력 크기/dtype: 실제 TFLite 모델 메타데이터에서 읽음
- 출력: `[1, 1, 17, 3]`, 각 keypoint는 `(y, x, confidence score)`
- confidence 기준: 기본 `0.05`

모델 파일은 현재 저장소에 없으므로 실제 입력 shape/dtype은 실행 검증하지 못했습니다.
코드에는 MediaPipe와 3D 좌표가 사용되지 않습니다.

## 전처리

원본 프레임의 종횡비를 유지하여 모델 입력 정사각형 안에 resize한 뒤 남는 영역을
0 값으로 padding합니다. 현재 구현은 letterbox이며 dynamic crop은 아닙니다.

## 관절 선택과 좌표 복원

MoveNet 표준 인덱스 중 다음을 사용합니다.

- 귀: left 3, right 4
- 어깨: left 5, right 6
- 골반: left 11, right 12

좌우 각각의 귀+어깨+골반 score 합을 비교해 더 높은 측면을 선택합니다. 모델의
정규화 좌표에서 padding을 제거하고 원본 프레임 픽셀 좌표로 환산합니다.

## 각도와 EMA

- 목 각도: 귀와 어깨의 수직선 대비 전방 기울기를 `atan2(dx, dy)`로 계산합니다.
- 몸통 각도: 어깨-골반 선의 수직 대비 기울기를 `atan2(abs(dx), abs(dy))`로
  계산합니다.
- EMA: 계산된 각도에 `alpha=0.3`을 적용합니다.

따라서 PPT의 “keypoint 좌표 자체에 EMA” 설명과 달리 현재 코드는 최종 각도 값을
평활합니다.

## 자세 판정과 유지 시간

| 상태 | `config/default.yaml` 기준 |
|---|---|
| `TURTLE_NECK` | 목 각도 ≥ 22° |
| `BENT_BACK` | 목 조건 미충족이고 골반이 보이며 몸통 각도 ≥ 15° |
| `NORMAL` | 두 불량 자세 조건 미충족 |
| `POSE_LOST` | 귀 또는 어깨 confidence 부족 |

같은 불량 자세가 60초 연속 유지되면 한 번만 Arduino 교정 명령을 보냅니다.
`NORMAL`, `POSE_LOST`, 다른 불량 자세로 바뀌면 유지 시간이 초기화됩니다.
교정이 Arduino에서 `APPLIED` 상태일 때 `NORMAL` 자세가 300초 연속 유지되면
복귀 명령을 요청합니다. 300초가 되기 전에 다른 자세로 바뀌거나 교정 상태가
`APPLIED`를 벗어나면 타이머는 초기화됩니다. 대기 시간은
`posture.normal_restore_delay_sec`에서 조정합니다.
