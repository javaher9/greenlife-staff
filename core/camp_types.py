"""Stable data contracts for the future Camp API integration.

Views currently persist to local Django models. Future API adapters can return
these shapes without changing templates/business logic.
"""
from typing import TypedDict, Literal, Optional, List

CampRole = Literal['owner','supervisor','worker','finance']
CampPurchaseStatus = Literal['pending','approved','rejected','purchased','paid']
CampStockStatus = Literal['ok','low','critical']
CampTaskStatus = Literal['todo','doing','done','stopped']
CampProjectStatus = Literal['active','paused','done']

class CampMoneySummary(TypedDict):
    today_cost: str
    week_cost: str
    worker_cost: str
    food_cost: str
    purchase_cost: str

class CampAlertDTO(TypedDict, total=False):
    level: Literal['good','warning','danger']
    title: str
    text: str
    entity: str
    entity_id: int

class CampDashboardDTO(TypedDict):
    date: str
    present_workers: int
    active_projects: int
    pending_purchases: int
    low_inventory: int
    photos: int
    tasks_done: int
    tasks_total: int
    money: CampMoneySummary
    alerts: List[CampAlertDTO]

class CampPurchaseDTO(TypedDict, total=False):
    id: int
    item_name: str
    category: str
    quantity: str
    unit: str
    estimated_amount: str
    final_amount: str
    request_date: str
    urgency: str
    status: CampPurchaseStatus
    invoice_image_url: Optional[str]

class CampInventoryDTO(TypedDict):
    id: int
    name: str
    category: str
    current_stock: str
    unit: str
    minimum_stock: str
    weekly_average_consumption: str
    status: CampStockStatus

class CampWorkerDTO(TypedDict, total=False):
    id: int
    full_name: str
    role: str
    status: str
    daily_wage: str
    present_today: bool
    start_time: Optional[str]
    end_time: Optional[str]

class CampTaskDTO(TypedDict, total=False):
    id: int
    date: str
    title: str
    responsible: str
    priority: str
    project_id: Optional[int]
    status: CampTaskStatus

class CampProjectDTO(TypedDict, total=False):
    id: int
    name: str
    manager: str
    start_date: str
    status: CampProjectStatus
    progress: int
    estimated_cost: str
    actual_cost: str
    last_progress_date: Optional[str]
