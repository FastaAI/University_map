from __future__ import annotations

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from pathlib import Path
from functools import lru_cache
import os
import re
import math
import pandas as pd
import difflib
import html
from typing import Any, Optional

from google import genai


app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SCHOOL_EXCEL = BASE_DIR / "yield" / "학교주소좌표.xlsx"

DEFAULT_LAT, DEFAULT_LON = 37.459882, 126.951905


# =============================
# 약칭 매핑
# =============================
ALIAS_MAP = {
    "서울대": "서울대학교",
    "설대": "서울대학교",
    "연대": "연세대학교",
    "고대": "고려대학교",

    "서강대": "서강대학교",
    "성대": "성균관대학교",
    "한대": "한양대학교",

    "중대": "중앙대학교",
    "경희대": "경희대학교",
    "외대": "한국외국어대학교",
    "시립대": "서울시립대학교",
    "서울시립대": "서울시립대학교",

    "건대": "건국대학교",
    "동국대": "동국대학교",
    "국민대": "국민대학교",
    "숭실대": "숭실대학교",
    "세종대": "세종대학교",
    "홍대": "홍익대학교",
    "명지대": "명지대학교",
    "상명대": "상명대학교",
    "가톨릭대": "가톨릭대학교",
    "한성대": "한성대학교",
    "서경대": "서경대학교",
    "광운대": "광운대학교",
    "가천대": "가천대학교",
    "단국대": "단국대학교",
    "아주대": "아주대학교",
    "인하대": "인하대학교",
    "서울과기대": "서울과학기술대학교",
    "서울여대": "서울여자대학교",
    "덕성여대": "덕성여자대학교",
    "동덕여대": "동덕여자대학교",
    "숙대": "숙명여자대학교",
    "이대": "이화여자대학교",

    "카이스트": "한국과학기술원",
    "kaist": "한국과학기술원",
    "포스텍": "포항공과대학교",
    "포공": "포항공과대학교",
    "gist": "광주과학기술원",
    "지디스트": "광주과학기술원",
    "unist": "울산과학기술원",
    "유니스트": "울산과학기술원",
    "dgist": "대구경북과학기술원",
    "디지스트": "대구경북과학기술원",
    "한기대": "한국기술교육대학교",

    "부산대": "부산대학교",
    "경북대": "경북대학교",
    "전남대": "전남대학교",
    "전북대": "전북대학교",
    "충남대": "충남대학교",
    "충북대": "충북대학교",
    "강원대": "강원대학교",
    "제주대": "제주대학교",
    "경상대": "경상국립대학교",
}


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def normalize_query(q: str) -> str:
    q = (q or "").strip()
    key = q.lower().replace(" ", "")
    if key in ALIAS_MAP:
        return ALIAS_MAP[key]
    if q in ALIAS_MAP:
        return ALIAS_MAP[q]
    return q


# =============================
# 주소에서 region 추정
# =============================
REGION_MAP = {
    "서울": ["서울", "서울특별시"],
    "부산": ["부산", "부산광역시"],
    "대구": ["대구", "대구광역시"],
    "인천": ["인천", "인천광역시"],
    "광주": ["광주", "광주광역시"],
    "대전": ["대전", "대전광역시"],
    "울산": ["울산", "울산광역시"],
    "세종": ["세종", "세종특별자치시"],
    "경기": ["경기", "경기도"],
    "강원": ["강원", "강원특별자치도", "강원도"],
    "충북": ["충북", "충청북도"],
    "충남": ["충남", "충청남도"],
    "전북": ["전북", "전라북도"],
    "전남": ["전남", "전라남도"],
    "경북": ["경북", "경상북도"],
    "경남": ["경남", "경상남도"],
    "제주": ["제주", "제주특별자치도"],
}


def infer_region(addr: str) -> str:
    a = (addr or "").strip()
    if not a:
        return "Unknown"
    first = a.split()[0] if a.split() else ""
    for reg, keys in REGION_MAP.items():
        for k in keys:
            if first.startswith(k) or k in first:
                return reg
    for reg, keys in REGION_MAP.items():
        for k in keys:
            if k in a:
                return reg
    return "Unknown"


