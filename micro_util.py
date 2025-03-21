import os
import sys

def is_excluded_directory(path, exclude_dirs=None):
    """
    Проверяет, является ли путь исключенным каталогом.
    """
    if exclude_dirs is None:
        exclude_dirs = {".git", "__pycache__", ".idea", ".venv"}

    # Разделяем путь на части и проверяем каждую часть
    parts = path.split(os.sep)
    for part in parts:
        if part.startswith(".") or part in exclude_dirs:
            return True
    return False


def generate_directory_structure(path, prefix="", exclude_dirs=None, max_depth=2, current_depth=0):
    """
    Рекурсивно создает псевдографическую структуру каталога.
    Исключает указанные каталоги и файлы.
    Ограничивает глубину вложенности.
    """
    if exclude_dirs is None:
        exclude_dirs = {".git", "__pycache__", ".idea", ".venv"}

    result = ""
    try:
        # Сортируем элементы: сначала папки, потом файлы
        entries = sorted(os.listdir(path), key=lambda x: (not os.path.isdir(os.path.join(path, x)), x))
    except PermissionError:
        return result  # Пропускаем недоступные директории

    for i, entry in enumerate(entries):
        full_path = os.path.join(path, entry)
        is_last = i == len(entries) - 1

        # Пропускаем исключенные каталоги и скрытые файлы/каталоги
        if is_excluded_directory(full_path, exclude_dirs):
            continue

        if os.path.isdir(full_path):
            # Добавляем папку в структуру
            result += f"{prefix}{'└── ' if is_last else '├── '}{entry}/\n"
            # Рекурсивно обрабатываем подкаталоги, если глубина позволяет
            if current_depth < max_depth:
                result += generate_directory_structure(
                    full_path,
                    prefix + ("    " if is_last else "│   "),
                    exclude_dirs,
                    max_depth,
                    current_depth + 1
                )
        else:
            # Добавляем файл в структуру
            result += f"{prefix}{'└── ' if is_last else '├── '}{entry}\n"

    return result


def get_file_contents(path, extensions=(".txt", ".json", ".py"), max_size=40000):
    """
    Читает содержимое файлов с указанными расширениями.
    Выводит прогресс-бар на основе количества считанных файлов.
    Игнорирует файлы размером больше max_size байт.
    """
    result = []
    total_files = 0
    processed_files = 0

    # Подсчитываем общее количество подходящих файлов
    for root, _, files in os.walk(path):
        if is_excluded_directory(root):
            continue
        for file in files:
            if file.endswith(extensions):
                total_files += 1

    # Читаем содержимое файлов
    for root, _, files in os.walk(path):
        if is_excluded_directory(root):
            continue
        for file in files:
            if file.endswith(extensions):
                file_path = os.path.join(root, file)
                processed_files += 1
                progress = processed_files / total_files * 100
                print(f"\rСчитано файлов: {processed_files}/{total_files} [{'#' * int(progress // 5):<20}] {progress:.1f}%", end="")

                # Проверяем размер файла
                file_size = os.path.getsize(file_path)
                result.append(f"\n\n=== File: {file_path} ===\n")
                if file_size > max_size:
                    result.append(f"Файл слишком большой ({file_size} байт). Содержимое не считано.\n")
                    continue

                # Читаем содержимое файла
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        result.append(f.read())
                except Exception as e:
                    result.append(f"Error reading file: {e}\n")

    return "".join(result)


def main():
    # Текущий каталог
    current_dir = os.getcwd()

    # Генерация структуры каталога
    print("Создание структуры каталога...")
    structure = generate_directory_structure(current_dir)

    # Получение содержимого файлов
    print("\nЧтение содержимого файлов...")
    file_contents = get_file_contents(current_dir)

    # Запись результата в файл
    output_file = "directory_structure_and_contents.txt"
    if os.path.exists(output_file):
        os.remove(output_file)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("Directory Structure:\n")
        f.write(structure)
        f.write("\n\nFile Contents:\n")
        f.write(file_contents)

    print(f"\nСтруктура каталога и содержимое файлов записаны в {output_file}")


if __name__ == "__main__":
    main()

