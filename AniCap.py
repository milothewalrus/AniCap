import os
import json
import numpy as np
import whisper
import librosa
from moviepy.editor import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip

# Fix for ImageMagick error:
if os.getenv("IMAGEMAGICK_BINARY") == "unset":
    os.environ["IMAGEMAGICK_BINARY"] = "convert"  # Ensure that "convert" is in your PATH.

def extract_audio(video_path, audio_path, fps=16000):
    """Extract audio from a video file and save as a WAV file."""
    clip = VideoFileClip(video_path)
    clip.audio.write_audiofile(audio_path, fps=fps)
    clip.close()

def run_whisper(audio_path, model_size="base"):
    """Run Whisper transcription and simulate word-level timing."""
    model = whisper.load_model(model_size)
    result = model.transcribe(audio_path)
    words = []
    for seg in result.get("segments", []):
        seg_start = seg["start"]
        seg_end = seg["end"]
        seg_text = seg["text"].strip()
        seg_words = seg_text.split()
        if not seg_words:
            continue
        duration = seg_end - seg_start
        word_duration = duration / len(seg_words)
        for i, word in enumerate(seg_words):
            word_start = seg_start + i * word_duration
            word_end = word_start + word_duration
            words.append({
                "word": word,
                "start": word_start,
                "end": word_end,
                "duration": word_duration
            })
    return words

def analyze_emphasis(audio_data, sr, word_start, word_end, global_rms, factor=1.2):
    """Determine if the word segment is emphasized by comparing its RMS energy."""
    start_sample = int(word_start * sr)
    end_sample = int(word_end * sr)
    word_samples = audio_data[start_sample:end_sample]
    if len(word_samples) == 0:
        return False
    word_rms = np.sqrt(np.mean(word_samples**2))
    return word_rms > factor * global_rms

def make_animated_textclip(text, start_time, duration, emphasis, video_width, video_height):
    """
    Create a TextClip that stays centered.
    If 'emphasis' is True, a slight horizontal bounce is applied.
    """
    txt_clip = TextClip(text, fontsize=40, color='white', font="Arial-Bold",
                        stroke_color="black", stroke_width=2)
    txt_clip = txt_clip.set_duration(duration).set_start(start_time)
    txt_w, txt_h = txt_clip.size

    def pos_func(t):
        # Always center the text clip
        x = (video_width - txt_w) / 2
        y = (video_height - txt_h) / 2
        if emphasis:
            x += 10 * np.sin(2 * np.pi * t)
        return (x, y)
    
    txt_clip = txt_clip.set_position(pos_func)
    return txt_clip

def main():
    # File paths.
    input_video = "input_video.mp4"  # Ensure this file exists.
    output_video = "output_video.mp4"
    temp_audio = "temp_audio.wav"
    transcript_file = "transcript.json"

    # Reuse existing audio if available.
    if os.path.exists(temp_audio):
        reuse_audio = input("Audio file '{}' exists. Reuse it? (y/n): ".format(temp_audio))
        if reuse_audio.strip().lower() != 'y':
            extract_audio(input_video, temp_audio, fps=16000)
    else:
        extract_audio(input_video, temp_audio, fps=16000)

    # Reuse existing transcript if available.
    if os.path.exists(transcript_file):
        reuse_transcript = input("Transcript file '{}' exists. Reuse it? (y/n): ".format(transcript_file))
        if reuse_transcript.strip().lower() == 'y':
            with open(transcript_file, 'r') as f:
                words = json.load(f)
        else:
            words = run_whisper(temp_audio, model_size="base")
            with open(transcript_file, 'w') as f:
                json.dump(words, f)
    else:
        words = run_whisper(temp_audio, model_size="base")
        with open(transcript_file, 'w') as f:
            json.dump(words, f)

    print(f"Detected {len(words)} words.")

    print("Loading audio for prosody analysis...")
    audio_data, sr = librosa.load(temp_audio, sr=16000)
    global_rms = np.sqrt(np.mean(audio_data**2))
    print(f"Global RMS energy: {global_rms:.5f}")

    print("Loading video for compositing...")
    video_clip = VideoFileClip(input_video)
    video_width, video_height = video_clip.size

    text_clips = []
    for idx, w in enumerate(words):
        base_duration = w["duration"]
        extended_duration = base_duration

        # If this is the last word overall, extend its duration to the end of the video.
        if idx == len(words) - 1:
            extended_duration = video_clip.duration - w["start"]
        else:
            # If the word ends with punctuation indicating sentence end,
            # and the gap to the next word is 2 seconds or more, extend the duration.
            if w["word"] and w["word"][-1] in ".!?":
                gap = words[idx+1]["start"] - w["end"]
                if gap >= 2:
                    extended_duration = base_duration + gap

        emphasis = analyze_emphasis(audio_data, sr, w["start"], w["end"], global_rms)
        txt_clip = make_animated_textclip(
            text=w["word"],
            start_time=w["start"],
            duration=extended_duration,
            emphasis=emphasis,
            video_width=video_width,
            video_height=video_height
        )
        text_clips.append(txt_clip)

    print("Compositing video and animated captions...")
    composite = CompositeVideoClip([video_clip, *text_clips])
    composite.duration = video_clip.duration

    print("Writing output video (this may take a while)...")
    composite.write_videofile(output_video, codec="libx264", audio_codec="aac")

    # Cleanup temporary audio file.
    if os.path.exists(temp_audio):
        os.remove(temp_audio)
    print("Done! Output saved as", output_video)

if __name__ == "__main__":
    main()
