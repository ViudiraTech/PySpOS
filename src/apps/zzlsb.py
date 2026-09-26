'''
 *
 *      zzlsb.py
 *      Number guessing game with a salt hint.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import random

FOOD_OPTIONS = ['', '炸鸡', '炖肉', '胖牛', '汉堡', '飞电6Chanllger']

# Play the guessing game: roll a secret number and a food, then hint
# how much salt that food needs.
def main():
    print("简单猜数字游戏，根据提示语找答案！\n")
    secret_number = random.randint(0, 100)
    # 2026-09-24 fix: FOOD_OPTIONS holds only 6 entries (index 0-5), so the old
    # randint(1, 6) could pick index 6 and raise list index out of range,
    # crashing the game on the first round one time in six.
    food_index = random.randint(1, len(FOOD_OPTIONS) - 1)
    print(f"大妈妈，你要做{FOOD_OPTIONS[food_index]}的话，你大概该放{float(secret_number / food_index)}克盐。\n\n")

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
            # 2026-09-24 fix: a closed stdin (EOF/Ctrl-D) has to end the game.
            # The old code caught it in a generic Exception, so once apps became real
            # child processes it spun forever and burned a whole CPU core.
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