'''
 *
 *      calc.py
 *      Demo app that shows the arithmetic syscalls.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import api
import math

# Add two numbers through the api syscall layer.
def add(a, b):
    return api.add(a, b)
# Subtract two numbers through the api syscall layer.
def subtract(a, b):
    return api.subtract(a, b)
# Multiply two numbers through the api syscall layer.
def multiply(a, b):
    return api.multiply(a, b)
# Divide two numbers through the api syscall layer.
def divide(a, b):
    return api.divide(a, b)

# Print the four basic operations for one pair of operands.
def main(num1,num2):
    print(f"{num1} + {num2} = {add(num1,num2)}")
    print(f"{num1} - {num2} = {subtract(num1,num2)}")
    print(f"{num1} * {num2} = {multiply(num1,num2)}")
    print(f"{num1} / {num2} = {divide(num1,num2)}")

# Return pi, for callers that import calc as a plain module.
def pi():
    return math.pi

if __name__ == "__main__":
    print(f"请不要直接运行此模块或 open calc，请在 main.py 中调用 calc 模块的 main 函数。")