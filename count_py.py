import os
output_filename = "combined.txt"
exclude_dirs = {".git", "__pycache__", "venv", ".idea","dist"}

def append_to_file():
    with open(output_filename, "w", encoding="utf-8") as out_file:
        for root, dirs, files in os.walk("."):
            # 排除特定文件夹
            dirs[:] = [d for d in dirs if d not in exclude_dirs]

            for file in sorted(files):
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path)

                    try:
                        with open(file_path, "r", encoding="utf-8") as in_file:
                            content = in_file.read()
                        print(rel_path)
                        out_file.write(f"== {rel_path} ==\n")
                        out_file.write(f"{content}\n\n")

                    except Exception as e:
                        print(f"处理 {rel_path} 时发生错误: {str(e)}")

    print(f"文件已合并保存至 {output_filename}")

def count_line():
    line = 0
    for root, dirs, files in os.walk("."):
        # 排除特定文件夹
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        for file in sorted(files):
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path)

                try:
                    with open(file_path, "r", encoding="utf-8") as in_file:
                        content = in_file.readlines()
                    line += len(content)
                    print(f"{line:<6}  {rel_path}")

                except Exception as e:
                    print(f"处理 {rel_path} 时发生错误: {str(e)}")

    print(f"所有代码文件总行数为 {line}")

if __name__ == "__main__":
    count_line()