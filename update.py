import os
import re
import subprocess
import json
from datetime import datetime
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm


def get_categories_in_batch(repos_to_categorize, existing_categories):
    print(
        f"  > Asking Gemini to categorize {len(repos_to_categorize)} repositories in a single batch..."
    )
    repos_json_string = json.dumps(repos_to_categorize, indent=2)

    prompt = f"""You are an expert programmer and a helpful API that categorizes GitHub repositories.
You will be given a JSON array of repositories. Your task is to return a single, valid JSON array of the same repositories, each with an added "category" field.

- If a fitting category already exists, please use it.
- Your entire response must be only the JSON array and nothing else.
- Do not be overly specific; try to keep the number of categories low.

Example Categories: Anti-Bot Bypass, Web Automation, Reverse Engineering, Misc, Web Frameworks, Account Generators, TLS Fingerprinting, Other Curated Lists.
Existing Categories: {', '.join(existing_categories) if existing_categories else 'None'}

Here is the JSON array of repositories to categorize:
{repos_json_string}
"""
    try:
        model = genai.GenerativeModel("gemini-2.5-pro")  # type: ignore
        response = model.generate_content(prompt)
        cleaned_json_text = response.text.strip().lstrip("```json").rstrip("```")
        categorized_list = json.loads(cleaned_json_text)
        # Return a simple dict of repo name -> category
        return {item["name"]: item["category"] for item in categorized_list}
    except Exception as e:
        print(f"  ! Error with Gemini API batch processing: {e}")
        return {}


def parse_readme(filepath):
    repos_by_category = {}
    if not os.path.exists(filepath):
        return repos_by_category
    current_category = "Uncategorized"
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            category_match = re.search(r"\|\s*\*\*`(.+?)`\*\*\s*\|", line)
            if category_match:
                current_category = category_match.group(1).strip()
                continue
            repo_match = re.search(r"\|\s*\[`(.+?)`\]\(", line)
            if repo_match:
                if current_category not in repos_by_category:
                    repos_by_category[current_category] = []
                repos_by_category[current_category].append(line.strip())
    return repos_by_category


def get_git_data(p):
    try:
        url = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=p,
            capture_output=True,
            check=True,
            encoding="utf-8",
        ).stdout.strip()
        gh_process = subprocess.run(
            [
                "gh",
                "repo",
                "view",
                url,
                "--json",
                "description,pushedAt,primaryLanguage",
            ],
            capture_output=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        repo_data = json.loads(gh_process.stdout)
        desc = repo_data.get("description") or ""
        pushed_at_str = repo_data.get("pushedAt", "")
        lang_data = repo_data.get("primaryLanguage")
        lang = lang_data.get("name") if lang_data else ""
        date_formatted = ""
        if pushed_at_str:
            date_obj = datetime.fromisoformat(pushed_at_str.replace("Z", "+00:00"))
            date_formatted = date_obj.strftime("%Y-%m-%d")
        return url, desc, date_formatted, lang
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        return None, None, None, None


def main():
    readme_path = "README.md"
    repos_by_category = parse_readme(readme_path)
    existing_names = {
        repo_name
        for rows in repos_by_category.values()
        for row in rows
        for repo_name in re.findall(r"\[`(.+?)`\]", row)
    }
    cwd = os.getcwd()
    new_repos_data = []

    all_local_dirs = sorted(
        [
            d
            for d in os.listdir(cwd)
            if os.path.isdir(os.path.join(cwd, d))
            and os.path.exists(os.path.join(cwd, d, ".git"))
        ]
    )
    new_dirs_to_process = [d for d in all_local_dirs if d not in existing_names]
    new_repo_paths = [os.path.join(cwd, d) for d in new_dirs_to_process]

    if not new_repo_paths:
        print("\nREADME.md is already up to date.")
        return

    print(f"\nFetching data for {len(new_repo_paths)} new repositories...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(
            tqdm(executor.map(get_git_data, new_repo_paths), total=len(new_repo_paths))
        )

    for i, (url, desc, last_updated, lang) in enumerate(results):
        if url:
            new_repos_data.append(
                {
                    "name": new_dirs_to_process[i],
                    "url": url,
                    "desc": desc,
                    "last_updated": last_updated,
                    "lang": lang,
                }
            )

    repo_info_for_gemini = [
        {"name": r["name"], "description": r["desc"], "language": r["lang"]}
        for r in new_repos_data
    ]
    categorized_repos = get_categories_in_batch(
        repo_info_for_gemini, list(repos_by_category.keys())
    )

    if not categorized_repos:
        print("\nCould not get categories from Gemini. Aborting update.")
        return

    for repo_data in new_repos_data:
        repo_name = repo_data["name"]
        category_input = categorized_repos.get(repo_name, "Uncategorized")
        lang_text = repo_data["lang"] or ""

        new_row = f"| [`{repo_name}`]({repo_data['url']}) | {lang_text} | {repo_data['desc'] or ''} | {repo_data['last_updated'] or ''} |"

        if category_input not in repos_by_category:
            repos_by_category[category_input] = []
        repos_by_category[category_input].append(new_row)
        print(f"  + Processed '{repo_name}' into category '{category_input}'")

    md_content = "# cool repos\n\n"
    md_content += (
        "| Repository | Language | Description | Last Updated |\n|---|---|---|---|\n"
    )
    all_rows = []
    is_first_category = True
    for category, rows in sorted(repos_by_category.items()):
        if not is_first_category:
            all_rows.append("| | | | |")
        all_rows.append(f"| **`{category}`** | | | |")
        all_rows.extend(sorted(rows, key=lambda line: line.split("`")[1].lower()))
        is_first_category = False

    md_content += "\n".join(all_rows)
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(
        f"\n✅ Successfully updated README.md with {len(new_repos_data)} new repositories!"
    )


if __name__ == "__main__":
    main()
