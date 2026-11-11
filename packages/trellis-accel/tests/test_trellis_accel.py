"""trellis-accel: one device choice and the start-up report (docs/hardware-acceleration-proposal.md).

PyTorch is replaced by a fake in each test, so the choice is tested for NVIDIA, AMD, Apple and CPU-only machines on
any machine; the OS probe is pointed at fake /sys and /proc trees."""
from __future__ import annotations

import types

import pytest
import trellis_accel as ta


def _torch(*, cuda=False, mps=False, hip=None, cuda_build="13.0", name="Fake GPU"):
    t = types.SimpleNamespace()
    t.__version__ = "2.13.0" + ("+rocm7.2" if hip else "")
    t.version = types.SimpleNamespace(cuda=None if hip else cuda_build, hip=hip)
    t.cuda = types.SimpleNamespace(is_available=lambda: cuda, get_device_name=lambda i=0: name)
    t.backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: mps))
    return t


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    for k in (ta.DEVICE_ENV, ta.ALLOW_MPS_ENV):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(ta, "KFD_NODES", tmp_path / "no-kfd")
    monkeypatch.setattr(ta, "NVIDIA_PROC", tmp_path / "no-nvidia")
    monkeypatch.setattr(ta.shutil, "which", lambda name: None)
    ta.report_once.cache_clear()


def _use(monkeypatch, torch):
    monkeypatch.setattr(ta, "_torch", lambda: torch)


# ── the choice ──

def test_an_amd_gpu_is_chosen_and_named(monkeypatch):
    _use(monkeypatch, _torch(cuda=True, hip="7.2.53211", name="AMD Radeon 890M Graphics"))
    c = ta.pick_device()
    assert c.device == "cuda" and c.gpu == "AMD Radeon 890M Graphics"
    assert "AMD (ROCm 7.2.53211)" in c.reason


def test_an_nvidia_gpu_is_chosen_before_apples(monkeypatch):
    _use(monkeypatch, _torch(cuda=True, mps=True, name="RTX"))
    c = ta.pick_device()
    assert c.device == "cuda" and "NVIDIA (CUDA)" in c.reason


def test_apples_gpu_when_there_is_no_other(monkeypatch):
    _use(monkeypatch, _torch(mps=True))
    assert ta.pick_device(purpose="embeddings").device == "mps"


def test_cpu_when_there_is_no_gpu_or_no_torch(monkeypatch):
    _use(monkeypatch, _torch())
    assert ta.pick_device().device == "cpu"
    _use(monkeypatch, None)
    c = ta.pick_device()
    assert c.device == "cpu" and c.reason == "PyTorch is not installed"


def test_docling_stays_off_apples_gpu_with_an_old_transformers(monkeypatch):
    _use(monkeypatch, _torch(mps=True))
    monkeypatch.setattr(ta.metadata, "version", lambda n: "5.10.1")
    c = ta.pick_device(purpose="docling")
    assert c.device == "cpu" and "transformers 5.10.1 predates 5.22.2" in c.reason
    assert ta.pick_device(purpose="embeddings").device == "mps"     # the rule is Docling's only


def test_docling_uses_apples_gpu_with_a_fixed_transformers(monkeypatch):
    _use(monkeypatch, _torch(mps=True))
    monkeypatch.setattr(ta.metadata, "version", lambda n: "5.22.2")
    assert ta.pick_device(purpose="docling").device == "mps"


@pytest.mark.parametrize(("value", "device"), [("0", "cpu"), ("no", "cpu"), ("1", "mps"), ("true", "mps")])
def test_the_docling_mps_switch_still_decides(monkeypatch, value, device):
    _use(monkeypatch, _torch(mps=True))
    monkeypatch.setattr(ta.metadata, "version", lambda n: "5.10.1" if device == "mps" else "5.22.2")
    monkeypatch.setenv(ta.ALLOW_MPS_ENV, value)
    assert ta.pick_device(purpose="docling").device == device


# ── overrides ──

def test_trellis_device_overrides_auto(monkeypatch):
    _use(monkeypatch, _torch(cuda=True))
    monkeypatch.setenv(ta.DEVICE_ENV, "cpu")
    c = ta.pick_device()
    assert c.device == "cpu" and c.reason == "TRELLIS_DEVICE asks for cpu"


def test_an_apps_own_setting_wins_over_trellis_device(monkeypatch):
    _use(monkeypatch, _torch(cuda=True))
    monkeypatch.setenv(ta.DEVICE_ENV, "cuda")
    assert ta.pick_device("cpu", purpose="embeddings").reason == "this app's setting asks for cpu"


