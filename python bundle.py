import os

# जिन फोल्डर्स या फाइल्स को नजरअंदाज करना है
EXCLUDE_DIRS = {'.git', '__pycache__', 'venv', '.venv', 'node_modules', '.idea', '.vscode'}
EXCLUDE_EXTS = {'.pyc', '.png', '.jpg', '.jpeg', '.zip', '.tar', '.gz', '.db', '.sqlite3'}

OUTPUT_FILE = "project_codebase.txt"

def bundle_project(root_dir="."):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as outfile:
        # 1. पहले प्रोजेक्ट का फाइल स्ट्रक्चर लिखें
        outfile.write("=== PROJECT STRUCTURE ===\n")
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            level = root.replace(root_dir, '').count(os.sep)
            indent = ' ' * 4 * level
            outfile.write(f"{indent}{os.path.basename(root)}/\n")
            sub_indent = ' ' * 4 * (level + 1)
            for f in files:
                if not any(f.endswith(ext) for ext in EXCLUDE_EXTS):
                    outfile.write(f"{sub_indent}{f}\n")
        
        outfile.write("\n" + "="*40 + "\n\n")

        # 2. अब हर फाइल का पाथ और उसका कोड लिखें
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for file in files:
                if any(file.endswith(ext) for ext in EXCLUDE_EXTS) or file == OUTPUT_FILE:
                    continue
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, root_dir)
                
                outfile.write(f"--- START FILE: {rel_path} ---\n")
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as infile:
                        outfile.write(infile.read())
                except Exception as e:
                    outfile.write(f"Error reading file: {e}")
                outfile.write(f"\n--- END FILE: {rel_path} ---\n\n")

    print(f"प्रोजेक्ट सफलतापूर्वक बंडल हुआ: {OUTPUT_FILE}")

if __name__ == "__main__":
    bundle_project(".")