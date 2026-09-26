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
        for i in string.printable:
            if i == ch or ch == " ":
                time.sleep(0.01)
                print(temp + i)
                temp += ch
                break
            else:
                time.sleep(0.01)
                print(temp + i)
    print() # print a blank line
    
if __name__ == "__exec__":
    main()
