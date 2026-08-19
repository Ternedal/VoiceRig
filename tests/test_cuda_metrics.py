from __future__ import annotations

import sys
from types import SimpleNamespace

import voicerig.runtime as runtime


def test_cuda_memory_stats_reports_current_and_peak_values(monkeypatch):
    gib = 1024 ** 3

    class FakeCuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def memory_allocated():
            return int(2.25 * gib)

        @staticmethod
        def memory_reserved():
            return int(3.5 * gib)

        @staticmethod
        def max_memory_allocated():
            return int(8.125 * gib)

        @staticmethod
        def max_memory_reserved():
            return int(9.0 * gib)

        @staticmethod
        def reset_peak_memory_stats():
            FakeCuda.reset_called = True

    FakeCuda.reset_called = False
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=FakeCuda))

    assert runtime.reset_cuda_peaks() is True
    assert FakeCuda.reset_called is True
    assert runtime.cuda_memory_stats() == {
        "available": True,
        "allocated_gb": 2.25,
        "reserved_gb": 3.5,
        "peak_allocated_gb": 8.125,
        "peak_reserved_gb": 9.0,
    }


def test_cuda_memory_stats_is_safe_without_cuda(monkeypatch):
    fake = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    monkeypatch.setitem(sys.modules, "torch", fake)

    assert runtime.reset_cuda_peaks() is False
    assert runtime.cuda_memory_stats()["available"] is False
