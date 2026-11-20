import time, secrets, logging
from fastapi import HTTPException
from redis import Redis
from sqlalchemy import select, delete, func
from sqlalchemy.exc import IntegrityError
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Dataset, Job, Recheck, RecheckTrial
from src.services.business import fit_assignment, run_recheck_trial, aggregate_recheck
from src.services.audit import record

ERROR_MIN, ERROR_MAX = 0.1, 25.0
TRIALS_MIN, TRIALS_MAX = 5, 100


def create(db, data, user):
    j = db.get(Job, data.job_id)
    if not j:
        raise HTTPException(404, '分析任务不存在')
    if j.status != 'completed':
        raise HTTPException(409, '仅已完成分群可以发起复核')
    if not (ERROR_MIN <= data.error_pct <= ERROR_MAX):
        raise HTTPException(422, f'误差范围须{ERROR_MIN}~{ERROR_MAX}%')
    if not (TRIALS_MIN <= data.trials <= TRIALS_MAX):
        raise HTTPException(422, f'试次数须{TRIALS_MIN}~{TRIALS_MAX}')
    rc = Recheck(name=data.name, job_id=j.id, error_pct=data.error_pct, trials_total=data.trials,
                 base_seed=secrets.randbits(63), status='queued', created_by=user.id, created_at=time.time())
    db.add(rc)
    db.flush()
    return rc


def enqueue(recheck_id):
    try:
        r = Redis.from_url(REDIS_URL)
        r.rpush('recheck:queue', recheck_id)
        r.close()
    except Exception:
        pass  # SQL queued status is the durable fallback


def trial_counts(db, recheck_ids):
    """各复核已结论试次统计：valid=成功，failed=失败。"""
    counts = {i: {'valid': 0, 'failed': 0} for i in recheck_ids}
    if not recheck_ids:
        return counts
    rows = db.execute(
        select(RecheckTrial.recheck_id, RecheckTrial.status, func.count())
        .where(RecheckTrial.recheck_id.in_(recheck_ids), RecheckTrial.status.in_(['completed', 'failed']))
        .group_by(RecheckTrial.recheck_id, RecheckTrial.status)).all()
    for recheck_id, status, n in rows:
        counts[recheck_id]['valid' if status == 'completed' else 'failed'] = n
    return counts


def claim(db, recheck_id, trial_index):
    """按唯一键认领试次；并发重试由约束去重，不重复计入同一试次。"""
    t = RecheckTrial(recheck_id=recheck_id, trial_index=trial_index, status='running')
    db.add(t)
    try:
        db.commit()
        return t
    except IntegrityError:
        db.rollback()
        return None


def run(recheck_id, budget=10):
    """补算缺失试次；全部试次有结论后聚合换群率。中断后再调用会从缺项继续。"""
    with Session() as db:
        rc = db.get(Recheck, recheck_id)
        if not rc or rc.status not in ('queued', 'running'):
            return
        j = db.get(Job, rc.job_id)
        d = db.get(Dataset, j.dataset_id) if j else None
        if not j or not d:
            rc.status = 'failed'
            rc.error = '来源分群或数据批次已不存在'
            rc.finished_at = time.time()
            db.commit()
            return
        k = int(j.params.get('clusters', 3))
        records = d.records
        try:
            base_assign = [int(v) for v in fit_assignment(records, k)]
        except Exception as exc:
            rc.status = 'failed'
            rc.error = f'基准分群复算失败：{exc}'[:990]
            rc.finished_at = time.time()
            record(db, 'worker', 'recheck.failed', {'id': rc.id, 'error': rc.error})
            db.commit()
            return
        if rc.status == 'queued':
            rc.status = 'running'
            db.commit()
        done = set(db.scalars(select(RecheckTrial.trial_index).where(RecheckTrial.recheck_id == rc.id)))
        missing = [i for i in range(rc.trials_total) if i not in done]
        for i in missing[:budget]:
            t = claim(db, rc.id, i)
            if t is None:
                continue  # 另一并发已认领该试次
            try:
                t.switched = run_recheck_trial(records, k, base_assign, rc.error_pct, rc.base_seed + i)
                t.status = 'completed'
            except Exception as exc:
                logging.exception('Recheck trial failed')
                t.status = 'failed'
                t.error = str(exc)[:490]
            t.finished_at = time.time()
            db.commit()
        trials = list(db.scalars(select(RecheckTrial).where(RecheckTrial.recheck_id == rc.id)))
        concluded = [t for t in trials if t.status in ('completed', 'failed')]
        if len(concluded) == rc.trials_total:
            rc.result = aggregate_recheck(rc, concluded, records, k)
            rc.status = 'completed'
            rc.finished_at = time.time()
            record(db, 'worker', 'recheck.completed', {'id': rc.id, 'valid': sum(1 for t in concluded if t.status == 'completed')})
        db.commit()


def recover(db):
    """worker启动恢复：中断的复核回到队列，未写完的试次删除后按缺项重算（种子固定，结果一致）。"""
    for rc in db.scalars(select(Recheck).where(Recheck.status == 'running')):
        rc.status = 'queued'
        record(db, 'worker', 'recheck.recovered', {'id': rc.id})
    db.execute(delete(RecheckTrial).where(RecheckTrial.status == 'running'))
