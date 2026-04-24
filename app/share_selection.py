from .core import *  # noqa: F401,F403

def normalize_share_selection_entry(item: Any) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    entry_id = str(item.get("id", "") or item.get("select_id", "")).strip()
    name = normalize_relative_path(item.get("name", ""))
    if not entry_id or not name:
        return {}
    is_dir = bool(item.get("is_dir"))
    parent_id = str(item.get("parent_id", "0") or "0").strip() or "0"
    return {
        "id": entry_id,
        "name": name,
        "is_dir": is_dir,
        "parent_id": parent_id,
        "cid": str(item.get("cid", "") or "").strip() if is_dir else "",
        "fid": str(item.get("fid", "") or "").strip() if not is_dir else "",
        "fid_token": str(item.get("fid_token", "") or item.get("share_fid_token", "") or "").strip(),
    }

def normalize_share_selection_meta(raw: Any) -> Dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    selected_entries: List[Dict[str, Any]] = []
    selected_ids: List[str] = []
    seen_ids: Set[str] = set()

    for item in data.get("selected_entries") or []:
        entry = normalize_share_selection_entry(item)
        entry_id = str(entry.get("id", "")).strip()
        if not entry_id or entry_id in seen_ids:
            continue
        seen_ids.add(entry_id)
        selected_entries.append(entry)
        selected_ids.append(entry_id)

    for raw_id in data.get("selected_ids") or []:
        entry_id = str(raw_id or "").strip()
        if not entry_id or entry_id in seen_ids:
            continue
        seen_ids.add(entry_id)
        selected_ids.append(entry_id)

    refresh_target_type = str(data.get("refresh_target_type", "") or "").strip().lower()
    if refresh_target_type not in ("folder", "file", "mixed"):
        if len(selected_entries) == 1:
            refresh_target_type = "folder" if selected_entries[0].get("is_dir") else "file"
        elif len(selected_ids) > 1:
            refresh_target_type = "mixed"
        else:
            refresh_target_type = ""

    auto_sharetitle = normalize_relative_path(data.get("auto_sharetitle", ""))
    if not auto_sharetitle and len(selected_entries) == 1:
        auto_sharetitle = normalize_relative_path(selected_entries[0].get("name", ""))

    return {
        "selected_ids": selected_ids,
        "selected_entries": selected_entries,
        "refresh_target_type": refresh_target_type,
        "share_root_title": normalize_relative_path(data.get("share_root_title", "")),
        "auto_sharetitle": auto_sharetitle,
        "selected_count": len(selected_ids),
    }

def merge_share_selection_meta(primary: Any, fallback: Any) -> Dict[str, Any]:
    left = normalize_share_selection_meta(primary)
    right = normalize_share_selection_meta(fallback)
    merged = {
        "selected_ids": left.get("selected_ids") or right.get("selected_ids") or [],
        "selected_entries": left.get("selected_entries") or right.get("selected_entries") or [],
        "refresh_target_type": left.get("refresh_target_type") or right.get("refresh_target_type") or "",
        "share_root_title": left.get("share_root_title") or right.get("share_root_title") or "",
        "auto_sharetitle": left.get("auto_sharetitle") or right.get("auto_sharetitle") or "",
    }
    return normalize_share_selection_meta(merged)
