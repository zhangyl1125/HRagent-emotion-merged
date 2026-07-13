from backend.schemas.coach import CoachReport


def test_coach_report_normalizes_string_risks_phrases_and_citations():
    report = CoachReport.model_validate(
        {
            "session_id": "s1",
            "summary": "ok",
            "top_risks": ["可能让员工更防御"],
            "key_strengths": "有开场",
            "key_improvements": {"one": "需要回到事实"},
            "better_phrases": [{"suggested_phrase": "我们先看事实。"}],
            "task_results": {},
            "citations": ["performance_feedback_basics.md"],
        }
    )

    assert report.top_risks[0].explanation == "可能让员工更防御"
    assert report.key_strengths == ["有开场"]
    assert report.key_improvements == ["需要回到事实"]
    assert report.better_phrases[0].suggestion == "我们先看事实。"
    assert report.task_results == []
    assert report.citations[0].source_id == "performance_feedback_basics.md"
    assert report.citations[0].title == "performance_feedback_basics.md"
