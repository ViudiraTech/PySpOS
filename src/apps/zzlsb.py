#   
#   zzlsb.py
#   简单的猜数字游戏（别问我为什么文件名是zzlsb）
#
#   2026/1/23 by GoutouStdio
#   @ 2022~2026 GoutouStdio. Open all rights.

import random

FOOD_OPTIONS = ['', '炸鸡', '炖肉', '胖牛', '汉堡', '飞电6Chanllger']

def main():
    print("简单猜数字游戏，根据提示语找答案！\n")
    secret_number = random.randint(0, 100)
    # 2026-09-24 修复：FOOD_OPTIONS 只有 6 项（下标 0-5），原来的
    # randint(1, 6) 会取到下标 6 → list index out of range，
    # 1/6 概率一开局就崩。
    food_index = random.randint(1, len(FOOD_OPTIONS) - 1)
    print(f"大妈妈，你要做{FOOD_OPTIONS[food_index]}的话，你大该要放{float(secret_number / food_index)}克盐。\n\n")

    while True:
        try:
            user_guess = int(input("输入你猜的数字："))

            if user_guess == secret_number:
                print("恭喜你猜中了！\n")
                break
            elif user_guess < secret_number:
                print("猜小了，再试试！\n")
            else:
                print("猜大了，再试试！\n")
        except EOFError:
            # 2026-09-24 修复：stdin 关闭（EOF/Ctrl-D）时必须退出。
            # 旧代码把它塞进通用 Exception 里，导致 apps 变成真子进程后
            # 无限空转吃满一个 CPU 核。
            print("\n输入已结束，游戏退出。\n")
            break
        except KeyboardInterrupt:
            print("\n已中断，游戏退出。\n")
            break
        except ValueError:
            print("请输入有效的数字！\n")
        except Exception as e:
            print(f"发生了未知错误：{e}\n")
            break

if __name__ == "__exec__":
    try:
        main()
    except Exception as e:
        print(f"程序运行出错：{str(e)}")
else:
    raise SystemError("请不要直接运行本程序")