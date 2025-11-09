from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.db import crud
from app.db.models import Admin as DBAdmin, Settings
from app.db.models import Node
from app.dependencies import (
    DBDep,
    AdminDep,
    SudoAdminDep,
    EndDateDep,
    StartDateDep,
)
from app.models.node import NodeStatus
from app.models.settings import (
    SubscriptionSettings,
    TelegramSettings,
    BackupSettings,
    BackupInfo,
)
from app.models.system import (
    UsersStats,
    NodesStats,
    AdminsStats,
    TrafficUsageSeries,
)
from app.models.user import UserExpireStrategy
from app.utils.backup import BackupManager

router = APIRouter(tags=["System"], prefix="/system")


@router.get("/settings/subscription", response_model=SubscriptionSettings)
def get_subscription_settings(db: DBDep, admin: SudoAdminDep):
    return db.query(Settings.subscription).first()[0]


@router.put("/settings/subscription", response_model=SubscriptionSettings)
def update_subscription_settings(
    db: DBDep, modifications: SubscriptionSettings, admin: SudoAdminDep
):
    settings = db.query(Settings).first()
    settings.subscription = modifications.model_dump(mode="json")
    db.commit()
    return settings.subscription


@router.get("/settings/telegram", response_model=TelegramSettings | None)
def get_telegram_settings(db: DBDep, admin: SudoAdminDep):
    return db.query(Settings.telegram).first().telegram


@router.put("/settings/telegram", response_model=TelegramSettings | None)
def update_telegram_settings(
    db: DBDep, new_telegram: TelegramSettings | None, admin: SudoAdminDep
):
    settings = db.query(Settings.telegram).first()
    settings.telegram = new_telegram
    db.commit()
    return settings.telegram


@router.get("/stats/admins", response_model=AdminsStats)
def get_admins_stats(db: DBDep, admin: SudoAdminDep):
    return AdminsStats(total=db.query(DBAdmin).count())


@router.get("/stats/nodes", response_model=NodesStats)
def get_nodes_stats(db: DBDep, admin: SudoAdminDep):
    return NodesStats(
        total=db.query(Node).count(),
        healthy=db.query(Node)
        .filter(Node.status == NodeStatus.healthy)
        .count(),
        unhealthy=db.query(Node)
        .filter(Node.status == NodeStatus.unhealthy)
        .count(),
    )


@router.get("/stats/traffic", response_model=TrafficUsageSeries)
def get_total_traffic_stats(
    db: DBDep, admin: AdminDep, start_date: StartDateDep, end_date: EndDateDep
):
    return crud.get_total_usages(db, admin, start_date, end_date)


@router.get("/stats/users", response_model=UsersStats)
def get_users_stats(db: DBDep, admin: AdminDep):
    return UsersStats(
        total=crud.get_users_count(
            db, admin=admin if not admin.is_sudo else None
        ),
        active=crud.get_users_count(
            db, admin=admin if not admin.is_sudo else None, is_active=True
        ),
        on_hold=crud.get_users_count(
            db,
            admin=admin if not admin.is_sudo else None,
            expire_strategy=UserExpireStrategy.START_ON_FIRST_USE,
        ),
        expired=crud.get_users_count(
            db,
            admin=admin if not admin.is_sudo else None,
            expired=True,
        ),
        limited=crud.get_users_count(
            db,
            admin=admin if not admin.is_sudo else None,
            data_limit_reached=True,
        ),
        online=crud.get_users_count(
            db, admin=admin if not admin.is_sudo else None, online=True
        ),
    )


# Backup Management Endpoints

@router.get("/settings/backup", response_model=BackupSettings)
def get_backup_settings(db: DBDep, admin: SudoAdminDep):
    """Get current backup settings"""
    settings_row = db.query(Settings.backup).first()
    if not settings_row or not settings_row[0]:
        return BackupSettings()
    return BackupSettings.model_validate(settings_row[0])


@router.put("/settings/backup", response_model=BackupSettings)
def update_backup_settings(
    db: DBDep, modifications: BackupSettings, admin: SudoAdminDep
):
    """Update backup settings"""
    settings = db.query(Settings).first()
    settings.backup = modifications.model_dump(mode="json")
    db.commit()
    return settings.backup


@router.get("/backups", response_model=list[BackupInfo])
async def list_backups(db: DBDep, admin: SudoAdminDep):
    """List all available backups"""
    backup_settings = get_backup_settings(db, admin)
    backup_manager = BackupManager(backup_settings)
    return await backup_manager.list_backups()


@router.post("/backups/create", response_model=BackupInfo)
async def create_backup(db: DBDep, admin: SudoAdminDep):
    """Create a new backup manually"""
    backup_settings = get_backup_settings(db, admin)
    backup_manager = BackupManager(backup_settings)
    backup_info = await backup_manager.create_backup()

    if not backup_info:
        raise HTTPException(status_code=500, detail="Backup creation failed")

    return backup_info


@router.get("/backups/{filename}/download")
async def download_backup(filename: str, db: DBDep, admin: SudoAdminDep):
    """Download a specific backup file"""
    backup_settings = get_backup_settings(db, admin)
    backup_manager = BackupManager(backup_settings)

    backups = await backup_manager.list_backups()
    backup = next((b for b in backups if b.filename == filename), None)

    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")

    return FileResponse(
        path=backup.location,
        filename=filename,
        media_type="application/gzip"
    )


@router.delete("/backups/{filename}")
async def delete_backup(filename: str, db: DBDep, admin: SudoAdminDep):
    """Delete a specific backup"""
    backup_settings = get_backup_settings(db, admin)
    backup_manager = BackupManager(backup_settings)

    success = await backup_manager.delete_backup(filename)

    if not success:
        raise HTTPException(status_code=404, detail="Backup not found or deletion failed")

    return {"message": f"Backup {filename} deleted successfully"}


@router.post("/backups/{filename}/restore")
async def restore_backup(filename: str, db: DBDep, admin: SudoAdminDep):
    """Restore from a specific backup"""
    backup_settings = get_backup_settings(db, admin)
    backup_manager = BackupManager(backup_settings)

    success = await backup_manager.restore_backup(filename)

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Backup restore failed. Please check logs for details."
        )

    return {"message": f"Backup {filename} restored successfully"}


@router.post("/backups/cleanup")
async def cleanup_old_backups(db: DBDep, admin: SudoAdminDep):
    """Manually trigger cleanup of old backups"""
    backup_settings = get_backup_settings(db, admin)
    backup_manager = BackupManager(backup_settings)

    await backup_manager.cleanup_old_backups()

    return {"message": "Old backups cleaned up successfully"}
