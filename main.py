"""
KOBIS(영화진흥위원회) 박스오피스 대시보드
- '어제'(한국시간 기준)부터 과거 2주(14일)간의 일별 박스오피스를 모아서 보여줍니다.
- 오늘 데이터는 아직 집계가 끝나지 않았기 때문에 항상 '어제'를 가장 최신 날짜로 사용합니다.
- 표에는 전일 대비 관객수 증감을 주식처럼 삼각형(▲/▼)으로 표시합니다.
- 상위 5편은 최근 2주간 일별 관객수 추이를 선 그래프로 보여줍니다.
- 상위 5편에 대해 네이버·왓챠피디아 리뷰 페이지로 바로 이동할 수 있는 링크를 제공합니다.
  (리뷰 본문을 직접 긁어오지는 않습니다 - 두 사이트 모두 리뷰용 공식 API가 없고,
   저작권·이용약관 문제가 있을 수 있어서 링크로 연결하는 방식을 사용했습니다.)
"""

import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # 파이썬 내장 라이브러리 (한국 시간 계산용)
from urllib.parse import quote  # 영화 제목을 URL에 안전하게 넣기 위한 인코딩

# ------------------------------------------------------------
# 1. 기본 설정
# ------------------------------------------------------------
st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")

KOBIS_URL = "http://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
NUM_DAYS = 14  # 수집할 기간 (2주)


def get_recent_dates_kst(num_days: int) -> list[str]:
    """한국 시간(Asia/Seoul) 기준으로 '어제'부터 과거 num_days일치 날짜를
    yyyymmdd 문자열 리스트로 반환합니다. 리스트의 마지막 원소가 가장 최근(어제)입니다.
    배포 서버가 해외 시간대여도 항상 한국 시간 기준으로 계산합니다."""
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    yesterday_kst = now_kst - timedelta(days=1)
    dates = [
        (yesterday_kst - timedelta(days=offset)).strftime("%Y%m%d")
        for offset in range(num_days - 1, -1, -1)
    ]
    return dates


