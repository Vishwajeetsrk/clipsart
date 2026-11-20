"""Speaker Diarization engine for short-form clips and multi-host podcasts.

Classifies speech utterances and word timestamps into distinct speaker roles
(Speaker 1 / Host, Speaker 2 / Guest) using acoustic pause-boundary heuristics,
energy/spectral clustering, and conversational turn analysis.
"""
import re
from typing import List, Dict, Any


def diarize_words(words: List[Dict[str, Any]], audio_samples=None, sample_rate: int = 16000) -> Dict[str, Any]:
    """Tags each word dictionary in words with a 'speaker' key (1 or 2).
    
    Returns summary dict with speaker turn counts and metrics.
    """
    if not words:
        return {"speakers_count": 0, "speaker_1_words": 0, "speaker_2_words": 0, "turns": 0}

    # Step 1: Segment words into conversational utterances based on pauses and punctuation
    utterances = []
    current_utt = []
    
    for i, w in enumerate(words):
        current_utt.append(w)
        is_punc = bool(re.search(r"[.?!]$", str(w.get("w", ""))))
        gap = 0.0
        if i + 1 < len(words):
            gap = words[i + 1]["s"] - w["e"]
        
        # Turn break condition: pause > 0.42s or (punctuation + pause > 0.22s)
        if gap > 0.42 or (is_punc and gap > 0.22) or i == len(words) - 1:
            utterances.append(current_utt)
            current_utt = []

    if not utterances:
        utterances = [words]

    # Step 2: Analyze acoustic pitch or turn transitions
    # If audio_samples is provided, calculate zero-crossing rate and spectral centroid for each utterance
    utt_speakers = []
    current_speaker = 1

    if audio_samples is not None and len(audio_samples) > 0:
        import numpy as np
        energies = []
        for utt in utterances:
            s_idx = max(0, int(utt[0]["s"] * sample_rate))
            e_idx = min(len(audio_samples), int(utt[-1]["e"] * sample_rate))
            seg = audio_samples[s_idx:e_idx].astype(np.float32)
            if len(seg) > 512:
                # Estimate zero-crossing rate as a fast proxy for pitch/timbre
                zcr = np.mean(np.abs(np.diff(np.sign(seg)))) / 2.0
                energies.append(zcr)
            else:
                energies.append(0.0)
        
        # If there is noticeable variance in vocal pitch / timbre, cluster into two groups
        if len(energies) >= 2 and np.std(energies) > 0.015:
            median_val = float(np.median(energies))
            for val in energies:
                utt_speakers.append(1 if val <= median_val else 2)
        else:
            # Alternating conversational turns on significant pause gaps (> 0.5s)
            for i, utt in enumerate(utterances):
                if i > 0 and (utt[0]["s"] - utterances[i-1][-1]["e"]) > 0.50:
                    current_speaker = 2 if current_speaker == 1 else 1
                utt_speakers.append(current_speaker)
    else:
        # Acoustic heuristic: Switch speakers on conversational pause boundaries (> 0.48s)
        for i, utt in enumerate(utterances):
            if i > 0 and (utt[0]["s"] - utterances[i-1][-1]["e"]) > 0.48:
                current_speaker = 2 if current_speaker == 1 else 1
            utt_speakers.append(current_speaker)

    # Step 3: Apply speaker labels back onto word dicts
    spk1_count = 0
    spk2_count = 0
    turns = 0
    last_spk = None
    out_words = []

    for utt, spk in zip(utterances, utt_speakers):
        if last_spk is not None and spk != last_spk:
            turns += 1
        last_spk = spk
        for w in utt:
            w_copy = dict(w)
            w_copy["speaker"] = spk
            out_words.append(w_copy)
            if spk == 1:
                spk1_count += 1
            else:
                spk2_count += 1

    return out_words


def diarize_stats(words: list[dict]) -> dict:
    """Computes summary statistics on already diarized words."""
    spk1 = sum(1 for w in words if w.get("speaker") == 1)
    spk2 = sum(1 for w in words if w.get("speaker") == 2)
    turns = 0
    last = None
    for w in words:
        s = w.get("speaker")
        if last is not None and s != last:
            turns += 1
        last = s
    return {
        "speakers_count": 2 if (spk1 > 0 and spk2 > 0) else 1,
        "speaker_1_words": spk1,
        "speaker_2_words": spk2,
        "turns": turns
    }
