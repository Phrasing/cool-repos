import os
import subprocess
from datetime import datetime
import json


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
            ["gh", "repo", "view", url, "--json", "description,pushedAt"],
            capture_output=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )

        repo_data = json.loads(gh_process.stdout)
        desc = repo_data.get("description") or ""
        pushed_at_str = repo_data.get("pushedAt", "")

        date_formatted = ""
        if pushed_at_str:
            date_obj = datetime.fromisoformat(pushed_at_str.replace("Z", "+00:00"))
            date_formatted = date_obj.strftime("%Y-%m-%d")

        return url, desc, date_formatted
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        return None, None, None


def main():
    cwd = os.getcwd()
    repos = []
    print(f"Scanning for repositories in: {cwd}")

    for d in sorted(os.listdir(cwd)):
        p = os.path.join(cwd, d)
        if not os.path.isdir(p) or not os.path.exists(os.path.join(p, ".git")):
            continue

        url, desc, last_updated = get_git_data(p)
        if url:
            repos.append((d, url, desc, last_updated))
            print(f"  - Found: {d}")

    header = "| Repository | Description | Last Updated |\n|---|---|---|"
    table_rows = [
        f"| [`{name}`]({url}) | {desc or ''} | {last_updated or ''} |"
        for name, url, desc, last_updated in repos
    ]

    md = "# Cool Repos\n\n" + header + "\n" + "\n".join(table_rows)

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(md)

    print("\nSuccessfully created README.md")


if __name__ == "__main__":
    main()