# =============================
# 데이터 로드(캐시)
# - type 완전 제거
# - region 컬럼 있으면 사용, 없으면 주소로 추정
# =============================
@lru_cache(maxsize=1)
def load_school_data_cached() -> pd.DataFrame:
    raw = pd.read_excel(SCHOOL_EXCEL, engine="openpyxl").copy()

    df = raw.iloc[:, [0, 1, 2, 3]].copy()
    df.columns = ["학교이름", "주소", "x", "y"]

    df["x"] = pd.to_numeric(df["x"], errors="coerce")
    df["y"] = pd.to_numeric(df["y"], errors="coerce")
    df = df.dropna(subset=["x", "y"])
    df = df[(df["x"] != 0) & (df["y"] != 0)]

    df["학교이름_norm"] = df["학교이름"].astype(str).str.strip()

    lower_cols = [str(c).strip().lower() for c in raw.columns]
    if "region" in lower_cols:
        region_series = raw.iloc[:, lower_cols.index("region")]
        df["region"] = region_series.astype(str).fillna("Unknown").str.strip()
        df.loc[df["region"].eq(""), "region"] = "Unknown"
    else:
        df["region"] = df["주소"].astype(str).apply(infer_region)

    return df


def load_school_data() -> pd.DataFrame:
    return load_school_data_cached()


# =============================
# 공통 검색
# =============================
def find_hits(
    df: pd.DataFrame,
    name: str,
    *,
    sim_threshold: float = 0.55,
    limit: int = 30
) -> pd.DataFrame:
    q = normalize_query(name)
    if not q:
        return pd.DataFrame()

    exact = df[df["학교이름_norm"].str.casefold() == q.casefold()]
    if not exact.empty:
        return exact

    cand = df[df["학교이름_norm"].str.contains(q, case=False, na=False)].copy()
    if cand.empty:
        df2 = df.copy()
        df2["__sim"] = df2["학교이름_norm"].apply(lambda s: similarity(q.lower(), str(s).lower()))
        cand = (
            df2[df2["__sim"] >= sim_threshold]
            .copy()
            .sort_values("__sim", ascending=False)
            .head(limit)
        )
    else:
        cand["__sim"] = cand["학교이름_norm"].apply(lambda s: similarity(q.lower(), str(s).lower()))
        cand = cand.sort_values("__sim", ascending=False).head(limit)

    return cand.drop_duplicates(subset=["학교이름_norm"])


def pick_best_hit(df: pd.DataFrame, name: str) -> Optional[dict[str, Any]]:
    hits = find_hits(df, name, sim_threshold=0.55, limit=10)
    if hits.empty:
        return None
    r = hits.iloc[0]
    return {
        "학교이름": str(r["학교이름"]),
        "주소": str(r["주소"]),
        "x": float(r["x"]),  # lon
        "y": float(r["y"]),  # lat
        "region": str(r.get("region", "Unknown")),
    }


# =============================
# Haversine 거리
# =============================
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# =============================
# region 색상
# =============================
REGION_COLOR = {
    "서울": "purple", "경기": "cadetblue", "인천": "darkpurple",
    "부산": "darkred", "대구": "darkblue", "광주": "darkgreen",
    "대전": "orange", "울산": "lightred", "세종": "lightblue",
    "강원": "beige", "충북": "lightgray", "충남": "lightgreen",
    "전북": "pink", "전남": "lightyellow", "경북": "black",
    "경남": "lightred", "제주": "lightgreen", "Unknown": "gray",
}


def pick_marker_color(region: str) -> str:
    return REGION_COLOR.get(region, "gray")


# =============================
# Gemini client/model
# =============================
@lru_cache(maxsize=1)
def get_gemini_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY", "AIzaSyBWBJackxzuigeRFLsTguANeM3-8qmwUxc").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    return genai.Client(api_key=api_key)


def get_gemini_model_name() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"


# =============================
# /chat: history를 프롬프트에 포함(기억 유지)
# =============================
class ChatReq(BaseModel):
    message: str
    history: list[dict[str, Any]] | None = None


def format_history(history: list[dict[str, Any]] | None, limit: int = 12) -> str:
    if not history:
        return ""
    h = history[-limit:]
    lines = []
    for m in h:
        role = (m.get("role") or "").strip().lower()
        text = (m.get("text") or "").strip()
        if not text:
            continue
        if role in ("bot", "assistant"):
            role = "ASSISTANT"
        else:
            role = "USER"
        lines.append(f"{role}: {text}")
    return "\n".join(lines)


