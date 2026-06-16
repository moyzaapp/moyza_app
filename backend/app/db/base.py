from sqlalchemy.orm import declarative_base
Base = declarative_base()

from app.models.user import User
from app.models.client import Client
from app.models.role import Role
from app.models.permission import Permission
from app.models.role_permission import RolePermission
from app.models.agent import Agent
from app.models.property import Property
from app.models.report import Report
from app.models.property_price_history import PropertyPriceHistory
from app.models.property_interaction import PropertyInteraction
from app.models.property_status_history import PropertyStatusHistory
from app.models.property_visit import PropertyVisit
from app.models.visit_audit_log import VisitAuditLog
from app.models.visit_otp_verification import VisitOTPVerification
from app.models.report_job_log import ReportJobLog
from app.models.ai_analysis_log import AIAnalysisLog