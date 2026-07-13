from backend.schemas.task import CoachTaskResult


def test_coach_task_result_normalizes_common_model_output_aliases():
    result = CoachTaskResult.model_validate(
        {
            "task_id": "redline_check",
            "task_name": "话术红线检测",
            "status": "completed",
            "summary": "未发现明显红线。",
            "dimension_scores": {},
            "evidence": {},
            "strengths": "有事实回顾",
            "improvement_points": None,
            "risks": {},
            "better_phrases": {},
            "citations": {},
        }
    )

    assert result.status == "success"
    assert result.dimension_scores == []
    assert result.evidence == []
    assert result.strengths == ["有事实回顾"]
    assert result.improvement_points == []
    assert result.risks == []
    assert result.better_phrases == []
    assert result.citations == []


def test_coach_task_result_normalizes_simplified_scores_risks_and_phrases():
    result = CoachTaskResult.model_validate(
        {
            "task_id": "performance_evaluation",
            "task_name": "绩效反馈质量评估",
            "summary": "需要更聚焦事实。",
            "dimension_scores": {"fact_based": 20, "action_plan": 0},
            "risks": ["可能激化防御情绪"],
            "better_phrases": [
                {
                    "original_context": "你这个月没做好",
                    "suggested_phrase": "我们先看本月目标和完成数据之间的差距。",
                }
            ],
        }
    )

    assert result.dimension_scores[0].id == "fact_based"
    assert result.dimension_scores[0].score == 20
    assert result.risks[0].explanation == "可能激化防御情绪"
    assert result.better_phrases[0].original == "你这个月没做好"
    assert result.better_phrases[0].suggestion == "我们先看本月目标和完成数据之间的差距。"


def test_coach_task_result_normalizes_string_citations():
    result = CoachTaskResult.model_validate(
        {
            "task_id": "rubric_evaluation",
            "task_name": "Rubric 综合评估",
            "summary": "ok",
            "citations": ["performance_feedback_basics.md"],
        }
    )

    assert result.citations == [{"source": "performance_feedback_basics.md"}]
