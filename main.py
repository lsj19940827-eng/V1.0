# -*- coding: utf-8 -*-
"""
渠系水力计算综合系统 V1.0

统一入口 —— 启动 PySide6 主程序
（集成：calc_渠系计算算法内核 + 倒虹吸水力计算 + 水面线推求）
"""


def main():
    """程序主入口"""
    import sys
    import os

    # ============================================================
    # 0. 确保项目根目录在搜索路径中
    # ============================================================
    _root = os.path.dirname(os.path.abspath(__file__))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from app_渠系计算前端.bootstrap import run as bootstrap_run

    try:
        exit_code = bootstrap_run()
        if "--webengine-probe-child" in sys.argv:
            # 探测进程是一次性的，避免 Qt WebEngine 清理阶段拖住父进程启动。
            for stream in (sys.stdout, sys.stderr):
                try:
                    stream.flush()
                except Exception:
                    pass
            os._exit(int(exit_code))
        sys.exit(exit_code)
    except Exception as e:
        import traceback
        try:
            print(f"程序启动失败: {e}")
            traceback.print_exc()
        except Exception:
            pass
        if not getattr(sys, 'frozen', False):
            input("按回车键退出...")
        sys.exit(1)


if __name__ == "__main__":
    main()
