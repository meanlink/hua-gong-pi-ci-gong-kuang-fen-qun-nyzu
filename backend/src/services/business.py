"""化工批次标准化KMeans分群与轮廓诊断。"""
import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

FEATURES = ["temperature_c", "pressure_bar", "residence_min", "yield_pct"]
LABELS = ["反应温度(℃)", "釜压(bar)", "停留时间(min)", "收率(%)"]
PERTURB_FEATURES = ["temperature_c", "pressure_bar"]  # 温压读数携带测量误差，复核时仅扰动这两列


def metadata():
    return {
        "name": "化工批次工况分群", "short": "batch-clusters",
        "tagline": "从成批工况中找出运行族群，辨认稳定窗口与边缘批次。",
        "client": "青禾精细化学 · 4人过程优化小组 · 180批已完成的实验釜记录",
        "workflow": "工艺工程师按温度区间手工分组，再逐张比对釜压、停留时间与收率。",
        "pains": ["不同单位导致距离被温度主导", "人为分组难覆盖多变量工况", "分群数量凭经验缺少轮廓质量依据"],
        "upstream": "实验釜完工记录 reactor_batches_2026Q4.csv",
        "downstream": "工艺评审会选择下一轮小试的候选运行窗口",
        "entities": ["实验釜批次", "工况分群试验", "工艺评审简报"],
        "dataset_name": "青禾实验釜180批温压时收率记录",
        "columns": [{"key": "batch_id", "label": "批次", "type": "string"}] + [{"key": k, "label": l, "type": "number"} for k, l in zip(FEATURES, LABELS)],
        "parameters": [{"key": "clusters", "label": "工况族群数量K", "type": "number", "default": 3, "min": 2, "max": 6}],
        "workbench_title": "标准化工况分群", "action_label": "计算族群与轮廓质量", "unit": "批次",
        "accent": "oklch(51% 0.12 115)", "style": "specimen-lab-press",
        "seed_story": ["09:00 工艺员导入 reactor_batches_2026Q4.csv 的180批记录", "09:10 确认温度、釜压、停留时间和收率四列完整", "09:20 创建K=3的标准化分群试验", "09:21 后端计算Z分数、KMeans和轮廓系数", "09:30 工艺员查看各族群原单位中心及批次数", "09:40 改为K=4复查是否把稳定族群过度切开", "10:00 下载族群摘要交评审会", "16:00 管理员将评审简报设为每周内部归档"],
        "method": "对四个特征做Z分数标准化后，KMeans(n_init=20,random_state=42)拟合；用欧氏距离轮廓系数评估分离度；中心反变换回业务单位。",
        "limitations": ["KMeans偏好球形且相近规模的群", "将收率作为分群特征，不是收率预测模型", "分群标签无好坏含义，不能直接形成生产指令"],
        "recheck": {
            "title": "温压扰动换群复核",
            "tagline": "温压读数含测量误差，评审需要知道哪些釜批在误差扰动下容易换群。",
            "method": "固定原批次、群数K、误差范围与每次抽样：对反应温度和釜压读数施加±误差范围内的均匀扰动，重新Z分数标准化并拟合KMeans(n_init=20,random_state=42)；停留时间与收率保持原记录。新旧族群按批次重合最多一一配对（匈牙利指派），仅标签对调不记为换群。每个试次使用固定随机种子，中断后只补算缺失试次，并发重试不重复计入同一试次。",
            "parameters": [
                {"key": "error_pct", "label": "测量误差范围(±%读数)", "type": "number", "default": 2, "min": 0.1, "max": 25},
                {"key": "trials", "label": "扰动试次数", "type": "number", "default": 20, "min": 5, "max": 100},
            ],
            "note": "全部试次得出结论后才展示各批换群率；失败试次不计入有效试次，失败原因随结果列出。",
        },
    }


def seed_records():
    rng = np.random.default_rng(1010)
    centers = [[78, 2.2, 46, 89], [96, 3.6, 30, 94], [112, 5.1, 22, 83]]
    scales = [2.2, 0.18, 2.4, 1.6]
    rows = []
    for i in range(180):
        values = rng.normal(centers[i % 3], scales)
        rows.append({"batch_id": f"QH-{i+1:03}", **{k: round(float(v), 2) for k, v in zip(FEATURES, values)}})
    return rows


