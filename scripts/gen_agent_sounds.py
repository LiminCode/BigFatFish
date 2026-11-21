# -*- coding: utf-8 -*-
"""生成 Agent 内置音效 WAV 文件（start.wav, done.wav, error.wav）。

使用标准库 wave + math 合成，采样率 22050Hz, 16bit, 单声道，峰值控制在 0.5 防止爆音。
- start: 上扬双音（约 0.25s）
- done: 悦耳上扬三音（约 0.4s）
- error: 下行低音（约 0.3s）
- attention: 两声短叮（约 0.22s，2026-11-21 起「等批准」的默认音）
- chime / bell / pop / trill: 备选音色，给四个时刻随意搭配（配置里写 ``builtin:agent-<名字>``）

文件名和 id 的对应表在 ``pet/click_sound.py`` 的 ``BUILTIN_AGENT_SOUNDS``；两边要一致（``tests/test_settings_and_resources.py`` 守着）。
频率为 0 的一段是静音（正弦恒为 0），用来在两声之间留空。
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 22050


def _generate_tone_samples(
    frequencies: list[float],
    durations: list[float],
    sample_rate: int = SAMPLE_RATE,
    peak_amplitude: float = 0.5,
    attack: float = 0.1,
    release: float = 0.2,
) -> list[int]:
    """生成包含多段音调的 16-bit PCM 采样序列，带有平滑淡入淡出（Envelope）。

    ``attack`` / ``release`` 是每一段里淡入、淡出各占的比例（默认 10% / 20%）；钟声那种要长尾巴的把 ``release`` 调大。"""
    all_samples: list[int] = []
    max_val = 32767 * peak_amplitude

    for freq, dur in zip(frequencies, durations):
        num_samples = int(sample_rate * dur)
        attack_len = int(num_samples * attack)
        decay_len = int(num_samples * release)
        sustain_len = num_samples - attack_len - decay_len

        for i in range(num_samples):
            # 包络计算
            if i < attack_len:
                env = i / attack_len
            elif i < attack_len + sustain_len:
                env = 1.0
            else:
                release_idx = i - (attack_len + sustain_len)
                env = 1.0 - (release_idx / max(1, decay_len))

            # 正弦波
            t = i / sample_rate
            val = math.sin(2.0 * math.pi * freq * t) * env * max_val
            all_samples.append(int(val))

    return all_samples


def _write_wav(output_path: Path, samples: list[int], sample_rate: int = SAMPLE_RATE) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(1)  # 单声道
        wf.setsampwidth(2)  # 16-bit = 2 bytes
        wf.setframerate(sample_rate)
        # 打包成 16-bit 有符号整数 (<h)
        raw_data = struct.pack(f"<{len(samples)}h", *samples)
        wf.writeframes(raw_data)


def generate_agent_sounds(target_dir: Path | None = None) -> dict[str, Path]:
    if target_dir is None:
        target_dir = Path(__file__).resolve().parents[1] / "assets" / "sounds" / "agent"

    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. start: 上扬双音（约 0.25s: 0.12s + 0.13s，440Hz -> 659.25Hz / A4 -> E5）
    start_samples = _generate_tone_samples([440.0, 659.25], [0.12, 0.13], peak_amplitude=0.5)
    start_path = target_dir / "start.wav"
    _write_wav(start_path, start_samples)

    # 2. done: 悦耳上扬三音（约 0.4s: 0.12s + 0.12s + 0.16s，523.25Hz -> 659.25Hz -> 783.99Hz / C5 -> E5 -> G5）
    done_samples = _generate_tone_samples([523.25, 659.25, 783.99], [0.12, 0.12, 0.16], peak_amplitude=0.5)
    done_path = target_dir / "done.wav"
    _write_wav(done_path, done_samples)

    # 3. error: 下行低音（约 0.3s: 0.15s + 0.15s，329.63Hz -> 220.0Hz / E4 -> A3）
    error_samples = _generate_tone_samples([329.63, 220.0], [0.15, 0.15], peak_amplitude=0.5)
    error_path = target_dir / "error.wav"
    _write_wav(error_path, error_samples)

    # 4. attention: 两声短叮（880Hz / A5 ×2，中间 0.06s 静音）——「停下来等你批准」
    attention_samples = _generate_tone_samples([880.0, 0.0, 880.0], [0.08, 0.06, 0.08], peak_amplitude=0.5)
    attention_path = target_dir / "attention.wav"
    _write_wav(attention_path, attention_samples)

    # 5. 备选音色
    extras = {
        # chime: 风铃，下行两音（C6 -> G5）
        "chime": _generate_tone_samples([1046.50, 783.99], [0.14, 0.20], peak_amplitude=0.45),
        # bell: 一声钟，起得快、尾巴长（C6，0.55s，70% 都在衰减）
        "bell": _generate_tone_samples([1046.50], [0.55], peak_amplitude=0.5, attack=0.02, release=0.7),
        # pop: 气泡，很短的上行两音（G4 -> C5）
        "pop": _generate_tone_samples([392.00, 523.25], [0.06, 0.06], peak_amplitude=0.5),
        # trill: 颤音，E5 / G5 快速交替四下
        "trill": _generate_tone_samples([659.25, 783.99, 659.25, 783.99], [0.06, 0.06, 0.06, 0.06], peak_amplitude=0.45),
    }
    extra_paths = {}
    for name, samples in extras.items():
        extra_paths[name] = target_dir / f"{name}.wav"
        _write_wav(extra_paths[name], samples)

    return {
        "start": start_path,
        "done": done_path,
        "error": error_path,
        "attention": attention_path,
        **extra_paths,
    }


if __name__ == "__main__":
    sounds = generate_agent_sounds()
    print("已生成 Agent 内置音效：")
    for name, path in sounds.items():
        print(f" - {name}: {path} ({path.stat().st_size} bytes)")