def extract_candidate_query(user_msg: str) -> str:
    m = (user_msg or "").strip()
    if not m:
        return ""
    q = re.findall(r"[\"“”'‘’]([^\"“”'‘’]{1,40})[\"“”'‘’]", m)
    if q:
        return q[0].strip()
    return m[:40].strip()


def build_actions_from_text(user_msg: str) -> list[dict[str, Any]]:
    df = load_school_data()
    q = extract_candidate_query(user_msg)
    if not q:
        return []
    hits = find_hits(df, q, sim_threshold=0.50, limit=8)
    if hits.empty:
        return []
    actions: list[dict[str, Any]] = []
    for _, r in hits.head(3).iterrows():
        uni = str(r["학교이름"])
        actions.append({"label": f"{uni} (2D)", "type": "open2d", "query": uni})
        actions.append({"label": f"{uni} (3D)", "type": "open3d", "query": uni})
    return actions


@app.post("/chat", response_class=JSONResponse)
def chat(req: ChatReq) -> JSONResponse:
    user_msg = (req.message or "").strip()
    if not user_msg:
        return JSONResponse(content={"reply": "메시지가 비어 있어. 한 줄만 적어줘.", "actions": []})

    actions = build_actions_from_text(user_msg)

    try:
        client = get_gemini_client()
        model_name = get_gemini_model_name()
    except Exception as e:
        return JSONResponse(content={
            "reply": "Gemini 키가 없어서 AI 응답은 못해. (GEMINI_API_KEY 설정 필요) 그래도 아래 버튼으로 열어봐.",
            "actions": actions,
            "error": str(e),
        })

    df = load_school_data()
    hist_text = format_history(req.history, limit=12)

    candidates = find_hits(df, extract_candidate_query(user_msg), sim_threshold=0.50, limit=6)
    cand_list = candidates["학교이름_norm"].head(5).tolist() if not candidates.empty else []

    system_instruction = (
        "너는 한국 고등학생을 돕는 대학 지도 상담 AI다. "
        "이 서비스는 대학을 2D(/search) 또는 3D(/3d)로 보여준다. "
        "입결/합격예측은 하지 말고, 검색어 정리/혼동 해소/다음 행동(지도에서 보기)을 돕는다. "
        "이전 대화 내용을 참고해 같은 질문을 반복하지 말아라. "
        "답변은 짧고 명확하게. 필요하면 질문은 1개만."
    )

    prompt = (
        f"{system_instruction}\n\n"
        f"[대화 기록]\n{hist_text}\n\n"
        f"[사용자 최신 메시지]\n{user_msg}\n\n"
        f"[앱 데이터 힌트]\n"
        f"- candidate_universities: {cand_list}\n"
        f"- note: 학교명이 헷갈리면(예: 서울대학교 vs 동서울대학교) 확인 질문 1개를 하라.\n"
    )

    try:
        resp = client.models.generate_content(
            model=model_name,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
        )
        reply = (resp.text or "").strip() or "흠… 다시 한 번만 말해줘."
        return JSONResponse(content={"reply": reply, "actions": actions})
    except Exception as e:
        return JSONResponse(content={"reply": "Gemini 호출 오류. 아래 버튼으로 먼저 열어봐.", "actions": actions, "error": str(e)})


# =============================
# region 옵션
# =============================
def get_region_options(df: pd.DataFrame):
    return sorted(df["region"].fillna("Unknown").astype(str).unique().tolist())


# =============================
# Home
# =============================
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    df = load_school_data()
    region_options = get_region_options(df)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "map": None,
            "message": "",
            "search": "",
            "region_options": region_options,
            "filter_region": "",
            "cmp_a": "",
            "cmp_b": "",
            "compare": None,
            "near_name": "",
            "near_radius": "5",
        },
    )


