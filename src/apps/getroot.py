'''
 *
 *      getroot.py
 *      App that requests temporary ROOT at runtime.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import api

# Main entry point
def main():
    if api.get_rootstate() or api.get_rootstate_bcfg():
        api.api_warn("当前已处于 ROOT 权限状态，无需重复获取。")
    else:
        api.api_warn("ROOT 拥有系统全部权限，请确认这是你本人的操作。")
        if not api.api_confirm("确认获取 ROOT 权限？"):
            print("操作已取消。")
            return
        api.api_info("准备获取 ROOT 权限...")
        if not api.authorize_root():
            api.api_error("ROOT 授权被拒绝")
            return
        if api.set_rootstate(True): # set the root state to true
            api.api_ok("已获取 ROOT 权限！（本次操作已审计）")
        else:
            api.api_error("获取 ROOT 权限失败！")
    print("操作成功完成。")

# The most important part
if __name__ == "__exec__":
    try:
        main()
    except Exception as e:
        print(f"程序运行出错：{str(e)}")
else:
    raise SystemError("请不要直接运行本程序")