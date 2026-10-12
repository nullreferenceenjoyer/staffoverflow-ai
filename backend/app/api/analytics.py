import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import func, select

from app.api.organizations import report_summary
from app.deps import Scope, get_scope
from app.models import Category, Project, Task, TaskStatus
from app.services import analytics, centralization
from app.services.functions import CATEGORY_TITLES

router = APIRouter(tags=["analytics"])


@router.get("/dashboard")
def dashboard(municipality_id: int | None = None, scope: Scope = Depends(get_scope)):
    reports = analytics.load_reports(scope.db, scope.org_ids(municipality_id))
    summary = analytics.summarize(reports)
    scenario = centralization.build_scenario(reports)

    projects = [p for p in scope.db.scalars(select(Project)) if scope.can_see_project(p)]
    by_status: dict[str, int] = {}
    for project in projects:
        by_status[project.status] = by_status.get(project.status, 0) + 1

    overdue = scope.db.scalar(
        select(func.count()).select_from(Task)
        .where(Task.status.in_((TaskStatus.todo, TaskStatus.in_progress)))
        .where(Task.due_date < func.current_date())
    )
    top = sorted(reports, key=lambda r: r.saving_potential_year, reverse=True)[:8]
    return {
        **summary,
        "centralization": {
            "stages": scenario["stages"],
            "released_total": scenario["released_total"],
            "saving_year": scenario["saving_year"],
        },
        "projects_by_status": by_status,
        "overdue_tasks": overdue if scope.is_regional else None,
        "top_organizations": [report_summary(r) for r in top],
    }


@router.get("/analytics/deviations")
def deviations(category: Category | None = None, municipality_id: int | None = None,
               limit: int = 200, scope: Scope = Depends(get_scope)):
    reports = analytics.load_reports(scope.db, scope.org_ids(municipality_id))
    return analytics.top_deviations(reports, category, min(limit, 1000))


@router.get("/analytics/deviations.csv")
def deviations_csv(municipality_id: int | None = None, scope: Scope = Depends(get_scope)):
    reports = analytics.load_reports(scope.db, scope.org_ids(municipality_id))
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Муниципалитет", "Учреждение", "Категория", "Функция", "Факт, ст.",
                     "Норматив, ст.", "Отклонение, ст.", "Эффект ФОТ за год, руб."])
    for row in analytics.top_deviations(reports, limit=100_000):
        writer.writerow([row["municipality"], row["organization"],
                         CATEGORY_TITLES[row["category"]], row["title"], row["actual"],
                         row["norm"], row["delta"], row["fot_effect_year"]])
    # BOM нужен, чтобы Excel открыл файл в правильной кодировке
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="deviations.csv"'},
    )


@router.get("/analytics/duplicates")
def duplicates(municipality_id: int | None = None, scope: Scope = Depends(get_scope)):
    """Дублирование функций: внутри учреждения и между учреждениями одной территории."""
    org_ids = scope.org_ids(municipality_id)
    reports = analytics.load_reports(scope.db, org_ids)
    scenario = centralization.build_scenario(reports)
    return {
        "internal": analytics.find_internal_duplicates(scope.db, org_ids),
        "across_organizations": [
            f for f in scenario["functions"]
            if f["category"] == Category.admin and f["organizations"] > 1
        ],
    }


@router.get("/analytics/inefficiency")
def inefficiency(municipality_id: int | None = None, scope: Scope = Depends(get_scope)):
    return analytics.find_inefficient_positions(scope.db, scope.org_ids(municipality_id))


@router.get("/analytics/centralization")
def centralization_scenario(municipality_id: int | None = None,
                            scope: Scope = Depends(get_scope)):
    reports = analytics.load_reports(scope.db, scope.org_ids(municipality_id))
    return centralization.build_scenario(reports)
