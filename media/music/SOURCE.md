# The music bed

`bed.mp3` is an instrumental generated for this video with **ACE-Step 1.5** (`ACE-Step/acestep-v15-xl-turbo`) on Vultr Serverless Inference's music endpoint (`POST /v1/music`), on 2026-11-09. No lyrics, no sampled material.

Request: caption *"Minimal ambient underscore, soft felt piano, warm analog pads, light brushed percussion far back, steady and unobtrusive, calm documentary background music, clean and polished, no vocals"*, 180 seconds, 84 bpm, C major, 4/4, seed 23, quality turbo. Three seeds were rendered (11, 23, 47); 23 was kept because its loudness varied least across the track (20-second windows within 0.8 dB until the final fade), measured with ffmpeg's volumedetect. Re-encoded here at 128 kbps.

`media/assemble.py` lays it under the narration at a low level, faded in and out, and ducked further whenever the voice speaks, so no word is covered. The voice-only cut is kept beside the finished video.
