# getroot.py - 获取 ROOT 权限的应用程序
# 2026-09-24 安全加固：此前无任何确认直接提权，现要求二次确认，
# 且操作会被记入 etc/audit.log（见 apps/api.py）。
import api

# 主函数
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
        if api.set_rootstate(True): # 设置root状态为真
            api.api_ok("已获取 ROOT 权限！（本次操作已审计）")
        else:
            api.api_error("获取 ROOT 权限失败！")
    print("操作成功完成。")

# 最重要的
if __name__ == "__exec__":
    try:
        main()
    except Exception as e:
        print(f"程序运行出错：{str(e)}")
else:
    raise SystemError("请不要直接运行本程序")