def _parse_k(params):
    try:
        raw_k = float(params.get("clusters", 3))
        k = int(raw_k)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("K须为2~6的整数。") from exc
    if raw_k != k or not 2 <= k <= 6:
        raise ValueError("K须为2~6的整数。")
    return k


def _validated_matrix(records, k):
    if len(records) < max(30, k * 5):
        raise ValueError("至少需要30条记录，且每个候选族群平均至少5条。")
    try:
        x = np.asarray([[float(row[f]) for f in FEATURES] for row in records])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("温度、釜压、停留时间、收率须完整且为数值。") from exc
    if not np.isfinite(x).all() or (x[:, 1:3] <= 0).any() or (x[:, 3] < 0).any() or (x[:, 3] > 100).any():
        raise ValueError("工况须为有限值，釜压与停留时间须正数，收率须0~100。")
    if np.unique(x, axis=0).shape[0] < k or np.std(x, axis=0).min() < 1e-9:
        raise ValueError("需要至少K种不同工况，且四个特征均须有变化。")
    return x


def analyze(records, params):
    k = _parse_k(params)
    x = _validated_matrix(records, k)
    scaler = StandardScaler()
    z = scaler.fit_transform(x)
    model = KMeans(n_clusters=k, n_init=20, random_state=42)
    assignment = model.fit_predict(z)
    centers = scaler.inverse_transform(model.cluster_centers_)
    # 以温度排序稳定显示标签，避免把算法内部随机标签误当业务等级。
    order = np.argsort(centers[:, 0])
    score = float(silhouette_score(z, assignment))
    rows = []
    chart_labels = []
    chart_values = [[] for _ in FEATURES]
    for display, cluster in enumerate(order, 1):
        n = int(np.sum(assignment == cluster))
        center = centers[cluster]
        rows.append({"cluster": f"工况族群{display}", "count": n, "share_pct": round(n / len(records) * 100, 1), **{f: round(float(v), 2) for f, v in zip(FEATURES, center)}})
        chart_labels.append(f"族群{display}")
        for j in range(len(FEATURES)):
            chart_values[j].append(round(float(model.cluster_centers_[cluster, j]), 3))
    best = max(rows, key=lambda row: row["yield_pct"])
    return {
        "summary": f"{len(records)}批工况分为{k}个族群；轮廓系数{score:.3f}，中心已还原为温度、釜压、时间和收率。",
        "metrics": [{"label": "轮廓系数", "value": round(score, 4)}, {"label": "族群数量", "value": k}, {"label": "批次数", "value": len(records)}, {"label": "标准化簇内平方和", "value": round(float(model.inertia_), 3)}],
        "table": {"columns": [{"key": "cluster", "label": "工况族群"}, {"key": "count", "label": "批次数"}, {"key": "share_pct", "label": "占比(%)"}] + [{"key": f, "label": l} for f, l in zip(FEATURES, LABELS)], "rows": rows},
        "chart": {"type": "bar", "labels": chart_labels, "series": [{"name": f"{LABELS[j]} Z中心", "values": chart_values[j]} for j in range(len(FEATURES))]},
        "findings": [f"{best['cluster']}的中心收率最高，为{best['yield_pct']}%；应结合温压窗口安排独立小试复核。", f"最小族群{min(row['count'] for row in rows)}批、最大族群{max(row['count'] for row in rows)}批；小群体可能对应边缘运行条件。", "对比不同K时优先观察轮廓系数与中心可解释性，簇内平方和随K增大通常会下降。"],
        "method": metadata()["method"], "warnings": ["分群用于探索，不表明某温压组合可安全放大。"] + (["轮廓系数低于0.25，当前工况分离较弱。"] if score < 0.25 else []),
    }


def fit_assignment(records, k):
    """验证并完整重新拟合，返回每批族群编号。基准分群与扰动试次共用同一口径。"""
    x = _validated_matrix(records, k)
    z = StandardScaler().fit_transform(x)
    model = KMeans(n_clusters=k, n_init=20, random_state=42)
    return model.fit_predict(z)


