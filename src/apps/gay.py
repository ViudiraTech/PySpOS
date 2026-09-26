'''
 *
 *      gay.py
 *      Typing animation demo app.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import string
import time

text = "Hello world Chen Yang is gay"

# Type the greeting out one printable character per frame.
def main():
    temp = ""
    for ch in text:
        typed = False
        for i in string.printable:
            if i == ch or ch == " ":
                time.sleep(0.01)
                print(temp + i)
                temp += ch
                typed = True
                break
            else:
                time.sleep(0.01)
                print(temp + i)
        if not typed:
            # A character outside string.printable is never reached by the inner
            # loop, so the old code dropped it and typed the rest of the string
            # shifted by one. Print it directly and move on, so every character
            # is emitted exactly once whatever the input holds.
            print(temp + ch)
            temp += ch
    print() # print a blank line
    
if __name__ == "__exec__":
    main()
