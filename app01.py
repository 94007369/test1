import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import json

# --- 1. 配色定义 (与你的一致) ---
CAT_COLORS = {"军事打击": "#ff4b4b", "防空拦截": "#ffa500", "人员伤亡": "#7d7d7d", "外交动向": "#1f6feb", "制裁经济": "#f1e05a", "内政局势": "#8957e5", "海峡安全": "#2ea043", "其他": "#6e7681"}
SRC_COLORS = {"Al Jazeera": "#ff9900", "Press TV (Iran)": "#00a651", "BBC Middle East": "#bb1919", "NYT Middle East": "#323333", "Times of Israel": "#005eb8", "TASS (Russia)": "#004a80", "CGTN (China)": "#de2110"}

st.set_page_config(layout="wide", page_title="美伊局势情报站")

# --- 2. 样式与 JS 注入 ---
# 合并所有颜色配置供 JS 使用
ALL_COLORS = {**CAT_COLORS, **SRC_COLORS}

st.markdown(f"""
    <style>
    .stApp {{ background-color: #0d1117; color: #c9d1d9; }}
    
    /* 1. 基础标签形状 (不设置背景色，交给 JS 处理) */
    span[data-baseweb="tag"] {{
        border-radius: 6px !important;
        padding: 0px 8px !important;
        border: 1px solid transparent !important;
        transition: all 0.2s !important;
    }}
    
    /* 2. 时间轴与卡片 */
    .timeline-container {{ position: relative; padding-left: 45px; margin-top: 20px; }}
    .timeline-container::before {{ content: ''; position: absolute; left: 20px; top: 0; bottom: 0; width: 2px; background: #30363d; }}
    .news-card {{ background-color: #161b22; border: 1px solid #30363d; padding: 20px; border-radius: 12px; margin-bottom: 20px; position: relative; }}
    .timeline-dot {{ position: absolute; left: -31px; top: 25px; width: 12px; height: 12px; background-color: #58a6ff; border-radius: 50%; border: 3px solid #0d1117; z-index: 2; }}
    .tag-base {{ padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: bold; margin-right: 6px; display: inline-block; }}
    
    /* 筛选器容器微调 */
    div[data-testid="stVerticalBlock"] > div:has(div.stMultiSelect) {{
        background: #161b22; padding: 12px; border-radius: 10px; border: 1px solid #30363d;
    }}
    </style>
""", unsafe_allow_html=True)

# 注入 JavaScript 自动染色脚本
# 它会实时监测页面上的标签文字，并匹配对应的颜色
js_code = f"""
<script>
    const colorMap = {json.dumps(ALL_COLORS)};
    function applyColors() {{
        // 获取父窗口（Streamlit 主页面）中的所有标签
        const tags = window.parent.document.querySelectorAll('span[data-baseweb="tag"]');
        tags.forEach(tag => {{
            // 提取标签文字，去掉最后的 '×' 关闭符号
            const label = tag.innerText.replace(/[\\s\\S]*?\\n/g, '').replace('×', '').trim();
            if (colorMap[label]) {{
                const color = colorMap[label];
                tag.style.setProperty('background-color', color + '33', 'important'); // 20% 透明背景
                tag.style.setProperty('color', color, 'important'); // 文字颜色
                tag.style.setProperty('border-color', color + '99', 'important'); // 60% 透明边框
            }}
        }});
    }}
    // 使用 MutationObserver 监听 DOM 变化（当用户增删标签时触发）
    const observer = new MutationObserver(applyColors);
    observer.observe(window.parent.document.body, {{ childList: true, subtree: true }});
    // 初始化执行一次
    applyColors();
</script>
"""
components.html(js_code, height=0)

# --- 3. 逻辑函数 ---
def get_date_range():
    options = []
    now = datetime.now()
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for i in range(7):
        d = now - timedelta(days=i)
        label = "今天" if i == 0 else "昨天" if i == 1 else f"{d.month}月{d.day}日 {weekdays[d.weekday()]}"
        options.append({"label": label, "val": d.strftime('%Y-%m-%d')})
    return options

