# 🧠 자세 평가 및 노이즈 필터링 알고리즘

## 1. 노이즈 제거 (Exponential Smoothing Filter)
프레임별 관절 측정값의 떨림(Jitter)을 방지하기 위해 지수 평활법을 적용한다.
$$\text{Smoothed\_Val} = \alpha \times \text{Current\_Val} + (1 - \alpha) \times \text{Previous\_Val} \quad (\alpha = 0.3)$$

## 2. 관절 각도 계산 및 임계값
- **목 전방 경사각 (Neck Angle)**: 귀와 어깨 위치 간 X/Y 축 차이를 삼각함수($\arctan$)로 산출 (임계값: $22^\circ$)
- **몸통 경사각 (Back Angle)**: 어깨와 엉덩이 관절 위치 수직 대비 기울기 산출 (임계값: $15^\circ$)
