from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import Optional
from datetime import datetime, timedelta

from app.db.deps import get_db
from app.models.ai_analysis_log import AIAnalysisLog
from app.models.property import Property

router = APIRouter()


@router.get("/api/ai-logs", response_class=JSONResponse)
async def get_ai_logs(
    property_id: Optional[int] = Query(None),
    analysis_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Endpoint para obtener logs de análisis de IA con filtros.

    Query params:
    - property_id: Filtrar por propiedad específica
    - analysis_type: Filtrar por tipo ("valuation" o "observations")
    - status: Filtrar por estado ("success", "error", "timeout")
    - limit: Cantidad máxima de resultados (default: 50)
    - offset: Offset para paginación (default: 0)
    """
    query = db.query(AIAnalysisLog)

    if property_id:
        query = query.filter(AIAnalysisLog.property_id == property_id)

    if analysis_type:
        query = query.filter(AIAnalysisLog.analysis_type == analysis_type)

    if status:
        query = query.filter(AIAnalysisLog.status == status)

    total = query.count()

    logs = query.order_by(
        desc(AIAnalysisLog.created_at)
    ).offset(offset).limit(limit).all()

    return {
        "logs": [
            {
                "id": log.id,
                "property_id": log.property_id,
                "property_title": log.property.title if log.property else None,
                "report_id": log.report_id,
                "analysis_type": log.analysis_type,
                "model_name": log.model_name,
                "temperature": float(log.temperature) if log.temperature else None,
                "max_tokens": log.max_tokens,
                "prompt_tokens": log.prompt_tokens,
                "completion_tokens": log.completion_tokens,
                "total_tokens": log.total_tokens,
                "estimated_cost": float(log.estimated_cost) if log.estimated_cost else None,
                "response_time_seconds": float(log.response_time_seconds) if log.response_time_seconds else None,
                "status": log.status,
                "error_message": log.error_message,
                "used_in_report": log.used_in_report,
                "created_at": log.created_at.isoformat() if log.created_at else None
            }
            for log in logs
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/api/ai-logs/{log_id}", response_class=JSONResponse)
async def get_ai_log_detail(
    log_id: int,
    db: Session = Depends(get_db)
):
    """
    Obtiene el detalle completo de un log específico, incluyendo prompt y response.
    """
    log = db.query(AIAnalysisLog).filter(AIAnalysisLog.id == log_id).first()

    if not log:
        return {"error": "Log no encontrado"}, 404

    return {
        "id": log.id,
        "property_id": log.property_id,
        "property_title": log.property.title if log.property else None,
        "property_address": log.property.address if log.property else None,
        "report_id": log.report_id,
        "analysis_type": log.analysis_type,
        "model_name": log.model_name,
        "temperature": float(log.temperature) if log.temperature else None,
        "max_tokens": log.max_tokens,
        "prompt": log.prompt,
        "response": log.response,
        "prompt_tokens": log.prompt_tokens,
        "completion_tokens": log.completion_tokens,
        "total_tokens": log.total_tokens,
        "estimated_cost": float(log.estimated_cost) if log.estimated_cost else None,
        "response_time_seconds": float(log.response_time_seconds) if log.response_time_seconds else None,
        "status": log.status,
        "error_message": log.error_message,
        "used_in_report": log.used_in_report,
        "extra_metadata": log.extra_metadata,
        "created_at": log.created_at.isoformat() if log.created_at else None
    }


@router.get("/api/ai-logs/stats/summary", response_class=JSONResponse)
async def get_ai_stats_summary(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """
    Obtiene estadísticas resumidas de los análisis de IA.

    Query params:
    - days: Cantidad de días a incluir en las estadísticas (default: 30)
    """
    start_date = datetime.utcnow() - timedelta(days=days)

    query = db.query(AIAnalysisLog).filter(AIAnalysisLog.created_at >= start_date)

    total_calls = query.count()
    success_count = query.filter(AIAnalysisLog.status == "success").count()
    error_count = query.filter(AIAnalysisLog.status == "error").count()

    # Totales de tokens
    tokens_sum = db.query(
        func.sum(AIAnalysisLog.total_tokens)
    ).filter(
        AIAnalysisLog.created_at >= start_date,
        AIAnalysisLog.status == "success"
    ).scalar() or 0

    # Costo total
    total_cost = db.query(
        func.sum(AIAnalysisLog.estimated_cost)
    ).filter(
        AIAnalysisLog.created_at >= start_date,
        AIAnalysisLog.status == "success"
    ).scalar() or 0

    # Tiempo promedio de respuesta
    avg_response_time = db.query(
        func.avg(AIAnalysisLog.response_time_seconds)
    ).filter(
        AIAnalysisLog.created_at >= start_date,
        AIAnalysisLog.status == "success"
    ).scalar() or 0

    # Por tipo de análisis
    valuations_count = query.filter(
        AIAnalysisLog.analysis_type == "valuation"
    ).count()

    observations_count = query.filter(
        AIAnalysisLog.analysis_type == "observations"
    ).count()

    # Cálculo de costos por modelo
    costs_by_model = db.query(
        AIAnalysisLog.model_name,
        func.count(AIAnalysisLog.id).label('count'),
        func.sum(AIAnalysisLog.estimated_cost).label('total_cost'),
        func.sum(AIAnalysisLog.total_tokens).label('total_tokens')
    ).filter(
        AIAnalysisLog.created_at >= start_date,
        AIAnalysisLog.status == "success"
    ).group_by(AIAnalysisLog.model_name).all()

    return {
        "period_days": days,
        "start_date": start_date.isoformat(),
        "end_date": datetime.utcnow().isoformat(),
        "total_calls": total_calls,
        "success_count": success_count,
        "error_count": error_count,
        "success_rate": round((success_count / total_calls * 100), 2) if total_calls > 0 else 0,
        "total_tokens": int(tokens_sum),
        "total_cost_usd": float(total_cost),
        "avg_response_time_seconds": float(avg_response_time),
        "valuations_count": valuations_count,
        "observations_count": observations_count,
        "costs_by_model": [
            {
                "model": model,
                "calls": count,
                "total_cost": float(cost or 0),
                "total_tokens": int(tokens or 0),
                "avg_cost_per_call": float(cost / count) if count > 0 and cost else 0
            }
            for model, count, cost, tokens in costs_by_model
        ]
    }


@router.get("/api/ai-logs/stats/daily", response_class=JSONResponse)
async def get_ai_stats_daily(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """
    Obtiene estadísticas diarias de análisis de IA (útil para gráficos).

    Query params:
    - days: Cantidad de días a incluir (default: 30)
    """
    start_date = datetime.utcnow() - timedelta(days=days)

    daily_stats = db.query(
        func.date(AIAnalysisLog.created_at).label('date'),
        func.count(AIAnalysisLog.id).label('total_calls'),
        func.sum(AIAnalysisLog.estimated_cost).label('total_cost'),
        func.sum(AIAnalysisLog.total_tokens).label('total_tokens'),
        func.count(
            func.nullif(AIAnalysisLog.status == "success", False)
        ).label('success_count')
    ).filter(
        AIAnalysisLog.created_at >= start_date
    ).group_by(
        func.date(AIAnalysisLog.created_at)
    ).order_by(
        func.date(AIAnalysisLog.created_at)
    ).all()

    return {
        "period_days": days,
        "daily_stats": [
            {
                "date": stat.date.isoformat() if stat.date else None,
                "total_calls": stat.total_calls,
                "success_count": stat.success_count or 0,
                "total_cost_usd": float(stat.total_cost or 0),
                "total_tokens": int(stat.total_tokens or 0)
            }
            for stat in daily_stats
        ]
    }


@router.get("/api/ai-logs/property/{property_id}/history", response_class=JSONResponse)
async def get_property_ai_history(
    property_id: int,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Obtiene el historial de análisis de IA para una propiedad específica.
    """
    property_item = db.query(Property).filter(Property.id == property_id).first()

    if not property_item:
        return {"error": "Propiedad no encontrada"}, 404

    logs = db.query(AIAnalysisLog).filter(
        AIAnalysisLog.property_id == property_id,
        AIAnalysisLog.status == "success"
    ).order_by(
        desc(AIAnalysisLog.created_at)
    ).limit(limit).all()

    # Calcular totales para esta propiedad
    total_cost = db.query(
        func.sum(AIAnalysisLog.estimated_cost)
    ).filter(
        AIAnalysisLog.property_id == property_id,
        AIAnalysisLog.status == "success"
    ).scalar() or 0

    total_tokens = db.query(
        func.sum(AIAnalysisLog.total_tokens)
    ).filter(
        AIAnalysisLog.property_id == property_id,
        AIAnalysisLog.status == "success"
    ).scalar() or 0

    return {
        "property_id": property_id,
        "property_title": property_item.title,
        "property_address": property_item.address,
        "total_analyses": len(logs),
        "total_cost_usd": float(total_cost),
        "total_tokens": int(total_tokens),
        "history": [
            {
                "id": log.id,
                "analysis_type": log.analysis_type,
                "model_name": log.model_name,
                "total_tokens": log.total_tokens,
                "estimated_cost": float(log.estimated_cost) if log.estimated_cost else None,
                "response_time_seconds": float(log.response_time_seconds) if log.response_time_seconds else None,
                "created_at": log.created_at.isoformat() if log.created_at else None
            }
            for log in logs
        ]
    }
