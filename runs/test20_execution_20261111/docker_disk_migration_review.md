# Docker Desktop 磁盘迁移审阅方案（2026-11-11）

状态：**只读调查与待决定方案，未执行迁移**。没有停止引擎、修改设置、写入 D 盘、移动/删除 VHDX、清理缓存或删除镜像。此方案不授予后续操作权限；根代理决定是否需要单独批准整体 Docker 存储迁移。

## 已核对的本机状态

| 项目 | 实测 |
| --- | --- |
| Docker Desktop Launcher 文件版本 | 4.98.0.245422 |
| `docker desktop version` | CLI plugin 4.98.0 |
| 后端 | Docker Desktop / WSL2，kernel 6.6.114.1-microsoft-standard-WSL2 |
| Linux 数据根 | `/var/lib/docker`（虚拟盘内路径，不能据此设置 Windows 迁移） |
| 主数据盘 | `C:\Users\remil\AppData\Local\Docker\wsl\disk\docker_data.vhdx` |
| 主数据盘文件/NTFS分配字节 | 14,882,439,168 bytes，约13.86 GiB |
| 引擎发行版盘 | `C:\Users\remil\AppData\Local\Docker\wsl\main\ext4.vhdx`，100,663,296 bytes（96 MiB） |
| C盘剩余 | 调查时5,606,301,696 bytes，约5.22 GiB，环境构建仍可能继续消耗 |
| D盘剩余 | 108,032,507,904 bytes，约100.62 GiB |
| 设置存储 | `%APPDATA%\Docker\settings-store.json`存在，SettingsVersion=48；该文件没有显式磁盘/WSL字段，未修改或据此推断不适用的隐藏配置 |

曾在沙箱内读到空目录/不可见引擎，准确路径和体积来自沙箱外的只读查询。盘文件正由引擎使用时不计算备份哈希，避免把运行中不一致拷贝称为备份。以上体积是某次观测，迁移前须重新测量。

## 官方支持路径与 CLI 结论

Docker 的 WSL2 专用文档明确把改变数据位置指向 Dashboard 的 **Settings → Resources → Advanced**。[WSL2 后端说明](https://docs.docker.com/desktop/features/wsl/)

本机 `docker desktop --help` 和官方 CLI 目录均没有磁盘迁移子命令；已列命令主要是 start/stop/restart/status、engine、update、diagnose、logs 等。因此本次没有找到可用于现有数据迁移的公开受支持安全 CLI，应使用 Desktop 设置界面。[Docker Desktop CLI](https://docs.docker.com/reference/cli/docker/desktop/)

安装器的 `--wsl-default-data-root` 是安装位置选项，不能当作现有镜像的迁移命令，也不建议为此重装。[Windows 安装参数](https://docs.docker.com/desktop/setup/install/windows-install/)

已装4.98.0的官方发布说明包含修复“跨卷复制超过5分钟导致磁盘移动失败”；这有利于选择当前受支持界面路径，但不构成无风险或原子迁移保证。[4.98.0 发布说明](https://docs.docker.com/desktop/release-notes/#4980)

注意：通用设置表的资源平台列与 WSL 专页表述有差异。此方案以 WSL 专页为主要支持依据；实际4.98界面的磁盘选项、按钮名称及目标路径显示仍需现场观察。如果未出现选项，停止，不编辑 settings-store、不尝试未公开后端 API。[设置说明](https://docs.docker.com/desktop/settings-and-maintenance/settings/)

## 建议的可审阅目标

- 新活动目标候选：`D:\DockerData\swe-repair-20261111`。
- 独立备份候选：`D:\DockerBackups\swe-repair-20261111-pre-move`。
- 两者均只是候选，**尚未创建**。执行前解析为绝对路径，确认目标为空、新目录且不含其他现有磁盘，不能选择“替换已有磁盘”。
- D盘可容纳当前约13.86GiB数据盘的一份停机备份和迁移副本，但未来镜像增长尚未测量，不能保证足够放入全部正式环境。备份加活动副本应预留至少当前数据盘两倍及增长余量，并保留至少4GiB C盘停止线。
- 不更改项目 checkout、原始 data/reports、历史 runs、镜像名称、实例 commit 或生成配置身份。

## 执行前提与顺序（尚未执行）

1. **停在无活动工作点。** 等所有 Docker build、公开测试和任何模型请求结束。核对本轮账本 pending；不能在生成或评分中途迁移。
2. **保存迁移前身份。** 新审计目录保存 Desktop/引擎版本、所有镜像完整ID与tag/digest、容器及卷清单、`docker system df -v`和C/D余量。保留本项目所有已有镜像；不执行 prune、image rm、volume rm或factory reset。
3. **完成停机备份。** 使用已公开的 Desktop stop/quit，等引擎完全停止后，才将原`docker_data.vhdx`复制到D的独立备份目录；保存设置文件副本，必要时保留原WSL目录布局的备份。对停止后的源文件与备份分别计算SHA256并核对字节数。不要删除源或备份。官方要求复制VM磁盘前Desktop完全停止，WSL2备份对象包括该主数据盘。[备份与恢复说明](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)
4. **由 Desktop 管理迁移。** 重新打开Desktop，进入Settings → Resources → Advanced，在Disk image location选择新D目录，并使用界面显示的Apply或Apply & Restart。观察界面完成，不手工移动VHDX、不使用junction/symlink替代、不`wsl --unregister`。若遇已有磁盘替换提示或失败，取消/停止，保留所有副本和日志。
5. **迁移后验收。** 重新读取实际活动位置与WSL2后端，核全部旧镜像完整ID、tag/digest、卷清单一致；无新容器残留。对评分控制器做一次无数据挂载的断网健康检查；对已准备实例复核实际镜像ID和base commit。确认原始93与归档131哈希未变，本轮记录完整。Desktop管理的移动可能清理旧活动副本以释放C空间，不能在未观察前承诺C必定回收多少；独立停机备份继续保留。
6. **确认后才恢复准备/实验。** 记录新的磁盘目录、配置与可用空间，保持原镜像/实验身份。只改变存储位置，不因为磁盘迁移重采样前缀或覆盖运行tag。

## 回滚与实际风险

- 停机且通过SHA256验证的备份是恢复依据，不能依赖界面移动自动保留旧源盘。禁止为了腾空间先删备份。
- 如迁移后校验失败，停止新的生成/build；优先用Desktop界面把活动位置退回原路径，确认该盘大小在C可容纳，再核验镜像ID。若Desktop无法启动，按官方备份恢复流程，在完全停机状态处理VHDX；恢复到原后端约定位置可能需要额外修复/重装授权，不能自动进行。
- 回到C需要足够空间；若迁移后又构建了新镜像，数据盘可能已大于C可用空间。恢复迁移前备份也只恢复迁移前Docker状态，不能声称包含后续构建。后续实验记录仍在项目目录，另行保留，不能用旧备份覆盖新结果。
- 迁移期间会中断整个Desktop引擎；掉电、目标权限、驱动器不可用或复制失败可能使服务不能启动。14.88GB文件复制与校验可能耗时数分钟，须等待完成，不能把超时等同已安全迁移。
- 本调查未核验D盘目录权限、文件系统兼容或实际UI操作；这些均是执行前检查项。未运行迁移、停止命令、备份复制、VHDX压缩或清理。