def load_data():
    try:
        conn = sqlite3.connect('war_archive.db')
        df = pd.read_sql("SELECT * FROM news WHERE is_ai_processed = 1 AND summary_zh != 'IGNORE_DATA' AND title_zh IS NOT NULL ORDER BY publish_time DESC", conn)
        conn.close()
        if not df.empty:
            df['event_key'] = df['event_key'].fillna(df['url'])
            df['pub_date'] = df['publish_time'].str[:10]
        return df
    except: return pd.DataFrame()

# --- 4. 界面渲染 ---
st.title("🛡️ 美以伊战争：全量情报聚合看板")

date_options = get_date_range()
selected_label = st.pills("时间选择", options=[d['label'] for d in date_options], default="今天", label_visibility="collapsed")
selected_date_val = next(d['val'] for d in date_options if d['label'] == selected_label)

df = load_data()

if not df.empty:
    f1, f2 = st.columns(2)
    with f1: src_filter = st.multiselect("📡 监测信源", df['source'].unique(), default=df['source'].unique())
    with f2: cat_filter = st.multiselect("🏷️ 情报分类", list(CAT_COLORS.keys()), default=list(CAT_COLORS.keys()))
    
    dff = df[(df['pub_date'] == selected_date_val) & (df['source'].isin(src_filter))]
    dff = dff[dff['category'].apply(lambda x: any(c.strip() in cat_filter for c in str(x).split(',')))]

    st.markdown(f"<div style='margin-bottom:15px; color:#8b949e;'>显示中：项目数量 <b>{len(dff)}</b></div>", unsafe_allow_html=True)
    
    st.markdown('<div class="timeline-container">', unsafe_allow_html=True)
    for _, group in dff.groupby('event_key', sort=False):
        main = group.iloc[0]
        others = group.iloc[1:]
        
        # 卡片内彩色标签渲染
        cat_html = "".join([f'<span class="tag-base" style="background:{CAT_COLORS.get(c.strip(), "#333")}33; color:{CAT_COLORS.get(c.strip(), "#ccc")}; border:1px solid {CAT_COLORS.get(c.strip(), "#333")}99;">{c.strip()}</span>' for c in str(main['category']).split(',')])
        src_c = SRC_COLORS.get(main['source'], "#30363d")

        st.markdown(f"""
<div class="news-card">
    <div class="timeline-dot"></div>
    <div style="display: flex; align-items: center; margin-bottom: 12px; gap: 4px;">
        <span class="tag-base" style="background:{src_c}; color:white;">{main['source']}</span>
        {cat_html}
        <span style="margin-left:auto; color:#8b949e; font-size:11px;">🕒 {main['publish_time']}</span>
    </div>
    <div style="font-size:1.2em; font-weight:bold; color:#e6edf3;">{main['title_zh']}</div>
    <div style="font-size:0.95em; color:#adbac7; line-height:1.6; margin-top:10px;">{main['summary_zh']}</div>
    <div style="margin-top:15px; text-align:right;"><a href="{main['url']}" target="_blank" style="color:#58a6ff; font-size:0.85em; text-decoration:none;">查看信源原文 →</a></div>
</div>
""", unsafe_allow_html=True)

        if not others.empty:
            with st.expander(f"🔗 发现 {len(others)} 条关联信源报道"):
                for _, sub in others.iterrows():
                    st.markdown(f'<div style="padding:10px; border-bottom:1px solid #30363d;"><span class="tag-base" style="background:{SRC_COLORS.get(sub["source"], "#333")}; color:white;">{sub["source"]}</span> <span style="color:#8b949e; font-size:11px;">{sub["publish_time"]}</span><div style="font-weight:bold; color:#adbac7; margin-top:5px;">{sub["title_zh"]}</div></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)