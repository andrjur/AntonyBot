import os
import logging
import re
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

def get_lesson_text(lesson_number: int, course_id: str) -> Optional[str]:
    """Gets lesson text content from various possible file formats."""
    possible_paths = [
        f"courses/{course_id}/lesson{lesson_number}.md",
        f"courses/{course_id}/lesson{lesson_number}.html",
        f"courses/{course_id}/lesson{lesson_number}.txt"
    ]
    
    for path in possible_paths:
        try:
            with open(path, 'r', encoding='utf-8') as file:
                return file.read()
        except FileNotFoundError:
            continue
        except Exception as e:
            logger.error(f"Error reading lesson file {path}: {e}")
    
    return None

def get_lesson_files(user_id: int, lesson_number: int, course_id: str) -> List[Dict]:
    """Gets lesson files with their delays."""
    files = []
    lesson_dir = f"courses/{course_id}/lesson{lesson_number}"
    delay_pattern = re.compile(r"_(\d+)(hour|min|m|h)(?:\.|$)")
    
    try:
        if not os.path.exists(lesson_dir):
            return files

        for filename in os.listdir(lesson_dir):
            file_path = os.path.join(lesson_dir, filename)
            if not os.path.isfile(file_path):
                continue

            # Calculate delay from filename
            delay = 0
            match = delay_pattern.search(filename)
            if match:
                value, unit = match.groups()
                value = int(value)
                if unit in ['min', 'm']:
                    delay = value * 60
                elif unit in ['hour', 'h']:
                    delay = value * 3600

            # Determine file type
            file_type = "document"
            if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                file_type = "photo"
            elif filename.lower().endswith(('.mp3', '.wav', '.ogg')):
                file_type = "audio"
            elif filename.lower().endswith(('.mp4', '.avi', '.mov')):
                file_type = "video"

            files.append({
                "path": file_path,
                "type": file_type,
                "delay": delay,
                "name": filename
            })

        # Sort files by delay
        return sorted(files, key=lambda x: x['delay'])

    except Exception as e:
        logger.error(f"Error getting lesson files for lesson {lesson_number}: {e}")
        return []