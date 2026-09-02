# MoveNet model files

이 디렉터리는 MoveNet SinglePose TFLite 모델을 두는 위치입니다. 모델 바이너리는
현재 저장소에 포함되어 있지 않습니다.

기본 설정(`config/default.yaml`)은 `thunder`입니다. 제출 기준 파일은
**MoveNet SinglePose Thunder v4의 TFLite float16 variant**입니다. 이 variant는
가중치를 float16으로 저장하지만 입력 텐서의 shape/dtype은 모델 메타데이터를
기준으로 처리합니다.

| 설정값 | 필요한 파일명 | 공식 참고 |
|---|---|---|
| `thunder` | `movenet_singlepose_thunder.tflite` | [MoveNet Thunder v4](https://tfhub.dev/google/movenet/singlepose/thunder/4) |
| `lightning` | `movenet_singlepose_lightning.tflite` | [MoveNet Lightning v4](https://tfhub.dev/google/movenet/singlepose/lightning/4) |

## Thunder v4 다운로드와 무결성 확인

저장소 루트에서 다음 명령을 실행합니다.

```bash
curl -L "https://tfhub.dev/google/lite-model/movenet/singlepose/thunder/tflite/float16/4?lite-format=tflite" \
  -o models/movenet_singlepose_thunder.tflite
echo "41641538679ec79b07d4101e591dda47d098c09af29607674b2a40b8a3798dd3  models/movenet_singlepose_thunder.tflite" \
  | sha256sum -c -
```

검증한 공식 파일 크기는 `12,584,128 bytes`, SHA-256은
`41641538679ec79b07d4101e591dda47d098c09af29607674b2a40b8a3798dd3`입니다.
다운로드한 파일은 FlatBuffer 식별자 `TFL3`을 가져야 합니다. 체크섬이 다르면
그 파일로 시연하지 말고 URL/variant를 다시 확인합니다.

공식 TensorFlow 예제에서 Thunder 입력은 256×256, Lightning 입력은 192×192이며
두 SinglePose 모델의 출력은 `[1, 1, 17, 3]`입니다. 이 프로젝트는 입력 크기와
dtype을 실제 TFLite 모델 메타데이터에서 읽고, 출력 형태를 실행 시 확인합니다.

제출 전에 다음을 확인하세요.

1. 실제 시연에 사용한 모델 종류를 확정합니다.
2. 공식 출처에서 TFLite 모델을 받아 위 파일명으로 저장합니다.
3. 모델 파일의 배포 허용 범위와 Apache 2.0 고지 의무를 확인합니다.
4. Raspberry Pi에서 모델 로드와 한 프레임 추론을 실행합니다.
5. 실제 파일의 입력 shape/dtype과 출력 shape를 개발완료보고서에 기록합니다.

모델이 없거나 손상된 경우 코드는 다른 모델로 자동 교체하지 않습니다. 따라서
`thunder`로 설정한 채 Lightning 파일만 두어도 실행되지 않습니다.
