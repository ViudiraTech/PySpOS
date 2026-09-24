# gettoken.py - 获取解锁密钥实用程序
#
# 审核算法（2026-09-24 重构，A+B 组合）：
#   A. 规则重构 —— 分数为主，速度不再定罪：
#      - 达到及格线即通过；答得快 + 全对 = 能力强，不是作弊
#        （测量学 person-fit 方向的共识：作弊信号是“难题答对+极短时”或
#        “极短时+答错”，从没有任何成熟做法惩罚“简单题又快又对”）。
#      - 时间只拦机器级异常：单题用时 < MACHINE_TAP_SECONDS(0.4s) 视为连点，
#        该题不得分；整卷连点数 >= MACHINE_TAP_LIMIT(5) 则整卷无效。
#        （0.4s 量级参考 rapid-guessing 文献中“未加工题干”的极短时定义，
#        人类读完题干再作答不可能稳定低于此值。）
#      - 总限时 TOTAL_TIME_LIMIT（行业实践 60~90s/选择题，这里 10 题给 300s，
#        只防查答案，不刁难正常作答）；超时按已答题结算。
#      - 未通过冷却 COOLDOWN_SECONDS，防刷题。
#   B. 题库纵深 —— 安全从“审速度”转到“背不下答案”：
#      - 分层随机抽题（True/False 各半），修复旧题库答案 99:26 偏斜下
#        “全蒙 y 得 79 分”的漏洞；每次题目 + 顺序都随机；
#      - 考后只告知对错，不泄露正确答案（本文件历来如此，保持）。
#
import api
import random
import json
import os
import time
from datetime import datetime
import printk

# ---------------- 可调配置区 ----------------
TOTAL_QUESTIONS = 10
PASS_SCORE = 80
SCORE_PER_QUESTION = 10

# 每类答案各抽一半（TOTAL_QUESTIONS 须为偶数；某池不足时自动回退全池随机）
TRUE_COUNT = TOTAL_QUESTIONS // 2
FALSE_COUNT = TOTAL_QUESTIONS - TRUE_COUNT

# 机器连点线：单题低于此用时视为无效作答（秒）
MACHINE_TAP_SECONDS = 0.4
# 整卷连点数达到此值 → 整卷无效（秒级连点不可能是人类作答）
MACHINE_TAP_LIMIT = 5
# 整卷总限时（秒）：只防查答案，正常作答绰绰有余
TOTAL_TIME_LIMIT = 300
# 未通过后的冷却（秒）：防高频刷题
COOLDOWN_SECONDS = 60

# 题库路径（跨平台：不再硬编码反斜杠，兼容 Linux/Mac/Windows）
QUESTION_BANK_PATH = os.path.join(os.getcwd(), 'apps', 'question_bank.json')


# ---------------- 纯函数（可单测） ----------------

def select_questions(pool, total=TOTAL_QUESTIONS,
                     n_true=TRUE_COUNT, n_false=FALSE_COUNT):
    """分层随机抽题：True 池抽 n_true，False 池抽 n_false，再整体乱序。

    池子不足时回退为全池随机抽取，保证永不崩溃。
    """
    trues = [q for q in pool if q.get("answer") is True]
    falses = [q for q in pool if q.get("answer") is False]
    if len(trues) >= n_true and len(falses) >= n_false:
        picked = random.sample(trues, n_true) + random.sample(falses, n_false)
    else:
        picked = random.sample(pool, min(total, len(pool)))
    random.shuffle(picked)
    return picked


def grade(results):
    """结算：results 为 [(correct: bool, cost: float)] 列表。

    返回 (score, machine_taps, valid)：
      - 单题 cost < MACHINE_TAP_SECONDS → 连点，该题不得分；
      - machine_taps >= MACHINE_TAP_LIMIT → 整卷无效。
    """
    score = 0
    machine_taps = 0
    for correct, cost in results:
        if cost < MACHINE_TAP_SECONDS:
            machine_taps += 1
            continue
        if correct:
            score += SCORE_PER_QUESTION
    valid = machine_taps < MACHINE_TAP_LIMIT
    return score, machine_taps, valid


def cooldown_remaining(last_fail_ts, now=None):
    """距上次失败不足 COOLDOWN_SECONDS 时返回剩余秒数，否则返回 0。"""
    now = now if now is not None else time.time()
    rest = COOLDOWN_SECONDS - (now - last_fail_ts)
    return max(0, int(rest))


# ---------------- 交互主流程 ----------------

def _load_bank():
    try:
        with open(QUESTION_BANK_PATH, 'r', encoding='utf-8') as f:
            bank = json.load(f)
    except FileNotFoundError:
        print(f"错误：题库文件不存在，路径：{QUESTION_BANK_PATH}")
        print("请确认question_bank.json文件位置后重试！")
        return None
    except json.JSONDecodeError:
        print("错误：题库文件格式错误（非合法JSON）")
        return None
    if "history" not in bank:
        bank["history"] = []
    if len(bank.get("questions", [])) < TOTAL_QUESTIONS:
        print(f"错误：题库数量不足！当前题库有{len(bank.get('questions', []))}道题，需要至少{TOTAL_QUESTIONS}道")
        return None
    return bank


