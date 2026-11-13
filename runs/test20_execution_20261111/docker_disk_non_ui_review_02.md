# Docker 磁盘非 UI 替代路径复核（2026-11-11）

状态：只读复核。未操作 Docker 引擎，未改设置、移动文件或停止进程。

## 本机白名单读取

读取 `%APPDATA%\Docker\settings-store.json`，仅输出磁盘相关字段（DataFolder/dataFolder、diskPath、diskSizeMiB、diskImageLocation 等，不区分大小写）。本次结果为 `disk_fields=[]`：当前文件没有这些显式覆盖字段。未打印 proxy、auth 或其他隐私设置，也没有因为字段缺失而插入默认字段。

这只能证明当前设置存储没有显式磁盘字段，不能证明设置 Draft、UI 或正在运行的后端已经迁移。实际是否迁移仍须根代理观察 UI 和后续活动 VHDX/镜像身份。

## 官方依据核查

- 官方设置文档给出 `settings-store.json` 的存储路径，但没有在所读页面定义 `DataFolder` 手工迁移现有 Windows WSL 数据盘的协议。[设置文档](https://docs.docker.com/desktop/settings-and-maintenance/settings/)
- 官方 WSL2 文档明确将改变磁盘位置指向 Dashboard 的 Settings → Resources → Advanced。[WSL2 后端](https://docs.docker.com/desktop/features/wsl/)
- 官方备份说明要求完全停止 Desktop 后备份 VM 数据盘，并描述恢复到对应后端约定位置。该文档不能推导为可直接修改任意数据目录字段完成跨盘迁移。[备份和恢复](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)
- 安装器的 `--wsl-default-data-root` 定义安装时的默认位置，未在所读官方文档中被声明为现有完整数据盘的迁移命令。[Windows 安装说明](https://docs.docker.com/desktop/setup/install/windows-install/)
- 本机和官方 `docker desktop` CLI 清单均未给出磁盘迁移子命令。[CLI 参考](https://docs.docker.com/reference/cli/docker/desktop/)

额外检索 `dataFolder` / `DataFolder` 只找到用户提交的非 Windows 场景 workaround，未找到能据以建议本机 Windows 4.98 手工改键迁移的官方受支持说明。未将 GitHub 仓库中的用户反馈当成产品支持协议。

## 建议

**不建议以“停机复制 VHDX + 手工插入/修改 DataFolder”代替 UI 迁移。** 当前证据不足以证明该路径受支持，也不能保证不会产生空新盘、数据路径失配或启动失败。

保留根代理已完成的停机备份和原件。若根代理判断需要交还用户点击最后确认，使用现有 UI 手动 handoff，并在完成后验证活动磁盘路径、全部镜像完整 ID、控制器健康与原始资产哈希。不以 installer 参数、未公开 API、junction 或 WSL unregister 绕过确认。

本文仅记录本次支持性调查，不宣称官方所有潜在接口均已穷尽，也不宣称 UI 迁移已经完成。
