# 无线安装到 3DS / 2DS

本 fork 的 Windows Builder 增加了 **无线安装 (FTP)…** 按钮。游戏程序仍在
3DS 上运行；FTP 用来从电脑传输已下载的程序和已制作的数据包，不需要拔出 SD 卡。

## 准备

1. 在已装自制系统的 3DS 上运行 [ftpd](https://github.com/mtheall/ftpd)。
   可以通过 Universal-Updater 安装。ftpd 是主机端服务，本工具是电脑端客户端。
2. 退出 Twin Embers，打开 ftpd，让电脑和 3DS 连接同一局域网。
3. 记下 ftpd 屏幕显示的 IP 地址和端口，通常端口是 `5000`。
4. 从上游最新 release 下载 `twinembers.3dsx`，用受支持的 ROM 在电脑本地生成
   `twinembers.pak`。**你提供的 v20230724 中文 ROM 目前尚不能生成原生双屏数据包**，
   适配诊断见 [CHINESE-ROM.md](CHINESE-ROM.md)。FTP 功能不会改变 ROM 兼容性。

## 图形界面

1. 运行本 fork 构建的 Windows Builder，点击 **无线安装 (FTP)…**。
2. 填写 IP、端口，以及 ftpd 中配置的用户名和密码。未设置认证时保持
   `anonymous`、空密码。IP 输入框只填地址，不要填写 `ftp://` 或目录。
3. 目标目录保持 `/3ds/twinembers`。它是 FTP 看到的 SD 卡路径，不是电脑的路径。
4. 选择本地 `.pak` 和 `.3dsx`。也可只传一个文件，例如更新 `.3dsx`。
   若某一项不传，将其路径清空。
5. 点击 **测试连接**。更新现有文件时勾选“替换已有程序／数据包”。
6. 点击 **无线安装**，等待上传和 SHA-256 回读校验完成。
7. 退出 ftpd，从 Homebrew Launcher 启动 Twin Embers。

主菜单 CIA 快捷方式只需安装一次；本工具不安装 CIA，也不上传或修改存档。
已有快捷方式在更新 `.3dsx` 后仍指向同一路径。

## 命令行

从仓库根目录安装 Builder：

```powershell
python -m pip install ./builder
firered3ds-builder upload --host 192.168.1.50 --port 5000 --pak C:\Games\twinembers.pak --game C:\Games\twinembers.3dsx
```

更新时添加 `--overwrite`。需要密码时添加 `--user 用户名 --ask-password`，
密码在终端中隐藏输入，不写到命令行或配置文件。

## 文件保护与限制

- 本地 `.pak` 会检查 ROM 标识、引擎 ABI、必需资源目录和全部 CRC；`.3dsx` 检查格式头。
- 先用唯一临时文件名上传所有文件，再下载回读验证 SHA-256，成功后才替换正式文件。
- 更新前重命名保留旧文件；第二个文件安装失败时回滚前面的文件。
- FTP 无法让两个文件一起原子替换；安装期间保持游戏关闭。取消在完整传输步骤之间生效。
- 网络中断时尝试重连清理；若恢复失败，提示保留的 `.previous` 备份路径。
  重新连接后检查目标目录，再决定是否恢复旧文件。
- `.sav` 和 `.sav.bak` 从不作为上传、替换或删除目标。
- FTP 为局域网明文协议；使用可信局域网，不需要公网端口转发。
- 本机通过真实本地 FTP 服务验证了上传、回读、更新与存档保留；尚未连接真实 3DS ftpd。

运行协议集成测试需要开发依赖 `pyftpdlib==2.1.0`；成品工具只使用 Python 标准库，
无需在用户电脑安装 Python 或 FTP 库。
