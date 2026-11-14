_COLOR_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


def _uptime(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


def ago(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def in_time(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"in {s}s"
    if s < 3600:
        return f"in {s // 60}m"
    if s < 86400:
        return f"in {s // 3600}h"
    return f"in {s // 86400}d"


def format_status_text(data: dict) -> str:
    lines: list[str] = []

    version = data.get("version", "?")
    uptime = data.get("uptime_seconds")
    uptime_str = _uptime(uptime) if uptime is not None else "?"

    all_colors = (
        [w.get("color", "green") for w in data.get("workers", {}).values()]
        + [j.get("color", "green") for j in data.get("jobs", {}).values()]
    )
    if "red" in all_colors:
        overall = "🔴"
    elif "yellow" in all_colors:
        overall = "🟡"
    else:
        overall = "🟢"

    lines.append(f"{overall}  monda v{version} | uptime: {uptime_str}")

    workers = data.get("workers", {})
    if workers:
        lines.append("\nWorkers:")
        for name, w in workers.items():
            emoji = _COLOR_EMOJI.get(w.get("color", "green"), "🟢")
            detail = w.get("detail", "")
            crashed_ago = w.get("crashed_ago")
            restart_count = w.get("restart_count", 0)
            last_restart_ago = w.get("last_restart_ago")
            if crashed_ago is not None:
                crash_error = w.get("crash_error") or "unknown error"
                suffix = f" [Crashed {ago(crashed_ago)}: {crash_error}]"
            elif last_restart_ago is not None and restart_count > 0:
                suffix = f" [Restarted {ago(last_restart_ago)}, {restart_count}x]"
            else:
                suffix = ""
            lines.append(f"  {emoji}  {name:<30} {detail}{suffix}")

    jobs = data.get("jobs", {})
    if jobs:
        lines.append("\nJobs:")
        for key, j in jobs.items():
            emoji = _COLOR_EMOJI.get(j.get("color", "green"), "🟢")
            detail = j.get("detail", "")
            next_run_in = j.get("next_run_in")
            parts = [detail]
            if next_run_in is not None:
                parts.append(f"Next: {in_time(next_run_in)}")
            lines.append(f"  {emoji}  {key:<38} {' | '.join(parts)}")

    return "\n".join(lines) + "\n"
