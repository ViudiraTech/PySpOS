'''
 *
 *      gettoken.py
 *      Quiz app used to obtain a session token.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import api
import random
import json
import os
import time
from datetime import datetime
import printk

TOTAL_QUESTIONS = 10
PASS_SCORE = 80
SCORE_PER_QUESTION = 10

# Take half of each answer class; TOTAL_QUESTIONS must be even and a short
# pool falls back to a plain random draw
TRUE_COUNT = TOTAL_QUESTIONS // 2
FALSE_COUNT = TOTAL_QUESTIONS - TRUE_COUNT

# Machine-tap floor: an answer faster than this counts as invalid (seconds)
MACHINE_TAP_SECONDS = 0.4
# Machine taps reaching this count invalidate the whole paper; nobody
# answers in seconds
MACHINE_TAP_LIMIT = 5
# Total time limit in seconds: it only stops answer lookups and never
# hampers normal answering
TOTAL_TIME_LIMIT = 300
# Cooldown after a failed pass, in seconds, to stop rapid retries
COOLDOWN_SECONDS = 60

# Question bank path, built with os.path.join instead of a hardcoded
# backslash so it works on Linux/Mac/Windows
QUESTION_BANK_PATH = os.path.join(os.getcwd(), 'apps', 'question_bank.json')


# Draw questions with a balanced True/False split, then shuffle them.
# A short pool falls back to a plain random draw, so this never raises.
def select_questions(pool, total=TOTAL_QUESTIONS,
                     n_true=TRUE_COUNT, n_false=FALSE_COUNT):
    trues = [q for q in pool if q.get("answer") is True]
    falses = [q for q in pool if q.get("answer") is False]
    if len(trues) >= n_true and len(falses) >= n_false:
        picked = random.sample(trues, n_true) + random.sample(falses, n_false)
    else:
        picked = random.sample(pool, min(total, len(pool)))
    random.shuffle(picked)
    return picked


# Score one attempt from (correct, cost) pairs, discarding answers
# faster than MACHINE_TAP_SECONDS. Returns (score, machine_taps,
# valid); reaching MACHINE_TAP_LIMIT taps invalidates the whole paper.
def grade(results):
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


# Seconds left before a failed attempt may be retried, 0 once the
# COOLDOWN_SECONDS cooldown has expired.
def cooldown_remaining(last_fail_ts, now=None):
    now = now if now is not None else time.time()
    rest = COOLDOWN_SECONDS - (now - last_fail_ts)
    return max(0, int(rest))


# Read the question bank, adding a history array when missing, and
# reject it if the file is unusable or holds fewer than
# TOTAL_QUESTIONS questions.
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


# Write the bank back with the new history record; never raises.
def _save_bank(bank):
    try:
        with open(QUESTION_BANK_PATH, 'w', encoding='utf-8') as f:
            json.dump(bank, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"{printk.RED_COLOR}错误：记录答题历史失败 - {str(e)}{printk.RESET_COLOR}")


# Print the most recent history record.
def _show_history(history):
    latest = history[-1]
    print("检测到有历史答题数据，以下是历史数据")
    print(f"上次得分：{latest['score']}分，状态：{'通过' if latest['pass'] else '未通过'}，"
          f"答题时间：{latest['timestamp']}，平均答题时间：{latest.get('avg_time', '-')}秒")


# Run the quiz: the score decides, and only machine-speed answers
# count as cheating. A timeout settles the questions already
# answered, a failure starts COOLDOWN_SECONDS, and passing grants
# neither ROOT nor any bootloader trust.
def main():
    print("旧版答题入口")
    print("答题结果不会授予 ROOT 或改变 Bootloader 信任域。")
    print(f"本流程仅保留兼容性（共{TOTAL_QUESTIONS}道题，一道题{SCORE_PER_QUESTION}分，"
          f"仅记录结果；限时{TOTAL_TIME_LIMIT}秒）。\n")

    bank = _load_bank()
    if bank is None:
        return
    history = bank["history"]

    if history:
        latest = history[-1]
        _show_history(history)
        # Cooldown: the last attempt failed and is still cooling down, so
        # refuse the retake
        if not latest.get("pass", False):
            rest = cooldown_remaining(latest.get("fail_ts", 0))
            if rest > 0:
                print(f"{printk.YELLOW_COLOR}上次未通过，冷却中，请 {rest} 秒后再试。{printk.RESET_COLOR}")
                return
        if not api.api_confirm("是否重新答题？（y/n）"):
            if latest.get("pass") and latest.get("score", 0) >= PASS_SCORE:
                print(f"{printk.GREEN_COLOR}审核通过，但 Token 不再是 Bootloader 授权凭据{printk.RESET_COLOR}")
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
    # Edge case: a timed-out run also passes when every answered question was
    # right, scaled by how much of the paper was answered
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
        print("审核通过，但 Token 不再是 Bootloader 授权凭据。")
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