def test_rocm_is_a_name_for_cuda(monkeypatch):
    _use(monkeypatch, _torch(cuda=True, hip="7.2"))
    monkeypatch.setenv(ta.DEVICE_ENV, "rocm")
    assert ta.pick_device().device == "cuda"


def test_a_device_this_torch_cannot_use_is_refused_with_a_sentence(monkeypatch):
    _use(monkeypatch, _torch())
    with pytest.raises(ta.DeviceUnavailable, match="asks for cuda, which PyTorch 2.13.0 cannot use"):
        ta.pick_device("cuda")
    monkeypatch.setenv(ta.DEVICE_ENV, "tpu")
    with pytest.raises(ta.DeviceUnavailable, match="it can be cpu, cuda, rocm, mps or auto"):
        ta.pick_device()


def test_asking_for_mps_where_docling_must_not_use_it_is_refused(monkeypatch):
    _use(monkeypatch, _torch(mps=True))
    monkeypatch.setattr(ta.metadata, "version", lambda n: "5.10.1")
    with pytest.raises(ta.DeviceUnavailable, match="asks for mps, but transformers 5.10.1"):
        ta.pick_device("mps", purpose="docling")


# ── the machine and the report ──

def _kfd(tmp_path, *versions):
    for i, v in enumerate(versions):
        node = tmp_path / "kfd" / str(i)
        node.mkdir(parents=True)
        (node / "properties").write_text(f"cpu_cores_count 0\nsimd_count 32\ngfx_target_version {v}\n")
    return tmp_path / "kfd"


def test_the_amd_gpu_is_read_from_kfd_as_its_gfx_name(monkeypatch, tmp_path):
    monkeypatch.setattr(ta, "KFD_NODES", _kfd(tmp_path, 0, 110500, 90010))   # node 0 is the CPU
    assert ta.probe_machine()["amd"] == ["gfx1150", "gfx90a"]


def test_an_nvidia_gpu_is_read_from_its_driver(monkeypatch, tmp_path):
    gpu = tmp_path / "nv" / "0000:01:00.0"
    gpu.mkdir(parents=True)
    (gpu / "information").write_text("Model: \t\t NVIDIA GeForce RTX 4090\nIRQ: 1\n")
    monkeypatch.setattr(ta, "NVIDIA_PROC", tmp_path / "nv")
    assert ta.probe_machine()["nvidia"] == ["NVIDIA GeForce RTX 4090"]


def test_hedwig_today_an_amd_gpu_and_the_cuda_build(monkeypatch, tmp_path):
    """hedwig on 2026-11-11: a Radeon 890M, and the lock's CUDA PyTorch, which cannot use it."""
    monkeypatch.setattr(ta, "KFD_NODES", _kfd(tmp_path, 0, 110500))
    _use(monkeypatch, _torch(cuda=False))
    r = ta.hardware_report()
    assert r["choice"]["device"] == "cpu"
    texts = [f["text"] for f in r["findings"]]
    assert any(t.startswith("AMD GPU gfx1150 found, but this environment has the CUDA PyTorch; a ROCm build")
               for t in texts)
    assert any("CUDA build (about 4.5 GB of NVIDIA libraries) and the machine has no NVIDIA GPU" in t for t in texts)
    line = ta.startup_line(r)
    assert line.startswith("hardware: PyTorch 2.13.0 (cuda); device cpu: no GPU this PyTorch can use; WARN: AMD GPU")


def test_hedwig_with_rocm_says_nothing_but_what_it_uses(monkeypatch, tmp_path):
    monkeypatch.setattr(ta, "KFD_NODES", _kfd(tmp_path, 0, 110500))
    _use(monkeypatch, _torch(cuda=True, hip="7.2.53211", name="AMD Radeon 890M Graphics"))
    r = ta.hardware_report()
    assert r["findings"] == [] and r["choice"]["device"] == "cuda" and r["build"]["kind"] == "rocm"


def test_a_matching_gpu_that_pytorch_cannot_open_is_a_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(ta, "KFD_NODES", _kfd(tmp_path, 110500))
    _use(monkeypatch, _torch(cuda=False, hip="7.2"))
    assert any("cannot use the GPU (driver, or permission" in f["text"] for f in ta.hardware_report()["findings"])


def test_a_refused_override_is_a_finding_not_a_crash(monkeypatch):
    _use(monkeypatch, _torch())
    monkeypatch.setenv(ta.DEVICE_ENV, "cuda")
    r = ta.hardware_report()
    assert r["choice"]["device"] is None and r["findings"][-1]["level"] == "warn"


def test_the_report_is_made_once(monkeypatch):
    calls = []
    monkeypatch.setattr(ta, "hardware_report", lambda: calls.append(1) or {"x": 1})
    assert ta.report_once() is ta.report_once() and calls == [1]
