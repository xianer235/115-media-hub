import logging
import re
import threading
import time
from typing import Any, Dict, List

import requests

from .base import CloudProvider
from .registry import register


ALIYUN_API_BASE = "https://api.alipan.com"
ALIYUN_CANARY_HEADER = "client=web,app=share,version=v2.3.1"
ALIYUN_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


class AliyunProvider(CloudProvider):
    name = "aliyun"
    label = "阿里云盘"
    link_type = "aliyun"
    auth_type = "refresh_token"
    config_keys = ["aliyun_refresh_token"]
    supports_subscription = True
    supports_offline = False
    supports_fixed_share_link = True
    supports_rename = True
    supports_move = True
    supports_copy = True
    supports_delete = True

    def __init__(self):
        super().__init__()
        self._access_token = None
        self._token_expiry = 0.0
        self._drive_id = None
        self._token_lock = threading.Lock()

    def _ensure_access_token(self, refresh_token: str) -> str:
        now = time.time()
        with self._token_lock:
            if self._access_token and now < self._token_expiry - 60:
                return self._access_token
            last_error = None
            token_endpoints = [
                "https://auth.alipan.com/v2/account/token",
                "https://auth.aliyundrive.com/v2/account/token",
                "https://api.alistgo.com/alist/ali_open/token",
            ]
            for url in token_endpoints:
                try:
                    resp = requests.post(
                        url,
                        json={
                            "grant_type": "refresh_token",
                            "refresh_token": refresh_token,
                        },
                        headers={"Content-Type": "application/json"},
                        timeout=15,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    token = data.get("access_token")
                    if token:
                        self._access_token = token
                        self._token_expiry = now + int(data.get("expires_in", 7200))
                        drive_id = str(data.get("default_drive_id", "") or "").strip()
                        if drive_id:
                            self._drive_id = drive_id
                        return token
                    err_msg = str(data.get("message", "") or data.get("error_description", "") or "")
                    if err_msg:
                        last_error = err_msg
                        break
                except requests.RequestException as exc:
                    last_error = str(exc)
                    continue
            if last_error:
                raise RuntimeError(f"阿里云盘 access_token 获取失败: {last_error}")
            raise RuntimeError("阿里云盘 access_token 获取失败，请检查 refresh_token 是否有效")

    def _base_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": ALIYUN_USER_AGENT,
            "Origin": "https://www.alipan.com",
            "Referer": "https://www.alipan.com/",
            "X-Canary": ALIYUN_CANARY_HEADER,
        }

    def _api_headers(self, refresh_token: str, share_token: str = "") -> Dict[str, str]:
        headers = self._base_headers()
        token = self._ensure_access_token(refresh_token)
        headers["Authorization"] = f"Bearer {token}"
        if share_token:
            headers["x-share-token"] = share_token
        return headers

    @staticmethod
    def _raise_for_api_error(data: Dict[str, Any], prefix: str = "阿里云盘 API 错误") -> None:
        code = str(data.get("code", "") or data.get("error", "") or "").strip()
        if not code or code.lower() in ("success", "ok", "200"):
            return
        message = str(
            data.get("message", "")
            or data.get("error_description", "")
            or data.get("msg", "")
            or code
        ).strip()
        if message and message != code:
            raise RuntimeError(f"{prefix}: {code} - {message}")
        raise RuntimeError(f"{prefix}: {code}")

    def _post_json(self, url: str, body: Dict[str, Any], headers: Dict[str, str], timeout: int = 30) -> Dict[str, Any]:
        self.throttle()
        resp = requests.post(
            url,
            headers=headers,
            json=body,
            timeout=timeout,
        )
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.text.strip():
            return {}
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("阿里云盘 API 返回格式异常")
        return data

    def _api_post(
        self,
        refresh_token: str,
        url: str,
        body: Dict[str, Any],
        timeout: int = 30,
        share_token: str = "",
    ) -> Dict[str, Any]:
        data = self._post_json(url, body, self._api_headers(refresh_token, share_token), timeout)
        self._raise_for_api_error(data)
        return data

    def _resolve_drive_id(self, refresh_token: str) -> str:
        if self._drive_id:
            return self._drive_id
        data = self._api_post(refresh_token, f"{ALIYUN_API_BASE}/v2/user/get", {})
        drive_id = str(data.get("default_drive_id", "") or "").strip()
        if not drive_id:
            raise RuntimeError("阿里云盘默认网盘 ID 获取失败")
        self._drive_id = drive_id
        return drive_id

    @staticmethod
    def _normalize_cid(cid: str) -> str:
        cid = str(cid or "").strip()
        return "root" if not cid or cid == "0" else cid

    def list_entries_payload(self, cookie, cid="root", folders_only=False):
        cid = self._normalize_cid(cid)
        body = {
            "drive_id": self._resolve_drive_id(refresh_token=cookie),
            "parent_file_id": cid,
            "limit": 200,
            "order_by": "updated_at",
            "order_direction": "DESC",
        }
        if folders_only:
            body["type"] = "folder"
        data = self._api_post(cookie, f"{ALIYUN_API_BASE}/v2/file/list", body)
        entries = []
        for item in data.get("items", []):
            is_dir = item.get("type") == "folder"
            item_id = str(item.get("file_id", ""))
            entries.append({
                "id": str(item.get("file_id", "")),
                "name": str(item.get("name", "")),
                "type": "folder" if item.get("type") == "folder" else "file",
                "is_dir": is_dir,
                "cid": item_id if is_dir else "",
                "fid": "" if is_dir else item_id,
                "size": int(item.get("size", 0) or 0),
                "parent_id": str(item.get("parent_file_id", cid)),
            })
        folder_count = sum(1 for item in entries if item.get("is_dir"))
        file_count = sum(1 for item in entries if not item.get("is_dir"))
        return {
            "entries": entries,
            "total": len(entries),
            "summary": {"folder_count": folder_count, "file_count": file_count},
        }

    def list_entries(self, cookie, cid="root"):
        return self.list_entries_payload(cookie, cid)["entries"]

    def create_folder(self, cookie, cid="root", folder_name=""):
        cid = self._normalize_cid(cid)
        data = self._api_post(cookie, f"{ALIYUN_API_BASE}/adrive/v2/file/createWithFolders", {
            "drive_id": self._resolve_drive_id(refresh_token=cookie),
            "parent_file_id": cid,
            "name": folder_name,
            "type": "folder",
            "check_name_mode": "refuse",
        })
        return {"cid": str(data.get("file_id", "")), "name": folder_name}

    def resolve_folder_id_by_path(self, cookie, relative_path):
        parts = [p.strip() for p in str(relative_path).split("/") if p.strip()]
        cid = "root"
        for name in parts:
            entries = self.list_entries(cookie, cid)
            found = next((e for e in entries if e.get("name") == name), None)
            if not found:
                return ""
            cid = found["id"]
        return cid

    def ensure_folder_id_by_path(self, cookie, relative_path):
        parts = [p.strip() for p in str(relative_path).split("/") if p.strip()]
        cid = "root"
        for name in parts:
            entries = self.list_entries(cookie, cid)
            found = next((e for e in entries if e.get("name") == name), None)
            if found:
                cid = found["id"]
            else:
                result = self.create_folder(cookie, cid, name)
                cid = result["cid"]
        return cid

    def resolve_share_payload(self, cookie, share_url, raw_text="", receive_code=""):
        share_text = str(share_url or "")
        share_id_match = re.search(r"/s/([A-Za-z0-9]+)", share_text)
        if not share_id_match:
            raise RuntimeError("无法识别阿里云盘分享链接")
        payload = {
            "share_id": share_id_match.group(1),
            "receive_code": str(receive_code or "").strip(),
            "url": share_text.strip(),
        }
        folder_match = re.search(r"/folder/([A-Za-z0-9]+)", share_text)
        if folder_match:
            payload["folder_id"] = folder_match.group(1)
        return payload

    def _get_share_token(self, share_id: str, receive_code: str = "") -> str:
        body = {"share_id": share_id}
        if receive_code:
            body["share_pwd"] = receive_code
        data = self._post_json(
            f"{ALIYUN_API_BASE}/v2/share_link/get_share_token",
            body,
            self._base_headers(),
            timeout=15,
        )
        self._raise_for_api_error(data, prefix="阿里云盘分享令牌获取失败")
        share_token = str(data.get("share_token", "") or "").strip()
        if not share_token:
            raise RuntimeError("阿里云盘分享令牌获取失败：返回为空，请检查分享链接或提取码")
        return share_token

    def _list_share_page(
        self,
        cookie: str,
        share_id: str,
        share_token: str,
        cid: str,
        marker: str,
        limit: int,
    ) -> Dict[str, Any]:
        data = self._api_post(
            cookie,
            f"{ALIYUN_API_BASE}/adrive/v3/file/list",
            {
                "share_id": share_id,
                "parent_file_id": cid,
                "limit": limit,
                "marker": marker,
                "order_by": "updated_at",
                "order_direction": "DESC",
                "image_thumbnail_process": "image/resize,w_160/format,jpeg",
                "image_url_process": "image/resize,w_1920/format,jpeg",
                "video_thumbnail_process": "video/snapshot,t_1000,f_jpg,ar_auto,w_300",
            },
            share_token=share_token,
        )
        return data

    @staticmethod
    def _normalize_share_entry(item: Dict[str, Any], share_id: str, share_token: str, cid: str) -> Dict[str, Any]:
        is_dir = item.get("type") == "folder"
        item_id = str(item.get("file_id", ""))
        return {
            "id": item_id,
            "name": str(item.get("name", "")),
            "type": "folder" if is_dir else "file",
            "is_dir": is_dir,
            "cid": item_id if is_dir else "",
            "fid": "" if is_dir else item_id,
            "size": int(item.get("size", 0) or 0),
            "parent_id": str(item.get("parent_file_id", cid) or cid),
            "share_id": share_id,
            "share_token": share_token,
            "drive_id": str(item.get("drive_id", "") or ""),
        }

    def list_share_entries(self, cookie, share_payload, cid="root", offset=0, limit=200):
        cid = self._normalize_cid(cid)
        if cid == "root":
            cid = str(share_payload.get("folder_id", "") or "").strip() or cid
        share_id = share_payload["share_id"]
        receive_code = share_payload.get("receive_code", "")
        share_token = str(share_payload.get("share_token", "") or "").strip()
        if not share_token:
            share_token = self._get_share_token(share_id, receive_code)

        normalized_offset = max(0, int(offset or 0))
        normalized_limit = max(1, min(int(limit or 200), 400))
        marker = ""
        skipped = 0
        entries = []
        next_marker = ""
        while len(entries) < normalized_limit:
            entries_data = self._list_share_page(
                cookie,
                share_id,
                share_token,
                cid,
                marker,
                min(200, normalized_limit + normalized_offset - skipped),
            )
            page_items = entries_data.get("items", []) if isinstance(entries_data.get("items", []), list) else []
            next_marker = str(entries_data.get("next_marker", "") or "").strip()
            if skipped + len(page_items) <= normalized_offset:
                skipped += len(page_items)
            else:
                start = max(0, normalized_offset - skipped)
                for item in page_items[start:]:
                    if not isinstance(item, dict):
                        continue
                    entries.append(self._normalize_share_entry(item, share_id, share_token, cid))
                    if len(entries) >= normalized_limit:
                        break
                skipped += len(page_items)
            marker = next_marker
            if not marker or not page_items:
                break
        next_offset = normalized_offset + len(entries)
        share_meta = {**share_payload, "share_token": share_token}
        if entries:
            drive_id = str(entries[0].get("drive_id", "") or "").strip()
            if drive_id:
                share_meta["drive_id"] = drive_id
        folder_count = sum(1 for item in entries if item.get("is_dir"))
        file_count = sum(1 for item in entries if not item.get("is_dir"))
        return {
            "entries": entries,
            "total": next_offset + (1 if next_marker else 0),
            "offset": normalized_offset,
            "next_offset": next_offset,
            "has_more": bool(next_marker),
            "share": share_meta,
            "share_title": str(share_payload.get("title", "") or share_payload.get("share_name", "") or "").strip(),
            "summary": {"folder_count": folder_count, "file_count": file_count},
        }

    def prepare_share_receive(self, cookie, share_payload, cid="root"):
        cid = self._normalize_cid(cid)
        share_id = share_payload["share_id"]
        receive_code = str(share_payload.get("receive_code", "") or "").strip()
        share_token = str(share_payload.get("share_token", "") or "").strip()
        if not share_token:
            share_token = self._get_share_token(share_id, receive_code)
        return {**share_payload, "share_token": share_token, "target_cid": cid}

    def _submit_copy_batch(
        self,
        cookie: str,
        share_id: str,
        share_token: str,
        drive_id: str,
        target_cid: str,
        file_ids: List[str],
    ) -> Dict[str, Any]:
        requests_payload = [
            {
                "body": {
                    "file_id": fid,
                    "share_id": share_id,
                    "auto_rename": True,
                    "to_parent_file_id": target_cid,
                    "to_drive_id": drive_id,
                },
                "headers": {"Content-Type": "application/json"},
                "id": str(index),
                "method": "POST",
                "url": "/file/copy",
            }
            for index, fid in enumerate(file_ids)
        ]
        data = self._api_post(
            cookie,
            f"{ALIYUN_API_BASE}/adrive/v4/batch",
            {"requests": requests_payload, "resource": "file"},
            timeout=60,
            share_token=share_token,
        )
        responses = data.get("responses", []) if isinstance(data.get("responses", []), list) else []
        errors = []
        for item in responses:
            if not isinstance(item, dict):
                continue
            status = int(item.get("status", 0) or 0)
            body = item.get("body", {}) if isinstance(item.get("body"), dict) else {}
            code = str(body.get("code", "") or body.get("error", "") or "").strip()
            if status >= 400 or code:
                message = str(body.get("message", "") or body.get("msg", "") or code or status).strip()
                errors.append(message)
        if errors:
            raise RuntimeError(f"阿里云盘转存失败: {'; '.join(errors[:3])}")
        return data

    def submit_share_receive(self, cookie, receive_payload, files):
        share_id = receive_payload["share_id"]
        share_token = receive_payload.get("share_token", "")
        if not share_token:
            share_token = self._get_share_token(share_id, receive_payload.get("receive_code", ""))
        target_cid = self._normalize_cid(receive_payload.get("target_cid", "root"))
        drive_id = self._resolve_drive_id(refresh_token=cookie)

        file_ids = [
            str(f.get("id", "")).strip()
            for f in (files or [])
            if str(f.get("id", "")).strip()
        ]
        if not file_ids:
            raise RuntimeError("未选择要转存的文件")

        for start in range(0, len(file_ids), 20):
            self._submit_copy_batch(
                cookie,
                share_id,
                share_token,
                drive_id,
                target_cid,
                file_ids[start:start + 20],
            )

        return {"success": True, "count": len(file_ids)}

    def probe_connectivity(self, cookie):
        try:
            self._ensure_access_token(cookie)
            return True
        except Exception as e:
            logging.warning(f"阿里云盘连接检测失败: {e}")
            return False

    def rename_entry(self, cookie, entry_id, new_name, parent_id=""):
        drive_id = self._resolve_drive_id(cookie)
        body = {
            "drive_id": drive_id,
            "file_id": str(entry_id).strip(),
            "name": str(new_name).strip(),
        }
        return self._api_post(cookie, f"{ALIYUN_API_BASE}/v3/file/update", body)

    def move_entries(self, cookie, entry_ids, target_id, source_id=""):
        drive_id = self._resolve_drive_id(cookie)
        target_pid = self._normalize_cid(target_id)
        for eid in entry_ids:
            body = {
                "drive_id": drive_id,
                "file_id": str(eid).strip(),
                "to_parent_file_id": target_pid,
            }
            self._api_post(cookie, f"{ALIYUN_API_BASE}/v3/file/move", body)
        return {"ok": True, "ids": entry_ids, "target_cid": target_id}

    def copy_entries(self, cookie, entry_ids, target_id, source_id=""):
        drive_id = self._resolve_drive_id(cookie)
        target_pid = self._normalize_cid(target_id)
        for eid in entry_ids:
            body = {
                "drive_id": drive_id,
                "file_id": str(eid).strip(),
                "to_parent_file_id": target_pid,
            }
            self._api_post(cookie, f"{ALIYUN_API_BASE}/v3/file/copy", body)
        return {"ok": True, "ids": entry_ids, "target_cid": target_id}

    def delete_entries(self, cookie, entry_ids, parent_id=""):
        drive_id = self._resolve_drive_id(cookie)
        headers = self._api_headers(cookie)
        for eid in entry_ids:
            body = {
                "drive_id": drive_id,
                "file_id": str(eid).strip(),
            }
            self.throttle()
            resp = requests.post(
                f"{ALIYUN_API_BASE}/v3/file/delete",
                headers=headers,
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
            # 阿里云盘 /v3/file/delete 返回 204 No Content 或空 body
            if resp.status_code != 204 and resp.text.strip():
                self._raise_for_api_error(resp.json())
        return {"ok": True, "ids": entry_ids}


register(AliyunProvider())