def _save_bank(bank):
    try:
        with open(QUESTION_BANK_PATH, 'w', encoding='utf-8') as f:
            json.dump(bank, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"{printk.RED_COLOR}错误：记录答题历史失败 - {str(e)}{printk.RESET_COLOR}")


def _show_history(history):
    latest = history[-1]
    print("检测到有历史答题数据，以下是历史数据")
    print(f"上次得分：{latest['score']}分，状态：{'通过' if latest['pass'] else '未通过'}，"
          f"答题时间：{latest['timestamp']}，平均答题时间：{latest.get('avg_time', '-')}秒")


def main():
    print("获取解锁密钥实用程序")
    print("注意：此密钥包含一些设备的敏感数据，请勿泄露！")
    print(f"解锁需要您判断一些选项（共{TOTAL_QUESTIONS}道题，一道题{SCORE_PER_QUESTION}分，"
          f"大于等于{PASS_SCORE}分可获取密钥；限时{TOTAL_TIME_LIMIT}秒）。\n")

    bank = _load_bank()
    if bank is None:
        return
    history = bank["history"]

    if history:
        latest = history[-1]
        _show_history(history)
        # 冷却：上次没过且还在冷却期内，拒绝重考
        if not latest.get("pass", False):
            rest = cooldown_remaining(latest.get("fail_ts", 0))
            if rest > 0:
                print(f"{printk.YELLOW_COLOR}上次未通过，冷却中，请 {rest} 秒后再试。{printk.RESET_COLOR}")
                return
        if not api.api_confirm("是否重新答题？（y/n）"):
            if latest.get("pass") and latest.get("score", 0) >= PASS_SCORE:
                print(f"{printk.GREEN_COLOR}您已通过测试，以下是你的解锁密钥{printk.RESET_COLOR}")
                print(f"解锁密钥（请妥善保管）: {api.return_token()}")
                return
            print(f"{printk.YELLOW_COLOR}您上次未通过测试，无法获取密钥，请重新答题。{printk.RESET_COLOR}")
            return

    selected = select_questions(bank["questions"])
    results = []
    answer_times = []
    t_start = time.time()
    timeout = False

    for idx, q in enumerate(selected, 1):
        elapsed = time.time() - t_start
        if elapsed >= TOTAL_TIME_LIMIT:
            timeout = True
            print(f"\n{printk.YELLOW_COLOR}总限时 {TOTAL_TIME_LIMIT} 秒已到，按已答 {len(results)} 题结算。{printk.RESET_COLOR}")
            break
        start_ts = time.time()
        user_ans = api.api_confirm(f"{idx}. {q['question']}")
        cost_time = round(time.time() - start_ts, 2)
        answer_times.append(cost_time)

        tapped = cost_time < MACHINE_TAP_SECONDS
        correct = (user_ans == q["answer"]) and not tapped
        results.append((correct, cost_time))
        if tapped:
            api.api_warn(f"用时 {cost_time} 秒过短，该题作答无效（疑似连点）。")
        elif correct:
            api.api_ok(f"答对了！（用时：{cost_time}秒）")
        else:
            api.api_warn(f"答错了，不加分。（用时：{cost_time}秒）")

    score, machine_taps, valid = grade(results)
    avg_time = round(sum(answer_times) / len(answer_times), 2) if answer_times else 0
    total_time = round(time.time() - t_start, 2)
    is_pass = valid and not timeout and score >= PASS_SCORE
    # 超时但已答部分满分这种极端情况也允许过：按“已答题均对且触线”折算
    if timeout and valid and results and score >= PASS_SCORE * len(results) / TOTAL_QUESTIONS:
        is_pass = True

    record = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "score": score,
        "pass": is_pass,
        "avg_time": avg_time,
        "total_time": total_time,
        "timeout": timeout,
        "answered": len(results),
        "machine_taps": machine_taps,
        "valid": valid,
    }
    if not is_pass:
        record["fail_ts"] = time.time()
    bank["history"].append(record)
    _save_bank(bank)

    print("\n" + "=" * 50)
    print(f"答题统计：共答 {len(results)} 题，平均用时 {avg_time} 秒，总用时 {total_time} 秒"
          + ("（超时结算）" if timeout else ""))
    if not valid:
        print(f"{printk.RED_COLOR}检测到 {machine_taps} 次机器级连点作答，本卷无效，请稍后重考。{printk.RESET_COLOR}")
        return
    if is_pass:
        print(f"{printk.GREEN_COLOR}恭喜！得分：{score}分（及格线{PASS_SCORE}分）{printk.RESET_COLOR}")
        print("审核通过，以下是你的解锁密钥")
        print(f"解锁密钥（请妥善保管）: {api.return_token()}")
        return
    print(f"{printk.YELLOW_COLOR}未通过测试：得分{score}分（及格线{PASS_SCORE}分）{printk.RESET_COLOR}")
    print(f"请 {COOLDOWN_SECONDS} 秒后重试。")


if __name__ == "__exec__":
    try:
        main()
    except Exception as e:
        print(f"程序运行出错：{str(e)}")
else:
    raise SystemError("请不要直接运行本程序")