# =============================
# Suggest
# =============================
@app.get("/suggest", response_class=JSONResponse)
def suggest(query: str = Query(..., min_length=1)) -> JSONResponse:
    df = load_school_data()
    q_raw = query.strip()
    q = q_raw.lower().replace(" ", "")

    suggestions: list[str] = []
    if q in ALIAS_MAP:
        suggestions.append(ALIAS_MAP[q])

    names = df["학교이름_norm"].unique().tolist()
    partial = [name for name in names if q in name.lower().replace(" ", "")]

    scored = []
    for name in names:
        name_key = name.lower().replace(" ", "")
        sim = similarity(q, name_key)
        if (q in name_key) or (sim > 0.35):
            scored.append((sim, name))

    scored_sorted = [n for _, n in sorted(scored, key=lambda x: x[0], reverse=True)]
    for name in partial + scored_sorted:
        if name not in suggestions:
            suggestions.append(name)
        if len(suggestions) >= 10:
            break

    return JSONResponse(content={"suggestions": suggestions})


# =============================
# Search (2D)
# =============================
@app.get("/search", response_class=HTMLResponse)
def search_school(request: Request, name: str = ""):
    import folium

    df = load_school_data()
    region_options = get_region_options(df)

    result_map_html = None
    message = ""
    search_input = name or ""

    if name:
        hits = find_hits(df, name, sim_threshold=0.55, limit=40)
        if hits.empty:
            message = f"'{name}'(으)로 검색된 학교가 없습니다."
        else:
            if len(hits) == 1:
                r = hits.iloc[0]
                region = str(r.get("region", "Unknown"))
                m = folium.Map(location=[r["y"], r["x"]], zoom_start=16, control_scale=True)
                folium.Marker(
                    [r["y"], r["x"]],
                    tooltip=str(r["학교이름"]),
                    popup=f"<b>{html.escape(str(r['학교이름']))}</b><br>{html.escape(str(r['주소']))}"
                          f"<br>region: {html.escape(region)}",
                    icon=folium.Icon(color=pick_marker_color(region), icon="info-sign"),
                ).add_to(m)
            else:
                center_lat = float(hits["y"].mean())
                center_lon = float(hits["x"].mean())
                m = folium.Map(location=[center_lat, center_lon], zoom_start=12, control_scale=True)
                bounds = []
                for _, r in hits.iterrows():
                    region = str(r.get("region", "Unknown"))
                    folium.CircleMarker(
                        [float(r["y"]), float(r["x"])],
                        radius=6,
                        tooltip=str(r["학교이름"]),
                        popup=f"<b>{html.escape(str(r['학교이름']))}</b><br>{html.escape(str(r['주소']))}"
                              f"<br>region: {html.escape(region)}",
                        fill=True,
                        fill_opacity=0.85,
                    ).add_to(m)
                    bounds.append((float(r["y"]), float(r["x"])))
                if bounds:
                    m.fit_bounds(bounds, padding=(30, 30))

            result_map_html = m._repr_html_()
            message = f"검색 결과 {len(hits)}개"

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "map": result_map_html,
            "message": message,
            "search": search_input,
            "region_options": region_options,
            "filter_region": "",
            "cmp_a": "",
            "cmp_b": "",
            "compare": None,
            "near_name": "",
            "near_radius": "5",
        },
    )


# =============================
# Browse (region 필터만)
# =============================
@app.get("/browse", response_class=HTMLResponse)
def browse(request: Request, filter_region: str = ""):
    import folium
    from folium.plugins import MarkerCluster

    df = load_school_data()
    region_options = get_region_options(df)

    dff = df.copy()
    if filter_region and filter_region != "ALL":
        dff = dff[dff["region"].astype(str) == filter_region]

    if dff.empty:
        m = folium.Map(location=[DEFAULT_LAT, DEFAULT_LON], zoom_start=11, control_scale=True)
        map_html = m._repr_html_()
        message = "필터 결과가 없습니다."
    else:
        center_lat = float(dff["y"].mean())
        center_lon = float(dff["x"].mean())
        m = folium.Map(location=[center_lat, center_lon], zoom_start=11, control_scale=True)

        cluster = MarkerCluster().add_to(m)
        bounds = []

        max_points = 800
        dff2 = dff.head(max_points)

        for _, r in dff2.iterrows():
            uni = str(r["학교이름"])
            addr = str(r["주소"])
            region = str(r.get("region", "Unknown"))
            color = pick_marker_color(region)

            folium.Marker(
                [float(r["y"]), float(r["x"])],
                tooltip=uni,
                popup=f"<b>{html.escape(uni)}</b><br>{html.escape(addr)}"
                      f"<br>region: {html.escape(region)}",
                icon=folium.Icon(color=color, icon="info-sign"),
            ).add_to(cluster)

            bounds.append((float(r["y"]), float(r["x"])))

        if bounds:
            m.fit_bounds(bounds, padding=(30, 30))

        map_html = m._repr_html_()
        message = f"필터 결과 {len(dff)}개 (지도에는 최대 {max_points}개 표시)"

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "map": map_html,
            "message": message,
            "search": "",
            "region_options": region_options,
            "filter_region": filter_region or "",
            "cmp_a": "",
            "cmp_b": "",
            "compare": None,
            "near_name": "",
            "near_radius": "5",
        },
    )


