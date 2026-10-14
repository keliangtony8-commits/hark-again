# 连发分组（运行中来的消息）准确率评测：跑 backend/tests/intake_cases.jsonl，量规则层与判官层。
#
# 为什么有它：HANDOFF §五 3 要“重新标注 57 组、报告真实准确率”，但旧沙盒里那套（work/e2e-harness/）
# 从没提交进 git，数字不可复现。这个评测进仓库，成为唯一真源：改了 app/message_intake.py 的规则先跑它。
#
# 两层：
#   规则层（默认，免费、确定性）：逐条比 rule()/reply_to 与标注 →
#     命中 = 规则答对了；误判 = 规则答了个确定的错（这是 bug）；交给判官 = 规则说拿不准（设计内的成本）。
#   判官层（EVAL_JUDGE=1，要真模型网关，走最便宜的 lite）：只对“交给判官”的那几条调真 judge()，
#     量拿不准的时候便宜模型答得对不对。本地没网关就到 VPS 容器里跑：docker compose exec backend python tests/smoke_intake_eval.py。
#
# 运行：
#   python tests/smoke_intake_eval.py            # 规则层，任何误判都退出码 1（当门用）
#   python tests/smoke_intake_eval.py -v         # 逐条打印（含每次判定的依据）
#   EVAL_JUDGE=1 python tests/smoke_intake_eval.py -v   # 加跑判官层
import asyncio
import json
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///" + os.path.join(os.path.dirname(__file__), ".eval-intake.db"))
os.environ.setdefault("LLM_BASE_URL", "http://x")
os.environ.setdefault("LITELLM_MASTER_KEY", "k")
os.environ.setdefault("OWNER_USERNAME", "u")
os.environ.setdefault("OWNER_PASSWORD", "p")
os.environ.setdefault("JWT_SECRET", "s" * 32)
os.environ.setdefault("VAULT_KEY", "")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import message_intake as mi  # noqa: E402

CASES = os.path.join(os.path.dirname(__file__), "intake_cases.jsonl")
KINDS = (mi.STEER, mi.NEW, mi.PROGRESS, mi.RIDE)
ABSTAIN = "judge"  # 规则拿不准，交给 lite 判官


