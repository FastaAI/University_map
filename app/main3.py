import pandas as pd
import folium
from folium.plugins import MarkerCluster

# 1) 데이터 불러오기
filePath = r'C:\Development\VS_CODE\동아리 활동\전국의 대학교 위치 시각화하기\venv1\yield\학교주소좌표.xlsx'

# header=0 → 첫 행을 컬럼명으로 인식
df = pd.read_excel(filePath, engine='openpyxl', header=0)

# 2) 앞의 4개 열만 가져오기 (자동 인덱스 활용)
df = df.iloc[:, [0, 1, 2, 3]]
df.columns = ['학교이름', '주소', 'x', 'y']

# 3) 좌표 데이터 정리
df['x'] = pd.to_numeric(df['x'], errors='coerce')   # 경도
df['y'] = pd.to_numeric(df['y'], errors='coerce')   # 위도
df = df.dropna(subset=['x','y'])
df = df[(df['x'] != 0) & (df['y'] != 0)]

# 4) 지도 중심을 데이터 평균 좌표로
center = [df['y'].mean(), df['x'].mean()]
m = folium.Map(location=center, zoom_start=7)

# 마커 클러스터 추가
cluster = MarkerCluster().add_to(m)

# 5) 마커 찍기 (위도, 경도 순서 주의!)
for _, row in df.iterrows():
    popup_html = f"{row['학교이름']}<br>{row['주소']}"
    folium.Marker(
        [row['y'], row['x']],
        popup=folium.Popup(popup_html, max_width=300),
        icon=folium.Icon(color='red')
    ).add_to(cluster)

# 6) 결과 저장
out_path = r'C:\Development\VS_CODE\동아리 활동\전국의 대학교 위치 시각화하기\venv1\yield\uni_map.html'
m.save(out_path)
print("저장 완료:", out_path)
