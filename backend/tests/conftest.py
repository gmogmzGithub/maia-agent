import pytest
from django.db import connection


@pytest.fixture(autouse=True)
def isolated_job_queue(db):
    """Django flush excludes Procrastinate's unmanaged job tables."""
    assert connection.settings_dict["NAME"].startswith("test_")
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE procrastinate_jobs RESTART IDENTITY CASCADE")
