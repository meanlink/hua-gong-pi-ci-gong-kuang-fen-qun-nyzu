from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import Recheck
from src.schemas.recheck import RecheckInput
from src.middlewares.auth import current_user, can_write
from src.services import rechecks
from src.services.audit import record
from src.utils.serialization import recheck_dict
router = APIRouter(prefix='/rechecks')
@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    rows = list(db.scalars(select(Recheck).order_by(Recheck.id.desc()).limit(100)))
    counts = rechecks.trial_counts(db, [r.id for r in rows])
    return [recheck_dict(r, counts.get(r.id)) for r in rows]
@router.post('', status_code=201)
def create(data: RecheckInput, db=Depends(get_db), u=Depends(can_write)):
    rc = rechecks.create(db, data, u)
    record(db, u.email, 'recheck.create', {'id': rc.id, 'job_id': rc.job_id, 'error_pct': rc.error_pct, 'trials': rc.trials_total})
    db.commit()
    rechecks.enqueue(rc.id)
    return recheck_dict(rc)
@router.get('/{id}')
def detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    rc = db.get(Recheck, id)
    if not rc:
        raise HTTPException(404, '复核任务不存在')
    return recheck_dict(rc, rechecks.trial_counts(db, [rc.id]).get(rc.id))
@router.post('/{id}/resume')
def resume(id: int, db=Depends(get_db), u=Depends(can_write)):
    rc = db.get(Recheck, id)
    if not rc:
        raise HTTPException(404, '复核任务不存在')
    if rc.status not in ('queued', 'running'):
        raise HTTPException(409, '复核已有结论，无需恢复')
    rechecks.enqueue(rc.id)  # 幂等：缺项按唯一键认领，并发重试不重复计入
    record(db, u.email, 'recheck.resume', {'id': id})
    db.commit()
    return recheck_dict(rc, rechecks.trial_counts(db, [rc.id]).get(rc.id))