def perturb_readings(records, error_pct, seed):
    """按固定种子对温压读数施加±error_pct%均匀扰动，其余列保持原记录。"""
    rng = np.random.default_rng(seed)
    jitter = rng.uniform(-error_pct / 100.0, error_pct / 100.0, size=(len(records), len(PERTURB_FEATURES)))
    out = []
    for i, row in enumerate(records):
        perturbed = dict(row)
        for j, f in enumerate(PERTURB_FEATURES):
            perturbed[f] = float(row[f]) * (1.0 + float(jitter[i, j]))
        out.append(perturbed)
    return out


def match_clusters(base, new, k):
    """新旧族群按批次重合最多一一配对，返回{新族群: 原族群}；标签对调不影响判定。"""
    overlap = np.zeros((k, k), dtype=int)
    for b, n in zip(base, new):
        overlap[int(b), int(n)] += 1
    rows, cols = linear_sum_assignment(-overlap)
    return {int(new_cluster): int(base_cluster) for base_cluster, new_cluster in zip(rows, cols)}


def run_recheck_trial(records, k, base_assign, error_pct, seed):
    """单个扰动试次：扰动→重新拟合→最大重合配对→返回换群批次号列表。"""
    new_assign = fit_assignment(perturb_readings(records, error_pct, seed), k)
    mapping = match_clusters(base_assign, new_assign, k)
    return [records[i]["batch_id"] for i in range(len(records)) if mapping[int(new_assign[i])] != int(base_assign[i])]


def aggregate_recheck(recheck, trials, records, k):
    """全部试次有结论后汇总：换群率=换群试次数/有效试次数；失败试次只列原因，不进分母。"""
    valid = [t for t in trials if t.status == "completed"]
    failed = sorted((t for t in trials if t.status == "failed"), key=lambda t: t.trial_index)
    n_valid = len(valid)
    counts = {row["batch_id"]: 0 for row in records}
    for t in valid:
        for batch_id in t.switched:
            counts[batch_id] = counts.get(batch_id, 0) + 1
    rows = [{"batch_id": bid, "switches": n, "switch_pct": round(n / n_valid * 100, 1) if n_valid else 0.0} for bid, n in counts.items()]
    rows.sort(key=lambda r: (-r["switch_pct"], r["batch_id"]))
    moved = sum(1 for r in rows if r["switches"] > 0)
    top = rows[0]
    failures = [{"trial": t.trial_index + 1, "error": t.error} for t in failed]
    chart_rows = rows[:12]
    return {
        "summary": f"固定原{len(records)}批与K={k}，对温压读数施加±{recheck.error_pct}%误差扰动：{recheck.trials_total}个试次全部得出结论，有效{n_valid}个、失败{len(failed)}个；{moved}批至少换群一次，最高换群率{top['switch_pct']}%。",
        "metrics": [{"label": "有效试次", "value": n_valid}, {"label": "失败试次", "value": len(failed)}, {"label": "出现换群批次", "value": moved, "unit": "批"}, {"label": "最高换群率", "value": top["switch_pct"], "unit": "%"}],
        "table": {"columns": [{"key": "batch_id", "label": "批次"}, {"key": "switches", "label": "换群次数"}, {"key": "switch_pct", "label": "换群率(%)"}], "rows": rows},
        "chart": {"type": "bar", "labels": [r["batch_id"] for r in chart_rows], "series": [{"name": "换群率(%)", "values": [r["switch_pct"] for r in chart_rows]}]},
        "findings": [
            f"{top['batch_id']}换群率最高，{n_valid}个有效试次中换群{top['switches']}次；该批位于族群边界，评审时建议优先复核其温压记录。" if n_valid else "没有有效试次，无法判断换群倾向。",
            f"{len(records) - moved}批在全部有效试次中从未换群，属于稳定核心批次。",
            "新旧族群按批次重合最多一一配对，仅标签对调不记为换群；换群率随误差范围扩大而上升，跨复核比较请保持口径一致。",
        ],
        "failures": failures,
        "params": {"clusters": k, "error_pct": recheck.error_pct, "trials": recheck.trials_total, "batches": len(records)},
        "method": metadata()["recheck"]["method"],
        "warnings": ([f"{len(failed)}个试次拟合失败，未计入有效试次；失败原因见下表。"] if failed else []) + (["有效试次为0，换群率不可用；请缩小误差范围后重新复核。"] if not n_valid else []),
    }
