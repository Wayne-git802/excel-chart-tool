"""AI 图表推荐服务 - 调用 DeepSeek API"""
import json
import os
import requests


class ChartRecommender:
    """向 LLM 请求图表推荐"""
    
    API_URL = "https://api.deepseek.com/chat/completions"
    
    def _get_api_key(self) -> str:
        """获取 API Key"""
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            for path in [
                os.path.expanduser("~/.hermes/.env"),
                os.path.join(os.path.dirname(__file__), "..", ".env"),
            ]:
                if os.path.exists(path):
                    with open(path) as f:
                        for line in f:
                            if line.startswith("DEEPSEEK_API_KEY="):
                                key = line.split("=", 1)[1].strip()
                                break
        return key
    
    def recommend(self, data_summary: dict, refine_prompt: str = "") -> list:
        """根据数据摘要推荐图表，可选 refine_prompt 微调推荐方向"""
        api_key = self._get_api_key()
        
        base_prompt = f"""你是一个数据分析专家。根据以下 Excel 数据摘要，推荐 3~5 个最合适的图表类型。

数据摘要：
{json.dumps(data_summary, ensure_ascii=False, indent=2)}

可用图表类型：bar(柱状图), line(折线图), pie(饼图), scatter(散点图), stacked_bar(堆叠柱状图), grouped_bar(分组柱状图), boxplot(箱线图), histogram(直方图), heatmap(热力图), scatter_matrix(散点矩阵), bubble(气泡图), funnel(漏斗图), treemap(矩形树图), area(面积图), radar(雷达图), gauge(仪表盘)

请严格返回 JSON 数组，每个元素格式：
{{
  "type": "图表类型代码",
  "type_cn": "图表中文名",
  "x": "X轴列名",
  "y": ["Y轴列名1", "Y轴列名2"],
  "reason": "推荐理由（一句话）"
}}"""

        if refine_prompt.strip():
            prompt = base_prompt + f"\n\n用户额外要求：{refine_prompt.strip()}\n请根据用户要求调整推荐，仍然只返回 JSON 数组。"
        else:
            prompt = base_prompt + "\n\n只返回 JSON 数组，不要其他内容。"

        if not api_key:
            return self._fallback_recommend(data_summary)
        
        try:
            session = requests.Session()
            session.trust_env = False  # bypass system proxy
            resp = session.post(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 1500,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("\n", 1)[0]
                return json.loads(content)
        except Exception:
            pass
        
        return self._fallback_recommend(data_summary)
    
    def _fallback_recommend(self, data_summary: dict) -> list:
        """无 API 时的规则推荐"""
        columns = data_summary.get("列信息", [])
        num_cols = [c for c in columns if c["类型"] in ("数值", "整数")]
        text_cols = [c for c in columns if c["类型"] in ("文本",)]
        date_cols = [c for c in columns if c["类型"] == "日期"]
        
        recommendations = []
        
        if date_cols and num_cols:
            recommendations.append({
                "type": "line", "type_cn": "折线图",
                "x": date_cols[0]["列名"],
                "y": [c["列名"] for c in num_cols[:2]],
                "reason": f"日期列 + 数值列，适合展示趋势变化"
            })
        
        if text_cols and num_cols:
            recommendations.append({
                "type": "bar", "type_cn": "柱状图",
                "x": text_cols[0]["列名"],
                "y": [c["列名"] for c in num_cols[:2]],
                "reason": f"分类列 + 数值列，适合对比各类别"
            })
        
        if text_cols and num_cols and len(text_cols[0].get("示例值", [])) <= 10:
            recommendations.append({
                "type": "pie", "type_cn": "饼图",
                "x": text_cols[0]["列名"],
                "y": [num_cols[0]["列名"]],
                "reason": "类别少 + 数值，适合看占比"
            })
        
        if len(num_cols) >= 2:
            recommendations.append({
                "type": "scatter", "type_cn": "散点图",
                "x": num_cols[0]["列名"],
                "y": [num_cols[1]["列名"]],
                "reason": "两个数值列，适合看相关性"
            })
        
        if len(num_cols) >= 2:
            recommendations.append({
                "type": "heatmap", "type_cn": "热力图",
                "x": "",
                "y": [c["列名"] for c in num_cols[:6]],
                "reason": "多个数值列，适合看整体关系"
            })
        
        return recommendations[:5]


def get_recommendations(df, analysis: dict, refine_prompt: str = "") -> list:
    """Bridge: adapt analysis dict to ChartRecommender format."""
    recommender = ChartRecommender()

    # Build summary in the format _fallback_recommend expects
    columns_info = []
    for col in analysis.get("columns", []):
        columns_info.append({
            "列名": col["name"],
            "类型": "数值" if col["dtype_cn"] in ("数值", "整数分类") else
                   "日期" if col["dtype_cn"] == "日期" else "文本",
            "示例值": [str(df[col["name"]].iloc[0])] if len(df) > 0 else [],
        })

    summary = {"列信息": columns_info, **analysis}
    return recommender.recommend(summary, refine_prompt=refine_prompt)
