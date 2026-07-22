"""
KOBIS(영화진흥위원회) 일별 박스오피스 대시보드
- '어제' 날짜(한국시간 기준) 기준 박스오피스 TOP 10을 보여줍니다.
- 오늘 데이터는 아직 집계가 끝나지 않았기 때문에 항상 '어제' 데이터를 조회합니다.
"""

import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # 파이썬 내장 라이브러리 (한국 시간 계산용)

# ------------------------------------------------------------
# 1. 기본 설정
# ------------------------------------------------------------
st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")

KOBIS_URL = "http://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"


def get_yesterday_kst() -> str:
    """한국 시간(Asia/Seoul) 기준으로 '어제' 날짜를 yyyymmdd 문자열로 반환합니다.
    배포 서버가 해외에 있어도(예: UTC 기준) 이 함수는 항상 한국 시간 기준으로 계산합니다."""
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.strftime("%Y%m%d")


@st.cache_data(ttl=3600)  # 같은 날짜는 1시간 동안 캐시해서 API 호출을 아낍니다.
def fetch_box_office(target_dt: str, api_key: str):
    """KOBIS API를 호출해서 일별 박스오피스 목록을 가져옵니다.
    성공 시 (True, DataFrame) 을, 실패 시 (False, 에러메시지) 를 반환합니다."""
    params = {
        "key": api_key,
        "targetDt": target_dt,
    }

    try:
        response = requests.get(KOBIS_URL, params=params, timeout=10)
        response.raise_for_status()  # HTTP 상태코드가 200이 아니면 예외 발생
    except requests.exceptions.RequestException as e:
        return False, f"KOBIS 서버에 요청하는 중 문제가 발생했어요. (오류: {e})"

    try:
        data = response.json()
    except ValueError:
        return False, "KOBIS 서버 응답을 해석할 수 없었어요. 잠시 후 다시 시도해 주세요."

    # API 자체 오류 응답 처리 (예: 인증키 오류 등)
    if "faultInfo" in data:
        message = data["faultInfo"].get("message", "알 수 없는 오류")
        return False, f"KOBIS API에서 오류를 반환했어요: {message}"

    try:
        movie_list = data["boxOfficeResult"]["dailyBoxOfficeList"]
    except KeyError:
        return False, "예상한 형식의 데이터를 받지 못했어요. KOBIS 서비스 상태를 확인해 주세요."

    if not movie_list:
        return False, "해당 날짜의 박스오피스 데이터가 아직 없어요."

    df = pd.DataFrame(movie_list)

    # ------------------------------------------------------------
    # 숫자가 전부 문자열로 오기 때문에, 숫자형으로 변환해줍니다.
    # (정렬, 그래프 등에 문자열 그대로 쓰면 "10"이 "2"보다 작게 취급되는 등 오류가 납니다)
    # ------------------------------------------------------------
    numeric_cols = ["rank", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return True, df


# ------------------------------------------------------------
# 2. 인증키 불러오기 (secrets에서만 불러오고, 코드에는 절대 쓰지 않습니다)
# ------------------------------------------------------------
api_key = st.secrets.get("KOBIS_KEY")

if not api_key:
    st.error(
        "KOBIS_KEY가 설정되지 않았어요. "
        "Streamlit Cloud의 앱 설정 > Secrets 메뉴에서 "
        "`KOBIS_KEY = \"발급받은 인증키\"` 형태로 등록해 주세요."
    )
    st.stop()

# ------------------------------------------------------------
# 3. 날짜 계산 (한국시간 기준 '어제')
# ------------------------------------------------------------
target_dt = get_yesterday_kst()
target_dt_display = datetime.strptime(target_dt, "%Y%m%d").strftime("%Y년 %m월 %d일")

st.title("🎬 어제의 박스오피스 대시보드")
st.caption(f"조회 기준일: {target_dt_display} (한국 시간 기준 '어제' / 오늘 데이터는 아직 집계 전이라 제외)")

# ------------------------------------------------------------
# 4. 데이터 가져오기
# ------------------------------------------------------------
success, result = fetch_box_office(target_dt, api_key)

if not success:
    # result가 에러 메시지 문자열인 경우
    st.warning(result)
    st.stop()

df = result  # result가 DataFrame인 경우

# ------------------------------------------------------------
# 5. 1위 영화 지표 카드
# ------------------------------------------------------------
top_movie = df.sort_values("rank").iloc[0]

st.subheader("👑 오늘의 1위 영화")
col1, col2, col3 = st.columns(3)
col1.metric("영화명", top_movie["movieNm"])
col2.metric("어제 관객수", f"{int(top_movie['audiCnt']):,}명")
col3.metric("누적 관객수", f"{int(top_movie['audiAcc']):,}명")

st.divider()

# ------------------------------------------------------------
# 6. 표: 순위 · 영화명 · 개봉일 · 관객수 · 누적관객 · 스크린수
# ------------------------------------------------------------
st.subheader("📋 박스오피스 순위표")

table_df = df.sort_values("rank")[
    ["rank", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]
].rename(
    columns={
        "rank": "순위",
        "movieNm": "영화명",
        "openDt": "개봉일",
        "audiCnt": "관객수",
        "audiAcc": "누적관객",
        "scrnCnt": "스크린수",
    }
)

st.dataframe(
    table_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "관객수": st.column_config.NumberColumn(format="%d"),
        "누적관객": st.column_config.NumberColumn(format="%d"),
        "스크린수": st.column_config.NumberColumn(format="%d"),
    },
)

# ------------------------------------------------------------
# 7. 그래프: 관객수 상위 5편 막대그래프
# ------------------------------------------------------------
st.subheader("📊 관객수 상위 5편")

top5 = df.sort_values("audiCnt", ascending=False).head(5)
chart_df = top5.set_index("movieNm")[["audiCnt"]].rename(columns={"audiCnt": "관객수"})

st.bar_chart(chart_df)
