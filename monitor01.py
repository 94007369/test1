import feedparser
import sqlite3
import json
import time
import os
from datetime import datetime, timedelta, timezone
from dateutil import parser as date_parser
from openai import OpenAI

# ================= 配置区 =================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

RSS_SOURCES = {
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "BBC Middle East": "http://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
    "NYT Middle East": "https://rss.nytimes.com/services/xml/rss/nyt/MiddleEast.xml",
    "Middle East Eye": "https://www.middleeasteye.net/rss",
    "Press TV (Iran)": "https://www.presstv.ir/rss/rss-101.xml",
    "Times of Israel": "https://www.timesofisrael.com/feed/",
    "CGTN (China)": "https://www.cgtn.com/subscribe/rss/section/world.xml"
}

KEYWORDS = ["iran", "Iranian", "us", "u.s.", "america","tehran", "hormuz", "strait", "israel", "military", "strike", "vessel", "maritime", "irgc", "middle-east"]
CATEGORIES = ["军事打击", "防空拦截", "人员伤亡", "外交动向", "制裁经济", "内政局势", "海峡安全", "其他"]

# ================= 数据库清理逻辑 (新增) =================
def cleanup_db():
    """删除超过7天的数据，保持数据库轮换"""
    conn = sqlite3.connect('war_archive.db')
    c = conn.cursor()
    # 计算7天前的日期
    limit_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M')
    c.execute('DELETE FROM news WHERE publish_time < ? AND publish_time != "N/A"', (limit_date,))
    conn.commit()
    conn.close()
    print("🧹 已完成数据库7天周期清理。")

# ================= 数据库逻辑 =================
def init_db():
    conn = sqlite3.connect('war_archive.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE, source TEXT, title TEXT, summary TEXT, 
                    publish_time TEXT, fetch_time TEXT,
                    title_zh TEXT, summary_zh TEXT, category TEXT, 
                    event_key TEXT, is_ai_processed INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

def fetch_rss():
    init_db()
    cleanup_db() # 每次启动先清理
    news_pool = []
    source_counts = {name: 0 for name in RSS_SOURCES.keys()}
    # 修改：支持 7 天内的历史回溯抓取
    time_limit = datetime.now(timezone.utc) - timedelta(days=7) 
    print(f"🚀 正在巡检官方信源... {datetime.now().strftime('%H:%M:%S')}")

    for name, url in RSS_SOURCES.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                pub_date = date_parser.parse(entry.published) if hasattr(entry, 'published') else None
                if pub_date and pub_date < time_limit: continue
                
                content = (entry.title + entry.get('summary', '')).lower()
                if any(word in content for word in KEYWORDS):
                    news_pool.append({
                        "source": name, "title": entry.title, "link": entry.link,
                        "published": pub_date.strftime('%Y-%m-%d %H:%M') if pub_date else "N/A",
                        "summary": entry.get('summary', 'No summary')[:500]
                    })
        except: continue
    
    conn = sqlite3.connect('war_archive.db')
    c = conn.cursor()
    added = 0
    for n in news_pool:
        try:
            c.execute('INSERT INTO news (url, source, title, summary, publish_time, fetch_time) VALUES (?,?,?,?,?,?)',
                      (n['link'], n['source'], n['title'], n['summary'], n['published'], datetime.now().isoformat()))
            added += 1
            source_counts[n['source']] += 1
        except: continue
    conn.commit()
    conn.close()
    print("-" * 30)
    for name, count in source_counts.items():
        print(f"✅ {name}: 新入库 {count} 条")
    print("-" * 30)
    print(f"📊 抓取完毕：新增 {added} 条记录入库。")

# ================= AI 全量聚合处理 =================
def process_all_with_ai():
    conn = sqlite3.connect('war_archive.db')
    c = conn.cursor()
    
    while True:
        c.execute('SELECT id, title, summary FROM news WHERE is_ai_processed = 0 LIMIT 20')
        rows = c.fetchall()
        if not rows:
            print("✨ 库内所有新闻已完成 AI 处理与聚合。")
            break

        batch_ids = [str(r[0]) for r in rows]
        batch_input = [{"id": str(r[0]), "title": r[1], "content": r[2]} for r in rows]
        
        # --- 保持原有 Prompt 结构，仅增加无关信息判定逻辑 ---
        prompt = f"""
### 角色
你是一个极其严谨的情报数据处理专家。

### 任务
处理以下美伊局势简报。
待处理 ID 范围：{", ".join(batch_ids)}

### 核心约束（绝对禁止违背）：
1. **ID 严格原样返回**：输入数据中的 'id' 是什么，返回的 JSON 中 'id' 必须是完全一致的【纯数字字符串】。
2. **条数一致性**：输入了 {len(batch_input)} 条数据，返回的 "news" 数组也必须是 {len(batch_input)} 条。
3. **事件聚合**：识别描述【同一实时事件】的新闻，分配相同的 'event_key'（简短英文）。
4. **分类选择**：只能从 {CATEGORIES} 中选择。
5. **无关信息处理**：如果某条新闻与美国伊朗战争、中东军事冲突、海峡安全完全无关（如英国罢工、苏丹动态等），请将其 category 设为 ["其他"] 且 summary_zh 统一写为 "IGNORE_DATA"。

### 输出格式
严格返回 JSON，根节点为 "news"：
{{
  "news": [
    {{
      "id": "必须是输入的原始纯数字字符串",
      "category": ["分类1"],
      "title_zh": "中文标题",
      "summary_zh": "30-50字中文摘要",
      "event_key": "事件标识"
    }}
  ]
}}

### 输入数据：
{json.dumps(batch_input, ensure_ascii=False)}
"""
        # ... 后面解析代码和原代码一致 ...
        try:
            res = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            raw_res = json.loads(res.choices[0].message.content)
            data = raw_res.get("news", raw_res)
            
            for item in data:
                try:
                    item_id_str = str(item.get('id', ''))
                    if item_id_str.isdigit():
                        item_id = int(item_id_str)
                        # 如果 AI 判定为无关，直接在入库时标记特殊分类，方便前端过滤
                        cat_str = ",".join(item.get('category', ["其他"]))
                        summary_zh = item['summary_zh']
                        
                        # 逻辑：如果是 IGNORE_DATA，我们可以选择不更新或者打个标
                        c.execute('''UPDATE news SET title_zh=?, summary_zh=?, category=?, event_key=?, is_ai_processed=1 
                                     WHERE id=?''', (item['title_zh'], summary_zh, cat_str, item.get('event_key'), item_id))
                except: continue
            
            for r in rows:
                c.execute('UPDATE news SET is_ai_processed=1 WHERE id=?', (r[0],))
            conn.commit()
            time.sleep(1.2)
        except: break
    conn.close()

if __name__ == "__main__":
    fetch_rss()
    process_all_with_ai()