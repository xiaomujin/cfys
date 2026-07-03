"""推送结果文件到 GitHub 仓库

通过 git clone/pull/push 方式同步 best_ips.txt 和 dns_ips.txt 到指定仓库。
"""

import base64
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

from src.config import load_config


class GitHubSync:
    def __init__(self, config) -> None:
        self.config = config
        # 优先使用配置文件中的 token，否则从环境变量读取
        self.token = config.token
        # 当前使用的代理（可动态切换）
        self._current_proxy = config.proxy

    def sync(self, files: Sequence[tuple[Path, Path | None]]) -> bool:
        """同步文件到 GitHub 仓库

        Args:
            files: [(源文件路径, 仓库内目标路径), ...]
                   目标路径为 None 时使用源文件名
        """
        if not self.config.enabled or not self.config.repo:
            return False
        if not self.token:
            print(
                "GitHub 推送警告: 未配置 Token；"
                "请在 config.toml [github] 中填写 TOKEN 或设置环境变量 GITHUB_TOKEN"
            )
            return False

        normalized = self._normalize_files(files)
        if not normalized:
            print("GitHub 推送跳过: 没有可推送的结果文件")
            return False

        # 尝试同步（先用代理）
        result = self._do_sync(normalized)
        
        # 如果失败且配置了代理且回退选项开启，尝试无代理
        if not result and self.config.proxy and self.config.fallback_no_proxy:
            print("\n代理模式失败，正在尝试无代理模式...")
            self._current_proxy = ""
            self._cleanup_worktree()
            result = self._do_sync(normalized)
            if result:
                print("无代理模式推送成功")
            else:
                print("无代理模式也失败了")
        
        return result

    def _do_sync(self, normalized: list[tuple[Path, Path]]) -> bool:
        """执行实际的同步操作"""
        proxy_info = f"代理: {self._current_proxy}" if self._current_proxy else "代理: 无"
        print(f"\n开始 GitHub 同步 ({proxy_info})")
        
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                self._ensure_worktree()
                for source, destination in normalized:
                    target_file = self.config.workdir / destination
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target_file)
                    self._git(["add", str(destination)])

                if not self._has_staged_changes():
                    if self._push_if_ahead():
                        print(f"GitHub 推送完成: 已推送待处理的提交到 {self.config.repo} ({self.config.branch})")
                    else:
                        print("GitHub 推送跳过: 结果文件无变化")
                    return True

                self._git(
                    [
                        "-c",
                        "user.name=IP Update Bot",
                        "-c",
                        "user.email=ip-update-bot@users.noreply.github.com",
                        "commit",
                        "-m",
                        self.config.message,
                    ]
                )
                self._git(["push", "origin", self.config.branch])
                names = ", ".join(str(destination) for _, destination in normalized)
                print(f"GitHub 推送完成: 已推送 {names} 到 {self.config.repo} ({self.config.branch})")
                return True
            except subprocess.TimeoutExpired:
                print(f"[尝试 {attempt}/{max_retries}] Git 操作超时")
                if attempt < max_retries:
                    self._cleanup_worktree()
                    time.sleep(3)
            except RuntimeError as exc:
                error_msg = str(exc)
                # 认证失败不重试
                if "401" in error_msg or "403" in error_msg or "authentication" in error_msg.lower():
                    print(f"GitHub 认证失败，请检查 Token 权限: {exc}")
                    return False
                # 推送冲突：远程有新提交
                if "rejected" in error_msg or "non-fast-forward" in error_msg:
                    print(f"[尝试 {attempt}/{max_retries}] 远程分支有更新，正在重新同步...")
                    self._cleanup_worktree()
                    if attempt < max_retries:
                        time.sleep(2)
                    continue
                # 其他运行时错误
                print(f"[尝试 {attempt}/{max_retries}] Git 操作失败: {exc}")
                if attempt < max_retries:
                    self._cleanup_worktree()
                    time.sleep(3)
            except OSError as exc:
                print(f"[尝试 {attempt}/{max_retries}] 文件系统错误: {exc}")
                if attempt < max_retries:
                    time.sleep(3)
        
        print(f"GitHub 推送失败: 已重试 {max_retries} 次")
        return False

    def _normalize_files(self, files: Sequence[tuple[Path, Path | None]]) -> list[tuple[Path, Path]]:
        normalized: list[tuple[Path, Path]] = []
        for source, target_path in files:
            if not source.exists():
                print(f"GitHub 推送跳过不存在的文件: {source}")
                continue
            destination = target_path or Path(source.name)
            if destination.is_absolute() or ".." in destination.parts:
                raise RuntimeError(f"目标路径必须是相对路径: {destination}")
            normalized.append((source, destination))
        return normalized

    def _ensure_worktree(self) -> None:
        git_dir = self.config.workdir / ".git"
        if git_dir.exists():
            # 清理可能的锁定文件
            self._cleanup_git_locks()
            # 强制同步到远程最新状态（丢弃本地所有未提交更改）
            self._git(["fetch", "origin", self.config.branch], check=False)
            self._git(["reset", "--hard"], check=False)
            self._git(["clean", "-fd"], check=False)  # 清理未跟踪文件
            self._git(["checkout", "-B", self.config.branch, f"origin/{self.config.branch}"])
            return

        # 检查目录是否存在但不是 git 仓库
        if self.config.workdir.exists():
            if any(self.config.workdir.iterdir()):
                # 尝试清理损坏的目录
                print(f"警告: 同步目录存在但非 git 仓库，正在清理: {self.config.workdir}")
                self._cleanup_worktree()
            else:
                self.config.workdir.rmdir()

        self.config.workdir.parent.mkdir(parents=True, exist_ok=True)
        
        # 尝试克隆远程仓库
        clone_result = self._git(
            ["clone", "--branch", self.config.branch, "--single-branch", self.config.repo, str(self.config.workdir)],
            cwd=None,
            check=False,
        )
        
        if clone_result.returncode != 0:
            error_msg = clone_result.stderr.strip() or clone_result.stdout.strip()
            # 如果是分支不存在，可能是空仓库，尝试初始化
            if "not found" in error_msg or "does not exist" in error_msg or "Remote branch" in error_msg:
                print(f"远程分支 {self.config.branch} 不存在，可能是空仓库，正在初始化...")
                self._init_empty_repo()
            else:
                raise RuntimeError(f"克隆仓库失败: {error_msg}")

    def _cleanup_git_locks(self) -> None:
        """清理 git 锁定文件（Windows 常见问题）"""
        lock_files = [
            self.config.workdir / ".git" / "index.lock",
            self.config.workdir / ".git" / "HEAD.lock",
            self.config.workdir / ".git" / "config.lock",
            self.config.workdir / ".git" / "refs" / "heads" / f"{self.config.branch}.lock",
            self.config.workdir / ".git" / "refs" / "remotes" / "origin" / f"{self.config.branch}.lock",
        ]
        for lock_file in lock_files:
            if lock_file.exists():
                try:
                    lock_file.unlink()
                    print(f"已清理锁定文件: {lock_file}")
                except OSError:
                    pass

    def _cleanup_worktree(self) -> None:
        """清理并删除工作目录（用于重试场景）"""
        if not self.config.workdir.exists():
            return
        # 先尝试重置 git 状态
        git_dir = self.config.workdir / ".git"
        if git_dir.exists():
            self._cleanup_git_locks()
            self._git(["reset", "--hard"], check=False)
            self._git(["clean", "-fd"], check=False)

        # 延迟删除（Windows 可能需要等待文件句柄释放）
        for attempt in range(3):
            try:
                shutil.rmtree(self.config.workdir)
                return
            except OSError as e:
                if attempt < 2:
                    time.sleep(2)
                else:
                    print(f"警告: 清理目录失败 ({e})，尝试强制删除...")
                    shutil.rmtree(self.config.workdir, ignore_errors=True)

        # 最终检查
        if self.config.workdir.exists():
            print(f"警告: 无法完全清理目录 {self.config.workdir}")

    def _init_empty_repo(self) -> None:
        """初始化空仓库（用于远程仓库为空的情况）"""
        # 创建目录
        self.config.workdir.mkdir(parents=True, exist_ok=True)

        # 初始化本地仓库
        self._git(["init"], cwd=self.config.workdir, check=False)

        # 设置用户信息
        self._git(["config", "user.name", "IP Update Bot"], cwd=self.config.workdir, check=False)
        self._git(["config", "user.email", "ip-update-bot@users.noreply.github.com"], cwd=self.config.workdir, check=False)

        # 创建分支
        self._git(["checkout", "-b", self.config.branch], cwd=self.config.workdir, check=False)

        # 添加远程仓库
        self._git(["remote", "add", "origin", self.config.repo], cwd=self.config.workdir, check=False)

        # 创建初始提交（空仓库需要至少一个 commit 才能 push）
        readme = self.config.workdir / "README.md"
        readme.write_text("# IP Results\n", encoding="utf-8")
        self._git(["add", "README.md"], cwd=self.config.workdir, check=False)
        self._git(
            ["-c", "user.name=IP Update Bot", "-c", "user.email=ip-update-bot@users.noreply.github.com",
             "commit", "-m", "Initial commit"],
            cwd=self.config.workdir, check=False,
        )

        print(f"已初始化空仓库，分支: {self.config.branch}")

    def _has_staged_changes(self) -> bool:
        diff = self._git(["diff", "--cached", "--quiet"], check=False)
        if diff.returncode == 0:
            return False
        if diff.returncode == 1:
            return True
        raise RuntimeError(diff.stderr.strip() or "git diff --cached --quiet failed")

    def _push_if_ahead(self) -> bool:
        # 检查远程分支是否存在
        remote_ref = f"origin/{self.config.branch}"
        ref_exists = self._git(["rev-parse", "--verify", remote_ref], check=False)
        if ref_exists.returncode != 0:
            # 远程分支不存在（可能是空仓库），尝试直接推送
            try:
                self._git(["push", "origin", self.config.branch])
                return True
            except RuntimeError:
                return False

        ahead = self._git(["rev-list", "--count", f"{remote_ref}..HEAD"], check=False)
        try:
            ahead_count = int(ahead.stdout.strip()) if ahead.returncode == 0 and ahead.stdout.strip() else 0
        except ValueError:
            ahead_count = 0

        if ahead_count <= 0:
            return False
        print(f"GitHub 推送: 正在推送 {ahead_count} 个待处理的本地提交")
        self._git(["push", "origin", self.config.branch])
        return True

    def _git(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        git = shutil.which("git")
        if git is None:
            raise RuntimeError("未找到 git 命令")

        command = [git]
        # 设置代理
        if self._current_proxy:
            command.extend(["-c", f"http.proxy={self._current_proxy}"])
            command.extend(["-c", f"https.proxy={self._current_proxy}"])
        # 设置认证头
        header = self._auth_header()
        if header:
            command.extend(["-c", f"http.https://github.com/.extraheader={header}"])
        if cwd is None and args[:1] != ["clone"]:
            cwd = self.config.workdir
        command.extend(args)

        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=self.config.timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if check and result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or f"git exited with {result.returncode}"
            raise RuntimeError(message)
        return result

    def _auth_header(self) -> str | None:
        if not self.token:
            return None
        value = base64.b64encode(f"x-access-token:{self.token}".encode("utf-8")).decode("ascii")
        return f"AUTHORIZATION: basic {value}"


def run_push(cfg=None) -> int:
    """供 main.py 调用的入口

    推送 best_ips.txt 和 dns_ips.txt 到 GitHub 仓库
    """
    if cfg is None:
        cfg = load_config()

    github = cfg.github
    if not github.enabled:
        print("GitHub 推送未启用，跳过")
        return 0

    if not github.repo:
        print("错误：请在 config.toml [github] 中填写 REPO")
        return 1

    # 准备要推送的文件列表
    files_to_push: list[tuple[Path, Path | None]] = []

    # best_ips.txt
    if cfg.best_output_file.exists():
        files_to_push.append((cfg.best_output_file, None))
    else:
        print(f"警告: {cfg.best_output_file} 不存在，跳过")

    # dns_ips.txt
    dns_ips_file = Path("dns_ips.txt")
    if dns_ips_file.exists():
        files_to_push.append((dns_ips_file, None))
    else:
        print(f"提示: {dns_ips_file} 不存在（DNS 推送未执行或未生成），跳过")

    if not files_to_push:
        print("没有可推送的文件，跳过 GitHub 推送")
        return 0

    syncer = GitHubSync(github)
    ok = syncer.sync(files_to_push)
    return 0 if ok else 1


def main() -> int:
    return run_push()


if __name__ == "__main__":
    raise SystemExit(main())
