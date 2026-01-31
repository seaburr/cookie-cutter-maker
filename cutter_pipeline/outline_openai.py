import base64
import os
from pathlib import Path
from openai import OpenAI

def generate_outline_png(prompt: str, out_path: str, size: str = "1024x1024") -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY env var")

    client = OpenAI()

    full_prompt = (
        "Create a very simple black and white coloring-book outline icon. "
        "Single closed outer contour only. No interior lines, no shading, no text. "
        "Centered, thick black stroke on white background. Subject: " + prompt
    )

    result = client.images.generate(
        model="gpt-image-1",
        prompt=full_prompt,
        size=size,
    )

    b64 = result.data[0].b64_json
    img_bytes = base64.b64decode(b64)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(img_bytes)
    return str(out)
