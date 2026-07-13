import os

import pytest

from backend.repositories.postgres_repository import PostgresRepository
from backend.schemas.employee_database import EmployeeDatabaseRecord, EmployeeDatabaseUpsertRequest
from backend.schemas.profile import EmployeeProfile
from backend.services.employee_database_service import EmployeeDatabaseService


def test_employee_database_profile_text_builder_without_database():
    record = EmployeeDatabaseRecord(
        employee_id="E001",
        employee_alias="员工A",
        department="销售部",
        role="销售经理",
        manager="经理B",
        profile=EmployeeProfile(
            employee_alias="员工A",
            role="销售经理",
            department="销售部",
            performance_rating="M-",
            review_cycle="2026 H1",
            conversation_topic="PIP / 绩效不达预期",
            key_goals=["季度销售额", "客户续约率"],
        ),
    )
    text = EmployeeDatabaseService._build_profile_text(record)
    assert "员工代称：员工A" in text
    assert "关键目标：季度销售额、客户续约率" in text


@pytest.mark.skipif(not os.getenv("POSTGRES_TEST_DATABASE_URL"), reason="需要真实 PostgreSQL + pgvector 测试库")
def test_employee_database_upsert_search_and_profile_text_against_postgres():
    repo = PostgresRepository(os.environ["POSTGRES_TEST_DATABASE_URL"])
    service = EmployeeDatabaseService(repository=repo)
    record = service.upsert(
        EmployeeDatabaseUpsertRequest(
            employee_id="E001",
            employee_alias="员工A",
            department="销售部",
            role="销售经理",
            manager="经理B",
            profile=EmployeeProfile(
                employee_alias="员工A",
                role="销售经理",
                department="销售部",
                performance_rating="M-",
                review_cycle="2026 H1",
                conversation_topic="PIP / 绩效不达预期",
                key_goals=["季度销售额", "客户续约率"],
            ),
        )
    )

    assert record.employee_id == "E001"
    assert "员工代称：员工A" in (record.profile_text or "")
    assert service.search("销售部")[0].employee_id == "E001"
    assert service.search(employee_id="E001")[0].employee_id == "E001"
    assert service.search(name="员工A")[0].employee_id == "E001"