# =============================
# Compare
# =============================
@app.get("/compare", response_class=HTMLResponse)
def compare_view(request: Request, a: str = "", b: str = ""):
    import folium

    df = load_school_data()
    region_options = get_region_options(df)

    A = pick_best_hit(df, a) if a else None
    B = pick_best_hit(df, b) if b else None

    compare_data = None
    message = ""
    map_html = None

    if not a or not b:
        message = "비교할 두 학교를 모두 입력해줘."
        m = folium.Map(location=[DEFAULT_LAT, DEFAULT_LON], zoom_start=11, control_scale=True)
        map_html = m._repr_html_()
    elif A is None or B is None:
        miss = []
        if A is None:
            miss.append(f"'{a}' 검색 실패")
        if B is None:
            miss.append(f"'{b}' 검색 실패")
        message = " / ".join(miss)
        m = folium.Map(location=[DEFAULT_LAT, DEFAULT_LON], zoom_start=11, control_scale=True)
        map_html = m._repr_html_()
    else:
        dist = haversine_km(A["y"], A["x"], B["y"], B["x"])
        compare_data = {"A": A, "B": B, "distance_km": f"{dist:.2f}"}
        message = f"비교: {A['학교이름']} vs {B['학교이름']} (직선거리 {dist:.2f} km)"

        center_lat = (A["y"] + B["y"]) / 2
        center_lon = (A["x"] + B["x"]) / 2
        m = folium.Map(location=[center_lat, center_lon], zoom_start=11, control_scale=True)

        folium.Marker(
            [A["y"], A["x"]],
            tooltip=f"A: {A['학교이름']}",
            popup=f"<b>A: {html.escape(A['학교이름'])}</b><br>{html.escape(A['주소'])}"
                  f"<br>region: {html.escape(A['region'])}",
            icon=folium.Icon(color=pick_marker_color(A["region"]), icon="info-sign"),
        ).add_to(m)

        folium.Marker(
            [B["y"], B["x"]],
            tooltip=f"B: {B['학교이름']}",
            popup=f"<b>B: {html.escape(B['학교이름'])}</b><br>{html.escape(B['주소'])}"
                  f"<br>region: {html.escape(B['region'])}",
            icon=folium.Icon(color=pick_marker_color(B["region"]), icon="info-sign"),
        ).add_to(m)

        folium.PolyLine(locations=[(A["y"], A["x"]), (B["y"], B["x"])], weight=5, opacity=0.8).add_to(m)
        m.fit_bounds([(A["y"], A["x"]), (B["y"], B["x"])], padding=(40, 40))
        map_html = m._repr_html_()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "map": map_html,
            "message": message,
            "search": "",
            "region_options": region_options,
            "filter_region": "",
            "cmp_a": a,
            "cmp_b": b,
            "compare": compare_data,
            "near_name": "",
            "near_radius": "5",
        },
    )


