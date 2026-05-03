"""
任务规划器 - 将复杂 Query 拆解为 DAG 任务图
使用轻量 Anthropic API 做快速规划，不消耗 Claude Code 配额
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional

import anthropic
from dotenv import load_dotenv

from agent.prompts import TASK_PLANNING_PROMPT

load_dotenv()


@dataclass
class AnalysisTask:
    id: str
    title: str
    description: str
    type: str                         # schema_explore | sql_query | python_analysis | summary
    dependencies: list[str] = field(default_factory=list)
    sql_hint: str = ""
    status: str = "pending"           # pending | running | done | failed
    result: Optional[str] = None


@dataclass
class AnalysisPlan:
    analysis_type: str                # trend | comparison | distribution | correlation | funnel | other
    summary: str
    tasks: list[AnalysisTask]


class TaskPlanner:
    """
    使用 Anthropic Messages API 做轻量任务规划。
    将用户 Query 拆解为有序的子任务列表（可含依赖关系）。
    """

    def __init__(self, model: str = "claude-3-5-haiku-20241022"):
        self.model = model
        self._client: Optional[anthropic.Anthropic] = None

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    async def plan(
        self,
        query: str,
        schema_info: dict | None = None,
    ) -> AnalysisPlan:
        """
        对用户 Query 进行任务规划。

        :param query:       用户自然语言问题
        :param schema_info: 数据表 schema 信息（可选，提升规划质量）
        :return:            AnalysisPlan
        """
        schema_str = json.dumps(schema_info, ensure_ascii=False, indent=2) if schema_info else "暂无 schema 信息，请先探索"

        prompt = TASK_PLANNING_PROMPT.format(
            query=query,
            schema_info=schema_str,
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = response.content[0].text
            return self._parse_plan(raw_text)
        except Exception as exc:
            # 规划失败时退回默认单任务计划
            return AnalysisPlan(
                analysis_type="other",
                summary=f"分析: {query[:50]}",
                tasks=[
                    AnalysisTask(
                        id="t1",
                        title="执行分析",
                        description=query,
                        type="schema_explore",
                        dependencies=[],
                    )
                ],
            )

    # ------------------------------------------------------------------ #
    #  Parse JSON from LLM response                                        #
    # ------------------------------------------------------------------ #

    def _parse_plan(self, raw_text: str) -> AnalysisPlan:
        """从 LLM 返回文本中解析 JSON 计划"""
        # 提取 JSON 块（处理 LLM 可能多余的 markdown 包裹）
        json_match = re.search(r"\{[\s\S]*\}", raw_text)
        if not json_match:
            raise ValueError(f"No JSON found in planning response: {raw_text[:200]}")

        data = json.loads(json_match.group())
        tasks = [
            AnalysisTask(
                id=t["id"],
                title=t["title"],
                description=t["description"],
                type=t.get("type", "sql_query"),
                dependencies=t.get("dependencies", []),
                sql_hint=t.get("sql_hint", ""),
            )
            for t in data.get("tasks", [])
        ]
        return AnalysisPlan(
            analysis_type=data.get("analysis_type", "other"),
            summary=data.get("summary", ""),
            tasks=tasks,
        )