def fetch_box_office_one_day(target_dt: str, api_key: str):
    """KOBIS API를 호출해서 특정 하루의 박스오피스 목록을 가져옵니다.
    성공 시 (True, DataFrame) 을, 실패 시 (False, 에러메시지) 를 반환합니다."""
    params = {"key": api_key, "targetDt": target_dt}

    try:
        response = requests.get(KOBIS_URL, params=params, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return False, f"{target_dt} 조회 중 KOBIS 서버 요청 문제가 발생했어요. (오류: {e})"

    try:
        data = response.json()
    except ValueError:
        return False, f"{target_dt} 응답을 해석할 수 없었어요."

    if "faultInfo" in data:
        message = data["faultInfo"].get("message", "알 수 없는 오류")
        return False, f"{target_dt} 조회 중 KOBIS API 오류: {message}"

    try:
        movie_list = data["boxOfficeResult"]["dailyBoxOfficeList"]
    except KeyError:
        return False, f"{target_dt} 응답 형식이 예상과 달랐어요."

    if not movie_list:
        return False, f"{target_dt}에는 박스오피스 데이터가 없어요."

    df = pd.DataFrame(movie_list)
    df["조회일자"] = target_dt

    # ------------------------------------------------------------
    # 숫자가 전부 문자열로 오기 때문에 숫자형으로 변환합니다.
    # audiInten(전일대비 관객수 증감)은 KOBIS가 매일 자체 계산해서 내려주는 값이라
    # 우리가 직접 전날 데이터와 비교하지 않아도 이 값 하나로 등락을 알 수 있습니다.
    # ------------------------------------------------------------
    numeric_cols = ["rank", "audiCnt", "audiAcc", "scrnCnt", "showCnt", "audiInten"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return True, df


@st.cache_data(ttl=3600)  # 1시간 동안 캐시해서 API 호출(하루당 1회 x 14일)을 아낍니다.
def fetch_two_weeks(api_key: str, date_list: tuple):
    """date_list에 담긴 날짜들에 대해 하루씩 박스오피스를 조회하고 하나로 합칩니다.
    반환값: (합쳐진 DataFrame, 실패한 날짜들의 에러 메시지 리스트)"""
    frames = []
    errors = []

    for target_dt in date_list:
        ok, result = fetch_box_office_one_day(target_dt, api_key)
        if ok:
            frames.append(result)
        else:
            errors.append(result)

    if not frames:
        return pd.DataFrame(), errors

    combined = pd.concat(frames, ignore_index=True)
    return combined, errors


def make_trend_arrow(audi_inten) -> str:
    """전일 대비 관객수 증감(audiInten)을 보고 주식처럼 삼각형 문구를 만듭니다.
    상승: 빨간 위쪽 삼각형 / 하락: 초록 아래쪽 삼각형 / 그 외: 보합 표시."""
    if pd.isna(audi_inten):
        return "· 정보없음"
    if audi_inten > 0:
        return f"▲ {int(audi_inten):,}"
    if audi_inten < 0:
        return f"▼ {int(abs(audi_inten)):,}"
    return "- 보합"


def style_trend_cell(val: str) -> str:
    """등락 컬럼 셀에 색을 입히는 스타일 함수 (▲=빨강, ▼=초록)."""
    if "▲" in val:
        return "color: red; font-weight: bold;"
    if "▼" in val:
        return "color: green; font-weight: bold;"
    return "color: gray;"


def make_review_links(movie_name: str) -> str:
    """영화 제목으로 네이버 영화 검색결과, 왓챠피디아 검색결과 링크를 만듭니다.
    리뷰 본문을 가져오는 게 아니라, 사용자가 직접 이동해서 볼 수 있는 링크만 제공합니다."""
    encoded = quote(movie_name)
    naver_url = f"https://movie.naver.com/movie/search/result.naver?query={encoded}&section=all"
    watcha_url = f"https://pedia.watcha.com/ko-KR/search?query={encoded}"
    return f"[네이버 리뷰 보기]({naver_url}) · [왓챠피디아 리뷰 보기]({watcha_url})"


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
# 3. 최근 2주 날짜 계산 (한국시간 기준, 가장 최근이 '어제')
# ------------------------------------------------------------
date_list = get_recent_dates_kst(NUM_DAYS)
yesterday_dt = date_list[-1]
yesterday_display = datetime.strptime(yesterday_dt, "%Y%m%d").strftime("%Y년 %m월 %d일")

st.title("🎬 어제의 박스오피스 대시보드")
st.caption(
    f"조회 기준일: {yesterday_display} (한국 시간 기준 '어제') · "
    f"최근 {NUM_DAYS}일간의 추이도 함께 확인할 수 있어요."
)

# ------------------------------------------------------------
# 4. 최근 2주 데이터 가져오기
# ------------------------------------------------------------
with st.spinner("최근 2주간 박스오피스 데이터를 불러오는 중이에요..."):
    combined_df, fetch_errors = fetch_two_weeks(api_key, tuple(date_list))

# 일부 날짜만 실패한 경우: 경고만 보여주고 나머지 데이터로 계속 진행
if fetch_errors:
    with st.expander(f"⚠️ 일부 날짜({len(fetch_errors)}건) 조회에 실패했어요. 눌러서 확인"):
        for err in fetch_errors:
            st.write("- " + err)

# 어제 데이터 자체가 없으면 더 진행할 수 없으므로 중단
if combined_df.empty or yesterday_dt not in combined_df["조회일자"].values:
    st.warning("어제 날짜의 박스오피스 데이터를 가져오지 못했어요. 잠시 후 다시 시도해 주세요.")
    st.stop()

yesterday_df = combined_df[combined_df["조회일자"] == yesterday_dt].sort_values("rank")

# ------------------------------------------------------------
# 5. 1위 영화 지표 카드 (등락도 함께 표시)
# ------------------------------------------------------------
top_movie = yesterday_df.iloc[0]
top_movie_inten = top_movie.get("audiInten", None)

st.subheader("👑 어제의 1위 영화")
col1, col2, col3 = st.columns(3)
col1.metric("영화명", top_movie["movieNm"])
col2.metric(
    "어제 관객수",
    f"{int(top_movie['audiCnt']):,}명",
    delta=(None if pd.isna(top_movie_inten) else f"{int(top_movie_inten):,}명"),
    delta_color="inverse",  # 국내 증권가 관례처럼 상승=빨강, 하락=초록으로 맞추기 위한 설정
)
col3.metric("누적 관객수", f"{int(top_movie['audiAcc']):,}명")

st.divider()

# ------------------------------------------------------------
# 6. 표: 순위 · 영화명 · 개봉일 · 관객수 · 등락 · 누적관객 · 스크린수
# ------------------------------------------------------------
st.subheader("📋 박스오피스 순위표 (어제 기준)")

table_df = yesterday_df.copy()
table_df["등락"] = table_df["audiInten"].apply(make_trend_arrow) if "audiInten" in table_df.columns else "· 정보없음"

table_df = table_df[
    ["rank", "movieNm", "openDt", "audiCnt", "등락", "audiAcc", "scrnCnt"]
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

# 숫자 컬럼은 보기 좋게 콤마가 들어간 문자열로 바꾸고, 등락 컬럼만 색을 입힙니다.
table_df["관객수"] = table_df["관객수"].map(lambda x: f"{int(x):,}")
table_df["누적관객"] = table_df["누적관객"].map(lambda x: f"{int(x):,}")
table_df["스크린수"] = table_df["스크린수"].map(lambda x: f"{int(x):,}")

styler = table_df.style.applymap(style_trend_cell, subset=["등락"]).hide(axis="index")
st.dataframe(styler, use_container_width=True)

# ------------------------------------------------------------
# 7. 그래프: 관객수 상위 5편 막대그래프 (어제 기준)
# ------------------------------------------------------------
st.subheader("📊 관객수 상위 5편 (어제 기준)")

top5 = yesterday_df.sort_values("audiCnt", ascending=False).head(5)
bar_chart_df = top5.set_index("movieNm")[["audiCnt"]].rename(columns={"audiCnt": "관객수"})
st.bar_chart(bar_chart_df)

top5_names = top5["movieNm"].tolist()

# ------------------------------------------------------------
# 8. 그래프: 상위 5편의 최근 2주 관객수 추이
# ------------------------------------------------------------
st.subheader(f"📈 상위 5편의 최근 {NUM_DAYS}일 관객수 추이")
st.caption(
    "KOBIS API는 하루에 상위 10위까지만 제공해서, 순위 밖으로 밀려난 날짜는 "
    "그래프에서 데이터가 비어있을 수 있어요."
)

trend_df = combined_df[combined_df["movieNm"].isin(top5_names)]
# 날짜 x 영화명 형태로 피벗해서 하나의 선 그래프로 볼 수 있게 만듭니다.
pivot_df = trend_df.pivot_table(index="조회일자", columns="movieNm", values="audiCnt", aggfunc="first")
pivot_df = pivot_df.sort_index()  # 날짜 오래된 순 -> 최근 순으로 정렬
st.line_chart(pivot_df)

st.divider()

# ------------------------------------------------------------
# 9. 상위 5편 리뷰 링크 (네이버 / 왓챠피디아)
# ------------------------------------------------------------
st.subheader("📝 상위 5편 리뷰 보러 가기")
st.caption("리뷰 본문을 직접 가져오지는 않고, 각 사이트의 리뷰 페이지로 바로 이동하는 링크예요.")

for _, row in top5.iterrows():
    st.markdown(f"**{row['movieNm']}** — {make_review_links(row['movieNm'])}")
