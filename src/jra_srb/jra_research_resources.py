"""概要: 研究プロセスの実メモリ使用量を監視する。
作成日: 2026-10-15
入力: 設定されたプロセスメモリ上限bytes。
出力: 使用量bytes、超過時ResearchError。
実行例: uv run pytest -q tests/test_jra_research_reader.py
注意事項: WindowsではPrivateUsage、他OSでは最大RSSを保守的に使用する。
"""

from __future__ import annotations

import ctypes
import os
import sys

from .jra_research_contracts import ResearchError


def memory_bytes() -> int:
    """現在プロセスのメモリbytesをOSから取得する。"""
    if os.name == "nt":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            """PROCESS_MEMORY_COUNTERS_EXのWindows ABIを表す。"""
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ResearchError("memory_measurement_failed")
        return counters.PrivateUsage
    import resource
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(usage if sys.platform == "darwin" else usage * 1024)


def check_memory(maximum: int) -> int:
    """実使用量を上限と照合し、超過時は処理を停止する。"""
    used = memory_bytes()
    if used > maximum:
        raise ResearchError("memory_limit", 4, used_bytes=used, maximum_bytes=maximum)
    return used