# =============================
# Nearby
# =============================
@app.get("/nearby", response_class=HTMLResponse)
def nearby_view(request: Request, name: str = "", radius_km: float = 5.0):
    import folium

    df = load_school_data()
    region_options = get_region_options(df)

    base = pick_best_hit(df, name) if name else None
    radius_km = float(radius_km or 5.0)

    if base is None:
        m = folium.Map(location=[DEFAULT_LAT, DEFAULT_LON], zoom_start=11, control_scale=True)
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "map": m._repr_html_(),
                "message": "기준 학교를 찾지 못했어. 학교명을 다시 입력해줘.",
                "search": "",
                "region_options": region_options,
                "filter_region": "",
                "cmp_a": "",
                "cmp_b": "",
                "compare": None,
                "near_name": name,
                "near_radius": str(radius_km),
            },
        )

    base_lat, base_lon = base["y"], base["x"]

    dff = df.copy()
    dff["__dist"] = dff.apply(lambda r: haversine_km(base_lat, base_lon, float(r["y"]), float(r["x"])), axis=1)
    near = dff[dff["__dist"] <= radius_km].sort_values("__dist", ascending=True).head(150)

    m = folium.Map(location=[base_lat, base_lon], zoom_start=13, control_scale=True)

    folium.Marker(
        [base_lat, base_lon],
        tooltip=f"BASE: {base['학교이름']}",
        popup=f"<b>BASE: {html.escape(base['학교이름'])}</b><br>{html.escape(base['주소'])}"
              f"<br>region: {html.escape(base['region'])}",
        icon=folium.Icon(color="blue", icon="star"),
    ).add_to(m)

    folium.Circle(
        location=[base_lat, base_lon],
        radius=radius_km * 1000,
        fill=False,
        weight=2,
    ).add_to(m)

    bounds = [(base_lat, base_lon)]
    for _, r in near.iterrows():
        uni = str(r["학교이름"])
        if uni == base["학교이름"]:
            continue
        dist = float(r["__dist"])
        region = str(r.get("region", "Unknown"))

        folium.CircleMarker(
            [float(r["y"]), float(r["x"])],
            radius=6,
            tooltip=f"{uni} ({dist:.2f}km)",
            popup=f"<b>{html.escape(uni)}</b><br>{html.escape(str(r['주소']))}"
                  f"<br>거리: {dist:.2f} km"
                  f"<br>region: {html.escape(region)}",
            fill=True,
            fill_opacity=0.85,
        ).add_to(m)
        bounds.append((float(r["y"]), float(r["x"])))

    if bounds:
        m.fit_bounds(bounds, padding=(30, 30))

    msg = f"'{base['학교이름']}' 기준 반경 {radius_km:g}km 내 대학 {max(len(near)-1,0)}개 표시(최대 150개)"
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "map": m._repr_html_(),
            "message": msg,
            "search": "",
            "region_options": region_options,
            "filter_region": "",
            "cmp_a": "",
            "cmp_b": "",
            "compare": None,
            "near_name": name,
            "near_radius": str(radius_km),
        },
    )


# =============================
# 3D + KML
# =============================
@app.get("/3d", response_class=HTMLResponse)
def view_3d(request: Request, name: str = ""):
    df = load_school_data()
    hits = find_hits(df, name, sim_threshold=0.55, limit=20) if name else pd.DataFrame()

    if hits.empty:
        init_lat, init_lon = DEFAULT_LAT, DEFAULT_LON
        message = "검색 결과가 없어서 기본 위치(서울)로 표시합니다."
        kml_url = ""
    else:
        init_lat = float(hits["y"].mean())
        init_lon = float(hits["x"].mean())
        message = f"3D 지도에서 '{name}' 검색 결과 {len(hits)}개를 표시합니다."
        kml_url = f"/kml?name={name}"

    init_alt = 6000 if hits.empty else (3500 if len(hits) > 1 else 1500)

    return templates.TemplateResponse(
        "vworld_3d.html",
        {
            "request": request,
            "search": name,
            "message": message,
            "init_lon": init_lon,
            "init_lat": init_lat,
            "init_alt": init_alt,
            "kml_url": kml_url,
        },
    )


@app.get("/kml")
def kml(name: str = ""):
    df = load_school_data()
    hits = find_hits(df, name, sim_threshold=0.55, limit=30)

    placemarks = []
    for _, r in hits.iterrows():
        uni = html.escape(str(r["학교이름"]))
        addr = html.escape(str(r["주소"]))
        lon = float(r["x"])
        lat = float(r["y"])
        placemarks.append(
            f"""
    <Placemark>
      <name>{uni}</name>
      <description>{addr}</description>
      <Point>
        <coordinates>{lon},{lat},0</coordinates>
      </Point>
    </Placemark>
""".rstrip()
        )

    doc_name = html.escape(name or "search")
    kml_text = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{doc_name}</name>
    {chr(10).join(placemarks) if placemarks else ""}
  </Document>
</kml>
"""
    return Response(content=kml_text, media_type="application/vnd.google-earth.kml+xml")


# 실행: uvicorn main:app --reload
