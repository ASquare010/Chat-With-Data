import os
import sqlite3
import pandas as pd
import io, base64
import PIL.Image as PIL
from pathlib import Path


def encode_image_to_base64(img: PIL.Image) -> str:
    """
    Encode a PIL.Image object as a base64 string and return it as a data URI.
    Supports multiple formats (JPEG, PNG, WEBP, etc.).
    """
    image_format = img.format if img.format else "JPEG"
    mime_map = {
        "JPEG": "image/jpeg",
        "JPG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
    }
    mime_type = mime_map.get(image_format.upper(), "image/jpeg")

    # Ensure the image is in a proper mode for JPEG conversion if needed.
    if image_format.upper() in ["JPEG", "JPG"] and img.mode != "RGB":
        img = img.convert("RGB")

    buffered = io.BytesIO()
    img.save(buffered, format=image_format)
    base64_str = base64.b64encode(buffered.getvalue()).decode("utf-8")

    return f"data:{mime_type};base64,{base64_str}"


def generate_multimodel_content(text: str, images: list) -> list:
    """Create a content list with a text message and image URLs encoded in base64 along with an image name."""
    content = [{"type": "text", "text": text}]

    if not images:
        return content

    for i, img in enumerate(images):
        image_name = img.filename if hasattr(img, "filename") else f"Image{i+1}"
        image_content = {
            "type": "image_url",
            "image_url": {"url": encode_image_to_base64(img), "name": image_name},
        }
        content.append(image_content)

    return content


def csv_to_sqlite(csv_file="data/data.csv", db_name="data/data.db", table_name="data"):
    df = pd.read_csv(csv_file)
    conn = sqlite3.connect(db_name)
    df.to_sql(table_name, conn, if_exists="replace", index=False)
    conn.close()


def get_column_names(table_name="data", db_name="data/data.db"):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()

    cursor.execute(f"PRAGMA table_info({table_name});")
    columns = [row[1] for row in cursor.fetchall()]

    conn.close()
    return columns


def run_sql_query(query, db_name="data/data.db"):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute(query)
    result = cursor.fetchall()
    conn.close()
    return result


def load_system_message(dir_path: str = "agent_prompt") -> dict:
    messages = {}

    for file_name in os.listdir(dir_path):
        if file_name.endswith(".md"):
            file_path = os.path.join(dir_path, file_name)

            with open(file_path, "r", encoding="utf-8") as file:
                content = file.read()
                messages[os.path.splitext(file_name)[0]] = content

    return messages


def save_graph_image(graph, filename: str = "graph_structure.png"):
    """Save the LangGraph structure image to disk (no Tkinter, no GUI)."""
    try:
        png_data = graph.get_graph(xray=True).draw_mermaid_png()

        output_dir = Path("outputs")
        output_dir.mkdir(exist_ok=True)

        filepath = output_dir / filename
        with open(filepath, "wb") as f:
            f.write(png_data)

        print(f"✅ Saved graph visualization to: {filepath.resolve()}")
    except Exception as e:
        print(f"❌ Failed to save graph image: {e}")
        try:
            print(graph.get_graph(xray=True).draw_mermaid())
        except Exception:
            pass