def load() -> list[dict]:
    with open(CASES, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def decide(m: dict) -> str:
    """这一条实际会被怎么处理（不含判官）：带引用 = 另一件事，否则看规则。"""
    if m.get("reply_to"):
        return mi.NEW
    return mi.rule(m.get("text", ""), bool(m.get("files"))) or ABSTAIN


def check_grouping(case: dict) -> list[str]:
    """顺带查分流装配：同类的合成一件、顺序固定、带引用一定进 NEW。"""
    bad: list[str] = []
    items = [mi.Arrival(f"{case['id']}-{i}", m.get("text", ""), m.get("text", ""), at=None,  # type: ignore[arg-type]
                        reply_to="q" if m.get("reply_to") else None, files=bool(m.get("files")))
             for i, m in enumerate(case["messages"])]
    got = mi.group(items, mi.STEER)
    order = [k for k, _ in got]
    if order != [k for k in (mi.STEER, mi.NEW, mi.PROGRESS, mi.RIDE) if k in order]:
        bad.append(f"{case['id']}: 分流顺序不对 {order}")
    total = sum(len(v) for _, v in got)
    if total != len(items):
        bad.append(f"{case['id']}: 分流里少了消息 {total} != {len(items)}")
    for kind, group in got:
        if kind == mi.NEW and any(a.reply_to is None and mi.rule(a.text, a.files) is not None for a in group):
            bad.append(f"{case['id']}: 规则能定的消息被塞进并行路")
    return bad


async def judge_layer(rows: list[dict]) -> dict:
    """对“交给判官”的条目调真模型（一次一条，按 case 分组传，和线上一致）。"""
    ok = bad = skipped = 0
    detail: list[str] = []
    for case in rows:
        need = [m for m in case["messages"] if decide(m) == ABSTAIN and not m.get("reply_to")]
        if not need:
            continue
        try:
            got = await mi.judge(case["task"], [m["text"] for m in need])
        except Exception as e:  # noqa: BLE001
            skipped += 1
            detail.append(f"  {case['id']}: 调不动模型（{e}）")
            continue
        want_new = any(m["expect"] == mi.NEW for m in need)
        want = mi.NEW if want_new else mi.STEER  # 判官只会答这两类：补充 or 新问题
        if got == want:
            ok += 1
        else:
            bad += 1
            detail.append(f"  ✗ {case['id']}: 期望 {want}，模型答 {got}｜{need[0]['text']}")
    return {"ok": ok, "bad": bad, "skipped": skipped, "detail": detail}


def main() -> int:
    verbose = "-v" in sys.argv
    cases = load()
    per_kind = {k: {"n": 0, "hit": 0, "miss": 0, "abstain": 0} for k in KINDS}
    hits = misses = abstains = 0
    miss_rows: list[str] = []
    abstain_rows: list[str] = []
    struct_bad: list[str] = []

    for case in cases:
        struct_bad += check_grouping(case)
        for m in case["messages"]:
            want = m["expect"]
            got = decide(m)
            per_kind[want]["n"] += 1
            if got == want:
                hits += 1
                per_kind[want]["hit"] += 1
                if verbose:
                    print(f"  ✓ {case['id']} {want:<8} {m['text'][:24]}")
            elif got == ABSTAIN:
                abstains += 1
                per_kind[want]["abstain"] += 1
                abstain_rows.append(f"{case['id']} 期望 {want:<8} 规则拿不准｜{m['text'][:24]}")
            else:
                misses += 1
                per_kind[want]["miss"] += 1
                miss_rows.append(f"{case['id']} 期望 {want:<8} 规则答 {got:<8}｜{m['text'][:24]}")

    total = hits + misses + abstains
    cases_judge = sum(1 for c in cases if any(decide(m) == ABSTAIN for m in c["messages"]))
    print(f"标注集：{len(cases)} 组 / {total} 条消息（backend/tests/intake_cases.jsonl）")
    print(f"规则层：命中 {hits}、误判 {misses}、交给判官 {abstains}"
          f"　→ 命中率 {hits / total:.1%}，误判率 {misses / total:.1%}，兜底率 {abstains / total:.1%}")
    print(f"组：{len(cases)} 组里 {len(cases) - cases_judge} 组纯靠规则定，{cases_judge} 组要问一次便宜模型"
          f"（{cases_judge / len(cases):.0%} 的连发多花一次 ≈200 token 的调用）")
    print(f"端到端（判官答对时）：{(hits + abstains) / total:.1%}")
    for k in KINDS:
        s = per_kind[k]
        print(f"  {k:<8} 共 {s['n']:>2}：命中 {s['hit']:>2}、误判 {s['miss']:>2}、交判官 {s['abstain']:>2}")
    if miss_rows:
        print("规则误判（bug，必须修或改标注并说明）：")
        for r in miss_rows:
            print("  ✗ " + r)
    if abstain_rows and verbose:
        print("交给判官（设计内）：")
        for r in abstain_rows:
            print("  · " + r)
    if struct_bad:
        print("分流装配有问题：")
        for r in struct_bad:
            print("  ✗ " + r)

    judge_bad = 0
    if os.environ.get("EVAL_JUDGE") == "1":
        res = asyncio.run(judge_layer(cases))
        judge_bad = res["bad"]
        print(f"判官层（真模型 · {mi.settings.router_model or mi.settings.summary_model}）："
              f"答对 {res['ok']}、答错 {res['bad']}、没调通 {res['skipped']}")
        for line in res["detail"]:
            print(line)
    else:
        print("判官层没跑（要真模型网关：EVAL_JUDGE=1，或到 VPS 容器里跑）")

    bad = misses + len(struct_bad) + judge_bad
    print("ALL OK" if bad == 0 else f"有 {bad} 处要处理")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
