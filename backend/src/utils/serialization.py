import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}
def recheck_dict(r, counts=None):
    d = {k: getattr(r, k) for k in ['id', 'name', 'job_id', 'error_pct', 'trials_total', 'status', 'result', 'error', 'created_at', 'finished_at']}
    d['trials_valid'] = (counts or {}).get('valid', 0)
    d['trials_failed'] = (counts or {}).get('failed', 0)
    d['trials_done'] = d['trials_valid'] + d['trials_failed']
    return d
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
